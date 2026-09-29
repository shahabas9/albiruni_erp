from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.lead_service import get_lead
from app.domain.opportunity_service import get_opportunity
from app.models.crm import ACTIVITY_TYPES, Activity, Lead, Opportunity
from app.models.sales import Customer
from app.schemas.crm import ActivityIn, ActivityUpdate


def list_activities(
    db: Session,
    context: RequestContext,
    *,
    show: str = "all",
    owner: str = "",
    lead_id: UUID | None = None,
    customer_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Activity], int]:
    """show: "open", "overdue", "done" or "all". Open and overdue lists are
    soonest-due first (overdue on top); the rest newest first."""

    stmt = select(Activity).where(Activity.tenant_id == context.tenant_id, Activity.company_id == context.company_id)
    if show in ("open", "overdue"):
        stmt = stmt.where(Activity.done.is_(False))
    if show == "overdue":
        stmt = stmt.where(Activity.due_at < crm_service.now_utc())
    if show == "done":
        stmt = stmt.where(Activity.done.is_(True))
    for column, value in ((Activity.lead_id, lead_id), (Activity.customer_id, customer_id),
                          (Activity.opportunity_id, opportunity_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    stmt = crm_service.filter_owner(stmt, Activity.owner_id, owner, context)
    if show in ("open", "overdue"):
        stmt = stmt.order_by(Activity.due_at.asc().nulls_last(), Activity.created_at.desc(), Activity.id)
    else:
        stmt = stmt.order_by(Activity.created_at.desc(), Activity.id)
    return crm_service.page(db, stmt, limit, offset)


def get_activity(db: Session, context: RequestContext, activity_id: UUID) -> Activity:
    activity = db.get(Activity, activity_id)
    if activity is None or activity.tenant_id != context.tenant_id or activity.company_id != context.company_id:
        raise NotFoundError(f"No activity with id {activity_id}")
    return activity


def related_labels(db: Session, context: RequestContext, activities: list[Activity]) -> dict[UUID, str]:
    """"Lead: …" / "Opportunity: …" / "Customer: …" per activity, three
    queries in all however many activities there are. A related record that
    has gone missing shows as "—" rather than failing the list."""

    def names(model, ids, label):
        ids = {i for i in ids if i}
        if not ids:
            return {}
        rows = db.execute(select(model).where(model.id.in_(ids), model.tenant_id == context.tenant_id)).scalars()
        return {r.id: label(r) for r in rows}

    leads = names(Lead, (a.lead_id for a in activities), lambda r: r.company_name or r.name)
    opps = names(Opportunity, (a.opportunity_id for a in activities), lambda r: r.name)
    customers = names(Customer, (a.customer_id for a in activities), lambda r: r.name)
    labels = {}
    for a in activities:
        if a.lead_id and a.lead_id in leads:
            labels[a.id] = f"Lead: {leads[a.lead_id]}"
        elif a.opportunity_id and a.opportunity_id in opps:
            labels[a.id] = f"Opportunity: {opps[a.opportunity_id]}"
        elif a.customer_id and a.customer_id in customers:
            labels[a.id] = f"Customer: {customers[a.customer_id]}"
        else:
            labels[a.id] = "—"
    return labels


def _parent(activity: Activity) -> tuple[str, UUID] | None:
    if activity.opportunity_id:
        return "opportunity", activity.opportunity_id
    if activity.lead_id:
        return "lead", activity.lead_id
    if activity.customer_id:
        return "customer", activity.customer_id
    return None


def _record_on_parent(db: Session, context: RequestContext, activity: Activity, action: str, summary: str) -> None:
    parent = _parent(activity)
    if parent:
        history.record(db, context, parent[0], parent[1], action, summary, {"activity_id": [None, str(activity.id)]})


def _due_at(due: date | None) -> datetime | None:
    """A date-only follow-up is due by the end of that day, so "due today"
    isn't reported overdue from midnight onward."""
    return datetime.combine(due, time(23, 59, 59), timezone.utc) if due else None


def create_activity(db: Session, context: RequestContext, body: ActivityIn) -> Activity:
    if body.type not in ACTIVITY_TYPES:
        raise ConflictError(f"'{body.type}' is not a valid activity type. Use one of: {', '.join(ACTIVITY_TYPES)}.")

    targets = [t for t in (body.lead_id, body.customer_id, body.opportunity_id) if t is not None]
    if len(targets) != 1:
        raise ConflictError("An activity must be linked to exactly one of: lead, customer, or opportunity.")

    # Default the owner to whoever owns the parent record, else the creator.
    parent_owner = None
    if body.lead_id:
        parent_owner = get_lead(db, context, body.lead_id).owner_user_id
    if body.customer_id:
        get_customer(db, context, body.customer_id)
    if body.opportunity_id:
        parent_owner = get_opportunity(db, context, body.opportunity_id).owner_user_id
    owner_id = (
        crm_service.resolve_owner(db, context, body.owner_id) if body.owner_id else parent_owner or context.user.id
    )

    due_at = body.due_at
    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    due_date = due_at.date() if due_at is not None else body.due_date

    activity = Activity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        type=body.type,
        subject=body.subject.strip(),
        notes=body.notes,
        due_date=due_date,
        due_at=due_at if due_at is not None else _due_at(body.due_date),
        owner_id=owner_id,
        lead_id=body.lead_id,
        customer_id=body.customer_id,
        opportunity_id=body.opportunity_id,
        created_by=context.user.id,
        done=body.done,
        completed_at=crm_service.now_utc() if body.done else None,
    )
    db.add(activity)
    db.flush()
    what = f"{activity.type}: {activity.subject}" if activity.subject else activity.type
    if activity.done:
        _record_on_parent(db, context, activity, "activity_logged", f"Logged {what}")
    else:
        when = f" for {activity.due_date.strftime('%d %b %Y')}" if activity.due_date else ""
        _record_on_parent(db, context, activity, "followup_scheduled", f"Follow-up scheduled{when} — {what}")
    db.commit()
    db.refresh(activity)
    return activity


def update_activity(db: Session, context: RequestContext, activity_id: UUID, body: ActivityUpdate) -> Activity:
    activity = get_activity(db, context, activity_id)
    changes = body.model_dump(exclude_unset=True)
    if "due_date" in changes:
        activity.due_at = _due_at(changes["due_date"])
    if "done" in changes and changes["done"] != activity.done:
        what = f"{activity.type}: {activity.subject}" if activity.subject else activity.type
        if changes["done"]:
            _record_on_parent(db, context, activity, "followup_done", f"Follow-up done — {what}")
        else:
            _record_on_parent(db, context, activity, "followup_reopened", f"Follow-up reopened — {what}")
    if "done" in changes:
        activity.completed_at = (activity.completed_at or crm_service.now_utc()) if changes["done"] else None
    for field, value in changes.items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity
