"""Integration checks for the CRM API (leads, opportunities, activities).

Run against an empty disposable database only:
  CRM_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import (
    routes_activities, routes_ask, routes_contacts, routes_crm, routes_customers, routes_imports, routes_leads,
    routes_opportunities,
)
from app.core.database import SessionLocal
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.core.dev_schema import ensure_dev_schema
from app.domain import activity_service, crm_service, customer_service, lead_service, opportunity_service, sales_service
from app.domain.duplicates import DuplicateError
from app.domain.errors import ConflictError
from app.models.crm import Activity, Contact, Lead, Opportunity
from app.models.identity import Role, User
from app.models.sales import Customer, Item, Quotation
from app.models.tenant import Company, Tenant
from app.schemas import crm
from app.schemas.ask import AskRequest, ConfirmRequest
from app.schemas.customers import CustomerIn, CustomerUpdate
from app.models.audit import AuditEvent
from app.toolgateway import tools_crm, tools_sales  # noqa: F401 — registers the tools


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

    def leads_out(self, context=None, **kw):
        args = {"q": "", "status_": "", "owner": "", "limit": None, "offset": 0, **kw}
        return routes_leads.list_leads(Response(), **args, context=context or self.context, db=self.db)

    def opps_out(self, context=None, **kw):
        args = {"q": "", "stage": "", "owner": "", "closed_since": None, "stale": False, "limit": None,
                "offset": 0, **kw}
        return routes_opportunities.list_opportunities(Response(), **args, context=context or self.context, db=self.db)

    def activities_out(self, **kw):
        args = {"show": "all", "open_only": False, "owner": "", "lead_id": None, "customer_id": None,
                "opportunity_id": None, "limit": None, "offset": 0, **kw}
        return routes_activities.list_activities(Response(), **args, context=self.context, db=self.db)

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

        listed = self.leads_out()[0]
        self.assertEqual(listed.converted_opportunity_id, opp.id)
        self.assertEqual(listed.owner_name, "Test user")
        with self.assertRaises(ConflictError):
            lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn())

    def test_conversion_never_merges_by_name_but_offers_the_match(self):
        existing = crm_service.find_or_create_customer(self.db, self.context, "Coastal Traders")
        self.db.add(Contact(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                            customer_id=existing.id, name="Ravi", phone="0495 2701234", email=""))
        self.db.commit()
        lead = self.lead(company_name="coastal traders", phone="+91 495 270 1234")

        matches = lead_service.customer_matches(self.db, self.context, lead.id)
        self.assertEqual([m["id"] for m in matches], [existing.id])
        self.assertEqual(matches[0]["reasons"], ["Same name", "Contact Ravi has this phone"])

        # No customer_id: a new customer, even though the name matches.
        _, customer, _, _ = lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn())
        self.assertNotEqual(customer.id, existing.id)

        # Picking the existing one links to it.
        other = self.lead(name="Anu", company_name="Coastal Traders", phone="98470 99999")
        _, linked, contact, _ = lead_service.convert_lead(
            self.db, self.context, other.id, crm.ConvertLeadIn(customer_id=existing.id))
        self.assertEqual((linked.id, contact.customer_id), (existing.id, existing.id))

    def test_new_lead_and_customer_warn_about_duplicates(self):
        first = self.lead(name="Nisha", phone="+91 94460 44556", email="Nisha@Example.test")
        with self.assertRaises(DuplicateError) as caught:
            self.lead(name="Nisha R", phone="09446044556")
        self.assertEqual(caught.exception.matches[0]["id"], str(first.id))
        with self.assertRaises(DuplicateError):
            self.lead(name="Someone", email="nisha@example.test")
        # Via the route: 409 with the matches, so the form can offer "create anyway".
        with self.assertRaises(HTTPException) as http:
            routes_leads.create_lead(crm.LeadIn(name="Nisha", phone="9446044556"), self.context, self.db)
        self.assertEqual(http.exception.status_code, 409)
        self.assertEqual(http.exception.detail["duplicates"][0]["id"], str(first.id))
        again = self.lead(name="Nisha (2nd branch)", phone="9446044556", allow_duplicate=True)
        self.assertNotEqual(again.id, first.id)

        customer_service.create_customer(self.db, self.context, CustomerIn(name="Rahman Traders"))
        with self.assertRaises(DuplicateError):
            customer_service.create_customer(self.db, self.context, CustomerIn(name=" rahman traders "))
        customer_service.create_customer(self.db, self.context, CustomerIn(name="Rahman Traders", allow_duplicate=True))

    def test_history_records_who_changed_what_and_where(self):
        lead = self.lead(name="Hist", company_name="History Co")
        lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(status="Contacted"))
        other = self.make_context(["*"], tenant=self.db.get(Tenant, self.context.tenant_id),
                                  company=self.db.get(Company, self.context.company_id))
        other.user.display_name = "Fathima"
        lead_service.assign_lead(self.db, self.context, lead.id, other.user.id)
        _, _, _, opp = lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn(opportunity_name="Big"))
        # Ask ERP actions are marked as such.
        preview = routes_ask.ask(AskRequest(text="log a call with History Co — no answer"), self.context, self.db)
        routes_ask.confirm(ConfirmRequest(preview_token=preview["preview_token"]), self.context, self.db)
        opportunity_service.update_opportunity(self.db, self.context, opp.id,
                                               crm.OpportunityUpdate(stage="Lost", lost_reason="Price too high"))

        timeline = routes_opportunities.opportunity_timeline(opp.id, self.context, self.db)
        actions = [(e["action"], e["source"]) for e in timeline]
        self.assertEqual(actions, [
            ("stage_changed", "app"), ("activity_logged", "ask_erp"), ("converted", "app"), ("created", "app"),
            ("owner_changed", "app"), ("status_changed", "app"), ("created", "app"),
        ])
        lost = timeline[0]
        self.assertEqual(lost["changes"]["stage"], ["Qualified", "Lost"])
        self.assertIn("Lost reason: — → Price too high", lost["summary"])
        self.assertEqual(lost["actor_name"], "Test user")
        self.assertEqual(timeline[4]["summary"], "Owner: Unassigned → Fathima")

        # Someone who can read leads but not deals doesn't see the deal's history.
        reader = self.make_context(["crm.lead.read"], tenant=self.db.get(Tenant, self.context.tenant_id),
                                   company=self.db.get(Company, self.context.company_id))
        lead_only = routes_leads.lead_timeline(lead.id, reader, self.db)
        self.assertEqual({e["record_type"] for e in lead_only}, {"lead"})

    def test_stale_limits_are_per_company_and_zero_turns_them_off(self):
        deal = self.deal()
        deal.stage_changed_at = deal.created_at = crm_service.now_utc() - timedelta(days=8)
        self.db.commit()
        self.assertTrue(self.opps_out()[0].is_stale)  # default New = 7 days
        # The SQL filter (lists, summary) agrees with the per-deal flag.
        self.assertEqual(len(self.opps_out(stale=True)), 1)
        self.assertEqual(routes_crm.summary("", 90, self.context, self.db).stale_deals, 1)

        crm_service.set_stale_limits(self.db, self.context, {"New": 10})
        self.assertFalse(self.opps_out()[0].is_stale)
        self.assertEqual(len(self.opps_out(stale=True)), 0)
        crm_service.set_stale_limits(self.db, self.context, {"New": 0})
        self.assertFalse(self.opps_out()[0].is_stale)
        self.assertEqual(len(self.opps_out(stale=True)), 0)

        # A recent follow-up revives it for the SQL filter too.
        crm_service.set_stale_limits(self.db, self.context, {"New": 7})
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Checked in", opportunity_id=deal.id, done=True))
        self.assertEqual((len(self.opps_out(stale=True)), self.opps_out()[0].is_stale), (0, False))
        self.assertEqual(crm_service.stale_limits(self.db, self.context)["Qualified"], 10)
        with self.assertRaises(ConflictError):
            crm_service.set_stale_limits(self.db, self.context, {"Won": 3})
        with self.assertRaises(HTTPException):  # needs crm.settings.write
            require_permission("crm.settings.write")(self.make_context(["crm.opportunity.read"]))

    def test_lists_page_filter_and_count(self):
        for i in range(5):
            self.lead(name=f"Paged {i}", company_name=f"Paging Co {i}", phone=f"98470 0000{i}")
        response = Response()
        page = routes_leads.list_leads(response, q="paging co", status_="open", owner="", limit=2, offset=2,
                                       context=self.context, db=self.db)
        self.assertEqual(response.headers["X-Total-Count"], "5")
        self.assertEqual([l.name for l in page], ["Paged 2", "Paged 1"])
        self.assertEqual(len(self.leads_out(q="Paging Kannur")), 0)  # every word must match
        self.assertEqual(len(self.leads_out(q="co 3")), 1)
        self.assertEqual(len(self.leads_out(owner="unassigned")), 5)
        self.assertEqual(len(self.leads_out(owner="me")), 0)

        old = self.deal(name="Old win")
        opportunity_service.update_opportunity(self.db, self.context, old.id, crm.OpportunityUpdate(stage="Won"))
        old.stage_changed_at = crm_service.now_utc() - timedelta(days=200)
        self.db.commit()
        self.deal(name="Open one")
        board = self.opps_out(closed_since=date.today() - timedelta(days=90))
        self.assertEqual([o.name for o in board], ["Open one"])
        self.assertEqual([o.name for o in self.opps_out(stage="closed")], ["Old win"])

    def test_summary_filters_deals_by_owner_and_reports_recent_closes(self):
        mine = self.deal(name="Mine", value=500, owner_user_id=self.context.user.id)
        self.deal(name="Nobody's", value=700)
        opportunity_service.update_opportunity(self.db, self.context, mine.id,
                                               crm.OpportunityUpdate(stage="Lost", lost_reason="Price too high"))
        team = routes_crm.summary("", 90, self.context, self.db)
        self.assertEqual((team.open_deals, team.recent_lost, team.recent_lost_value), (1, 1, 500))
        self.assertEqual([(r.reason, r.count) for r in team.lost_reasons], [("Price too high", 1)])
        self.assertEqual([o.name for o in team.recently_closed], ["Mine"])
        own = routes_crm.summary("me", 90, self.context, self.db)
        self.assertEqual((own.open_deals, own.recent_lost), (0, 1))
        self.assertEqual(routes_crm.summary("unassigned", 90, self.context, self.db).open_value, 700)

    def test_customer_and_contact_lists_page_and_search(self):
        for i in range(4):
            customer = crm_service.find_or_create_customer(self.db, self.context, f"Paging Traders {i}")
            self.db.add(Contact(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                                customer_id=customer.id, name=f"Person {i}", phone=f"9000000{i:03d}"))
        self.db.commit()
        response = Response()
        page = routes_customers.list_customers(response, q="paging traders", active=None, limit=2, offset=2,
                                               context=self.context, db=self.db)
        self.assertEqual((response.headers["X-Total-Count"], [c.name for c in page]),
                         ("4", ["Paging Traders 2", "Paging Traders 3"]))
        response = Response()
        contacts = routes_contacts.list_contacts(response, q="traders 1", customer_id=None, limit=50, offset=0,
                                                 context=self.context, db=self.db)
        self.assertEqual(([c.name for c in contacts], response.headers["X-Total-Count"]), (["Person 1"], "1"))
        only = routes_contacts.list_contacts(Response(), q="", customer_id=contacts[0].customer_id, limit=None,
                                             offset=0, context=self.context, db=self.db)
        self.assertEqual([c.name for c in only], ["Person 1"])

    def test_summary_counts_without_loading_every_record(self):
        deal = self.deal(value=1000)
        self.lead(name="No owner")
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Late", opportunity_id=deal.id, due_date=date.today() - timedelta(days=2)))
        out = routes_crm.summary("", 90, self.context, self.db)
        self.assertEqual((out.open_deals, out.open_value, out.overdue_followups), (1, 1000, 1))
        self.assertEqual(out.unassigned, 2)  # the lead and the deal
        self.assertEqual(out.overdue_items[0].related_label, f"Opportunity: {deal.name}")

        reader = self.make_context(["crm.activity.read"], tenant=self.db.get(Tenant, self.context.tenant_id),
                                   company=self.db.get(Company, self.context.company_id))
        limited = routes_crm.summary("", 90, reader, self.db)
        self.assertEqual((limited.open_deals, limited.unassigned, limited.overdue_followups), (0, 0, 1))

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
        listed = self.activities_out()[0]
        self.assertTrue(listed.is_overdue)
        summary = self.leads_out()[0]
        self.assertEqual((summary.open_activities, summary.overdue_activities), (1, 1))

        activity_service.update_activity(self.db, self.context, task.id, crm.ActivityUpdate(done=True))
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(self.activities_out(show="open"), [])
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
        result = self.activities_out()[0]
        self.assertEqual(result.related_label, "Customer: Customer notes")
        self.assertIsNone(result.due_at)
        self.assertFalse(result.is_overdue)

    # --- Quotation numbers ------------------------------------------------------

    def test_quotation_numbers_count_per_tenant_and_year(self):
        year = datetime.now(timezone.utc).year
        other = self.make_context(["*"])  # a second business, its own tenant
        first = sales_service.next_quotation_number(self.db, self.context)
        self.assertEqual(first, f"QT-{year}-00001")
        self.assertEqual(sales_service.next_quotation_number(self.db, other), f"QT-{year}-00001")
        self.assertEqual(sales_service.next_quotation_number(self.db, self.context), f"QT-{year}-00002")
        self.db.commit()

        # A tenant with quotations from before the counter continues after its highest number.
        legacy = self.make_context(["*"])
        customer = crm_service.find_or_create_customer(self.db, legacy, "Legacy")
        self.db.add(Quotation(tenant_id=legacy.tenant_id, company_id=legacy.company_id, number=f"QT-{year}-00041",
                              customer_id=customer.id, subtotal=0, total=0, created_by=legacy.user.id))
        self.db.commit()
        self.assertEqual(sales_service.next_quotation_number(self.db, legacy), f"QT-{year}-00042")
        self.db.commit()

        # The same number is fine in another tenant, refused within one.
        other_customer = crm_service.find_or_create_customer(self.db, other, "Other")
        self.db.add(Quotation(tenant_id=other.tenant_id, company_id=other.company_id, number=f"QT-{year}-00041",
                              customer_id=other_customer.id, subtotal=0, total=0, created_by=other.user.id))
        self.db.commit()
        self.db.add(Quotation(tenant_id=legacy.tenant_id, company_id=legacy.company_id, number=f"QT-{year}-00041",
                              customer_id=customer.id, subtotal=0, total=0, created_by=legacy.user.id))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

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
        listed = self.opps_out()[0]
        self.assertEqual((listed.stage, [q.number for q in listed.quotations]), ("Proposal", [result["number"]]))

        opportunity_service.update_opportunity(self.db, self.context, opp.id, crm.OpportunityUpdate(stage="Lost", lost_reason="No budget"))
        with self.assertRaises(HTTPException) as refused:
            routes_opportunities.quote_opportunity(opp.id, body, self.context, self.db)
        self.assertEqual(refused.exception.status_code, 422)

    # --- Lost reasons, stage dates, idle deals -------------------------------

    def deal(self, **fields):
        customer = crm_service.find_or_create_customer(self.db, self.context, fields.pop("customer", "Deal customer"))
        self.db.commit()
        return opportunity_service.create_opportunity(self.db, self.context,
            crm.OpportunityIn(customer_id=customer.id, name=fields.pop("name", "Deal"), **fields))

    def test_losing_a_deal_needs_a_reason_and_reopening_clears_it(self):
        opp = self.deal()
        first_change = opp.stage_changed_at
        with self.assertRaises(ConflictError):
            opportunity_service.update_opportunity(self.db, self.context, opp.id, crm.OpportunityUpdate(stage="Lost"))
        lost = opportunity_service.update_opportunity(self.db, self.context, opp.id,
            crm.OpportunityUpdate(stage="Lost", lost_reason="  Price too high "))
        self.assertEqual((lost.stage, lost.lost_reason), ("Lost", "Price too high"))
        self.assertGreater(lost.stage_changed_at, first_change)
        # Editing a lost deal without touching the stage doesn't demand a new reason.
        opportunity_service.update_opportunity(self.db, self.context, opp.id, crm.OpportunityUpdate(value=10))
        reopened = opportunity_service.update_opportunity(self.db, self.context, opp.id,
            crm.OpportunityUpdate(stage="Negotiation"))
        self.assertEqual(reopened.lost_reason, "")

    def test_untouched_deals_go_stale_and_any_touch_revives_them(self):
        opp = self.deal()
        old = datetime.now(timezone.utc) - timedelta(days=30)
        opp.created_at = old
        opp.stage_changed_at = old
        self.db.commit()
        listed = self.opps_out()[0]
        self.assertTrue(listed.is_stale)
        self.assertEqual(listed.idle_days, 30)

        activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="Call", subject="Checked in", opportunity_id=opp.id, done=True))
        listed = self.opps_out()[0]
        self.assertFalse(listed.is_stale)
        self.assertEqual(listed.idle_days, 0)

        opportunity_service.update_opportunity(self.db, self.context, opp.id,
            crm.OpportunityUpdate(stage="Won"))
        opp.stage_changed_at = old
        self.db.commit()
        # Closed deals never count as stale.
        self.assertFalse(self.opps_out()[0].is_stale)

    def test_logging_a_call_that_already_happened(self):
        lead = self.lead()
        call = activity_service.create_activity(self.db, self.context,
            crm.ActivityIn(type="WhatsApp", subject="WhatsApp — sent price list", lead_id=lead.id, done=True))
        self.assertTrue(call.done)
        self.assertIsNotNone(call.completed_at)
        self.assertFalse(crm_service.is_overdue(call))
        self.assertEqual(self.leads_out()[0].open_activities, 0)

    # --- Ask ERP: CRM commands ------------------------------------------------------

    def ask(self, text, context=None):
        return routes_ask.ask(AskRequest(text=text, timezone="Asia/Kolkata"), context or self.context, self.db)

    def confirm(self, preview, context=None):
        return routes_ask.confirm(ConfirmRequest(preview_token=preview["preview_token"]), context or self.context, self.db)

    def test_ask_logs_a_call_after_confirmation_only(self):
        lead = self.lead(name="Nisha R", company_name="Kannur Tiles & Co")
        preview = self.ask("called nisha, she wants 200 boxes")
        self.assertEqual(preview["type"], "action_preview")
        self.assertIn({"label": "On", "value": "Lead: Kannur Tiles & Co (Nisha R)"}, preview["lines"])
        self.assertEqual(self.db.execute(select(Activity).where(Activity.lead_id == lead.id)).first(), None)

        result = self.confirm(preview)
        call = self.db.execute(select(Activity).where(Activity.lead_id == lead.id)).scalar_one()
        self.assertEqual((call.type, call.done, call.notes), ("Call", True, "she wants 200 boxes"))
        self.assertIn("Logged", result["result_summary"])
        audit = self.db.execute(select(AuditEvent).where(AuditEvent.tool_name == "crm.log_activity.v1",
                                                         AuditEvent.tenant_id == self.context.tenant_id)).scalar_one()
        self.assertTrue(audit.confirmed)
        with self.assertRaises(HTTPException):  # single use
            self.confirm(preview)

    def test_ask_schedules_in_the_users_timezone_on_the_only_open_deal(self):
        opp = self.deal(customer="Malabar Hardware", name="Branch expansion", owner_user_id=self.context.user.id)
        preview = self.ask("remind me to call Malabar tomorrow at 3pm")
        self.assertIn({"label": "On", "value": "Deal: Branch expansion"}, preview["lines"])
        self.confirm(preview)
        task = self.db.execute(select(Activity).where(Activity.opportunity_id == opp.id)).scalar_one()
        local = task.due_at.astimezone(ZoneInfo("Asia/Kolkata"))
        self.assertEqual((local.hour, local.minute), (15, 0))
        self.assertEqual(local.date(), (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).date())
        self.assertFalse(task.done)

    def test_ask_asks_which_one_when_a_name_is_ambiguous(self):
        crm_service.find_or_create_customer(self.db, self.context, "Rahman Traders")
        self.lead(name="Rahman K", company_name="Rahman Steels")
        self.db.commit()
        reply = self.ask("log a call with rahman")
        self.assertEqual(reply["type"], "clarify")
        self.assertEqual(len(reply["options"]), 2)
        picked = self.ask(reply["options"][0])
        self.assertEqual(picked["type"], "action_preview")
        unknown = self.ask("log a call with Zebra Foods")
        self.assertEqual(unknown["type"], "clarify")

    def test_ask_closing_a_deal_as_lost_needs_a_reason(self):
        opp = self.deal(customer="Feroke Tiles", name="Monsoon stock")
        reply = self.ask("mark Feroke lost")
        self.assertEqual(reply["type"], "clarify")
        preview = self.ask(reply["options"][0])
        self.assertEqual(preview["type"], "action_preview")
        self.confirm(preview)
        self.db.refresh(opp)
        self.assertEqual((opp.stage, opp.lost_reason), ("Lost", "Price too high"))

    def test_ask_answers_reads_and_respects_permissions(self):
        lead = self.lead()
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Chase payment", lead_id=lead.id,
            due_at=datetime.now(timezone.utc) - timedelta(days=2)))
        answer = self.ask("what's overdue today")
        self.assertEqual(answer["type"], "answer")
        self.assertEqual(answer["items"][0]["title"], "Chase payment")
        self.assertEqual(answer["items"][0]["tone"], "bad")

        viewer = self.make_context(["crm.lead.read"], *self._tenant_and_company())
        self.assertEqual(self.ask("what's overdue today", viewer)["type"], "denied")
        self.assertEqual(self.ask("log a call with Customer Co", viewer)["type"], "denied")
        other = self.make_context(["*"], *self._tenant_and_company())
        preview = self.ask("log a call with Customer Co")
        with self.assertRaises(HTTPException) as stolen:
            self.confirm(preview, other)
        self.assertEqual(stolen.exception.status_code, 403)

    # --- CSV import -----------------------------------------------------------------

    def import_csv(self, kind, text, commit=False, context=None):
        return routes_imports.import_csv(kind, routes_imports.ImportIn(csv=text), commit, context or self.context, self.db)

    def test_lead_import_matches_loose_headers_and_skips_duplicates(self):
        self.lead(name="Existing", phone="+91 94460 44556")
        colleague = self.make_context([], *self._tenant_and_company())
        csv_text = (
            "\ufeffContact Person;Business;Mobile No;E-mail;Remarks;Assigned To\n"
            "Nisha R;Kannur Tiles;09446044556;;dup of existing;\n"          # same number, other format
            "Shafeeq;Calicut Build Mart;98470 11223;shafeeq@example.test;;\n"
            ";Beypore Traders;98470 99999;;company only;Test user\n"
            "Anil;;98470 11223;;same as row 3;\n"                             # duplicate inside the file
            "Bad Email;X;;not-an-email;;\n"
            "Ghost;Y;;;;Nobody\n"
            ";;;;;\n"                                                             # blank line, ignored
        )
        preview = self.import_csv("leads", csv_text)
        by_line = {r["line"]: r for r in preview["rows"]}
        self.assertEqual(preview["columns"]["phone"], "Mobile No")
        self.assertEqual((preview["total"], preview["ok"], preview["duplicates"], preview["errors"]), (6, 2, 2, 2))
        self.assertEqual(by_line[2]["status"], "duplicate")
        self.assertEqual(by_line[4]["values"]["name"], "Beypore Traders")  # company used as the name
        self.assertEqual(by_line[5]["status"], "duplicate")
        self.assertIn("valid email", by_line[6]["messages"][0])
        self.assertIn("Nobody", by_line[7]["messages"][0])
        self.assertEqual(len(lead_service.list_leads(self.db, self.context)[0]), 1)  # dry run wrote nothing

        done = self.import_csv("leads", csv_text, commit=True)
        self.assertEqual(done["created"], 2)
        leads = {l.name: l for l in lead_service.list_leads(self.db, self.context)[0]}
        self.assertEqual(leads["Shafeeq"].source, "Import")
        self.assertEqual(leads["Shafeeq"].owner_user_id, self.context.user.id)  # importer owns by default
        imported = routes_leads.lead_timeline(leads["Shafeeq"].id, self.context, self.db)[0]
        self.assertEqual((imported["action"], imported["source"]), ("created", "import"))
        self.assertEqual(self.import_csv("leads", csv_text)["ok"], 0)  # re-import finds them all

        writer = self.make_context(["crm.lead.write"], *self._tenant_and_company())
        other_owner = self.import_csv("leads", f"name,phone,owner\nZed,9000000001,{colleague.user.username}\n", context=writer)
        self.assertEqual(other_owner["errors"], 1)

    def test_customer_import_validates_gstin_and_amounts(self):
        crm_service.find_or_create_customer(self.db, self.context, "Rahman Traders")
        self.db.commit()
        result = self.import_csv("customers", (
            "Party Name,GSTIN/UIN,Credit Limit\n"
            "Coastal Traders,27aapfu0939f1zv,\"₹1,50,000\"\n"
            "rahman traders,,\n"
            "Typo Co,27AAPFU0939F1ZX,0\n"
            "Minus,,-5\n"
        ), commit=True)
        by_line = {r["line"]: r for r in result["rows"]}
        self.assertEqual((result["created"], result["duplicates"], result["errors"]), (1, 1, 2))
        coastal = self.db.execute(select(Customer).where(Customer.name == "Coastal Traders",
                                                         Customer.tenant_id == self.context.tenant_id)).scalar_one()
        self.assertEqual((coastal.gstin, float(coastal.credit_limit)), ("27AAPFU0939F1ZV", 150000.0))
        self.assertIn("check character", by_line[4]["messages"][0])

    def test_import_rejects_unusable_files_and_missing_permission(self):
        for bad in ("", "phone,email\n123,a@b.c\n", "name\n"):
            with self.assertRaises(HTTPException) as refused:
                self.import_csv("leads", bad)
            self.assertEqual(refused.exception.status_code, 422)
        reader = self.make_context(["crm.lead.read"], *self._tenant_and_company())
        with self.assertRaises(HTTPException) as denied:
            self.import_csv("leads", "name\nA\n", context=reader)
        self.assertEqual(denied.exception.status_code, 403)

    # --- GSTIN -------------------------------------------------------------------

    def test_gstin_is_normalised_and_checksummed(self):
        self.assertEqual(CustomerIn(name="A", gstin=" 27aapfu0939f1zv ").gstin, "27AAPFU0939F1ZV")
        self.assertEqual(CustomerIn(name="A").gstin, "")
        for bad in ("27AAPFU0939F1ZX", "27AAPFU0939F1Z", "99AAPFU0939F1ZV"):
            with self.assertRaises(ValidationError):
                CustomerIn(name="A", gstin=bad)
        self.assertIsNone(CustomerUpdate(name="B").gstin)
        self.assertEqual(CustomerUpdate(gstin="").gstin, "")

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
