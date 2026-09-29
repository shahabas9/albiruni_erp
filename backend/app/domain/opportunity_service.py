from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPPORTUNITY_STAGES, Opportunity
from app.schemas.crm import OpportunityIn, OpportunityUpdate


def list_opportunities(db: Session, context: RequestContext) -> list[Opportunity]:
    stmt = (
        select(Opportunity)
        .where(Opportunity.tenant_id == context.tenant_id, Opportunity.company_id == context.company_id)
        .order_by(Opportunity.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_opportunity(db: Session, context: RequestContext, opportunity_id: UUID) -> Opportunity:
    opp = db.get(Opportunity, opportunity_id)
    if opp is None or opp.tenant_id != context.tenant_id or opp.company_id != context.company_id:
        raise NotFoundError(f"No opportunity with id {opportunity_id}")
    return opp


def create_opportunity(db: Session, context: RequestContext, body: OpportunityIn) -> Opportunity:
    get_customer(db, context, body.customer_id)  # 404s if not this tenant's
    opp = Opportunity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        customer_id=body.customer_id,
        name=body.name.strip(),
        stage="New",
        value=body.value,
        probability_pct=body.probability_pct,
        expected_close_date=body.expected_close_date,
        notes=body.notes,
        stage_changed_at=crm_service.now_utc(),
        owner_user_id=crm_service.resolve_owner(db, context, body.owner_user_id),
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def update_opportunity(db: Session, context: RequestContext, opportunity_id: UUID, body: OpportunityUpdate) -> Opportunity:
    opp = get_opportunity(db, context, opportunity_id)
    data = body.model_dump(exclude_unset=True)
    if "lost_reason" in data:
        data["lost_reason"] = (data["lost_reason"] or "").strip()
    stage = data.get("stage", opp.stage)
    if stage not in OPPORTUNITY_STAGES:
        raise ConflictError(f"'{stage}' is not a valid stage. Use one of: {', '.join(OPPORTUNITY_STAGES)}.")
    if stage == "Lost":
        # Required on the way into Lost; older Lost deals without one stay editable.
        moving_to_lost = opp.stage != "Lost" or "lost_reason" in data
        if moving_to_lost and not data.get("lost_reason", opp.lost_reason):
            raise ConflictError("Say why this deal was lost — pick or type a reason.")
    else:
        data["lost_reason"] = ""  # a reopened or won deal carries no lost reason
    if stage != opp.stage:
        opp.stage_changed_at = crm_service.now_utc()
    for field, value in data.items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return opp


def assign_opportunity(
    db: Session, context: RequestContext, opportunity_id: UUID, owner_user_id: UUID | None
) -> Opportunity:
    opp = get_opportunity(db, context, opportunity_id)
    opp.owner_user_id = crm_service.resolve_owner(db, context, owner_user_id)
    db.commit()
    db.refresh(opp)
    return opp
