from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.lead_service import get_lead
from app.domain.opportunity_service import get_opportunity
from app.models.crm import ACTIVITY_TYPES, Activity
from app.schemas.crm import ActivityIn, ActivityUpdate


def list_activities(db: Session, context: RequestContext) -> list[Activity]:
    stmt = (
        select(Activity)
        .where(Activity.tenant_id == context.tenant_id, Activity.company_id == context.company_id)
        .order_by(Activity.created_at.desc())
    )
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
            return f"Lead: {get_lead(db, context, activity.lead_id).name}"
        if activity.opportunity_id:
            return f"Opportunity: {get_opportunity(db, context, activity.opportunity_id).name}"
        if activity.customer_id:
            return f"Customer: {get_customer(db, context, activity.customer_id).name}"
    except NotFoundError:
        pass
    return "—"


def create_activity(db: Session, context: RequestContext, body: ActivityIn) -> Activity:
    if body.type not in ACTIVITY_TYPES:
        raise ConflictError(f"'{body.type}' is not a valid activity type. Use one of: {', '.join(ACTIVITY_TYPES)}.")

    targets = [t for t in (body.lead_id, body.customer_id, body.opportunity_id) if t is not None]
    if len(targets) != 1:
        raise ConflictError("An activity must be linked to exactly one of: lead, customer, or opportunity.")

    if body.lead_id:
        get_lead(db, context, body.lead_id)
    if body.customer_id:
        get_customer(db, context, body.customer_id)
    if body.opportunity_id:
        get_opportunity(db, context, body.opportunity_id)

    activity = Activity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        type=body.type,
        subject=body.subject,
        notes=body.notes,
        due_date=body.due_date,
        lead_id=body.lead_id,
        customer_id=body.customer_id,
        opportunity_id=body.opportunity_id,
        created_by=context.user.id,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def update_activity(db: Session, context: RequestContext, activity_id: UUID, body: ActivityUpdate) -> Activity:
    activity = get_activity(db, context, activity_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity
