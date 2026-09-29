from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import activity_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Activity
from app.schemas.crm import ActivityIn, ActivityOut, ActivityUpdate

router = APIRouter(prefix="/api/activities", tags=["crm"])


def _to_out(db: Session, context: RequestContext, a: Activity) -> ActivityOut:
    return ActivityOut(
        id=a.id, type=a.type, subject=a.subject, notes=a.notes, due_date=a.due_date, done=a.done,
        lead_id=a.lead_id, customer_id=a.customer_id, opportunity_id=a.opportunity_id,
        related_label=activity_service.related_label(db, context, a), created_at=a.created_at,
    )


@router.get("", response_model=list[ActivityOut])
def list_activities(
    context: RequestContext = Depends(require_permission("crm.activity.read")),
    db: Session = Depends(get_db),
):
    return [_to_out(db, context, a) for a in activity_service.list_activities(db, context)]


@router.post("", response_model=ActivityOut)
def create_activity(
    body: ActivityIn,
    context: RequestContext = Depends(require_permission("crm.activity.write")),
    db: Session = Depends(get_db),
):
    try:
        activity = activity_service.create_activity(db, context, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(db, context, activity)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_out(db, context, activity)
