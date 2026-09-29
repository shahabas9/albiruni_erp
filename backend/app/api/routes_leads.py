from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import lead_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Lead
from app.schemas.crm import ConvertLeadIn, ConvertLeadOut, LeadIn, LeadOut, LeadUpdate

router = APIRouter(prefix="/api/leads", tags=["crm"])


def _to_out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id, name=lead.name, company_name=lead.company_name, email=lead.email, phone=lead.phone,
        source=lead.source, status=lead.status, notes=lead.notes, owner_user_id=lead.owner_user_id,
        converted_customer_id=lead.converted_customer_id, created_at=lead.created_at,
    )


@router.get("", response_model=list[LeadOut])
def list_leads(
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    return [_to_out(l) for l in lead_service.list_leads(db, context)]


@router.post("", response_model=LeadOut)
def create_lead(
    body: LeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    return _to_out(lead_service.create_lead(db, context, body))


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(lead_service.update_lead(db, context, lead_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{lead_id}/convert", response_model=ConvertLeadOut)
def convert_lead(
    lead_id: UUID,
    body: ConvertLeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.convert")),
    db: Session = Depends(get_db),
):
    """The flagship CRM action: turns a qualified Lead into a real Customer +
    Contact (+ optionally an Opportunity), atomically. Once converted, a lead
    is a historical record, not an editable one."""

    try:
        lead, customer, contact, opportunity = lead_service.convert_lead(db, context, lead_id, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ConvertLeadOut(
        lead_id=lead.id,
        customer_id=customer.id,
        contact_id=contact.id,
        opportunity_id=opportunity.id if opportunity else None,
    )
