"""Integration checks for the CRM API (leads, opportunities, activities).

Run against an empty disposable database only:
  CRM_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.api import routes_activities, routes_leads, routes_opportunities
from app.core.database import SessionLocal
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.core.dev_schema import ensure_dev_schema
from app.domain import activity_service, crm_service, lead_service, opportunity_service
from app.domain.errors import ConflictError
from app.models.crm import Activity, Lead, Opportunity
from app.models.identity import Role, User
from app.models.sales import Item
from app.models.tenant import Company, Tenant
from app.schemas import crm
from app.toolgateway import tools_sales  # noqa: F401 — registers the quotation tool


@unittest.skipUnless(os.environ.get("CRM_TEST_DB") == "1", "requires a disposable PostgreSQL database")
class CrmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_dev_schema()
        ensure_dev_schema()  # Upgrades must remain safe to repeat.

    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.context = self.make_context(["*"])
        self.db.commit()

    def make_context(self, permissions, tenant=None, company=None):
        if tenant is None:
            tenant = Tenant(name="CRM test", code=uuid4().hex)
            self.db.add(tenant)
            self.db.flush()
            company = Company(tenant_id=tenant.id, name="Test", code="test")
            self.db.add(company)
            self.db.flush()
        role = Role(tenant_id=tenant.id, name=uuid4().hex, permissions=permissions)
        self.db.add(role)
        self.db.flush()
        user = User(tenant_id=tenant.id, company_id=company.id, role_id=role.id,
                    username=uuid4().hex, display_name="Test user", hashed_password="unused")
        self.db.add(user)
        self.db.flush()
        return RequestContext(user, tenant.id, company.id, permissions, "en-IN")

    def lead(self, **fields):
        return lead_service.create_lead(self.db, self.context, crm.LeadIn(
            name=fields.pop("name", "Contact"), company_name=fields.pop("company_name", "Customer Co"), **fields))

    # --- Leads ----------------------------------------------------------------

    def test_conversion_creates_contact_opportunity_and_moves_follow_ups(self):
        lead = self.lead(email="person@example.test", owner_user_id=self.context.user.id)
        task = activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Call", subject="Follow up", lead_id=lead.id))
        lead, customer, contact, opp = lead_service.convert_lead(
            self.db, self.context, lead.id, crm.ConvertLeadIn(opportunity_name="Deal", opportunity_value=250))

        self.assertEqual((lead.status, lead.converted_customer_id, lead.converted_opportunity_id),
                         ("Converted", customer.id, opp.id))
        self.assertEqual((contact.customer_id, contact.email), (customer.id, "person@example.test"))
        self.assertEqual((opp.name, float(opp.value), opp.stage, opp.lead_id), ("Deal", 250, "Qualified", lead.id))
        self.assertEqual(opp.owner_user_id, self.context.user.id)
        self.db.refresh(task)
        self.assertEqual((task.opportunity_id, task.lead_id), (opp.id, None))

        listed = routes_leads.list_leads(self.context, self.db)[0]
        self.assertEqual(listed.converted_opportunity_id, opp.id)
        self.assertEqual(listed.owner_name, "Test user")
        with self.assertRaises(ConflictError):
            lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn())

    def test_conversion_reuses_a_same_named_customer(self):
        existing = crm_service.find_or_create_customer(self.db, self.context, "Coastal Traders")
        self.db.commit()
        lead = self.lead(company_name="coastal traders")
        _, customer, _, _ = lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn())
        self.assertEqual(customer.id, existing.id)

    def test_lost_leads_and_direct_converted_status_are_refused(self):
        lead = self.lead()
        with self.assertRaises(ConflictError):
            lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(status="Converted"))
        lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(status="Lost"))
        with self.assertRaises(ConflictError):
            lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn())

    # --- Ownership --------------------------------------------------------------

    def test_owner_must_belong_to_the_same_company(self):
        outsider = self.make_context(["*"])  # a separate tenant
        lead = self.lead()
        with self.assertRaises(ConflictError):
            lead_service.assign_lead(self.db, self.context, lead.id, outsider.user.id)
        with self.assertRaises(ConflictError):
            self.lead(owner_user_id=outsider.user.id)
        colleague = self.make_context(["crm.lead.read"], *self._tenant_and_company())
        assigned = lead_service.assign_lead(self.db, self.context, lead.id, colleague.user.id)
        self.assertEqual(assigned.owner_user_id, colleague.user.id)
        self.assertIsNone(lead_service.assign_lead(self.db, self.context, lead.id, None).owner_user_id)

    def test_assigning_someone_else_needs_the_assign_permission(self):
        writer = self.make_context(["crm.lead.write", "crm.lead.read"], *self._tenant_and_company())
        colleague = self.make_context([], *self._tenant_and_company())
        with self.assertRaises(HTTPException) as denied:
            routes_leads.create_lead(crm.LeadIn(name="X", owner_user_id=colleague.user.id), writer, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        mine = routes_leads.create_lead(crm.LeadIn(name="Y", owner_user_id=writer.user.id), writer, self.db)
        self.assertEqual(mine.owner_user_id, writer.user.id)
        with self.assertRaises(HTTPException):
            require_permission("crm.lead.assign")(writer)

    def test_assignee_list_accepts_any_crm_read_permission(self):
        reader = self.make_context(["crm.activity.read"], *self._tenant_and_company())
        self.assertIs(require_any_permission("crm.lead.read", "crm.activity.read")(reader), reader)
        names = {a.display_name for a in routes_activities.list_assignees(reader, self.db)}
        self.assertIn("Test user", names)

    # --- Activities -------------------------------------------------------------

    def test_follow_up_lifecycle_and_summaries(self):
        lead = self.lead()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        task = activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Email", subject="Reply", due_at=past, lead_id=lead.id))
        self.assertEqual(task.due_date, past.date())
        self.assertEqual(task.owner_id, self.context.user.id)  # lead unowned -> creator
        listed = routes_activities.list_activities(False, self.context, self.db)[0]
        self.assertTrue(listed.is_overdue)
        summary = routes_leads.list_leads(self.context, self.db)[0]
        self.assertEqual((summary.open_activities, summary.overdue_activities), (1, 1))

        activity_service.update_activity(self.db, self.context, task.id, crm.ActivityUpdate(done=True))
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(routes_activities.list_activities(True, self.context, self.db), [])
        activity_service.update_activity(self.db, self.context, task.id, crm.ActivityUpdate(done=False, due_date=None))
        self.assertIsNone(task.completed_at)
        self.assertIsNone(task.due_at)
        self.assertFalse(crm_service.is_overdue(task))

    def test_dated_follow_up_is_overdue_only_after_its_day_ends(self):
        lead = self.lead()
        today = datetime.now(timezone.utc).date()
        due_today = activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Call", subject="Today", due_date=today, lead_id=lead.id))
        due_yesterday = activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Call", subject="Yesterday", due_date=today - timedelta(days=1), lead_id=lead.id))
        self.assertFalse(crm_service.is_overdue(due_today))
        self.assertTrue(crm_service.is_overdue(due_yesterday))

    def test_customer_notes_have_a_label_and_no_due_time(self):
        customer = crm_service.find_or_create_customer(self.db, self.context, "Customer notes")
        self.db.commit()
        activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Note", subject="Customer note", customer_id=customer.id))
        result = routes_activities.list_activities(False, self.context, self.db)[0]
        self.assertEqual(result.related_label, "Customer: Customer notes")
        self.assertIsNone(result.due_at)
        self.assertFalse(result.is_overdue)

    # --- Opportunity -> Quotation -------------------------------------------------

    def test_quoting_an_opportunity_links_it_and_moves_it_to_proposal(self):
        customer = crm_service.find_or_create_customer(self.db, self.context, "Quote customer")
        self.db.add(Item(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                         sku="T-1", name="Test item", uom="box", unit_price=100, stock_qty=50))
        self.db.commit()
        opp = opportunity_service.create_opportunity(self.db, self.context,
            crm.OpportunityIn(customer_id=customer.id, name="Deal"))
        body = crm.OpportunityQuotationIn(lines=[{"item_name": "Test item", "qty": 3}])

        result = routes_opportunities.quote_opportunity(opp.id, body, self.context, self.db)
        self.assertEqual((result["total"], result["opportunity_id"]), (300.0, str(opp.id)))
        listed = routes_opportunities.list_opportunities(self.context, self.db)[0]
        self.assertEqual((listed.stage, [q.number for q in listed.quotations]), ("Proposal", [result["number"]]))

        opportunity_service.update_opportunity(self.db, self.context, opp.id, crm.OpportunityUpdate(stage="Lost"))
        with self.assertRaises(HTTPException) as refused:
            routes_opportunities.quote_opportunity(opp.id, body, self.context, self.db)
        self.assertEqual(refused.exception.status_code, 422)

    # --- Upgrades -----------------------------------------------------------------

    def test_retired_crm_permissions_are_expanded(self):
        tenant_id = self.context.tenant_id
        role = Role(tenant_id=tenant_id, name="Legacy", permissions=["crm.read", "crm.write", "crm.assign", "audit.read"])
        self.db.add(role)
        self.db.commit()
        ensure_dev_schema()
        self.db.refresh(role)
        self.assertNotIn("crm.read", role.permissions)
        for p in ("audit.read", "crm.lead.read", "crm.activity.write", "crm.lead.convert",
                  "crm.lead.assign", "crm.opportunity.assign"):
            self.assertIn(p, role.permissions)
        self.assertEqual(len(role.permissions), len(set(role.permissions)))

    def test_existing_prototype_records_survive_upgrade(self):
        lead = self.db.execute(select(Lead).where(Lead.name == "Legacy contact")).scalar_one_or_none()
        if lead is None:
            self.skipTest("No legacy fixture in fresh database")
        self.assertEqual(lead.company_name, "Legacy company")
        opp = self.db.execute(select(Opportunity).where(Opportunity.name == "Legacy deal")).scalar_one()
        self.assertEqual(opp.value, 125)
        self.assertEqual(opp.stage, "Qualified")
        self.assertEqual(opp.customer.name, "Legacy customer")
        task = self.db.execute(select(Activity).where(Activity.subject == "Legacy task")).scalar_one()
        self.assertEqual(task.type, "Call")
        self.assertEqual(task.due_date, date(2026, 9, 20))
        self.assertIsNotNone(task.due_at)
        self.assertTrue(task.done)
        self.assertIsNotNone(task.completed_at)

    def _tenant_and_company(self):
        return self.db.get(Tenant, self.context.tenant_id), self.db.get(Company, self.context.company_id)
