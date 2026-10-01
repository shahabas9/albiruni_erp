"""Integration checks for the sales cycle: GST, orders, deliveries, invoices,
credit notes, payments and receivables.

Run against an empty disposable database only:
  CRM_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, Response
from sqlalchemy import select

from datetime import timedelta

from app.api import routes_ask, routes_share, routes_customers, routes_deliveries, routes_receivables, routes_reports, routes_invoices, routes_items, routes_orders, routes_payments, routes_sales
from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.core.migrations import upgrade_database
from app.domain import credit_note_service, customer_service, delivery_service, receivables, sales_reports, order_service, stock_service, quotation_service, sales_service, sales_settings, tax
from app.domain.errors import ConflictError
from app.models.audit import AuditEvent
from app.models.documents import Invoice
from app.models.crm import Opportunity
from app.models.identity import Role, User
from app.models.sales import Item, Quotation
from app.models.tenant import Company, Tenant
from app.schemas.customers import CustomerIn, CustomerUpdate
from app.schemas.invoices import CreditLineIn, CreditNoteIn, InvoiceDraftIn, InvoiceLineIn, IssueIn
from app.schemas.ask import AskRequest, ConfirmRequest
from app.schemas.items import ItemIn, ItemUpdate
from app.schemas.payments import AllocateIn, AllocationIn, ReceiptIn, TdsCertificateIn
from app.schemas.orders import (
    QuickPaymentIn, QuickSaleIn,
    DeliveryIn, DeliveryLineIn, DocLineIn, OrderIn, OrderUpdate, ReasonIn, StockAdjustIn,
)
from app.schemas.sales import (
    CompanyProfileUpdate, CreateQuotationIn, QuotationActionIn, QuotationLineIn, QuotationUpdate,
)
from app.toolgateway import tools_crm, tools_documents, tools_sales  # noqa: F401 — registers the tools

KERALA_GSTIN = "32AABCA1234F1ZI"
KERALA_CUSTOMER_GSTIN = "32AAFCR4321M1ZG"
KARNATAKA_GSTIN = "29AAGCC5678K1ZZ"


class TaxMathTests(unittest.TestCase):
    def test_within_state_splits_cgst_and_sgst_after_discount(self):
        worked = tax.compute(
            [tax.LineIn(Decimal(100), Decimal(420), Decimal(18)), tax.LineIn(Decimal(50), Decimal(610), Decimal(5))],
            3, interstate=False,
        )
        self.assertEqual(worked.subtotal, Decimal("72500.00"))
        self.assertEqual(worked.taxable, Decimal("70325.00"))
        self.assertEqual((worked.cgst, worked.sgst, worked.igst), (Decimal("4406.23"), Decimal("4406.23"), 0))
        self.assertEqual(worked.round_off, Decimal("-0.46"))
        self.assertEqual(worked.grand_total, Decimal("79137.00"))

    def test_between_states_is_igst(self):
        worked = tax.compute([tax.LineIn(Decimal(3), Decimal("99.99"), Decimal(18))], 0, interstate=True)
        self.assertEqual((worked.cgst, worked.sgst, worked.igst), (0, 0, Decimal("53.99")))
        self.assertEqual(worked.grand_total, Decimal("354.00"))

    def test_words_years_and_codes(self):
        self.assertEqual(tax.amount_in_words(Decimal("1234567.50")),
                         "Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven and Fifty Paise Only")
        self.assertEqual(tax.amount_in_words(100000), "Rupees One Lakh Only")
        self.assertEqual(tax.fy_label(date(2027, 3, 31)), "26-27")
        self.assertEqual(tax.fy_label(date(2027, 4, 1)), "27-28")
        self.assertEqual(tax.clean_state("9"), "09")
        with self.assertRaises(ValueError):
            tax.clean_state("99")
        with self.assertRaises(ValueError):
            tax.clean_rate(7)
        with self.assertRaises(ValueError):
            tax.clean_hsn("12a4")


@unittest.skipUnless(os.environ.get("CRM_TEST_DB") == "1", "requires a disposable PostgreSQL database")
class SalesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        upgrade_database()

    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.context = self.make_context(["*"])
        self.db.commit()

    def make_context(self, permissions, tenant_id=None, company_id=None):
        if tenant_id is None:
            tenant = Tenant(name="Sales test", code=uuid4().hex)
            self.db.add(tenant)
            self.db.flush()
            company = Company(tenant_id=tenant.id, name="Test", code="test", legal_name="Test Traders Pvt Ltd",
                              gstin=KERALA_GSTIN, state_code="32", address="Kozhikode")
            self.db.add(company)
            self.db.flush()
            tenant_id, company_id = tenant.id, company.id
        role = Role(tenant_id=tenant_id, name=uuid4().hex, permissions=permissions)
        self.db.add(role)
        self.db.flush()
        user = User(tenant_id=tenant_id, company_id=company_id, role_id=role.id,
                    username=uuid4().hex, display_name="Test user", hashed_password="unused")
        self.db.add(user)
        self.db.flush()
        return RequestContext(user, tenant_id, company_id, permissions, "en-IN")

    def customer(self, name="Rahman Traders", **fields):
        return customer_service.create_customer(self.db, self.context, CustomerIn(name=name, **fields))

    def item(self, name="Product A", price=420, rate=18, stock=500, **fields):
        item = Item(tenant_id=self.context.tenant_id, company_id=self.context.company_id, sku=uuid4().hex[:8],
                    name=name, uom="box", unit_price=price, stock_qty=0, gst_rate=rate, hsn_code="6907", **fields)
        self.db.add(item)
        self.db.flush()
        if stock:
            stock_service.move(self.db, self.context, item, stock, "Opening")
        self.db.commit()
        return item

    def quote(self, customer_name="Rahman Traders", item="Product A", qty=10, discount=0, context=None):
        context = context or self.context
        pricing = sales_service.price_quotation(self.db, context, customer_name, [{"item_name": item, "qty": qty}],
                                                discount)
        quotation = sales_service.persist_quotation(self.db, context, pricing, context.user.id)
        self.db.commit()
        return quotation

    def order(self, customer, lines, context=None, **fields):
        body = OrderIn(customer_id=customer.id, lines=[DocLineIn(**l) for l in lines], **fields)
        return routes_orders.create_order(body, Response(), context or self.context, self.db)

    def confirm(self, order_id, context=None):
        return routes_orders.confirm_order(order_id, context or self.context, self.db)

    def confirmed_order(self, lines, customer=None):
        customer = customer or self.customer(allow_duplicate=True)
        order = self.order(customer, lines)
        return self.confirm(order.id)

    def deliver(self, order, quantities, context=None, **fields):
        body = DeliveryIn(lines=[DeliveryLineIn(order_line_id=order.lines[i].id, qty=q)
                                 for i, q in quantities.items()], **fields)
        return routes_deliveries.create_delivery(order.id, body, context or self.context, self.db)

    def draft(self, order, quantities=None, context=None):
        lines = None if quantities is None else [
            InvoiceLineIn(order_line_id=order.lines[i].id, qty=q) for i, q in quantities.items()]
        return routes_invoices.create_draft(order.id, InvoiceDraftIn(lines=lines), context or self.context, self.db)

    def issue(self, invoice, day=None, context=None):
        return routes_invoices.issue_invoice(invoice.id, IssueIn(invoice_date=day), context or self.context, self.db)

    def invoice_for(self, customer, qty, item=None):
        item = item or self.item(stock=1000)
        order = self.confirmed_order([{"item_id": item.id, "qty": qty}], customer)
        return self.issue(self.draft(order))

    def pay(self, customer, amount, mode="UPI", reference="UTR123", context=None, **fields):
        body = ReceiptIn(customer_id=customer.id, amount=amount, mode=mode, reference=reference, **fields)
        return routes_payments.record_payment(body, context or self.context, self.db)

    def credit(self, invoice, kind, lines, context=None, **fields):
        body = CreditNoteIn(kind=kind, reason=fields.pop("reason", "Damaged in transit"),
                            lines=[CreditLineIn(invoice_line_id=invoice.lines[i].id, **v) for i, v in lines.items()],
                            **fields)
        return routes_invoices.create_credit_note(invoice.id, body, context or self.context, self.db)


class GstTests(SalesTestCase):
    def test_quotation_charges_igst_to_another_state_and_cgst_sgst_within(self):
        self.item()
        self.customer("Coastal Traders", gstin=KARNATAKA_GSTIN)
        self.customer("Rahman Traders", gstin=KERALA_CUSTOMER_GSTIN)

        away = sales_service.price_quotation(self.db, self.context, "Coastal Traders",
                                             [{"item_name": "Product A", "qty": 10}], 0)
        self.assertEqual((away.place_of_supply, away.interstate, away.igst, away.cgst), ("29", True, 756.0, 0))
        self.assertEqual((away.total, away.grand_total), (4200.0, 4956.0))

        home = sales_service.price_quotation(self.db, self.context, "Rahman Traders",
                                             [{"item_name": "Product A", "qty": 10}], 0)
        self.assertEqual((home.place_of_supply, home.cgst, home.sgst, home.igst), ("32", 378.0, 378.0, 0))

        quotation = sales_service.persist_quotation(self.db, self.context, away, self.context.user.id)
        self.assertEqual((float(quotation.grand_total), quotation.place_of_supply), (4956.0, "29"))
        self.assertEqual((float(quotation.lines[0].gst_rate), float(quotation.lines[0].tax_amount)), (18.0, 756.0))

    def test_missing_rate_or_state_is_a_warning_on_quotations(self):
        self.item("Loose part", rate=None)
        self.customer("Walk-in")
        pricing = sales_service.price_quotation(self.db, self.context, "Walk-in",
                                                [{"item_name": "Loose part", "qty": 1}], 0)
        self.assertEqual(pricing.grand_total, 420.0)
        self.assertTrue(any("no GST rate" in w for w in pricing.warnings))
        self.assertTrue(any("state isn't set" in w for w in pricing.warnings))

    def test_company_profile_takes_its_state_from_the_gstin(self):
        updated = sales_settings.update_profile(self.db, self.context, CompanyProfileUpdate(
            gstin=KARNATAKA_GSTIN.lower(), address="  Mangaluru  "))
        self.assertEqual((updated.gstin, updated.state_code, updated.address), (KARNATAKA_GSTIN, "29", "Mangaluru"))
        with self.assertRaises(ConflictError):
            sales_settings.update_profile(self.db, self.context, CompanyProfileUpdate(state_code="32"))
        with self.assertRaises(ConflictError):
            sales_settings.update_profile(self.db, self.context, CompanyProfileUpdate(gstin="32AABCA1234F1ZX"))

    def test_customer_state_follows_the_gstin(self):
        registered = self.customer(gstin=KERALA_CUSTOMER_GSTIN)
        self.assertEqual(registered.state_code, "32")
        with self.assertRaises(ConflictError):
            self.customer("Other", gstin=KERALA_CUSTOMER_GSTIN, state_code="29", allow_duplicate=True)

        moved = customer_service.update_customer(self.db, self.context, registered.id,
                                                 CustomerUpdate(gstin=KARNATAKA_GSTIN))
        self.assertEqual(moved.state_code, "29")
        with self.assertRaises(ConflictError):
            customer_service.update_customer(self.db, self.context, registered.id, CustomerUpdate(state_code="32"))

        unregistered = self.customer("Walk-in", state_code="33")
        self.assertEqual(unregistered.state_code, "33")



class OrderTests(SalesTestCase):
    def test_a_quotation_becomes_one_order_with_its_prices(self):
        item = self.item()
        self.customer(gstin=KERALA_CUSTOMER_GSTIN)
        quotation = self.quote(qty=10, discount=2)
        item.unit_price = 500  # a later price rise doesn't touch the agreed price
        self.db.commit()

        order = routes_orders.order_from_quotation(quotation.id, Response(), self.context, self.db)
        self.assertEqual((order.status, order.quotation_number, order.discount_pct), ("Draft", quotation.number, 2))
        self.assertEqual((order.lines[0].unit_price, order.grand_total), (420, float(quotation.grand_total)))
        self.assertFalse(order.needs_approval)
        self.assertRegex(order.number, r"^SO/\d\d-\d\d/00001$")
        self.db.refresh(quotation)
        self.assertEqual(quotation.status, "Accepted")
        with self.assertRaises(HTTPException) as again:
            routes_orders.order_from_quotation(quotation.id, Response(), self.context, self.db)
        self.assertEqual(again.exception.status_code, 409)

    def test_quotation_actions_follow_the_rules(self):
        self.item()
        self.customer()
        quotation = self.quote(discount=5)
        self.assertEqual(quotation.status, "Pending approval")
        seller = self.make_context(["sales.quotation.create", "sales.quotation.read"],
                                   self.context.tenant_id, self.context.company_id)
        with self.assertRaises(HTTPException) as denied:
            routes_sales.quotation_action(quotation.id, "approve", QuotationActionIn(), seller, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException):  # needs approval before it can go out
            routes_sales.quotation_action(quotation.id, "send", QuotationActionIn(), seller, self.db)

        approved = routes_sales.quotation_action(quotation.id, "approve", QuotationActionIn(), self.context, self.db)
        self.assertEqual((approved.status, approved.status_note), ("Draft", "Discount approved by Test user"))
        sent = routes_sales.quotation_action(quotation.id, "send", QuotationActionIn(), seller, self.db)
        self.assertEqual(sent.status, "Sent")
        with self.assertRaises(HTTPException):
            routes_sales.quotation_action(quotation.id, "reject", QuotationActionIn(note=" "), seller, self.db)
        rejected = routes_sales.quotation_action(quotation.id, "reject", QuotationActionIn(note="Too dear"),
                                                 seller, self.db)
        self.assertEqual((rejected.status, rejected.status_note), ("Rejected", "Too dear"))
        with self.assertRaises(ConflictError):
            order_service.order_from_quotation(self.db, self.context, quotation.id)

        # An approved quote's discount carries its approval onto the order.
        reopened = quotation_service.change_status(self.db, self.context, quotation.id, "reopen")
        self.assertEqual(reopened.status, "Draft")
        order = routes_orders.order_from_quotation(quotation.id, Response(), seller, self.db)
        self.assertFalse(order.needs_approval)
        self.assertEqual(self.confirm(order.id, self.with_orders(seller)).status, "Confirmed")

    def with_orders(self, context):
        return self.make_context([*context.permissions, "sales.order.read", "sales.order.write"],
                                 context.tenant_id, context.company_id)

    def test_big_discounts_and_low_prices_need_a_manager_to_confirm(self):
        item = self.item()
        customer = self.customer()
        seller = self.make_context(["sales.order.read", "sales.order.write"], self.context.tenant_id,
                                   self.context.company_id)
        discounted = self.order(customer, [{"item_id": item.id, "qty": 5}], seller, discount_pct=5)
        cheap = self.order(customer, [{"item_id": item.id, "qty": 5, "unit_price": 400}], seller)
        fair = self.order(customer, [{"item_id": item.id, "qty": 5, "unit_price": 450}], seller, discount_pct=2)
        self.assertEqual([o.needs_approval for o in (discounted, cheap, fair)], [True, True, False])

        for order in (discounted, cheap):
            with self.assertRaises(HTTPException) as refused:
                self.confirm(order.id, seller)
            self.assertEqual(refused.exception.status_code, 422)
            self.assertIn("manager", refused.exception.detail)
        self.assertEqual(self.confirm(fair.id, seller).status, "Confirmed")
        manager = self.confirm(discounted.id)
        self.assertEqual((manager.status, manager.approved_by_name), ("Confirmed", "Test user"))
        audit = self.db.execute(select(AuditEvent).where(
            AuditEvent.tenant_id == self.context.tenant_id, AuditEvent.tool_name == "sales.confirm_order.v1",
        )).scalars().all()
        self.assertEqual(sorted(a.validation_result for a in audit), ["FAIL", "FAIL", "PASS", "PASS"])

    def test_credit_limit_counts_open_orders(self):
        item = self.item()
        customer = self.customer(credit_limit=10000)
        seller = self.make_context(["sales.order.read", "sales.order.write"], self.context.tenant_id,
                                   self.context.company_id)
        first = self.order(customer, [{"item_id": item.id, "qty": 10}], seller)  # 4,956 with GST
        second = self.order(customer, [{"item_id": item.id, "qty": 12}], seller)  # 5,947
        self.assertEqual(self.confirm(first.id, seller).status, "Confirmed")
        with self.assertRaises(HTTPException) as over:
            self.confirm(second.id, seller)
        self.assertIn("credit limit", over.exception.detail)
        self.assertEqual(order_service.credit_exposure(self.db, self.context, customer.id), 4956.0)
        self.assertEqual(self.confirm(second.id).status, "Confirmed")  # override via "*"

    def test_confirming_wins_the_deal_and_cancelling_needs_a_clean_order(self):
        item = self.item()
        customer = self.customer()
        opp = Opportunity(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                          customer_id=customer.id, name="Deal", value=1000, stage="Proposal")
        self.db.add(opp)
        self.db.commit()
        pricing = sales_service.price_quotation(self.db, self.context, customer.name,
                                                [{"item_name": item.name, "qty": 2}], 0)
        quotation = sales_service.persist_quotation(self.db, self.context, pricing, self.context.user.id)
        quotation.opportunity_id = opp.id
        self.db.commit()
        order = routes_orders.order_from_quotation(quotation.id, Response(), self.context, self.db)
        self.confirm(order.id)
        self.db.refresh(opp)
        self.assertEqual(opp.stage, "Won")

        with self.assertRaises(HTTPException):  # confirmed: no more edits
            routes_orders.update_order(order.id, OrderUpdate(discount_pct=1), Response(), self.context, self.db)
        cancelled = routes_orders.cancel_order(order.id, ReasonIn(reason="Customer changed mind"), self.context,
                                               self.db)
        self.assertEqual((cancelled.status, cancelled.cancel_reason), ("Cancelled", "Customer changed mind"))
        with self.assertRaises(HTTPException):
            self.confirm(order.id)
        # A cancelled order frees the quotation for a new one.
        self.assertEqual(routes_orders.order_from_quotation(quotation.id, Response(), self.context, self.db).status,
                         "Draft")

    def test_drafts_reprice_and_refuse_items_without_a_rate(self):
        item = self.item(stock=3)
        customer = self.customer(gstin=KARNATAKA_GSTIN)
        draft = self.order(customer, [{"item_id": item.id, "qty": 5}])
        self.assertEqual((draft.igst, draft.grand_total), (378.0, 2478.0))
        self.assertTrue(any("only 3" in w for w in draft.warnings))
        edited = routes_orders.update_order(draft.id, OrderUpdate(lines=[DocLineIn(item_id=item.id, qty=1)]),
                                            Response(), self.context, self.db)
        self.assertEqual((len(edited.lines), edited.grand_total), (1, 496.0))

        untaxed = self.item("Loose part", rate=None)
        with self.assertRaises(HTTPException) as refused:
            self.order(customer, [{"item_id": untaxed.id, "qty": 1}])
        self.assertIn("GST rate", refused.exception.detail)
        routes_orders.delete_order(draft.id, self.context, self.db)
        with self.assertRaises(HTTPException):
            routes_orders.get_order(draft.id, self.context, self.db)



class DeliveryTests(SalesTestCase):
    def test_partial_deliveries_take_stock_and_complete_the_order(self):
        a, b = self.item("Tiles", stock=100), self.item("Grout", stock=10)
        order = self.confirmed_order([{"item_id": a.id, "qty": 60}, {"item_id": b.id, "qty": 4}])

        first = self.deliver(order, {0: 40}, vehicle_no="kl 11 ab 1234")
        self.assertRegex(first.number, r"^DN/\d\d-\d\d/00001$")
        self.assertEqual((first.vehicle_no, first.lines[0].qty), ("KL 11 AB 1234", 40))
        order = routes_orders.get_order(order.id, self.context, self.db)
        self.assertEqual((order.status, order.lines[0].delivered_qty), ("Partly delivered", 40))
        self.db.refresh(a)
        self.assertEqual(float(a.stock_qty), 60)

        with self.assertRaises(HTTPException) as too_many:
            self.deliver(order, {0: 21})
        self.assertIn("Only 20", too_many.exception.detail)
        self.deliver(order, {0: 20, 1: 4})
        order = routes_orders.get_order(order.id, self.context, self.db)
        self.assertEqual(order.status, "Delivered")

        ledger = routes_deliveries.stock_ledger(a.id, Response(), 50, 0, self.context, self.db)
        self.assertEqual([(m.kind, m.qty, m.balance_after) for m in ledger],
                         [("Delivery", -20, 40), ("Delivery", -40, 60), ("Opening", 100, 100)])
        self.assertEqual(ledger[0].ref_number[:3], "DN/")

        with self.assertRaises(HTTPException):  # delivered goods: the order can't just be cancelled
            routes_orders.cancel_order(order.id, ReasonIn(reason="x"), self.context, self.db)

    def test_two_deliveries_of_the_last_stock_at_once_cant_both_succeed(self):
        import threading
        from types import SimpleNamespace

        scarce = self.item("Last boxes", stock=5)
        orders = [self.confirmed_order([{"item_id": scarce.id, "qty": 5}]) for _ in range(2)]
        # A plain user object: each thread has its own session and must not touch this one's.
        context = RequestContext(SimpleNamespace(id=self.context.user.id, display_name="Test user"),
                                 self.context.tenant_id, self.context.company_id, ["*"], "en-IN")
        results = []

        def deliver(order_id, line_id):
            db = SessionLocal()
            try:
                # Load the item first, as the real flow does, before the lock is taken.
                delivery_service.create_delivery(db, context, order_id, [{"order_line_id": line_id, "qty": 5}])
                db.commit()
                results.append("ok")
            except ConflictError:
                db.rollback()
                results.append("refused")
            finally:
                db.close()

        threads = [threading.Thread(target=deliver, args=(o.id, o.lines[0].id)) for o in orders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.db.expire_all()
        self.assertEqual(sorted(results), ["ok", "refused"])
        self.assertEqual(float(self.db.get(Item, scarce.id).stock_qty), 0)

    def test_stock_cant_go_negative_unless_the_company_allows_it(self):
        scarce = self.item("Scarce", stock=5)
        order = self.confirmed_order([{"item_id": scarce.id, "qty": 8}])
        with self.assertRaises(HTTPException) as short:
            self.deliver(order, {0: 8})
        self.assertIn("Only 5", short.exception.detail)
        sales_settings.update_profile(self.db, self.context, CompanyProfileUpdate(allow_negative_stock=True))
        self.deliver(order, {0: 8})
        self.db.refresh(scarce)
        self.assertEqual(float(scarce.stock_qty), -3)

    def test_cancelling_a_delivery_puts_stock_back(self):
        item = self.item(stock=50)
        order = self.confirmed_order([{"item_id": item.id, "qty": 10}])
        delivery = self.deliver(order, {0: 10})
        with self.assertRaises(HTTPException):
            routes_deliveries.cancel_delivery(delivery.id, ReasonIn(reason=" "), self.context, self.db)
        cancelled = routes_deliveries.cancel_delivery(delivery.id, ReasonIn(reason="Truck never left"),
                                                      self.context, self.db)
        self.assertEqual((cancelled.status, cancelled.cancel_reason), ("Cancelled", "Truck never left"))
        self.db.refresh(item)
        self.assertEqual(float(item.stock_qty), 50)
        order = routes_orders.get_order(order.id, self.context, self.db)
        self.assertEqual((order.status, order.lines[0].delivered_qty), ("Confirmed", 0))
        with self.assertRaises(HTTPException):
            routes_deliveries.cancel_delivery(delivery.id, ReasonIn(reason="again"), self.context, self.db)

    def test_services_are_not_delivered_and_drafts_cant_be(self):
        service = self.item("Installation", price=1500, stock=0, kind="service")
        goods = self.item(stock=10)
        customer = self.customer()
        draft = self.order(customer, [{"item_id": goods.id, "qty": 1}])
        with self.assertRaises(HTTPException):
            self.deliver(draft, {0: 1})
        order = self.confirmed_order([{"item_id": goods.id, "qty": 2}, {"item_id": service.id, "qty": 1}], customer)
        with self.assertRaises(HTTPException) as refused:
            self.deliver(order, {1: 1})
        self.assertIn("service", refused.exception.detail)
        self.deliver(order, {0: 2})  # all goods delivered: done, the service is invoiced
        self.assertEqual(routes_orders.get_order(order.id, self.context, self.db).status, "Delivered")

    def test_stock_changes_by_hand_are_recorded_with_a_reason(self):
        created = routes_items.create_item(ItemIn(sku="NEW-1", name="New item", unit_price=10, stock_qty=12,
                                                  gst_rate=5), self.context, self.db)
        clerk = self.make_context(["inventory.item.read", "inventory.item.write"], self.context.tenant_id,
                                  self.context.company_id)
        with self.assertRaises(HTTPException) as denied:
            routes_items.update_item(created.id, ItemUpdate(stock_qty=3), clerk, self.db)
        self.assertEqual(denied.exception.status_code, 409)
        routes_items.update_item(created.id, ItemUpdate(name="Renamed"), clerk, self.db)  # other fields are fine

        routes_deliveries.adjust_stock(created.id, StockAdjustIn(counted_qty=9, reason="Count 30 Sep"),
                                       self.context, self.db)
        ledger = routes_deliveries.stock_ledger(created.id, Response(), 50, 0, self.context, self.db)
        self.assertEqual([(m.kind, m.qty, m.balance_after, m.note) for m in ledger],
                         [("Adjustment", -3, 9, "Count 30 Sep"), ("Opening", 12, 12, "Opening stock")])
        with self.assertRaises(HTTPException):
            routes_deliveries.adjust_stock(created.id, StockAdjustIn(counted_qty=9, reason="again"),
                                           self.context, self.db)



class InvoiceTests(SalesTestCase):
    def test_invoice_what_was_delivered_then_lock_it(self):
        item = self.item(stock=100)
        customer = self.customer(gstin=KARNATAKA_GSTIN, payment_terms_days=15)
        order = self.confirmed_order([{"item_id": item.id, "qty": 10}], customer)
        self.deliver(order, {0: 4})

        draft = self.draft(order)
        self.assertEqual((draft.status, draft.number, draft.lines[0].qty), ("Draft", None, 4))
        self.assertEqual((draft.igst, draft.grand_total, draft.payment_status), (302.4, 1982.0, "Draft"))
        issued = self.issue(draft)
        self.assertRegex(issued.number, r"^INV/\d\d-\d\d/00001$")
        self.assertLessEqual(len(issued.number), 16)
        self.assertEqual((issued.status, issued.payment_status, issued.balance), ("Issued", "Unpaid", 1982.0))
        self.assertEqual((issued.due_date - issued.invoice_date).days, 15)
        self.assertEqual((issued.seller_gstin, issued.buyer_gstin, issued.place_of_supply_name),
                         (KERALA_GSTIN, KARNATAKA_GSTIN, "Karnataka"))
        self.assertEqual(issued.amount_in_words, "Rupees One Thousand Nine Hundred Eighty Two Only")
        self.assertEqual([(h.hsn_code, h.gst_rate, h.taxable_value) for h in issued.hsn_summary],
                         [("6907", 18.0, 1680.0)])
        order = routes_orders.get_order(order.id, self.context, self.db)
        self.assertEqual((order.lines[0].invoiced_qty, order.invoice_status), (4, "Partly invoiced"))

        # Locked: can't delete, re-issue, and later edits to the customer don't reach it.
        with self.assertRaises(HTTPException):
            routes_invoices.delete_draft(issued.id, self.context, self.db)
        with self.assertRaises(HTTPException):
            self.issue(issued)
        customer_service.update_customer(self.db, self.context, customer.id, CustomerUpdate(name="Renamed Co"))
        self.assertEqual(routes_invoices.get_invoice(issued.id, self.context, self.db).buyer_name, "Rahman Traders")

        # Nothing delivered-but-uninvoiced is left; the rest can still be picked by hand.
        with self.assertRaises(HTTPException) as nothing:
            self.draft(order)
        self.assertIn("deliver the goods first", nothing.exception.detail)
        rest = self.issue(self.draft(order, {0: 6}))
        self.assertTrue(rest.number.endswith("00002"))
        self.assertEqual(routes_orders.get_order(order.id, self.context, self.db).invoice_status, "Invoiced")

    def test_two_drafts_cant_invoice_the_same_goods(self):
        item = self.item()
        order = self.confirmed_order([{"item_id": item.id, "qty": 5}])
        first, second = self.draft(order), self.draft(order)  # both default to all 5 (nothing delivered yet)
        self.issue(first)
        with self.assertRaises(HTTPException) as late:
            self.issue(second)
        self.assertIn("another invoice took the rest", late.exception.detail)
        routes_invoices.delete_draft(second.id, self.context, self.db)

    def test_issuing_needs_seller_details_and_dates_in_order(self):
        item = self.item()
        order = self.confirmed_order([{"item_id": item.id, "qty": 2}])
        company = self.db.get(Company, self.context.company_id)
        company.gstin = ""
        self.db.commit()
        draft = self.draft(order, {0: 1})
        with self.assertRaises(HTTPException) as missing:
            self.issue(draft)
        self.assertIn("GSTIN", missing.exception.detail)
        company.gstin = KERALA_GSTIN
        self.db.commit()

        with self.assertRaises(HTTPException):
            self.issue(draft, date.today() + timedelta(days=1))
        self.issue(draft)
        earlier = self.draft(order, {0: 1})
        if tax.fy_start_year(date.today() - timedelta(days=1)) == tax.fy_start_year(date.today()):
            with self.assertRaises(HTTPException) as backdated:
                self.issue(earlier, date.today() - timedelta(days=1))
            self.assertIn("date order", backdated.exception.detail)
        audit = self.db.execute(select(AuditEvent.validation_result).where(
            AuditEvent.tenant_id == self.context.tenant_id, AuditEvent.tool_name == "sales.issue_invoice.v1",
        )).scalars().all()
        self.assertIn("PASS", audit)
        self.assertIn("FAIL", audit)

    def test_services_and_overdue_status(self):
        service = self.item("Installation", price=1000, stock=0, kind="service")
        order = self.confirmed_order([{"item_id": service.id, "qty": 1}])
        invoice = self.issue(self.draft(order))
        self.assertEqual(invoice.lines[0].qty, 1)
        row = self.db.get(Invoice, invoice.id)
        row.due_date = date.today() - timedelta(days=3)
        self.db.commit()
        self.assertEqual(routes_invoices.get_invoice(invoice.id, self.context, self.db).payment_status, "Overdue")
        listed = routes_invoices.list_invoices(Response(), "overdue", None, None, "", None, 0, self.context, self.db)
        self.assertEqual([i.id for i in listed], [invoice.id])



class CreditNoteTests(SalesTestCase):
    def issued(self, qty=4, stock=100, price=420):
        item = self.item(stock=stock, price=price)
        order = self.confirmed_order([{"item_id": item.id, "qty": qty}])
        self.deliver(order, {0: qty})
        return item, self.issue(self.draft(order))

    def test_returns_credit_the_invoice_and_can_restock(self):
        item, invoice = self.issued()  # 4 × 420 = 1,680 + 302.40 GST = 1,982
        note = self.credit(invoice, "Return", {0: {"qty": 1}}, restock=True)
        self.assertRegex(note.number, r"^CN/\d\d-\d\d/00001$")
        self.assertEqual((note.total, note.cgst, note.sgst, note.grand_total), (420.0, 37.8, 37.8, 496.0))
        self.assertEqual((note.invoice_number, note.restocked), (invoice.number, True))
        self.db.refresh(item)
        self.assertEqual(float(item.stock_qty), 97)  # 100 − 4 delivered + 1 back
        after = routes_invoices.get_invoice(invoice.id, self.context, self.db)
        self.assertEqual((after.amount_credited, after.balance, after.lines[0].credited_qty), (496.0, 1486.0, 1))

        # Without restock: no stock change.
        self.credit(invoice, "Return", {0: {"qty": 1}}, restock=False)
        self.db.refresh(item)
        self.assertEqual(float(item.stock_qty), 97)
        with self.assertRaises(HTTPException) as too_many:
            self.credit(invoice, "Return", {0: {"qty": 3}})
        self.assertIn("Only 2", too_many.exception.detail)

        # Returning the rest clears the invoice exactly.
        self.credit(invoice, "Return", {0: {"qty": 2}})
        cleared = routes_invoices.get_invoice(invoice.id, self.context, self.db)
        self.assertEqual((cleared.balance, cleared.payment_status), (0.0, "Credited"))
        ledger = routes_deliveries.stock_ledger(item.id, Response(), 50, 0, self.context, self.db)
        self.assertEqual((ledger[0].kind, ledger[0].qty, ledger[0].ref_number), ("Return", 1, note.number))

    def test_price_corrections_are_capped_at_the_lines_value(self):
        _, invoice = self.issued(qty=2)  # 840 taxable
        note = self.credit(invoice, "Price correction", {0: {"amount": 100}}, reason="Agreed rate was lower")
        self.assertEqual((note.lines[0].qty, note.total, note.grand_total), (0, 100.0, 118.0))
        with self.assertRaises(HTTPException) as too_much:
            self.credit(invoice, "Price correction", {0: {"amount": 741}})
        self.assertIn("740", too_much.exception.detail)
        # A return after a correction credits what's left of the value.
        rest = self.credit(invoice, "Return", {0: {"qty": 2}})
        self.assertEqual(rest.total, 740.0)
        self.assertEqual(routes_invoices.get_invoice(invoice.id, self.context, self.db).balance, 0.0)

    def test_credit_notes_need_an_issued_invoice_in_time_and_the_permission(self):
        item = self.item()
        order = self.confirmed_order([{"item_id": item.id, "qty": 2}])
        draft = self.draft(order)
        with self.assertRaises(HTTPException):
            self.credit(draft, "Return", {0: {"qty": 1}})
        invoice = self.issue(draft)
        clerk = self.make_context(["sales.invoice.read", "sales.invoice.write"], self.context.tenant_id,
                                  self.context.company_id)
        with self.assertRaises(HTTPException) as denied:
            self.credit(invoice, "Return", {0: {"qty": 1}}, clerk)
        self.assertEqual(denied.exception.status_code, 403)

        row = self.db.get(Invoice, invoice.id)
        row.invoice_date = date(date.today().year - 3, 5, 1)
        self.db.commit()
        with self.assertRaises(HTTPException) as late:
            self.credit(invoice, "Return", {0: {"qty": 1}})
        self.assertIn("only until", late.exception.detail)
        self.assertEqual(credit_note_service.deadline(date(2026, 5, 1)), date(2027, 11, 30))
        self.assertEqual(credit_note_service.deadline(date(2027, 2, 1)), date(2027, 11, 30))



class PaymentTests(SalesTestCase):
    def test_payments_settle_the_oldest_invoices_first_and_keep_the_rest(self):
        customer = self.customer()
        older = self.invoice_for(customer, 1)  # 496
        newer = self.invoice_for(customer, 2)  # 991
        row = self.db.get(Invoice, older.id)
        row.due_date = row.due_date - timedelta(days=10)
        self.db.commit()

        receipt = self.pay(customer, 1000)
        self.assertRegex(receipt.number, r"^RCT/\d\d-\d\d/00001$")
        self.assertEqual([(a.invoice_number, a.amount) for a in receipt.allocations],
                         [(older.number, 496.0), (newer.number, 504.0)])
        self.assertEqual(routes_invoices.get_invoice(older.id, self.context, self.db).payment_status, "Paid")
        partly = routes_invoices.get_invoice(newer.id, self.context, self.db)
        self.assertEqual((partly.payment_status, partly.balance), ("Partly paid", 487.0))
        self.assertEqual([p.number for p in partly.payments], [receipt.number])

        advance = self.pay(customer, 600, mode="Cash", reference="")
        self.assertEqual((advance.allocated, advance.unallocated), (487.0, 113.0))
        self.assertEqual(float(receivables.net_owed(self.db, self.context, customer.id)), -113.0)

        # The advance is applied to the next invoice when asked.
        third = self.invoice_for(customer, 1)
        applied = routes_payments.allocate_payment(advance.id, AllocateIn(), self.context, self.db)
        self.assertEqual(applied.unallocated, 0)
        self.assertEqual(routes_invoices.get_invoice(third.id, self.context, self.db).balance, 383.0)

    def test_payment_rules(self):
        customer, other = self.customer(), self.customer("Other Co")
        invoice = self.invoice_for(customer, 1)
        theirs = self.invoice_for(other, 1)
        cases = [
            ({"amount": 200000, "mode": "Cash", "reference": ""}, "269ST"),
            ({"amount": 100, "mode": "Cheque", "reference": ""}, "cheque number"),
            ({"amount": 600, "allocations": [AllocationIn(invoice_id=invoice.id, amount=600)]}, "only has"),
            ({"amount": 100, "allocations": [AllocationIn(invoice_id=theirs.id, amount=100)]}, "another customer"),
            ({"amount": 100, "allocations": [AllocationIn(invoice_id=invoice.id, amount=150)]}, "left to allocate"),
            ({"amount": 100, "receipt_date": date.today() + timedelta(days=1)}, "future"),
        ]
        for fields, message in cases:
            with self.subTest(message):
                with self.assertRaises(HTTPException) as refused:
                    self.pay(customer, **fields)
                self.assertIn(message, refused.exception.detail)
        kept = self.pay(customer, 100, allocations=[])  # [] keeps it all as an advance
        self.assertEqual(kept.unallocated, 100)
        clerk = self.make_context(["sales.payment.read"], self.context.tenant_id, self.context.company_id)
        with self.assertRaises(HTTPException) as denied:
            self.pay(customer, 10, context=clerk)
        self.assertEqual(denied.exception.status_code, 403)

    def test_a_bounced_cheque_makes_the_invoice_owed_again(self):
        customer = self.customer()
        invoice = self.invoice_for(customer, 1)
        cheque = self.pay(customer, 496, mode="Cheque", reference="004512")
        self.assertEqual(routes_invoices.get_invoice(invoice.id, self.context, self.db).payment_status, "Paid")
        voided = routes_payments.void_payment(cheque.id, ReasonIn(reason="Cheque bounced"), self.context, self.db)
        self.assertEqual((voided.status, voided.allocated, voided.unallocated), ("Voided", 0, 0))
        again = routes_invoices.get_invoice(invoice.id, self.context, self.db)
        self.assertEqual((again.balance, again.payment_status), (496.0, "Unpaid"))
        with self.assertRaises(HTTPException):
            routes_payments.void_payment(cheque.id, ReasonIn(reason="again"), self.context, self.db)

    def test_unpaid_invoices_count_against_the_credit_limit(self):
        item = self.item(stock=1000)
        customer = self.customer(credit_limit=6000)
        seller = self.make_context(["sales.order.read", "sales.order.write"], self.context.tenant_id,
                                   self.context.company_id)
        self.invoice_for(customer, 10, item)  # 4,956 owed
        order = self.order(customer, [{"item_id": item.id, "qty": 4}], seller)  # 1,982 more
        with self.assertRaises(HTTPException) as over:
            self.confirm(order.id, seller)
        self.assertIn("credit limit", over.exception.detail)
        self.pay(customer, 4956)
        self.assertEqual(self.confirm(order.id, seller).status, "Confirmed")



class ReceivablesTests(SalesTestCase):
    def age(self, invoice, days_overdue):
        row = self.db.get(Invoice, invoice.id)
        row.due_date = date.today() - timedelta(days=days_overdue)
        row.invoice_date = min(row.invoice_date, row.due_date)
        self.db.commit()

    def test_ageing_buckets_by_days_overdue_less_advances(self):
        item = self.item(stock=1000)
        late, fresh = self.customer("Late Payer"), self.customer("Fresh Buyer")
        for qty, days in ((1, 5), (2, 45), (1, 120)):
            self.age(self.invoice_for(late, qty, item), days)
        self.invoice_for(fresh, 1, item)  # not due yet
        self.pay(fresh, 1000, allocations=[])  # an advance bigger than what it owes
        self.customer("Quiet Co")  # owes nothing: left out

        report = routes_receivables.ageing(None, "", self.context, self.db)
        rows = {r["customer_name"]: r for r in report["rows"]}
        self.assertEqual(set(rows), {"Late Payer", "Fresh Buyer"})
        self.assertEqual(report["rows"][0]["customer_name"], "Late Payer")  # most overdue first
        l = rows["Late Payer"]
        self.assertEqual((l["d1_30"], l["d31_60"], l["d61_90"], l["d90_plus"], l["not_due"]),
                         (496.0, 991.0, 0.0, 496.0, 0.0))
        self.assertEqual((l["overdue"], l["open_invoices"]), (1983.0, 3))
        f = rows["Fresh Buyer"]
        self.assertEqual((f["not_due"], f["advance"], f["net"]), (496.0, 1000.0, -504.0))
        self.assertEqual(report["totals"]["net"], 1983.0 - 504.0)

        overview = routes_customers.customer_overview(late.id, self.context, self.db)
        self.assertEqual((overview["account"]["overdue"], overview["account"]["open_invoices"]), (1983.0, 3))

    def test_statement_runs_a_balance_from_what_was_brought_forward(self):
        item = self.item(stock=1000)
        customer = self.customer()
        first = self.invoice_for(customer, 1, item)  # 496
        row = self.db.get(Invoice, first.id)
        row.invoice_date = date.today() - timedelta(days=40)
        self.db.commit()
        self.invoice_for(customer, 2, item)  # 991 today
        self.pay(customer, 300)
        voided = self.pay(customer, 100, mode="Cheque", reference="11")
        routes_payments.void_payment(voided.id, ReasonIn(reason="Bounced"), self.context, self.db)

        start = date.today() - timedelta(days=10)
        st = routes_receivables.statement(customer.id, start, date.today(), self.context, self.db)
        self.assertEqual(st["opening_balance"], 496.0)
        self.assertEqual([(l["kind"], l["debit"], l["credit"], l["balance"]) for l in st["lines"]],
                         [("Invoice", 991.0, 0.0, 1487.0), ("Payment", 0.0, 300.0, 1187.0)])
        self.assertEqual(st["closing_balance"], 1187.0)
        self.assertEqual(float(receivables.net_owed(self.db, self.context, customer.id)), 1187.0)
        with self.assertRaises(HTTPException):
            routes_receivables.statement(customer.id, date.today(), start, self.context, self.db)



class ReportTests(SalesTestCase):
    def test_gstr1_puts_each_sale_in_its_section(self):
        item = self.item(stock=5000)
        registered = self.customer("Registered Co", gstin=KERALA_CUSTOMER_GSTIN)
        far_big = self.customer("Far Big Buyer", state_code="33")
        far_small = self.customer("Far Small Buyer", state_code="33")
        local = self.customer("Walk-in Local", state_code="32")

        b2b = self.invoice_for(registered, 10, item)  # 4,200 + 756
        b2cl = self.invoice_for(far_big, 300, item)  # 1,26,000 + IGST: over ₹1 lakh, other state
        self.invoice_for(far_small, 10, item)  # other state but small: B2CS
        b2cs_local = self.invoice_for(local, 5, item)
        self.credit(b2b, "Return", {0: {"qty": 2}})  # 840 back from a registered buyer: CDNR
        self.credit(b2cs_local, "Return", {0: {"qty": 1}})  # netted into B2CS

        today = date.today()
        report = routes_reports.gstr1(today, today, self.context, self.db)
        self.assertEqual([(r["gstin"], r["invoice_number"], r["taxable_value"], r["cgst"]) for r in report["b2b"]],
                         [(KERALA_CUSTOMER_GSTIN, b2b.number, 4200.0, 378.0)])
        self.assertEqual([(r["invoice_number"], r["place_of_supply"], r["igst"]) for r in report["b2cl"]],
                         [(b2cl.number, "33-Tamil Nadu", 22680.0)])
        b2cs = {(r["place_of_supply"], r["rate"]): r for r in report["b2cs"]}
        self.assertEqual(b2cs[("33-Tamil Nadu", 18.0)]["igst"], 756.0)
        self.assertEqual(b2cs[("32-Kerala", 18.0)]["taxable_value"], 2100.0 - 420.0)
        self.assertEqual([(r["gstin"], r["taxable_value"], r["invoice_number"]) for r in report["cdnr"]],
                         [(KERALA_CUSTOMER_GSTIN, 840.0, b2b.number)])
        self.assertEqual(report["cdnur"], [])
        hsn = {(r["type"], r["uqc"]): r for r in report["hsn"]}
        self.assertEqual((hsn[("B2B", "BOX")]["qty"], hsn[("B2B", "BOX")]["taxable_value"]), (8.0, 3360.0))
        self.assertEqual(hsn[("B2C", "BOX")]["qty"], 300 + 10 + 5 - 1)
        docs = {d["nature"]: d for d in report["docs"]}
        self.assertEqual(docs["Invoices for outward supply"]["total"], 4)
        self.assertTrue(docs["Credit notes"]["from"].startswith("CN/"))

        register = routes_reports.sales_register(today, today, self.context, self.db)
        self.assertEqual((register["invoices"], register["credit_notes"]), (4, 2))
        self.assertEqual(register["totals"]["taxable_value"], 4200 + 126000 + 4200 + 2100 - 840 - 420)

        response = routes_reports.report_csv("b2b", today, today, self.context, self.db)
        body = response.body.decode()
        self.assertTrue(body.startswith("\ufeffGSTIN/UIN of Recipient,Receiver Name"))
        self.assertIn(b2b.number, body)
        self.assertEqual(response.headers["X-Row-Count"], "1")
        audit = self.db.execute(select(AuditEvent).where(
            AuditEvent.tenant_id == self.context.tenant_id, AuditEvent.tool_name == "sales.export_report.v1",
        )).scalars().all()
        self.assertEqual(len(audit), 1)

    def test_reports_need_the_permission_and_a_sane_period(self):
        clerk = self.make_context(["sales.invoice.read"], self.context.tenant_id, self.context.company_id)
        with self.assertRaises(HTTPException) as denied:
            routes_reports.report_csv("b2b", date.today(), date.today(), clerk, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            routes_reports.gstr1(date.today(), date.today() - timedelta(days=1), self.context, self.db)
        self.assertEqual(sales_reports.uqc("Boxes"), "BOX")
        self.assertEqual(sales_reports.uqc("bundle"), "OTH")



class AskAndAlertTests(SalesTestCase):
    def ask(self, text, context=None):
        return routes_ask.ask(AskRequest(text=text), context or self.context, self.db)

    def test_ask_who_owes_and_how_much_one_customer_owes(self):
        item = self.item(stock=100)
        customer = self.customer("Rahman Traders")
        invoice = self.invoice_for(customer, 2, item)  # 991
        self.age_invoice(invoice, 40)
        answer = self.ask("Who owes us money?")
        self.assertEqual(answer["type"], "answer")
        self.assertIn("₹991 is overdue", answer["message"])
        self.assertEqual(answer["items"][0]["title"], "Rahman Traders — ₹991")
        one = self.ask("how much does Rahman Traders owe")
        self.assertIn("Rahman Traders owes ₹991 on 1 invoice, ₹991 of it overdue", one["message"])
        self.assertEqual(one["items"][0]["link"], f"/sales/invoices/{invoice.id}")
        clerk = self.make_context(["crm.lead.read"], self.context.tenant_id, self.context.company_id)
        self.assertEqual(self.ask("Who owes us money?", clerk)["type"], "denied")

    def test_ask_records_a_payment_only_after_confirmation(self):
        item = self.item(stock=100)
        customer = self.customer("Coastal Traders")
        invoice = self.invoice_for(customer, 2, item)  # 991
        needs_ref = self.ask("Received ₹500 from Coastal Traders by UPI")
        self.assertEqual(needs_ref["type"], "clarify")
        preview = self.ask("Received ₹500 from Coastal Traders by UPI, UTR 998877")
        self.assertEqual(preview["type"], "action_preview")
        self.assertIn({"label": "Applies to", "value": f"Oldest first: {invoice.number}"}, preview["lines"])
        self.assertEqual(routes_invoices.get_invoice(invoice.id, self.context, self.db).amount_paid, 0)  # nothing yet
        done = routes_ask.confirm(ConfirmRequest(preview_token=preview["preview_token"]), self.context, self.db)
        self.assertIn("Recorded payment RCT/", done["result_summary"])
        self.assertEqual(routes_invoices.get_invoice(invoice.id, self.context, self.db).balance, 491.0)
        how = self.ask("received 200 from Coastal Traders")
        self.assertEqual((how["type"], how["message"]), ("clarify", "How was it paid?"))

    def test_ask_drafts_an_invoice_for_the_one_order_waiting(self):
        item = self.item(stock=100)
        customer = self.customer("Malabar Hardware")
        self.assertEqual(self.ask("invoice Malabar Hardware order")["type"], "message")  # nothing to invoice
        order = self.confirmed_order([{"item_id": item.id, "qty": 3}], customer)
        self.deliver(order, {0: 3})
        preview = self.ask("Invoice Malabar Hardware's order")
        self.assertEqual((preview["type"], preview["tool_name"]), ("action_preview", "sales.draft_invoice.v1"))
        done = routes_ask.confirm(ConfirmRequest(preview_token=preview["preview_token"]), self.context, self.db)
        draft = routes_invoices.get_invoice(UUID(done["invoice_id"]), self.context, self.db)
        self.assertEqual((draft.status, draft.lines[0].qty, draft.order_number), ("Draft", 3, order.number))

    def age_invoice(self, invoice, days):
        row = self.db.get(Invoice, invoice.id)
        row.due_date = date.today() - timedelta(days=days)
        self.db.commit()

    def test_overdue_invoices_alert_once(self):
        from app.domain import notifications
        from app.models.crm import Notification

        item = self.item(stock=100)
        issuer = self.make_context(["*"], self.context.tenant_id, self.context.company_id)
        invoice = self.invoice_for(self.customer(), 1, item)
        row = self.db.get(Invoice, invoice.id)
        row.issued_by = issuer.user.id
        self.db.commit()
        self.age_invoice(invoice, 1)
        paid = self.invoice_for(self.customer("Paid Up"), 1, item)
        self.age_invoice(paid, 1)
        self.pay(self.db.get(Invoice, paid.id).customer, 496)

        notifications.raise_overdue_invoice_alerts(self.db)
        notifications.raise_overdue_invoice_alerts(self.db)  # once only
        alerts = self.db.execute(select(Notification).where(
            Notification.tenant_id == self.context.tenant_id, Notification.kind == "invoice_overdue",
        )).scalars().all()
        self.assertEqual([(a.user_id, a.link) for a in alerts], [(issuer.user.id, f"/sales/invoices/{invoice.id}")])



class QuickSaleTests(SalesTestCase):
    def sell(self, lines, context=None, **fields):
        body = QuickSaleIn(lines=[DocLineIn(**l) for l in lines], **fields)
        return routes_orders.quick_sale(body, context or self.context, self.db)

    def test_counter_sale_does_everything_in_one_go(self):
        goods, service = self.item(stock=20), self.item("Fitting", price=500, stock=0, kind="service")
        out = self.sell([{"item_id": goods.id, "qty": 2}, {"item_id": service.id, "qty": 1}],
                        payment=QuickPaymentIn(amount=1581, mode="Cash"))
        invoice = routes_invoices.get_invoice(out.invoice_id, self.context, self.db)
        self.assertEqual((invoice.status, invoice.customer_name, invoice.grand_total, invoice.payment_status),
                         ("Issued", "Walk-in customer", 1581.0, "Paid"))
        order = routes_orders.get_order(out.order_id, self.context, self.db)
        self.assertEqual((order.status, order.invoice_status), ("Delivered", "Invoiced"))
        self.db.refresh(goods)
        self.assertEqual(float(goods.stock_qty), 18)
        again = self.sell([{"item_id": goods.id, "qty": 1}])  # same walk-in customer, paid later
        self.assertIsNone(again.receipt_id)
        self.assertEqual(routes_invoices.get_invoice(again.invoice_id, self.context, self.db).customer_name,
                         "Walk-in customer")

    def test_any_refusal_saves_nothing(self):
        scarce = self.item(stock=1)
        orders_before = len(routes_orders.list_orders(Response(), "", None, "", False, None, 0, self.context, self.db))
        with self.assertRaises(HTTPException) as short:
            self.sell([{"item_id": scarce.id, "qty": 3}])
        self.assertIn("Only 1", short.exception.detail)
        with self.assertRaises(HTTPException) as overpaid:
            self.sell([{"item_id": scarce.id, "qty": 1}], payment=QuickPaymentIn(amount=10000, mode="Cash"))
        self.assertIn("change", overpaid.exception.detail)
        self.assertEqual(len(routes_orders.list_orders(Response(), "", None, "", False, None, 0, self.context,
                                                       self.db)), orders_before)
        self.db.refresh(scarce)
        self.assertEqual(float(scarce.stock_qty), 1)
        clerk = self.make_context(["sales.invoice.write", "sales.order.write"], self.context.tenant_id,
                                  self.context.company_id)
        self.db.commit()  # a refused sale rolls back; the user must already be saved
        with self.assertRaises(HTTPException) as denied:
            self.sell([{"item_id": scarce.id, "qty": 1}], clerk)
        self.assertIn("sales.delivery.write", denied.exception.detail)



class QuotationFormTests(SalesTestCase):
    def create(self, customer, lines, **fields):
        body = CreateQuotationIn(customer_id=customer.id, lines=[QuotationLineIn(**l) for l in lines], **fields)
        result = routes_sales.create_quotation(body, self.context, self.db)
        return routes_sales.get_quotation(UUID(result["quotation_id"]), self.context, self.db)

    def test_form_quotes_pick_items_set_prices_and_expire(self):
        item = self.item()
        customer = self.customer()
        quote = self.create(customer, [{"item_id": item.id, "qty": 10}], notes="Delivery in a week")
        self.assertEqual((quote.status, quote.grand_total, quote.notes), ("Draft", 4956.0, "Delivery in a week"))
        self.assertEqual(quote.valid_until, date.today() + timedelta(days=15))
        cheap = self.create(customer, [{"item_id": item.id, "qty": 10, "unit_price": 400}])
        self.assertEqual(cheap.status, "Pending approval")  # below list price

        # Editing a draft re-prices it; a bigger discount sends it for approval.
        edited = routes_sales.update_quotation(quote.id, QuotationUpdate(
            lines=[QuotationLineIn(item_id=item.id, qty=20)], discount_pct=5), self.context, self.db)
        self.assertEqual((edited.status, edited.total), ("Pending approval", 7980.0))
        back = routes_sales.update_quotation(quote.id, QuotationUpdate(discount_pct=1), self.context, self.db)
        self.assertEqual((back.status, back.total), ("Draft", 8316.0))

        sent = routes_sales.quotation_action(quote.id, "send", QuotationActionIn(), self.context, self.db)
        with self.assertRaises(HTTPException):  # a sent quote's content is fixed
            routes_sales.update_quotation(quote.id, QuotationUpdate(discount_pct=0), self.context, self.db)
        row = self.db.get(Quotation, sent.id)
        row.valid_until = date.today() - timedelta(days=1)
        self.db.commit()
        self.assertTrue(routes_sales.get_quotation(sent.id, self.context, self.db).is_expired)
        with self.assertRaises(HTTPException) as expired:
            routes_sales.quotation_action(quote.id, "accept", QuotationActionIn(), self.context, self.db)
        self.assertIn("expired", expired.exception.detail)
        with self.assertRaises(ConflictError):
            order_service.order_from_quotation(self.db, self.context, quote.id)
        extended = routes_sales.update_quotation(
            quote.id, QuotationUpdate(valid_until=date.today() + timedelta(days=7)), self.context, self.db)
        self.assertFalse(extended.is_expired)
        self.assertEqual(routes_sales.quotation_action(quote.id, "accept", QuotationActionIn(), self.context,
                                                       self.db).status, "Accepted")



class ShareTests(SalesTestCase):
    def test_share_links_open_one_document_and_nothing_else(self):
        from app.core.config import settings

        customer = self.customer()
        invoice = self.invoice_for(customer, 2)
        out = routes_share.share_document(routes_share.ShareIn(kind="invoice", id=invoice.id), self.context, self.db)
        self.assertIn(f"invoice {invoice.number}", out["message"])
        self.assertIsNone(out["emailed_to"])
        token = out["url"].rsplit("/d/", 1)[1]
        public = routes_share.public_document(token, self.db)
        self.assertEqual((public["kind"], public["document"].number, public["company"]["gstin"]),
                         ("invoice", invoice.number, KERALA_GSTIN))
        with self.assertRaises(HTTPException):  # tampered
            routes_share.public_document(token[:-2] + ("AA" if token[-2:] != "AA" else "BB"), self.db)

        # Statements carry their period; email needs SMTP.
        st = routes_share.share_document(routes_share.ShareIn(kind="statement", id=customer.id), self.context, self.db)
        statement = routes_share.public_document(st["url"].rsplit("/d/", 1)[1], self.db)["document"]
        self.assertEqual(statement["closing_balance"], 991.0)
        self.addCleanup(setattr, settings, "smtp_host", settings.smtp_host)
        settings.smtp_host = ""
        with self.assertRaises(HTTPException) as no_smtp:
            routes_share.share_document(routes_share.ShareIn(kind="invoice", id=invoice.id, email="a@b.example"),
                                        self.context, self.db)
        self.assertIn("SMTP", no_smtp.exception.detail)

    def test_sharing_needs_the_documents_read_permission(self):
        draft = self.draft(self.confirmed_order([{"item_id": self.item().id, "qty": 1}]))
        with self.assertRaises(HTTPException) as unissued:
            routes_share.share_document(routes_share.ShareIn(kind="invoice", id=draft.id), self.context, self.db)
        self.assertIn("Issue the invoice", unissued.exception.detail)
        quote = self.quote()
        clerk = self.make_context(["sales.invoice.read"], self.context.tenant_id, self.context.company_id)
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            routes_share.share_document(routes_share.ShareIn(kind="quotation", id=quote.id), clerk, self.db)
        self.assertEqual(denied.exception.status_code, 403)



class TdsTests(SalesTestCase):
    def test_tds_deducted_settles_the_invoice_and_is_reported(self):
        customer = self.customer(gstin=KARNATAKA_GSTIN)
        invoice = self.invoice_for(customer, 20)  # 9,912 with GST
        with self.assertRaises(HTTPException) as no_section:
            self.pay(customer, 9744, allocations=[AllocationIn(invoice_id=invoice.id, amount=9744, tds_amount=168)])
        self.assertIn("section", no_section.exception.detail)
        with self.assertRaises(HTTPException) as too_much:
            self.pay(customer, 9744, tds_section="194Q",
                     allocations=[AllocationIn(invoice_id=invoice.id, amount=9744, tds_amount=200)])
        self.assertIn("more", too_much.exception.detail)

        receipt = self.pay(customer, 9744, tds_section="194q",
                           allocations=[AllocationIn(invoice_id=invoice.id, amount=9744, tds_amount=168)])
        self.assertEqual((receipt.tds_amount, receipt.tds_section, receipt.unallocated), (168.0, "194Q", 0))
        paid = routes_invoices.get_invoice(invoice.id, self.context, self.db)
        self.assertEqual((paid.amount_paid, paid.amount_tds, paid.balance, paid.payment_status),
                         (9744.0, 168.0, 0.0, "Paid"))
        self.assertEqual(float(receivables.net_owed(self.db, self.context, customer.id)), 0)

        today = date.today()
        report = routes_reports.tds(today, today, self.context, self.db)
        row = next(r for r in report["rows"] if r["receipt_number"] == receipt.number)
        self.assertEqual((row["customer_pan"], row["section"], row["tds_amount"], row["certificate_received"]),
                         (KARNATAKA_GSTIN[2:12], "194Q", 168.0, "No"))
        routes_payments.tds_certificate(receipt.id, TdsCertificateIn(received=True), self.context, self.db)
        row = next(r for r in routes_reports.tds(today, today, self.context, self.db)["rows"]
                   if r["receipt_number"] == receipt.number)
        self.assertEqual(row["certificate_received"], "Yes")

        # Voiding takes the TDS back off too.
        routes_payments.void_payment(receipt.id, ReasonIn(reason="Wrong customer"), self.context, self.db)
        again = routes_invoices.get_invoice(invoice.id, self.context, self.db)
        self.assertEqual((again.amount_tds, again.balance), (0.0, 9912.0))


if __name__ == "__main__":
    unittest.main()
