from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.api.routes_leads import http_error
from app.api.routes_sales import to_quotation_out
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, opportunity_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Opportunity
from app.schemas.crm import OpportunityIn, OpportunityOut, OpportunityQuotationIn, OpportunityUpdate, OwnerIn
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/opportunities", tags=["crm"])

ASSIGN = "crm.opportunity.assign"


def _to_out(o: Opportunity, stats: crm_service.FollowUpStats, owners: dict, quotes: dict) -> OpportunityOut:
    return OpportunityOut(
        id=o.id, customer_id=o.customer_id, customer_name=o.customer.name, lead_id=o.lead_id, name=o.name,
        stage=o.stage, value=float(o.value), probability_pct=o.probability_pct,
        expected_close_date=o.expected_close_date, notes=o.notes, owner_user_id=o.owner_user_id,
        owner_name=owners.get(o.owner_user_id), quotations=[to_quotation_out(q) for q in quotes.get(o.id, [])],
        created_at=o.created_at, **stats.for_opportunity(o.id),
    )


def _single_out(db: Session, context: RequestContext, o: Opportunity) -> OpportunityOut:
    return _to_out(
        o,
        crm_service.FollowUpStats(db, context),
        crm_service.owner_names(db, {o.owner_user_id}),
        crm_service.quotations_for(db, [o.id]),
    )


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    opps = opportunity_service.list_opportunities(db, context)
    stats = crm_service.FollowUpStats(db, context)
    owners = crm_service.owner_names(db, {o.owner_user_id for o in opps})
    quotes = crm_service.quotations_for(db, [o.id for o in opps])
    return [_to_out(o, stats, owners, quotes) for o in opps]


@router.post("", response_model=OpportunityOut)
def create_opportunity(
    body: OpportunityIn,
    context: RequestContext = Depends(require_permission("crm.opportunity.write")),
    db: Session = Depends(get_db),
):
    if body.owner_user_id not in (None, context.user.id) and not context.has_permission(ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {ASSIGN}")
    try:
        return _single_out(db, context, opportunity_service.create_opportunity(db, context, body))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.patch("/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(
    opportunity_id: UUID,
    body: OpportunityUpdate,
    context: RequestContext = Depends(require_permission("crm.opportunity.write")),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, opportunity_service.update_opportunity(db, context, opportunity_id, body))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.patch("/{opportunity_id}/owner", response_model=OpportunityOut)
def assign_opportunity(
    opportunity_id: UUID,
    body: OwnerIn,
    context: RequestContext = Depends(require_permission(ASSIGN)),
    db: Session = Depends(get_db),
):
    try:
        opp = opportunity_service.assign_opportunity(db, context, opportunity_id, body.owner_user_id)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc
    return _single_out(db, context, opp)


@router.post("/{opportunity_id}/quotations")
def quote_opportunity(
    opportunity_id: UUID,
    body: OpportunityQuotationIn,
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    """Opportunity -> Quotation. Permission to *create* the quote
    (sales.quotation.create) is checked and audited by the tool gateway,
    exactly like every other quotation."""

    try:
        opp = opportunity_service.get_opportunity(db, context, opportunity_id)
    except NotFoundError as exc:
        raise http_error(exc) from exc

    args = {
        "customer_name": opp.customer.name,
        "opportunity_id": str(opp.id),
        "lines": [line.model_dump() for line in body.lines],
        "discount_pct": body.discount_pct,
    }
    return execute_tool(
        db,
        context,
        "sales.create_quotation_draft.v1",
        args,
        request_text=f"[form] Quotation for opportunity '{opp.name}'",
        intent="sales.create_quotation",
        correlation_id=new_correlation_id(),
        confirmed=True,
    )
