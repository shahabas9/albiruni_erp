"""CRM: leads, opportunities, follow-up activities and ownership.

Plain form-path CRUD guarded by require_permission. The one CRM write that
creates a financial document — raising a quotation from an opportunity —
goes through the same sales.create_quotation_draft.v1 tool as every other
quotation, so pricing, discount policy and the audit trail are identical.
"""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.api.routes_sales import to_quotation_out
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service
from app.domain.sales_service import DomainValidationError
from app.models.crm import Activity, Lead, Opportunity
from app.schemas.crm import (
    ActivityIn,
    ActivityOut,
    AssigneeOut,
    ConvertLeadIn,
    LeadIn,
    LeadOut,
    LeadStatusIn,
    OpportunityIn,
    OpportunityOut,
    OpportunityQuotationIn,
    OwnerIn,
    StageIn,
)
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/crm", tags=["crm"])

READ = "crm.read"
WRITE = "crm.write"
ASSIGN = "crm.assign"


def _unprocessable(exc: DomainValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


class _ActivityStats:
    """Open/overdue follow-up counts per lead and per opportunity, from one query."""

    def __init__(self, db: Session, context: RequestContext):
        self.now = crm_service.now_utc()
        self.by_lead: dict[UUID, list[Activity]] = defaultdict(list)
        self.by_opp: dict[UUID, list[Activity]] = defaultdict(list)
        for a in crm_service.list_activities(db, context, open_only=True):
            if a.opportunity_id:
                self.by_opp[a.opportunity_id].append(a)
            elif a.lead_id:
                self.by_lead[a.lead_id].append(a)

    def summary(self, activities: list[Activity]) -> dict:
        return {
            "open_activities": len(activities),
            "overdue_activities": sum(1 for a in activities if crm_service.is_overdue(a, self.now)),
            "next_due_at": min((a.due_at for a in activities), default=None),
        }


def _lead_out(lead: Lead, stats: _ActivityStats) -> LeadOut:
    return LeadOut(
        id=lead.id,
        name=lead.name,
        organization=lead.organization,
        phone=lead.phone,
        email=lead.email,
        source=lead.source,
        status=lead.status,
        owner_id=lead.owner_id,
        owner_name=lead.owner.display_name if lead.owner else None,
        converted_opportunity_id=lead.converted_opportunity_id,
        created_at=lead.created_at,
        **stats.summary(stats.by_lead.get(lead.id, [])),
    )


def _opp_out(opp: Opportunity, stats: _ActivityStats, quotes: dict) -> OpportunityOut:
    return OpportunityOut(
        id=opp.id,
        title=opp.title,
        customer_name=opp.customer.name,
        lead_id=opp.lead_id,
        stage=opp.stage,
        expected_value=float(opp.expected_value),
        expected_close=opp.expected_close,
        owner_id=opp.owner_id,
        owner_name=opp.owner.display_name if opp.owner else None,
        quotations=[to_quotation_out(q) for q in quotes.get(opp.id, [])],
        created_at=opp.created_at,
        **stats.summary(stats.by_opp.get(opp.id, [])),
    )


def _single_opp_out(db: Session, context: RequestContext, opp: Opportunity) -> OpportunityOut:
    return _opp_out(opp, _ActivityStats(db, context), crm_service.quotations_for(db, [opp.id]))


def _single_lead_out(db: Session, context: RequestContext, lead: Lead) -> LeadOut:
    return _lead_out(lead, _ActivityStats(db, context))


# --- Assignees --------------------------------------------------------------


@router.get("/assignees", response_model=list[AssigneeOut])
def list_assignees(context: RequestContext = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return [AssigneeOut(id=u.id, display_name=u.display_name) for u in crm_service.list_assignees(db, context)]


# --- Leads ------------------------------------------------------------------


@router.get("/leads", response_model=list[LeadOut])
def list_leads(context: RequestContext = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    stmt = (
        select(Lead)
        .where(Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id)
        .order_by(Lead.created_at.desc())
    )
    stats = _ActivityStats(db, context)
    return [_lead_out(lead, stats) for lead in db.execute(stmt).scalars()]


@router.post("/leads", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(body: LeadIn, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)):
    if body.owner_id is not None and body.owner_id != context.user.id and not context.has_permission(ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {ASSIGN}")
    try:
        lead = crm_service.create_lead(db, context, **body.model_dump())
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_lead_out(db, context, lead)


@router.patch("/leads/{lead_id}/owner", response_model=LeadOut)
def assign_lead(
    lead_id: UUID, body: OwnerIn, context: RequestContext = Depends(require_permission(ASSIGN)), db: Session = Depends(get_db)
):
    try:
        lead = crm_service.get_lead(db, context, lead_id)
        lead.owner_id = crm_service.resolve_owner(db, context, body.owner_id)
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_lead_out(db, context, lead)


@router.patch("/leads/{lead_id}/status", response_model=LeadOut)
def update_lead_status(
    lead_id: UUID, body: LeadStatusIn, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)
):
    try:
        lead = crm_service.get_lead(db, context, lead_id)
        crm_service.set_lead_status(lead, body.status)
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_lead_out(db, context, lead)


@router.post("/leads/{lead_id}/convert", response_model=OpportunityOut)
def convert_lead(
    lead_id: UUID, body: ConvertLeadIn, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)
):
    try:
        lead = crm_service.get_lead(db, context, lead_id)
        opp = crm_service.convert_lead(db, context, lead, **body.model_dump())
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_opp_out(db, context, opp)


# --- Opportunities ------------------------------------------------------------


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(context: RequestContext = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(Opportunity.tenant_id == context.tenant_id, Opportunity.company_id == context.company_id)
        .order_by(Opportunity.created_at.desc())
    )
    opps = list(db.execute(stmt).scalars())
    stats = _ActivityStats(db, context)
    quotes = crm_service.quotations_for(db, [o.id for o in opps])
    return [_opp_out(o, stats, quotes) for o in opps]


@router.post("/opportunities", response_model=OpportunityOut, status_code=status.HTTP_201_CREATED)
def create_opportunity(
    body: OpportunityIn, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)
):
    if body.owner_id is not None and body.owner_id != context.user.id and not context.has_permission(ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {ASSIGN}")
    try:
        opp = crm_service.create_opportunity(db, context, **body.model_dump())
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_opp_out(db, context, opp)


@router.patch("/opportunities/{opportunity_id}/owner", response_model=OpportunityOut)
def assign_opportunity(
    opportunity_id: UUID,
    body: OwnerIn,
    context: RequestContext = Depends(require_permission(ASSIGN)),
    db: Session = Depends(get_db),
):
    try:
        opp = crm_service.get_opportunity(db, context, opportunity_id)
        opp.owner_id = crm_service.resolve_owner(db, context, body.owner_id)
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_opp_out(db, context, opp)


@router.patch("/opportunities/{opportunity_id}/stage", response_model=OpportunityOut)
def update_stage(
    opportunity_id: UUID,
    body: StageIn,
    context: RequestContext = Depends(require_permission(WRITE)),
    db: Session = Depends(get_db),
):
    try:
        opp = crm_service.get_opportunity(db, context, opportunity_id)
        crm_service.set_stage(opp, body.stage)
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _single_opp_out(db, context, opp)


@router.post("/opportunities/{opportunity_id}/quotations")
def quote_opportunity(
    opportunity_id: UUID,
    body: OpportunityQuotationIn,
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Opportunity -> Quotation. Permission to *create* the quote is checked
    (and audited) by the tool gateway, exactly like every other quotation."""

    try:
        opp = crm_service.get_opportunity(db, context, opportunity_id)
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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
        request_text=f"[form] Quotation for opportunity '{opp.title}'",
        intent="sales.create_quotation",
        correlation_id=new_correlation_id(),
        confirmed=True,
    )


# --- Activities -------------------------------------------------------------


@router.get("/activities", response_model=list[ActivityOut])
def list_activities(
    open_only: bool = True,
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    activities = crm_service.list_activities(db, context, open_only=open_only)
    lead_ids = {a.lead_id for a in activities if a.lead_id}
    opp_ids = {a.opportunity_id for a in activities if a.opportunity_id}
    lead_names = {
        lead.id: lead.organization or lead.name
        for lead in db.execute(select(Lead).where(Lead.id.in_(lead_ids))).scalars()
    } if lead_ids else {}
    opp_names = {
        o.id: o.title for o in db.execute(select(Opportunity).where(Opportunity.id.in_(opp_ids))).scalars()
    } if opp_ids else {}
    now = crm_service.now_utc()
    return [_activity_out(a, now, opp_names, lead_names) for a in activities]


def _activity_out(a: Activity, now: datetime, opp_names: dict, lead_names: dict) -> ActivityOut:
    related = opp_names.get(a.opportunity_id) if a.opportunity_id else lead_names.get(a.lead_id)
    return ActivityOut(
        id=a.id,
        kind=a.kind,
        subject=a.subject,
        due_at=a.due_at,
        completed_at=a.completed_at,
        is_overdue=crm_service.is_overdue(a, now),
        lead_id=a.lead_id,
        opportunity_id=a.opportunity_id,
        related_name=related or "—",
        owner_id=a.owner_id,
        owner_name=a.owner.display_name if a.owner else None,
    )


@router.post("/activities", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    body: ActivityIn, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)
):
    try:
        activity = crm_service.create_activity(db, context, **body.model_dump())
    except DomainValidationError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return _reload_activity_out(db, context, activity)


@router.post("/activities/{activity_id}/complete", response_model=ActivityOut)
def complete_activity(
    activity_id: UUID, context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)
):
    try:
        activity = crm_service.get_activity(db, context, activity_id)
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if activity.completed_at is None:
        activity.completed_at = crm_service.now_utc()
    db.commit()
    return _reload_activity_out(db, context, activity)


def _reload_activity_out(db: Session, context: RequestContext, a: Activity) -> ActivityOut:
    opp_names = {a.opportunity_id: crm_service.get_opportunity(db, context, a.opportunity_id).title} if a.opportunity_id else {}
    lead_names = {}
    if a.lead_id:
        lead = crm_service.get_lead(db, context, a.lead_id)
        lead_names = {lead.id: lead.organization or lead.name}
    return _activity_out(a, crm_service.now_utc(), opp_names, lead_names)
