from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, lead_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Lead
from app.schemas.crm import ConvertLeadIn, ConvertLeadOut, LeadIn, LeadOut, LeadUpdate, OwnerIn

router = APIRouter(prefix="/api/leads", tags=["crm"])

ASSIGN = "crm.lead.assign"


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _to_out(lead: Lead, stats: crm_service.FollowUpStats, owners: dict) -> LeadOut:
    return LeadOut(
        id=lead.id, name=lead.name, company_name=lead.company_name, email=lead.email, phone=lead.phone,
        source=lead.source, status=lead.status, notes=lead.notes, owner_user_id=lead.owner_user_id,
        owner_name=owners.get(lead.owner_user_id), converted_customer_id=lead.converted_customer_id,
        converted_opportunity_id=lead.converted_opportunity_id, created_at=lead.created_at,
        **stats.for_lead(lead.id),
    )


def _single_out(db: Session, context: RequestContext, lead: Lead) -> LeadOut:
    return _to_out(lead, crm_service.FollowUpStats(db, context), crm_service.owner_names(db, {lead.owner_user_id}))


@router.get("", response_model=list[LeadOut])
def list_leads(
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    leads = lead_service.list_leads(db, context)
    stats = crm_service.FollowUpStats(db, context)
    owners = crm_service.owner_names(db, {lead.owner_user_id for lead in leads})
    return [_to_out(lead, stats, owners) for lead in leads]


@router.post("", response_model=LeadOut)
def create_lead(
    body: LeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    if body.owner_user_id not in (None, context.user.id) and not context.has_permission(ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {ASSIGN}")
    try:
        return _single_out(db, context, lead_service.create_lead(db, context, body))
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, lead_service.update_lead(db, context, lead_id, body))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.patch("/{lead_id}/owner", response_model=LeadOut)
def assign_lead(
    lead_id: UUID,
    body: OwnerIn,
    context: RequestContext = Depends(require_permission(ASSIGN)),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, lead_service.assign_lead(db, context, lead_id, body.owner_user_id))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.post("/{lead_id}/convert", response_model=ConvertLeadOut)
def convert_lead(
    lead_id: UUID,
    body: ConvertLeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.convert")),
    db: Session = Depends(get_db),
):
    """Turns a qualified Lead into a Customer + Contact (+ optionally an
    Opportunity), atomically. Once converted, a lead is a historical record,
    not an editable one."""

    try:
        lead, customer, contact, opportunity = lead_service.convert_lead(db, context, lead_id, body)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc

    return ConvertLeadOut(
        lead_id=lead.id,
        customer_id=customer.id,
        contact_id=contact.id,
        opportunity_id=opportunity.id if opportunity else None,
    )
