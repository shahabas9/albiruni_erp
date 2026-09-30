from uuid import UUID

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.api.routes_leads import http_error
from app.api.routes_sales import to_quotation_out
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, history, opportunity_service, record_admin
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Opportunity
from app.schemas.crm import (
    OpportunityIn,
    OpportunityOut,
    OpportunityQuotationIn,
    OpportunityUpdate,
    OwnerIn,
    TimelineEntry,
)
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/opportunities", tags=["crm"])

ASSIGN = "crm.opportunity.assign"


def _to_out(
    o: Opportunity, stats: crm_service.FollowUpStats, owners: dict, quotes: dict, touches: dict, limits: dict
) -> OpportunityOut:
    return OpportunityOut(
        id=o.id, customer_id=o.customer_id, customer_name=o.customer.name, lead_id=o.lead_id, name=o.name,
        stage=o.stage, value=float(o.value), probability_pct=o.probability_pct,
        expected_close_date=o.expected_close_date, notes=o.notes, lost_reason=o.lost_reason,
        stage_changed_at=o.stage_changed_at, owner_user_id=o.owner_user_id,
        owner_name=owners.get(o.owner_user_id), tags=list(o.tags or []), custom=dict(o.custom or {}), quotations=[to_quotation_out(q) for q in quotes.get(o.id, [])],
        created_at=o.created_at, **stats.for_opportunity(o.id),
        **crm_service.idle_status(o, touches[o.id], limits),
    )


def opportunity_rows(db: Session, context: RequestContext, opps: list[Opportunity]) -> list[OpportunityOut]:
    ids = [o.id for o in opps]
    stats = crm_service.FollowUpStats(db, context, opportunity_ids=ids)
    owners = crm_service.owner_names(db, {o.owner_user_id for o in opps})
    quotes = crm_service.quotations_for(db, ids)
    touches = crm_service.last_touches(db, context, opps)
    limits = crm_service.stale_limits(db, context)
    return [_to_out(o, stats, owners, quotes, touches, limits) for o in opps]


def _single_out(db: Session, context: RequestContext, o: Opportunity) -> OpportunityOut:
    return opportunity_rows(db, context, [o])[0]


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    response: Response,
    q: str = "",
    stage: str = Query("", description='A stage, "open" or "closed"'),
    owner: str = Query("", description='"me", "unassigned" or a user id'),
    closed_since: date | None = Query(None, description="Open deals plus those won/lost since this date"),
    stale: bool = False,
    tag: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    """Newest first. The total matching count is in the X-Total-Count header."""

    try:
        opps, total = opportunity_service.list_opportunities(
            db, context, q=q, stage=stage, owner=owner, closed_since=closed_since, stale_only=stale, tag=tag,
            limit=limit, offset=offset,
        )
    except ConflictError as exc:
        raise http_error(exc) from exc
    response.headers["X-Total-Count"] = str(total)
    return opportunity_rows(db, context, opps)


@router.get("/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(
    opportunity_id: UUID,
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, opportunity_service.get_opportunity(db, context, opportunity_id))
    except NotFoundError as exc:
        raise http_error(exc) from exc


@router.get("/{opportunity_id}/timeline", response_model=list[TimelineEntry])
def opportunity_timeline(
    opportunity_id: UUID,
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    """Who changed what on this deal, newest first — including the lead it
    was converted from."""

    try:
        opp = opportunity_service.get_opportunity(db, context, opportunity_id)
    except NotFoundError as exc:
        raise http_error(exc) from exc
    refs = [("opportunity", opp.id)]
    if opp.lead_id and context.has_permission("crm.lead.read"):
        refs.append(("lead", opp.lead_id))
    return history.timeline(db, context, refs)


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


@router.delete("/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opportunity(
    opportunity_id: UUID,
    context: RequestContext = Depends(require_permission("crm.opportunity.delete")),
    db: Session = Depends(get_db),
):
    """Removes a deal with its follow-ups and files — unless it has quotations
    (mark it Lost instead)."""

    try:
        record_admin.delete_opportunity(db, context, opportunity_id)
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
