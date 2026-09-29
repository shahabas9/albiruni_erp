"""Integration checks for the two CRM interfaces sharing PostgreSQL records.

Run against an empty disposable database only:
  CRM_MERGE_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.core.dev_schema import ensure_dev_schema
from app.domain import activity_service, crm_service, lead_service, opportunity_service
from app.models.crm import Contact, Lead, Opportunity
from app.models.identity import Role, User
from app.models.sales import Customer
from app.models.tenant import Company, Tenant
from app.schemas import crm as local
from app.api import routes_activities, routes_crm, routes_leads, routes_opportunities


@unittest.skipUnless(os.environ.get("CRM_MERGE_TEST_DB") == "1", "requires a disposable PostgreSQL database")
class CrmMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_dev_schema()
        ensure_dev_schema()  # Upgrades must remain safe to repeat.

    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        tenant = Tenant(name="Merge test", code=uuid4().hex)
        self.db.add(tenant)
        self.db.flush()
        company = Company(tenant_id=tenant.id, name="Test", code="test")
        role = Role(tenant_id=tenant.id, name="Test", permissions=["*"])
        self.db.add_all([company, role])
        self.db.flush()
        user = User(tenant_id=tenant.id, company_id=company.id, role_id=role.id,
                    username=uuid4().hex, display_name="Test", hashed_password="unused")
        self.db.add(user)
        self.db.flush()
        self.context = RequestContext(user, tenant.id, company.id, ["*"], "en-IN")
        self.db.commit()

    def local_lead(self):
        return lead_service.create_lead(self.db, self.context, local.LeadIn(
            name="Contact", company_name="Customer", notes="Retained notes"))

    def test_local_conversion_is_visible_in_workspace(self):
        lead = self.local_lead()
        task = activity_service.create_activity(self.db, self.context,
            local.ActivityIn(type="Note", subject="Follow up", lead_id=lead.id))
        lead, customer, contact, opp = lead_service.convert_lead(
            self.db, self.context, lead.id, local.ConvertLeadIn(opportunity_value=250))
        self.assertEqual(lead.converted_opportunity_id, opp.id)
        self.assertEqual(opp.lead_id, lead.id)
        self.assertEqual(contact.customer_id, customer.id)
        self.assertEqual(task.opportunity_id, opp.id)
        self.assertIsNone(task.lead_id)
        result = routes_crm.list_opportunities(self.context, self.db)[0]
        self.assertEqual((result.title, result.expected_value), (opp.name, 250))
        crm_service.assert_quotable(opp)
        crm_service.advance_on_quotation(opp)
        self.assertEqual(opp.stage, "Proposal")
        self.assertEqual(routes_crm.list_activities(True, self.context, self.db)[0].due_at, None)

    def test_workspace_conversion_preserves_local_contacts_and_fields(self):
        lead = crm_service.create_lead(self.db, self.context, name="Person", organization="Company",
            phone="123", email="person@example.test", source="Web", owner_id=self.context.user.id)
        opp = crm_service.convert_lead(self.db, self.context, lead,
            title="Deal", expected_value=400, expected_close=date.today())
        self.db.commit()
        local_lead = routes_leads.list_leads(self.context, self.db)[0]
        self.assertEqual(local_lead.company_name, "Company")
        self.assertEqual(local_lead.converted_customer_id, opp.customer_id)
        contacts = self.db.execute(select(Contact).where(Contact.customer_id == opp.customer_id)).scalars().all()
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].email, "person@example.test")
        result = routes_opportunities.list_opportunities(self.context, self.db)[0]
        self.assertEqual((result.name, result.value, result.stage), ("Deal", 400, "Qualified"))
        opportunity_service.update_opportunity(self.db, self.context, opp.id, local.OpportunityUpdate(value=900))
        self.assertEqual(routes_crm.list_opportunities(self.context, self.db)[0].expected_value, 900)

    def test_activity_updates_remain_consistent_across_interfaces(self):
        lead = self.local_lead()
        due = datetime.now(timezone.utc) - timedelta(hours=1)
        task = crm_service.create_activity(self.db, self.context, kind="Email", subject="Reply",
            due_at=due, lead_id=lead.id, opportunity_id=None, owner_id=None)
        self.db.commit()
        result = routes_activities.list_activities(self.context, self.db)[0]
        self.assertEqual((result.type, result.due_date, result.done), ("Email", due.date(), False))
        self.assertTrue(crm_service.is_overdue(task))
        activity_service.update_activity(self.db, self.context, task.id, local.ActivityUpdate(done=True))
        self.assertEqual(crm_service.list_activities(self.db, self.context, open_only=True), [])
        self.assertIsNotNone(task.completed_at)
        activity_service.update_activity(self.db, self.context, task.id, local.ActivityUpdate(done=False, due_date=None))
        self.assertIsNone(task.completed_at)
        self.assertIsNone(task.due_at)
        self.assertFalse(crm_service.is_overdue(task))
        routes_crm.complete_activity(task.id, self.context, self.db)
        self.assertTrue(routes_activities.list_activities(self.context, self.db)[0].done)

    def test_customer_notes_are_readable_from_workspace(self):
        customer = Customer(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                            name="Customer notes")
        self.db.add(customer)
        self.db.commit()
        activity_service.create_activity(self.db, self.context, local.ActivityIn(
            type="Note", subject="Customer note", customer_id=customer.id))
        result = routes_crm.list_activities(True, self.context, self.db)[0]
        self.assertEqual(result.related_name, customer.name)
        self.assertIsNone(result.due_at)
        routes_crm.complete_activity(result.id, self.context, self.db)
        self.assertTrue(routes_activities.list_activities(self.context, self.db)[0].done)

    def test_existing_prototype_records_survive_upgrade(self):
        lead = self.db.execute(select(Lead).where(Lead.name == "Legacy contact")).scalar_one_or_none()
        if lead is None:
            self.skipTest("No legacy fixture in fresh database")
        self.assertEqual(lead.company_name, "Legacy company")
        opp = self.db.execute(select(Opportunity).where(Opportunity.name == "Legacy deal")).scalar_one()
        self.assertEqual(opp.value, 125)
        self.assertEqual(opp.stage, "Qualified")
        self.assertEqual(opp.customer.name, "Legacy customer")
        from app.models.crm import Activity
        task = self.db.execute(select(Activity).where(Activity.subject == "Legacy task")).scalar_one()
        self.assertEqual(task.type, "Call")
        self.assertEqual(task.due_date, date(2026, 9, 20))
        self.assertIsNotNone(task.due_at)
        self.assertTrue(task.done)
        self.assertIsNotNone(task.completed_at)
