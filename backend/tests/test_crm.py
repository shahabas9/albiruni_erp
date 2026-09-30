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
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Activity, Contact, CrmEvent, Lead, Opportunity
from app.models.identity import Role, User
from app.models.sales import Customer, Item, Quotation
from app.models.tenant import Company, Tenant
from app.schemas import crm
from app.schemas.ask import AskRequest, ConfirmRequest
from app.schemas.customers import CustomerIn, CustomerUpdate
from app.models.audit import AuditEvent
from app.ai import crm_resolver
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
        reader = self.make_context(["crm.lead.read", "crm.records.all"],
                                   tenant=self.db.get(Tenant, self.context.tenant_id),
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

        reader = self.make_context(["crm.activity.read", "crm.records.all"],
                                   tenant=self.db.get(Tenant, self.context.tenant_id),
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

    # --- Lead rotation ----------------------------------------------------------

    def colleague(self, name, permissions=("*",)):
        other = self.make_context(list(permissions), *self._tenant_and_company())
        other.user.display_name = name
        self.db.commit()
        return other.user

    def test_rotation_hands_new_leads_out_in_turn(self):
        asha, binu = self.colleague("Asha"), self.colleague("Binu")
        self.assertFalse(routes_crm.get_rotation(self.context, self.db)["enabled"])
        with self.assertRaises(HTTPException):  # can't switch it on empty
            routes_crm.put_rotation(crm.RotationIn(enabled=True, user_ids=[]), self.context, self.db)
        status = routes_crm.put_rotation(crm.RotationIn(enabled=True, user_ids=[asha.id, binu.id]), self.context, self.db)
        self.assertEqual(status["next_user_name"], "Asha")

        owners = [self.lead(name=f"R{i}", assign_by_rotation=True).owner_user_id for i in range(3)]
        self.assertEqual(owners, [asha.id, binu.id, asha.id])
        self.assertIn("assigned by rotation to Asha",
                      routes_leads.lead_timeline(self.leads_out(q="R0")[0].id, self.context, self.db)[0]["summary"])
        # Without the flag the form's owner applies as before.
        self.assertEqual(self.lead(name="Mine", owner_user_id=self.context.user.id).owner_user_id, self.context.user.id)

        # A deactivated member is skipped, not handed leads.
        self.db.get(User, binu.id).active = False
        self.db.commit()
        self.assertEqual([self.lead(name=f"S{i}", assign_by_rotation=True).owner_user_id for i in range(2)],
                         [asha.id, asha.id])

        # CSV rows with no Owner go round too; rows naming an owner don't.
        self.db.get(User, binu.id).active = True
        self.db.commit()
        self.import_csv("leads", "name,phone,owner\nCsv A,9000011111,\nCsv B,9000022222,Asha\nCsv C,9000033333,\n",
                        commit=True)
        by_name = {l.name: l.owner_user_id for l in self.leads_out(q="Csv")}
        self.assertEqual(by_name, {"Csv A": binu.id, "Csv B": asha.id, "Csv C": asha.id})

        # Off: rotation leads are unassigned; outsiders can't join; only settings writers change it.
        routes_crm.put_rotation(crm.RotationIn(enabled=False, user_ids=[asha.id]), self.context, self.db)
        self.assertIsNone(self.lead(name="Off", assign_by_rotation=True).owner_user_id)
        with self.assertRaises(HTTPException):
            routes_crm.put_rotation(crm.RotationIn(enabled=True, user_ids=[self.make_context(["*"]).user.id]),
                                    self.context, self.db)
        with self.assertRaises(HTTPException):
            require_permission("crm.settings.write")(self.make_context(["crm.lead.read"]))

    # --- Sales targets ----------------------------------------------------------

    def test_targets_compare_each_persons_wins_with_their_month(self):
        asha = self.colleague("Asha")
        month = crm_service.now_utc().date().replace(day=1)
        label = f"{month:%Y-%m}"
        routes_crm.put_targets(crm.TargetsIn(month=label, targets=[
            crm.TargetIn(user_id=asha.id, amount=100000), crm.TargetIn(user_id=self.context.user.id, amount=50000),
        ]), self.context, self.db)

        won = self.deal(name="Won big", value=60000, owner_user_id=asha.id)
        opportunity_service.update_opportunity(self.db, self.context, won.id, crm.OpportunityUpdate(stage="Won"))
        old = self.deal(name="Won last year", value=999, owner_user_id=asha.id)
        opportunity_service.update_opportunity(self.db, self.context, old.id, crm.OpportunityUpdate(stage="Won"))
        old.stage_changed_at = crm_service.now_utc() - timedelta(days=400)
        self.deal(name="Closing soon", value=20000, probability_pct=50, owner_user_id=asha.id,
                  expected_close_date=month + timedelta(days=5))
        self.db.commit()

        report = routes_crm.get_targets(label, self.context, self.db)
        rows = {r["name"]: r for r in report["rows"]}
        self.assertEqual((rows["Asha"]["target"], rows["Asha"]["won_value"], rows["Asha"]["won_count"],
                          rows["Asha"]["pct"], rows["Asha"]["forecast"]), (100000, 60000, 1, 60, 10000))
        self.assertEqual((rows["Test user"]["won_value"], rows["Test user"]["pct"]), (0, 0))
        self.assertEqual((report["team_target"], report["team_won"], report["team_pct"]), (150000, 60000, 40))

        # 0 removes a target; another month is separate; bad input is refused.
        routes_crm.put_targets(crm.TargetsIn(month=label, targets=[crm.TargetIn(user_id=asha.id, amount=0)]),
                               self.context, self.db)
        self.assertIsNone({r["name"]: r for r in routes_crm.get_targets(label, self.context, self.db)["rows"]}["Asha"]["pct"])
        self.assertEqual(routes_crm.get_targets("2020-01", self.context, self.db)["team_target"], 0)
        with self.assertRaises(HTTPException):
            routes_crm.get_targets("2026-13", self.context, self.db)
        with self.assertRaises(HTTPException):  # not this company's user
            routes_crm.put_targets(crm.TargetsIn(month=label, targets=[
                crm.TargetIn(user_id=self.make_context(["*"]).user.id, amount=5)]), self.context, self.db)
        with self.assertRaises(HTTPException):
            require_permission("crm.settings.write")(self.make_context(["crm.opportunity.read"]))

    # --- Tags and custom fields ---------------------------------------------------

    def field(self, record_type, label, field_type, options=()):
        return routes_crm.create_custom_field(
            crm.CustomFieldIn(record_type=record_type, label=label, field_type=field_type, options=list(options)),
            self.context, self.db)

    def test_tags_are_normalized_counted_and_filterable(self):
        lead = self.lead(name="Tagged", tags=["VIP", " vip ", "Kerala  North", ""])
        self.assertEqual(lead.tags, ["vip", "kerala north"])
        self.lead(name="Other", tags=["vip"])
        self.assertEqual({l.name for l in self.leads_out(tag="VIP")}, {"Tagged", "Other"})
        self.assertEqual([l.name for l in self.leads_out(tag="kerala north")], ["Tagged"])
        counts = routes_crm.list_tags("lead", self.context, self.db)
        self.assertEqual(counts[0], {"tag": "vip", "count": 2})

        lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(tags=["vip", "hot"]))
        latest = routes_leads.lead_timeline(lead.id, self.context, self.db)[0]
        self.assertEqual(latest["summary"], "Tags: vip, kerala north → vip, hot")
        with self.assertRaises(ConflictError):
            lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(tags=[f"t{i}" for i in range(21)]))

        deal = self.deal(name="Tagged deal", tags=["Export"])
        self.assertEqual([o.name for o in self.opps_out(tag="export")], ["Tagged deal"])
        customer = customer_service.create_customer(self.db, self.context, CustomerIn(name="Tag Co", tags=["Distributor"]))
        page = routes_customers.list_customers(Response(), q="", active=None, tag="distributor", limit=None, offset=0,
                                               context=self.context, db=self.db)
        self.assertEqual([c.id for c in page], [customer.id])
        self.assertEqual(deal.tags, ["export"])

    def test_custom_fields_validate_values_and_show_in_history(self):
        budget = self.field("lead", "Budget", "number")
        city = self.field("lead", "City", "select", ["Kozhikode", "Kannur"])
        visit = self.field("lead", "Site visit", "date")
        self.field("lead", "GST registered", "checkbox")
        self.assertEqual((budget.key, city.key, visit.key), ("budget", "city", "site_visit"))
        with self.assertRaises(HTTPException):  # same name twice
            self.field("lead", "budget", "text")
        with self.assertRaises(HTTPException):  # a dropdown needs choices
            self.field("lead", "Region", "select")

        lead = self.lead(name="Custom", custom={"budget": "2,50,000", "city": "Kannur", "gst_registered": True})
        self.assertEqual(lead.custom, {"budget": 250000, "city": "Kannur", "gst_registered": True})
        for bad in ({"budget": "lots"}, {"city": "Delhi"}, {"site_visit": "31/12/2026"}, {"nope": 1},
                    {"gst_registered": "yes"}):
            with self.assertRaises(ConflictError, msg=bad):
                lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(custom=bad))
        self.db.rollback()

        lead = lead_service.update_lead(self.db, self.context, lead.id,
                                        crm.LeadUpdate(custom={"budget": None, "site_visit": "2026-12-31"}))
        self.assertEqual(lead.custom, {"city": "Kannur", "gst_registered": True, "site_visit": "2026-12-31"})
        summary = routes_leads.lead_timeline(lead.id, self.context, self.db)[0]["summary"]
        self.assertEqual(summary, "Budget: 250000 → —; Site visit: — → 2026-12-31")

        # Archiving hides the field but keeps what's saved; its values can't be set any more.
        routes_crm.update_custom_field(city.id, crm.CustomFieldUpdate(active=False), self.context, self.db)
        self.assertNotIn("city", [f.key for f in routes_crm.list_custom_fields("lead", False, self.context, self.db)])
        lead = lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(custom={"budget": 5}))
        self.assertEqual(lead.custom["city"], "Kannur")
        with self.assertRaises(ConflictError):
            lead_service.update_lead(self.db, self.context, lead.id, crm.LeadUpdate(custom={"city": "Kozhikode"}))
        self.db.rollback()

        # Fields belong to one record type; deals and customers have their own.
        stage = self.field("opportunity", "Competitor", "text")
        deal = self.deal(name="With competitor", custom={stage.key: "Acme"})
        self.assertEqual(self.opps_out(q="With competitor")[0].custom, {"competitor": "Acme"})
        with self.assertRaises(ConflictError):
            self.deal(name="Wrong field", custom={"budget": 1})
        self.db.rollback()
        with self.assertRaises(HTTPException):
            require_permission("crm.settings.write")(self.make_context(["crm.lead.read"]))
        self.assertEqual(deal.custom, {"competitor": "Acme"})

    def test_csv_import_reads_a_tags_column(self):
        self.import_csv("leads", "name,phone,tags\nCsv Tag,9011122233,VIP; Kerala | hot\n", commit=True)
        self.assertEqual(self.leads_out(q="Csv Tag")[0].tags, ["vip", "kerala", "hot"])

    # --- Attachments -------------------------------------------------------------

    def test_attachments_store_download_and_respect_permissions(self):
        import io
        import tempfile
        from app.api import routes_attachments
        from app.core.config import settings
        from app.domain import attachment_service

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_dir, old_mb = settings.attachments_dir, settings.attachment_max_mb
        settings.attachments_dir, settings.attachment_max_mb = folder.name, 1
        self.addCleanup(setattr, settings, "attachments_dir", old_dir)
        self.addCleanup(setattr, settings, "attachment_max_mb", old_mb)

        lead = self.lead(name="With files")
        saved = attachment_service.save(self.db, self.context, "lead", lead.id, "../../etc/quote <v2>.pdf",
                                        "application/pdf", io.BytesIO(b"%PDF-1.4 hello"))
        self.assertEqual((saved["filename"], saved["size_bytes"], saved["uploaded_by_name"]),
                         ("quote v2.pdf", 14, "Test user"))
        listed = routes_attachments.list_attachments("lead", lead.id, self.context, self.db)
        self.assertEqual([a["id"] for a in listed], [saved["id"]])
        self.assertEqual(routes_leads.lead_timeline(lead.id, self.context, self.db)[0]["summary"], "Attached quote v2.pdf")

        response = routes_attachments.download_attachment(saved["id"], self.context, self.db)
        self.assertEqual(open(response.path, "rb").read(), b"%PDF-1.4 hello")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.media_type, "application/octet-stream")

        for name, data in (("run.exe", b"MZ"), ("empty.txt", b""), ("big.bin", b"x" * (1024 * 1024 + 1))):
            with self.assertRaises(ConflictError, msg=name):
                attachment_service.save(self.db, self.context, "lead", lead.id, name, None, io.BytesIO(data))
        # Refused uploads leave nothing behind.
        leftovers = [p for p in __import__("pathlib").Path(folder.name).rglob("*") if p.is_file()]
        self.assertEqual(len(leftovers), 1)

        # Read needs the record's read permission; upload/delete need write; other companies see nothing.
        reader = self.make_context(["crm.lead.read", "crm.records.all"], *self._tenant_and_company())
        self.assertEqual(len(routes_attachments.list_attachments("lead", lead.id, reader, self.db)), 1)
        with self.assertRaises(HTTPException) as denied:
            routes_attachments.delete_attachment(saved["id"], reader, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as other:
            routes_attachments.list_attachments("lead", lead.id, self.make_context(["*"]), self.db)
        self.assertEqual(other.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            routes_attachments.list_attachments("lead", lead.id, self.make_context(["crm.opportunity.read"],
                                                *self._tenant_and_company()), self.db)

        routes_attachments.delete_attachment(saved["id"], self.context, self.db)
        self.assertEqual(routes_attachments.list_attachments("lead", lead.id, self.context, self.db), [])
        self.assertFalse(any(p.is_file() for p in __import__("pathlib").Path(folder.name).rglob("*")))

        customer = crm_service.find_or_create_customer(self.db, self.context, "Files Co")
        self.db.commit()
        attachment_service.save(self.db, self.context, "customer", customer.id, "gst.png", "image/png", io.BytesIO(b"png"))
        self.assertEqual(len(routes_attachments.list_attachments("customer", customer.id, self.context, self.db)), 1)

    # --- Web enquiry form ----------------------------------------------------------

    def test_web_form_creates_leads_safely(self):
        from app.domain import web_form
        from app.domain.errors import NotFoundError

        web_form.reset_rate_limits()
        self.addCleanup(web_form.reset_rate_limits)
        off = routes_crm.get_web_form(self.context, self.db)
        self.assertEqual((off["enabled"], off["key"]), (False, None))
        on = routes_crm.put_web_form(crm.WebFormIn(enabled=True, source="Website form"), self.context, self.db)
        key = on["key"]
        self.assertTrue(on["enabled"] and len(key) >= 30)

        result = web_form.submit(self.db, key, {"name": "Visitor", "phone": "+91 90000 12345",
                                                "message": "Need 200 boxes"}, "10.0.0.1")
        self.assertTrue(result["created"])
        lead = lead_service.get_lead(self.db, self.context, result["lead_id"])
        self.assertEqual((lead.source, lead.notes, lead.owner_user_id), ("Website form", "Need 200 boxes", None))
        entry = routes_leads.lead_timeline(lead.id, self.context, self.db)[0]
        self.assertEqual((entry["source"], entry["actor_name"]), ("web_form", None))

        # The same person again: a note on their lead, not a second lead.
        again = web_form.submit(self.db, key, {"name": "Visitor", "phone": "9000012345", "message": "Any update?"},
                                "10.0.0.2")
        self.assertEqual((again["created"], again["lead_id"]), (False, lead.id))
        notes = self.activities_out(lead_id=lead.id)
        self.assertEqual([a.subject for a in notes], ["Web enquiry: Any update?"])

        # New leads follow the rotation when it's on.
        asha = self.colleague("Asha")
        routes_crm.put_rotation(crm.RotationIn(enabled=True, user_ids=[asha.id]), self.context, self.db)
        rotated = web_form.submit(self.db, key, {"name": "Rotated", "email": "r@example.test"}, "10.0.0.3")
        self.assertEqual(lead_service.get_lead(self.db, self.context, rotated["lead_id"]).owner_user_id, asha.id)

        # Bad input, bots, floods, wrong or disabled keys.
        for bad in ({"name": "No contact"}, {"phone": "9000099999"}, {"name": "X", "email": "nope"},
                    {"name": "X", "phone": "123"}, {"name": "X" * 161, "phone": "9000099999"}):
            with self.assertRaises(ConflictError, msg=bad):
                web_form.submit(self.db, key, bad, "10.0.0.4")
        bot = web_form.submit(self.db, key, {"name": "Bot", "phone": "9000077777", "website": "http://spam"}, "10.0.0.5")
        self.assertEqual((bot["created"], bot["lead_id"]), (False, None))
        self.assertEqual(self.leads_out(q="Bot"), [])
        for i in range(web_form.PER_IP_LIMIT[0]):
            try:
                web_form.submit(self.db, key, {"name": f"Flood {i}", "phone": f"91000{i:05d}"}, "10.0.0.6")
            except ConflictError:
                pass
        with self.assertRaises(web_form.RateLimited):
            web_form.submit(self.db, key, {"name": "One more", "phone": "9100099999"}, "10.0.0.6")
        with self.assertRaises(NotFoundError):
            web_form.submit(self.db, "not-the-key", {"name": "X", "phone": "9000099999"}, "10.0.0.7")
        old_key = key
        key = routes_crm.new_web_form_key(self.context, self.db)["key"]
        self.assertNotEqual(key, old_key)
        with self.assertRaises(NotFoundError):
            web_form.form_for_key(self.db, old_key)
        routes_crm.put_web_form(crm.WebFormIn(enabled=False), self.context, self.db)
        with self.assertRaises(NotFoundError):
            web_form.form_for_key(self.db, key)
        with self.assertRaises(HTTPException):
            require_permission("crm.settings.write")(self.make_context(["crm.lead.read"]))

    # --- Record visibility --------------------------------------------------------

    def test_without_see_all_people_only_see_their_own_records(self):
        rep_perms = ["crm.lead.read", "crm.lead.write", "crm.opportunity.read", "crm.opportunity.write",
                     "crm.activity.read", "crm.activity.write"]
        rep = self.make_context(rep_perms, *self._tenant_and_company())
        other = self.make_context(rep_perms, *self._tenant_and_company())
        mine = self.lead(name="Rep lead", company_name="Rep Co", phone="9123400001", owner_user_id=rep.user.id)
        theirs = self.lead(name="Other lead", company_name="Secret Co", phone="9123400002",
                           owner_user_id=other.user.id)
        my_deal = self.deal(name="Rep deal", owner_user_id=rep.user.id, value=100)
        their_deal = self.deal(name="Secret deal", owner_user_id=other.user.id, value=900)
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Chase secret", opportunity_id=their_deal.id,
            due_date=date.today() - timedelta(days=1)))
        on_mine = activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Chase mine", opportunity_id=my_deal.id, owner_id=other.user.id))

        self.assertEqual([l.name for l in self.leads_out(context=rep)], ["Rep lead"])
        self.assertEqual([o.name for o in self.opps_out(context=rep)], ["Rep deal"])
        with self.assertRaises(HTTPException) as hidden:
            routes_leads.get_lead(theirs.id, rep, self.db)
        self.assertEqual(hidden.exception.status_code, 404)
        with self.assertRaises(NotFoundError):  # can't change it either
            opportunity_service.update_opportunity(self.db, rep, their_deal.id, crm.OpportunityUpdate(value=1))
        # Follow-ups: theirs hidden, but one someone else owns on MY deal is visible.
        rows = routes_activities.list_activities(Response(), show="all", open_only=False, owner="", lead_id=None,
                                                 customer_id=None, opportunity_id=None, limit=None, offset=0,
                                                 context=rep, db=self.db)
        self.assertEqual([a.subject for a in rows], ["Chase mine"])
        self.assertEqual(activity_service.get_activity(self.db, rep, on_mine.id).id, on_mine.id)

        summary = routes_crm.summary("", 90, rep, self.db)
        self.assertEqual((summary.open_deals, summary.open_value, summary.overdue_followups, summary.unassigned),
                         (1, 100, 0, 0))
        self.assertEqual([r["name"] for r in routes_crm.get_targets("", rep, self.db)["rows"]], ["Test user"])

        # A duplicate warning says a match exists without revealing whose.
        with self.assertRaises(DuplicateError) as dup:
            lead_service.create_lead(self.db, rep, crm.LeadIn(name="Copy", phone="9123400002"))
        self.assertEqual(dup.exception.matches[0]["label"], "A lead owned by someone else")
        self.assertEqual(dup.exception.matches[0]["id"], "")

        # Ask ERP only finds your own records and has no team view.
        self.assertEqual({m.label for m in crm_resolver.find(self.db, rep, "Secret Co deal", kinds=("lead", "opportunity"))}, set())
        answer = routes_ask.ask(AskRequest(text="what's overdue for the team"), rep, self.db)
        self.assertNotIn("Chase secret", str(answer))

        # With the permission (or "*"), everything as before.
        boss = self.make_context(rep_perms + ["crm.records.all"], *self._tenant_and_company())
        self.assertEqual({l.name for l in self.leads_out(context=boss)} >= {"Rep lead", "Other lead"}, True)
        self.assertEqual(len(self.opps_out(context=self.context)), 2)
        self.assertEqual(mine.owner_user_id, rep.user.id)

    # --- Notifications ------------------------------------------------------------

    def test_notifications_reach_the_right_people(self):
        from app.api import routes_notifications
        from app.domain import notifications, web_form

        asha = self.colleague("Asha")
        asha_ctx = RequestContext(asha, self.context.tenant_id, self.context.company_id, ["*"], "en-IN")
        inbox = lambda ctx=asha_ctx: routes_notifications.list_notifications(False, 30, ctx, self.db)  # noqa: E731

        lead = self.lead(name="For Asha", owner_user_id=asha.id)
        mine = self.lead(name="Mine")  # created and owned by me: nobody to tell
        lead_service.assign_lead(self.db, self.context, mine.id, asha.id)
        deal = self.deal(name="Asha deal", owner_user_id=asha.id)
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(
            type="Call", subject="Ring them", lead_id=lead.id, owner_id=asha.id, due_date=date.today()))
        titles = [n.title for n in inbox()["items"]]
        self.assertEqual(titles, ["Follow-up for you: Call: Ring them", "New deal for you: Asha deal",
                                  "Lead assigned to you: Customer Co", "New lead for you: Customer Co"])
        self.assertEqual(inbox()["unread"], 4)
        self.assertEqual(routes_notifications.list_notifications(False, 30, self.context, self.db)["unread"], 0)

        # Overdue alerts: once, to the owner; again only after the due time changes.
        late = activity_service.create_activity(self.db, asha_ctx, crm.ActivityIn(
            type="Task", subject="Send price list", opportunity_id=deal.id, due_date=date.today() - timedelta(days=1)))
        self.assertEqual(notifications.raise_overdue_alerts(self.db) >= 1, True)
        notifications.raise_overdue_alerts(self.db)
        overdue = [n for n in inbox()["items"] if n.kind == "followup_overdue"]
        self.assertEqual([n.title for n in overdue], ["Overdue: Send price list"])
        self.assertEqual(overdue[0].link, f"/crm?opp={deal.id}")
        activity_service.update_activity(self.db, asha_ctx, late.id,
                                         crm.ActivityUpdate(due_date=date.today() - timedelta(days=1)))
        notifications.raise_overdue_alerts(self.db)
        self.assertEqual(len([n for n in inbox()["items"] if n.kind == "followup_overdue"]), 2)

        # Web enquiries with no owner go to people who can hand leads out.
        web_form.reset_rate_limits()
        key = routes_crm.put_web_form(crm.WebFormIn(enabled=True), self.context, self.db)["key"]
        web_form.submit(self.db, key, {"name": "Visitor", "phone": "9444455555", "message": "Hi"}, "10.1.1.1")
        me = routes_notifications.list_notifications(False, 30, self.context, self.db)["items"]
        self.assertEqual(me[0].title, "New web enquiry: Visitor")

        # Mark read; email goes to people with an address, skipped otherwise.
        routes_notifications.mark_read(routes_notifications.ReadIn(ids=[inbox()["items"][0].id]), asha_ctx, self.db)
        self.assertEqual(inbox()["unread"], 6)  # 4 + 2 overdue + the web enquiry (she can hand leads out) - 1 read
        routes_notifications.mark_read(routes_notifications.ReadIn(), asha_ctx, self.db)
        self.assertEqual(inbox()["unread"], 0)

        from app.core.config import settings
        self.addCleanup(setattr, settings, "smtp_host", settings.smtp_host)
        self.addCleanup(setattr, settings, "smtp_from", settings.smtp_from)
        settings.smtp_host, settings.smtp_from = "smtp.test", "crm@example.test"
        routes_notifications.put_preferences(routes_notifications.PreferencesIn(email="asha@example.test"),
                                             asha_ctx, self.db)
        sent = []
        outcome = notifications.send_pending_emails(self.db, send=lambda to, subject, text: sent.append((to, subject)))
        self.assertTrue(all(to == "asha@example.test" for to, _ in sent) and len(sent) == 7)
        self.assertGreaterEqual(outcome["skipped"], 1)  # my own notifications: no address
        self.assertEqual(notifications.send_pending_emails(self.db, send=lambda *a: sent.append(a))["sent"], 0)
        with self.assertRaises(ValidationError):
            routes_notifications.PreferencesIn(email="not an email")

    # --- Delete and merge ---------------------------------------------------------

    def test_delete_refuses_history_others_depend_on(self):
        from app.domain import record_admin

        lead = self.lead(name="Throwaway")
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(type="Call", subject="x", lead_id=lead.id))
        routes_leads.delete_lead(lead.id, self.context, self.db)
        self.assertEqual(self.leads_out(q="Throwaway"), [])
        self.assertEqual(self.db.execute(select(Activity).where(Activity.lead_id == lead.id)).first(), None)
        events = self.db.execute(select(CrmEvent).where(CrmEvent.record_id == lead.id)).scalars().all()
        self.assertIn("deleted", [e.action for e in events])  # the trail survives the record

        converted = self.lead(name="Converted one")
        _, customer, contact, opp = lead_service.convert_lead(self.db, self.context, converted.id, crm.ConvertLeadIn())
        with self.assertRaises(HTTPException):
            routes_leads.delete_lead(converted.id, self.context, self.db)
        with self.assertRaises(ConflictError):  # has a deal (and a converted lead)
            record_admin.delete_customer(self.db, self.context, customer.id)

        quoted = self.deal(name="Quoted deal")
        self.db.add(Quotation(tenant_id=self.context.tenant_id, company_id=self.context.company_id,
                              number=f"QT-T-{uuid4().hex[:6]}", customer_id=quoted.customer_id, opportunity_id=quoted.id,
                              subtotal=0, total=0, created_by=self.context.user.id))
        self.db.commit()
        with self.assertRaises(ConflictError):
            record_admin.delete_opportunity(self.db, self.context, quoted.id)
        record_admin.delete_opportunity(self.db, self.context, opp.id)  # no quotes: fine, lead link cleared
        self.db.refresh(converted)
        self.assertIsNone(converted.converted_opportunity_id)

        routes_contacts.delete_contact(contact.id, self.context, self.db)
        empty = crm_service.find_or_create_customer(self.db, self.context, "Empty Co")
        self.db.commit()
        record_admin.delete_customer(self.db, self.context, empty.id)
        with self.assertRaises(HTTPException):
            require_permission("crm.lead.delete")(self.make_context(["crm.lead.write"]))

    def test_merging_folds_everything_into_the_kept_record(self):
        from app.domain import record_admin

        keep = self.lead(name="Nisha", company_name="Kannur Tiles", phone="9447000001", tags=["vip"], notes="First")
        dupe = lead_service.create_lead(self.db, self.context, crm.LeadIn(
            name="Nisha R", company_name="", email="nisha@example.test", phone="09447000001", tags=["export"],
            notes="Second", allow_duplicate=True))
        activity_service.create_activity(self.db, self.context, crm.ActivityIn(type="Call", subject="On dupe", lead_id=dupe.id))
        groups = routes_leads.lead_duplicates(self.context, self.db)
        self.assertEqual([{l.id for l in g["leads"]} for g in groups], [{keep.id, dupe.id}])

        merged = routes_leads.merge_lead(keep.id, crm.MergeIn(remove_id=dupe.id), self.context, self.db)
        self.assertEqual((merged.email, merged.company_name, merged.tags), ("nisha@example.test", "Kannur Tiles", ["vip", "export"]))
        self.assertEqual(lead_service.get_lead(self.db, self.context, keep.id).notes, "First\n\nSecond")
        self.assertEqual([a.subject for a in self.activities_out(lead_id=keep.id)], ["On dupe"])
        history_actions = [e["action"] for e in routes_leads.lead_timeline(keep.id, self.context, self.db)]
        self.assertEqual(history_actions[0], "merged")
        self.assertEqual(history_actions.count("created"), 2)  # dupe's history came along
        with self.assertRaises(HTTPException):
            routes_leads.get_lead(dupe.id, self.context, self.db)
        self.assertEqual(routes_leads.lead_duplicates(self.context, self.db), [])

        # Customers: contacts, deals, quotations and converted leads all move over.
        a = customer_service.create_customer(self.db, self.context, CustomerIn(name="Rahman Traders"))
        b = customer_service.create_customer(self.db, self.context, CustomerIn(name="rahman  traders", gstin="32ABCDE1234F1Z9",
                                                                                allow_duplicate=True))
        self.db.add(Contact(tenant_id=self.context.tenant_id, company_id=self.context.company_id, customer_id=b.id, name="Rafi"))
        deal = opportunity_service.create_opportunity(self.db, self.context, crm.OpportunityIn(customer_id=b.id, name="B deal"))
        groups = routes_customers.customer_duplicates(self.context, self.db)
        self.assertEqual([{c.id for c in g["customers"]} for g in groups], [{a.id, b.id}])
        kept = routes_customers.merge_customer(a.id, crm.MergeIn(remove_id=b.id), self.context, self.db)
        self.assertEqual(kept.gstin, "32ABCDE1234F1Z9")
        self.db.refresh(deal)
        self.assertEqual(deal.customer_id, a.id)
        self.assertEqual(self.db.execute(select(Contact).where(Contact.customer_id == a.id)).scalar_one().name, "Rafi")
        self.assertIsNone(self.db.get(Customer, b.id))
        with self.assertRaises(HTTPException):
            routes_customers.merge_customer(a.id, crm.MergeIn(remove_id=a.id), self.context, self.db)

    # --- Customer page ------------------------------------------------------------

    def test_customer_page_brings_everything_together(self):
        customer = customer_service.create_customer(self.db, self.context, CustomerIn(name="Page Co", credit_limit=5000))
        customer_service.update_customer(self.db, self.context, customer.id, CustomerUpdate(credit_limit=8000, tags=["key account"]))
        lead = self.lead(name="Page lead", company_name="Page Co")
        lead_service.convert_lead(self.db, self.context, lead.id, crm.ConvertLeadIn(customer_id=customer.id, opportunity_value=300))
        won = opportunity_service.create_opportunity(self.db, self.context, crm.OpportunityIn(customer_id=customer.id, name="Won one", value=1000))
        opportunity_service.update_opportunity(self.db, self.context, won.id, crm.OpportunityUpdate(stage="Won"))
        self.deal(name="Elsewhere")  # another customer's deal

        overview = routes_customers.customer_overview(customer.id, self.context, self.db)
        self.assertEqual((overview["open_deals"], overview["open_value"], overview["won_deals"], overview["won_value"],
                          overview["contacts"], overview["quotations"]), (1, 300, 1, 1000, 1, 0))
        deals = self.opps_out(customer_id=customer.id)
        self.assertEqual({o.name for o in deals}, {"Won one", "Page Co — new opportunity"})

        timeline = routes_customers.customer_timeline(customer.id, self.context, self.db)
        summaries = [e["summary"] for e in timeline]
        self.assertIn("Credit limit: ₹5,000 → ₹8,000; Tags: — → key account", summaries)
        self.assertIn("Customer created: Page Co", summaries)
        self.assertIn("Deal created: Won one (stage New)", summaries)
        self.assertEqual({e["record_type"] for e in timeline}, {"customer", "opportunity", "lead"})

        # Someone who can't see the deals doesn't get their numbers or history here.
        rep = self.make_context(["sales.customer.read", "crm.opportunity.read"], *self._tenant_and_company())
        self.assertEqual(routes_customers.customer_overview(customer.id, rep, self.db)["open_deals"], 0)
        self.assertEqual({e["record_type"] for e in routes_customers.customer_timeline(customer.id, rep, self.db)}, {"customer"})

    # --- Export -------------------------------------------------------------------

    def test_exports_follow_filters_visibility_and_are_audited(self):
        import csv as csvlib
        from starlette.requests import Request
        from app.api import routes_exports

        def export(kind, context=None, **params):
            query = "&".join(f"{k}={v}" for k, v in params.items()).encode()
            request = Request({"type": "http", "method": "GET", "path": f"/api/exports/{kind}.csv",
                               "query_string": query, "headers": []})
            response = routes_exports.export_csv(kind, request, context or self.context, self.db)
            text = response.body.decode("utf-8")
            self.assertTrue(text.startswith("\ufeff"))
            return list(csvlib.reader(text[1:].splitlines()))

        budget = self.field("lead", "Budget", "number")
        self.lead(name="Export me", company_name="=HYPERLINK(\"http://x\")", tags=["vip"], custom={budget.key: 5000})
        self.lead(name="Not me", tags=["cold"])
        rows = export("leads", tag="vip")
        self.assertEqual(rows[0][:3] + rows[0][-1:], ["Name", "Company", "Phone", "Budget"])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1][0], rows[1][1], rows[1][7], rows[1][-1]),
                         ("Export me", "'=HYPERLINK(\"http://x\")", "vip", "5000"))

        self.deal(name="Exported deal", value=1000, probability_pct=40)
        deal_rows = export("opportunities")
        self.assertEqual(deal_rows[1][:6], ["Exported deal", "Deal customer", "New", "1000.0", "40", "400.0"])

        audit = self.db.execute(select(AuditEvent).where(AuditEvent.tool_name == "crm.export_records.v1")
                                .order_by(AuditEvent.created_at.desc())).scalars().first()
        self.assertEqual((audit.result_summary, audit.validation_result), ("Exported 1 opportunities (filters: none)", "PASS"))

        rep = self.make_context(["crm.lead.read", "crm.export"], *self._tenant_and_company())
        self.assertEqual(len(export("leads", rep)), 1)  # header only: owns none of them
        with self.assertRaises(HTTPException) as no_export:
            export("leads", self.make_context(["crm.lead.read", "crm.records.all"], *self._tenant_and_company()))
        self.assertEqual(no_export.exception.status_code, 403)
        with self.assertRaises(HTTPException) as no_read:
            export("customers", rep)
        self.assertEqual(no_read.exception.status_code, 403)

    # --- Bulk actions -------------------------------------------------------------

    def test_bulk_actions_apply_the_single_edit_rules(self):
        from app.api import routes_notifications

        asha = self.colleague("Asha")
        asha_ctx = RequestContext(asha, self.context.tenant_id, self.context.company_id, ["*"], "en-IN")
        leads = [self.lead(name=f"Bulk {i}", company_name=f"Bulk Co {i}") for i in range(3)]
        converted = self.lead(name="Bulk converted", company_name="Bulk Co converted")
        lead_service.convert_lead(self.db, self.context, converted.id, crm.ConvertLeadIn(create_opportunity=False))

        out = routes_leads.bulk_lead(crm.BulkIn(action="assign", ids=[l.id for l in leads] + [converted.id],
                                                value=str(asha.id)), self.context, self.db)
        self.assertEqual((out["matched"], out["done"]), (4, 3))
        self.assertIn("converted", out["skipped"][0]["reason"])
        self.assertEqual({l.owner_user_id for l in self.leads_out(q="Bulk Co", status_="open")}, {asha.id})
        inbox = routes_notifications.list_notifications(False, 30, asha_ctx, self.db)["items"]
        self.assertEqual([n.title for n in inbox if "assigned" in n.title], ["3 leads assigned to you"])  # one alert, not three

        # "All matching" uses the list filters; tags go through normal validation and history.
        out = routes_leads.bulk_lead(crm.BulkIn(action="add_tag", filters={"q": "Bulk Co", "status": "open"}, value="Q4 Push"),
                                     self.context, self.db)
        self.assertEqual(out["done"], 3)
        self.assertEqual([l.name for l in self.leads_out(tag="q4 push")], ["Bulk 2", "Bulk 1", "Bulk 0"])
        self.assertEqual(routes_leads.lead_timeline(leads[0].id, self.context, self.db)[0]["summary"], "Tags: — → q4 push")
        routes_leads.bulk_lead(crm.BulkIn(action="status", ids=[leads[0].id], value="Contacted"), self.context, self.db)
        self.assertEqual(lead_service.get_lead(self.db, self.context, leads[0].id).status, "Contacted")

        # Deals: moving to Lost needs a reason, like one at a time.
        deals = [self.deal(name=f"Bulk deal {i}") for i in range(2)]
        refused = routes_opportunities.bulk_opportunity(crm.BulkIn(action="stage", ids=[d.id for d in deals], value="Lost"),
                                                        self.context, self.db)
        self.assertEqual((refused["done"], len(refused["skipped"])), (0, 2))
        lost = routes_opportunities.bulk_opportunity(
            crm.BulkIn(action="stage", ids=[d.id for d in deals], value="Lost", lost_reason="Budget cut"), self.context, self.db)
        self.assertEqual(lost["done"], 2)

        customer = customer_service.create_customer(self.db, self.context, CustomerIn(name="Bulk customer"))
        routes_customers.bulk_customer(crm.BulkIn(action="deactivate", ids=[customer.id]), self.context, self.db)
        self.assertFalse(customer_service.get_customer(self.db, self.context, customer.id).active)

        # Permissions per action; ids someone can't see are simply not targets.
        writer = self.make_context(["crm.lead.read", "crm.lead.write"], *self._tenant_and_company())
        with self.assertRaises(HTTPException) as denied:
            routes_leads.bulk_lead(crm.BulkIn(action="assign", ids=[leads[1].id], value=None), writer, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        hidden = routes_leads.bulk_lead(crm.BulkIn(action="add_tag", ids=[leads[1].id], value="x"), writer, self.db)
        self.assertEqual((hidden["matched"], hidden["done"]), (0, 0))
        with self.assertRaises(HTTPException):
            routes_leads.bulk_lead(crm.BulkIn(action="delete"), self.context, self.db)  # neither ids nor filters

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

        viewer = self.make_context(["crm.lead.read", "crm.records.all"], *self._tenant_and_company())
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
