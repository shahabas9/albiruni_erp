from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import opportunity_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Opportunity
from app.schemas.crm import OpportunityIn, OpportunityOut, OpportunityUpdate

router = APIRouter(prefix="/api/opportunities", tags=["crm"])


def _to_out(o: Opportunity) -> OpportunityOut:
    return OpportunityOut(
        id=o.id, customer_id=o.customer_id, customer_name=o.customer.name, name=o.name, stage=o.stage,
        value=float(o.value), probability_pct=o.probability_pct, expected_close_date=o.expected_close_date,
        notes=o.notes, owner_user_id=o.owner_user_id, created_at=o.created_at,
    )


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    return [_to_out(o) for o in opportunity_service.list_opportunities(db, context)]


@router.post("", response_model=OpportunityOut)
def create_opportunity(
    body: OpportunityIn,
    context: RequestContext = Depends(require_permission("crm.opportunity.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(opportunity_service.create_opportunity(db, context, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(
    opportunity_id: UUID,
    body: OpportunityUpdate,
    context: RequestContext = Depends(require_permission("crm.opportunity.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(opportunity_service.update_opportunity(db, context, opportunity_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
