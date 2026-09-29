from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes_leads import http_error
from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import activity_service, crm_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Activity
from app.schemas.crm import ActivityIn, ActivityOut, ActivityUpdate, AssigneeOut

router = APIRouter(prefix="/api/activities", tags=["crm"])
assignees_router = APIRouter(prefix="/api/assignees", tags=["crm"])


def _to_out(db: Session, context: RequestContext, a: Activity, owners: dict) -> ActivityOut:
    return ActivityOut(
        id=a.id, type=a.type, subject=a.subject, notes=a.notes, due_date=a.due_date, due_at=a.due_at,
        done=a.done, completed_at=a.completed_at, is_overdue=crm_service.is_overdue(a),
        lead_id=a.lead_id, customer_id=a.customer_id, opportunity_id=a.opportunity_id,
        related_label=activity_service.related_label(db, context, a),
        owner_id=a.owner_id, owner_name=owners.get(a.owner_id), created_at=a.created_at,
    )


@router.get("", response_model=list[ActivityOut])
def list_activities(
    open_only: bool = False,
    context: RequestContext = Depends(require_permission("crm.activity.read")),
    db: Session = Depends(get_db),
):
    activities = activity_service.list_activities(db, context, open_only=open_only)
    owners = crm_service.owner_names(db, {a.owner_id for a in activities})
    return [_to_out(db, context, a, owners) for a in activities]


@router.post("", response_model=ActivityOut)
def create_activity(
    body: ActivityIn,
    context: RequestContext = Depends(require_permission("crm.activity.write")),
    db: Session = Depends(get_db),
):
    try:
        activity = activity_service.create_activity(db, context, body)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc
    return _to_out(db, context, activity, crm_service.owner_names(db, {activity.owner_id}))


@router.patch("/{activity_id}", response_model=ActivityOut)
def update_activity(
    activity_id: UUID,
    body: ActivityUpdate,
    context: RequestContext = Depends(require_permission("crm.activity.write")),
    db: Session = Depends(get_db),
):
    try:
        activity = activity_service.update_activity(db, context, activity_id, body)
    except NotFoundError as exc:
        raise http_error(exc) from exc
    return _to_out(db, context, activity, crm_service.owner_names(db, {activity.owner_id}))


@assignees_router.get("", response_model=list[AssigneeOut])
def list_assignees(
    context: RequestContext = Depends(
        require_any_permission("crm.lead.read", "crm.opportunity.read", "crm.activity.read")
    ),
    db: Session = Depends(get_db),
):
    """People a lead, opportunity or follow-up can be assigned to."""

    return [AssigneeOut(id=u.id, display_name=u.display_name) for u in crm_service.list_assignees(db, context)]
