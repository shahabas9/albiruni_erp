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

from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.core.dev_schema import ensure_dev_schema
from app.domain import customer_service, sales_service, sales_settings, tax
from app.domain.errors import ConflictError
from app.models.identity import Role, User
from app.models.sales import Item
from app.models.tenant import Company, Tenant
from app.schemas.customers import CustomerIn, CustomerUpdate
from app.schemas.sales import CompanyProfileUpdate
from app.toolgateway import tools_crm, tools_sales  # noqa: F401 — registers the tools

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
                    name=name, uom="box", unit_price=price, stock_qty=stock, gst_rate=rate, hsn_code="6907", **fields)
        self.db.add(item)
        self.db.commit()
        return item


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


if __name__ == "__main__":
    unittest.main()
