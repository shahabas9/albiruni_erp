"""Rules shared across the CRM services: ownership, follow-up status and the
opportunity <-> quotation link.

lead_service, opportunity_service and activity_service own their records'
CRUD; this module holds what more than one of them (or the sales tool) needs.
Every lookup is scoped by tenant *and* company from the RequestContext — an id
from the client is never trusted on its own.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import ConflictError
from app.models.crm import OPEN_STAGES, Activity, CrmSettings, Lead, Opportunity
from app.models.identity import User
from app.models.sales import Customer, Quotation

# A quotation raised against an opportunity still in an early stage moves it
# to Proposal — the quote *is* the proposal. Later stages are left alone.
_STAGES_BEFORE_PROPOSAL = ("New", "Qualified")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_overdue(activity: Activity, at: datetime | None = None) -> bool:
    return not activity.done and activity.due_at is not None and activity.due_at < (at or now_utc())


# --- Visibility -------------------------------------------------------------

# Without this permission a person sees only the leads, deals and follow-ups
# they own (plus follow-ups on their own leads/deals). Customers and contacts
# stay shared: quotations and the whole team need them.
SEE_ALL = "crm.records.all"


def sees_all(context: RequestContext) -> bool:
    # No user = the system itself (e.g. the public web form).
    return context.user is None or context.has_permission(SEE_ALL)


def only_visible(stmt: Select, owner_column, context: RequestContext) -> Select:
    """Narrows a lead/opportunity query to what the caller may see."""

    return stmt if sees_all(context) else stmt.where(owner_column == context.user.id)


def can_see(owner_id: UUID | None, context: RequestContext) -> bool:
    return sees_all(context) or owner_id == context.user.id


def visible_activities(stmt: Select, context: RequestContext) -> Select:
    """Follow-ups the caller owns, or that sit on a lead/deal they own."""

    if sees_all(context):
        return stmt
    me = context.user.id
    my_leads = select(Lead.id).where(Lead.owner_user_id == me)
    my_deals = select(Opportunity.id).where(Opportunity.owner_user_id == me)
    return stmt.where(or_(
        Activity.owner_id == me, Activity.lead_id.in_(my_leads), Activity.opportunity_id.in_(my_deals)
    ))


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


# --- Lead rotation --------------------------------------------------------------


def _settings_row(db: Session, context: RequestContext, *, lock: bool = False) -> CrmSettings | None:
    stmt = select(CrmSettings).where(
        CrmSettings.company_id == context.company_id, CrmSettings.tenant_id == context.tenant_id
    )
    return db.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()


def _rotation_pool(db: Session, context: RequestContext, user_ids: list[str]) -> list[User]:
    """The rotation's members in order, skipping anyone deactivated or moved away."""

    ids = []
    for raw in user_ids:
        try:
            ids.append(UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return []
    users = {
        u.id: u
        for u in db.execute(
            select(User).where(
                User.id.in_(ids), User.tenant_id == context.tenant_id,
                User.company_id == context.company_id, User.active.is_(True),
            )
        ).scalars()
    }
    return [users[i] for i in ids if i in users]


def rotation_status(db: Session, context: RequestContext) -> dict:
    row = _settings_row(db, context)
    rotation = (row.lead_rotation if row else None) or {}
    pool = _rotation_pool(db, context, rotation.get("user_ids", []))
    last = str(rotation.get("last_user_id") or "")
    ids = [str(u.id) for u in pool]
    up_next = pool[(ids.index(last) + 1) % len(pool)] if last in ids else (pool[0] if pool else None)
    return {
        "enabled": bool(rotation.get("enabled")) and bool(pool),
        "user_ids": [str(u.id) for u in pool],
        "next_user_id": str(up_next.id) if up_next else None,
        "next_user_name": up_next.display_name if up_next else None,
    }


def set_rotation(db: Session, context: RequestContext, enabled: bool, user_ids: list[UUID]) -> dict:
    if len(set(user_ids)) != len(user_ids):
        raise ConflictError("Each person can be in the rotation once.")
    pool = _rotation_pool(db, context, [str(i) for i in user_ids])
    if len(pool) != len(user_ids):
        raise ConflictError("Everyone in the rotation must be an active user of this company.")
    if enabled and not pool:
        raise ConflictError("Add at least one person before turning the rotation on.")
    row = _settings_row(db, context, lock=True)
    if row is None:
        row = CrmSettings(company_id=context.company_id, tenant_id=context.tenant_id, stale_after_days={})
        db.add(row)
    last = (row.lead_rotation or {}).get("last_user_id")
    row.lead_rotation = {"enabled": enabled, "user_ids": [str(i) for i in user_ids], "last_user_id": last}
    db.commit()
    return rotation_status(db, context)


def next_rotation_owner(db: Session, context: RequestContext) -> User | None:
    """The next person in the lead rotation (and moves the rotation on), or
    None when it's off. Locks the settings row until the caller's commit, so
    two leads arriving together go to two different people."""

    row = _settings_row(db, context, lock=True)
    rotation = (row.lead_rotation if row else None) or {}
    if not rotation.get("enabled"):
        return None
    pool = _rotation_pool(db, context, rotation.get("user_ids", []))
    if not pool:
        return None
    ids = [str(u.id) for u in pool]
    last = str(rotation.get("last_user_id") or "")
    chosen = pool[(ids.index(last) + 1) % len(pool)] if last in ids else pool[0]
    row.lead_rotation = {**rotation, "last_user_id": str(chosen.id)}
    return chosen


# --- Listing ------------------------------------------------------------------

MAX_PAGE = 200


def filter_owner(stmt: Select, column, owner: str, context: RequestContext) -> Select:
    """owner: "" (anyone), "me", "unassigned" or a user id."""

    if owner == "me":
        return stmt.where(column == context.user.id)
    if owner == "unassigned":
        return stmt.where(column.is_(None))
    if owner:
        try:
            return stmt.where(column == UUID(owner))
        except ValueError as exc:
            raise ConflictError("owner must be 'me', 'unassigned' or a user id.") from exc
    return stmt


def search(q: str, *columns):
    """Every word must appear in one of the columns (case-insensitive)."""

    words = [w.replace("%", r"\%").replace("_", r"\_") for w in q.split()]
    return and_(*(or_(*(c.ilike(f"%{w}%") for c in columns)) for w in words))


def page(db: Session, stmt: Select, limit: int | None, offset: int) -> tuple[list, int]:
    """One page of `stmt`'s rows plus the total count, so screens can page
    through thousands of records instead of loading them all."""

    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    if limit is not None:
        stmt = stmt.limit(min(limit, MAX_PAGE))
    rows = list(db.execute(stmt.offset(offset)).scalars().unique())
    return rows, total


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

    def __init__(
        self,
        db: Session,
        context: RequestContext,
        *,
        lead_ids: list[UUID] | None = None,
        opportunity_ids: list[UUID] | None = None,
    ):
        """Pass the ids on screen to load only their follow-ups."""

        self.now = now_utc()
        self._by_lead: dict[UUID, list[Activity]] = defaultdict(list)
        self._by_opp: dict[UUID, list[Activity]] = defaultdict(list)
        stmt = select(Activity).where(
            Activity.tenant_id == context.tenant_id,
            Activity.company_id == context.company_id,
            Activity.done.is_(False),
        )
        if lead_ids is not None or opportunity_ids is not None:
            stmt = stmt.where(or_(
                Activity.lead_id.in_(lead_ids or []), Activity.opportunity_id.in_(opportunity_ids or [])
            ))
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

# Default days an open deal may go untouched in each stage before it's flagged
# (Pipedrive calls this "rotting"). Each company can override them
# (CrmSettings.stale_after_days); 0 turns the warning off for that stage.
STALE_AFTER_DAYS = {"New": 7, "Qualified": 10, "Proposal": 14, "Negotiation": 7}
MAX_STALE_DAYS = 365


def stale_limits(db: Session, context: RequestContext) -> dict[str, int]:
    row = db.get(CrmSettings, context.company_id)
    saved = row.stale_after_days if row and row.tenant_id == context.tenant_id else {}
    return {stage: int(saved.get(stage, default)) for stage, default in STALE_AFTER_DAYS.items()}


def set_stale_limits(db: Session, context: RequestContext, limits: dict[str, int]) -> dict[str, int]:
    unknown = set(limits) - set(STALE_AFTER_DAYS)
    if unknown:
        raise ConflictError(f"Unknown stage(s): {', '.join(sorted(unknown))}. Use {', '.join(STALE_AFTER_DAYS)}.")
    for stage, days in limits.items():
        if not 0 <= int(days) <= MAX_STALE_DAYS:
            raise ConflictError(f"{stage}: use 0 (off) to {MAX_STALE_DAYS} days.")
    row = db.get(CrmSettings, context.company_id)
    if row is None:
        row = CrmSettings(company_id=context.company_id, tenant_id=context.tenant_id, stale_after_days={})
        db.add(row)
    row.stale_after_days = {**(row.stale_after_days or {}), **{k: int(v) for k, v in limits.items()}}
    db.commit()
    return stale_limits(db, context)


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


def stale_only(stmt: Select, context: RequestContext, limits: dict[str, int], at: datetime | None = None) -> Select:
    """Narrows a select over Opportunity to deals idle past their stage's
    limit — the same rule as idle_status, computed in SQL so a list or count
    of stale deals never loads every open deal."""

    activity = (
        select(
            Activity.opportunity_id.label("opp_id"),
            func.max(func.greatest(Activity.created_at, func.coalesce(Activity.completed_at, Activity.created_at)))
            .label("at"),
        )
        .where(Activity.tenant_id == context.tenant_id, Activity.opportunity_id.is_not(None))
        .group_by(Activity.opportunity_id)
        .subquery()
    )
    quote = (
        select(Quotation.opportunity_id.label("opp_id"), func.max(Quotation.created_at).label("at"))
        .where(Quotation.tenant_id == context.tenant_id, Quotation.opportunity_id.is_not(None))
        .group_by(Quotation.opportunity_id)
        .subquery()
    )
    # GREATEST skips NULLs in Postgres: a deal with no follow-ups or quotes
    # is judged on its creation / stage-change date alone.
    last_touch = func.greatest(Opportunity.created_at, Opportunity.stage_changed_at, activity.c.at, quote.c.at)
    now = at or now_utc()
    # idle_days >= limit  <=>  last_touch <= now - limit days
    conditions = [
        and_(Opportunity.stage == stage, last_touch <= now - timedelta(days=days))
        for stage, days in limits.items() if days > 0
    ]
    return (
        stmt.outerjoin(activity, activity.c.opp_id == Opportunity.id)
        .outerjoin(quote, quote.c.opp_id == Opportunity.id)
        .where(or_(*conditions) if conditions else false())
    )


def idle_status(opp: Opportunity, last_touch: datetime, limits: dict[str, int], at: datetime | None = None) -> dict:
    idle_days = max(((at or now_utc()) - last_touch).days, 0)
    limit = limits.get(opp.stage, 0)  # closed stages have no limit; 0 = warning off
    return {
        "last_touch_at": last_touch,
        "idle_days": idle_days,
        "is_stale": limit > 0 and idle_days >= limit,
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
