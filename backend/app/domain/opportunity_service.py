from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
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
        name=body.name,
        stage="New",
        value=body.value,
        probability_pct=body.probability_pct,
        expected_close_date=body.expected_close_date,
        notes=body.notes,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def update_opportunity(db: Session, context: RequestContext, opportunity_id: UUID, body: OpportunityUpdate) -> Opportunity:
    opp = get_opportunity(db, context, opportunity_id)
    data = body.model_dump(exclude_unset=True)
    if "stage" in data and data["stage"] not in OPPORTUNITY_STAGES:
        raise ConflictError(f"'{data['stage']}' is not a valid stage. Use one of: {', '.join(OPPORTUNITY_STAGES)}.")
    for field, value in data.items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return opp
