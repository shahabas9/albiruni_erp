"""Rules shared across the CRM services: ownership, follow-up status and the
opportunity <-> quotation link.

lead_service, opportunity_service and activity_service own their records'
CRUD; this module holds what more than one of them (or the sales tool) needs.
Every lookup is scoped by tenant *and* company from the RequestContext — an id
from the client is never trusted on its own.
"""

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import ConflictError
from app.models.crm import OPEN_STAGES, Activity, Opportunity
from app.models.identity import User
from app.models.sales import Customer, Quotation

# A quotation raised against an opportunity still in an early stage moves it
# to Proposal — the quote *is* the proposal. Later stages are left alone.
_STAGES_BEFORE_PROPOSAL = ("New", "Qualified")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_overdue(activity: Activity, at: datetime | None = None) -> bool:
    return not activity.done and activity.due_at is not None and activity.due_at < (at or now_utc())


# --- Ownership --------------------------------------------------------------


def list_assignees(db: Session, context: RequestContext) -> list[User]:
    """Users a lead/opportunity/activity can be assigned to: same tenant and company."""

    stmt = (
        select(User)
        .where(User.tenant_id == context.tenant_id, User.company_id == context.company_id)
        .order_by(User.display_name)
    )
    return list(db.execute(stmt).scalars().all())


def resolve_owner(db: Session, context: RequestContext, owner_id: UUID | None) -> UUID | None:
    """Validates an owner picked in the UI. None means 'unassigned'."""

    if owner_id is None:
        return None
    user = db.get(User, owner_id)
    if user is None or user.tenant_id != context.tenant_id or user.company_id != context.company_id:
        raise ConflictError("That user can't own records in this company.")
    return user.id


def owner_names(db: Session, owner_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {i for i in owner_ids if i is not None}
    if not ids:
        return {}
    return {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()}


# --- Customers ----------------------------------------------------------------


def find_or_create_customer(db: Session, context: RequestContext, name: str) -> Customer:
    """Reuses a same-named customer instead of creating a duplicate account."""

    existing = db.execute(
        select(Customer).where(
            Customer.tenant_id == context.tenant_id,
            Customer.company_id == context.company_id,
            func.lower(Customer.name) == name.strip().lower(),
        )
    ).scalars().first()
    if existing is not None:
        return existing
    customer = Customer(
        tenant_id=context.tenant_id, company_id=context.company_id, name=name.strip(), credit_limit=0, active=True
    )
    db.add(customer)
    db.flush()
    return customer


# --- Follow-ups -------------------------------------------------------------


class FollowUpStats:
    """Open/overdue follow-up counts per lead and per opportunity, from one query."""

    def __init__(self, db: Session, context: RequestContext):
        self.now = now_utc()
        self._by_lead: dict[UUID, list[Activity]] = defaultdict(list)
        self._by_opp: dict[UUID, list[Activity]] = defaultdict(list)
        stmt = select(Activity).where(
            Activity.tenant_id == context.tenant_id,
            Activity.company_id == context.company_id,
            Activity.done.is_(False),
        )
        for a in db.execute(stmt).scalars():
            if a.opportunity_id:
                self._by_opp[a.opportunity_id].append(a)
            elif a.lead_id:
                self._by_lead[a.lead_id].append(a)

    def _summary(self, activities: list[Activity]) -> dict:
        return {
            "open_activities": len(activities),
            "overdue_activities": sum(1 for a in activities if is_overdue(a, self.now)),
            "next_due_at": min((a.due_at for a in activities if a.due_at is not None), default=None),
        }

    def for_lead(self, lead_id: UUID) -> dict:
        return self._summary(self._by_lead.get(lead_id, []))

    def for_opportunity(self, opportunity_id: UUID) -> dict:
        return self._summary(self._by_opp.get(opportunity_id, []))


# --- Idle deals -----------------------------------------------------------------

# Days an open deal may go untouched in each stage before it's flagged
# (Pipedrive calls this "rotting"). Late stages go cold faster.
STALE_AFTER_DAYS = {"New": 7, "Qualified": 10, "Proposal": 14, "Negotiation": 7}


def last_touches(db: Session, context: RequestContext, opportunities: list[Opportunity]) -> dict[UUID, datetime]:
    """Most recent sign of life per deal: creation, stage change, any follow-up
    logged or completed on it, or a quotation raised for it."""

    touches = {o.id: max(o.created_at, o.stage_changed_at or o.created_at) for o in opportunities}
    if not touches:
        return touches
    ids = list(touches)
    activity_rows = db.execute(
        select(
            Activity.opportunity_id,
            func.max(func.greatest(Activity.created_at, func.coalesce(Activity.completed_at, Activity.created_at))),
        )
        .where(Activity.tenant_id == context.tenant_id, Activity.opportunity_id.in_(ids))
        .group_by(Activity.opportunity_id)
    )
    quote_rows = db.execute(
        select(Quotation.opportunity_id, func.max(Quotation.created_at))
        .where(Quotation.tenant_id == context.tenant_id, Quotation.opportunity_id.in_(ids))
        .group_by(Quotation.opportunity_id)
    )
    for opp_id, at in [*activity_rows, *quote_rows]:
        if at is not None and at > touches[opp_id]:
            touches[opp_id] = at
    return touches


def idle_status(opp: Opportunity, last_touch: datetime, at: datetime | None = None) -> dict:
    idle_days = max(((at or now_utc()) - last_touch).days, 0)
    limit = STALE_AFTER_DAYS.get(opp.stage)
    return {
        "last_touch_at": last_touch,
        "idle_days": idle_days,
        "is_stale": limit is not None and idle_days >= limit,
    }


# --- Opportunity -> Quotation -------------------------------------------------


def assert_quotable(opp: Opportunity) -> None:
    if opp.stage not in OPEN_STAGES:
        raise ConflictError(f"This opportunity is {opp.stage} — reopen it before quoting.")


def advance_on_quotation(opp: Opportunity) -> None:
    if opp.stage in _STAGES_BEFORE_PROPOSAL:
        opp.stage = "Proposal"
        opp.stage_changed_at = now_utc()


def quotations_for(db: Session, opportunity_ids: list[UUID]) -> dict[UUID, list[Quotation]]:
    if not opportunity_ids:
        return {}
    rows = db.execute(
        select(Quotation).where(Quotation.opportunity_id.in_(opportunity_ids)).order_by(Quotation.created_at.desc())
    ).scalars()
    grouped: dict[UUID, list[Quotation]] = {}
    for q in rows:
        grouped.setdefault(q.opportunity_id, []).append(q)
    return grouped
