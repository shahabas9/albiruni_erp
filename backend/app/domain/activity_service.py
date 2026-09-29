from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.lead_service import get_lead
from app.domain.opportunity_service import get_opportunity
from app.models.crm import ACTIVITY_TYPES, Activity
from app.schemas.crm import ActivityIn, ActivityUpdate


def list_activities(db: Session, context: RequestContext, *, open_only: bool = False) -> list[Activity]:
    stmt = (
        select(Activity)
        .where(Activity.tenant_id == context.tenant_id, Activity.company_id == context.company_id)
        .order_by(Activity.created_at.desc())
    )
    if open_only:
        stmt = stmt.where(Activity.done.is_(False))
    return list(db.execute(stmt).scalars().all())


def get_activity(db: Session, context: RequestContext, activity_id: UUID) -> Activity:
    activity = db.get(Activity, activity_id)
    if activity is None or activity.tenant_id != context.tenant_id or activity.company_id != context.company_id:
        raise NotFoundError(f"No activity with id {activity_id}")
    return activity


def related_label(db: Session, context: RequestContext, activity: Activity) -> str:
    # Resolve lazily and defensively — a related record may have been
    # deleted/converted since the activity was logged; never 500 for that.
    try:
        if activity.lead_id:
            lead = get_lead(db, context, activity.lead_id)
            return f"Lead: {lead.company_name or lead.name}"
        if activity.opportunity_id:
            return f"Opportunity: {get_opportunity(db, context, activity.opportunity_id).name}"
        if activity.customer_id:
            return f"Customer: {get_customer(db, context, activity.customer_id).name}"
    except NotFoundError:
        pass
    return "—"


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
    db.commit()
    db.refresh(activity)
    return activity


def update_activity(db: Session, context: RequestContext, activity_id: UUID, body: ActivityUpdate) -> Activity:
    activity = get_activity(db, context, activity_id)
    changes = body.model_dump(exclude_unset=True)
    if "due_date" in changes:
        activity.due_at = _due_at(changes["due_date"])
    if "done" in changes:
        activity.completed_at = (activity.completed_at or crm_service.now_utc()) if changes["done"] else None
    for field, value in changes.items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity
