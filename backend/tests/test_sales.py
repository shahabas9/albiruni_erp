"""Integration checks for the sales cycle: GST, orders, deliveries, invoices,
credit notes, payments and receivables.

Run against an empty disposable database only:
  CRM_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import select

from app.api import routes_deliveries, routes_items, routes_orders, routes_sales
from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.core.dev_schema import ensure_dev_schema
from app.domain import customer_service, order_service, stock_service, quotation_service, sales_service, sales_settings, tax
from app.domain.errors import ConflictError
from app.models.audit import AuditEvent
from app.models.crm import Opportunity
from app.models.identity import Role, User
from app.models.sales import Item
from app.models.tenant import Company, Tenant
from app.schemas.customers import CustomerIn, CustomerUpdate
from app.schemas.items import ItemIn, ItemUpdate
from app.schemas.orders import (
    DeliveryIn, DeliveryLineIn, DocLineIn, OrderIn, OrderUpdate, ReasonIn, StockAdjustIn,
)
from app.schemas.sales import CompanyProfileUpdate, QuotationActionIn
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
        ensure_dev_schema()

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
    def confirmed_order(self, lines, customer=None):
        customer = customer or self.customer(allow_duplicate=True)
        order = self.order(customer, lines)
        return self.confirm(order.id)

    def deliver(self, order, quantities, context=None, **fields):
        body = DeliveryIn(lines=[DeliveryLineIn(order_line_id=order.lines[i].id, qty=q)
                                 for i, q in quantities.items()], **fields)
        return routes_deliveries.create_delivery(order.id, body, context or self.context, self.db)

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


if __name__ == "__main__":
    unittest.main()
