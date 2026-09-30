from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, contains_eager

from app.core.deps import RequestContext
from app.domain import crm_service, fields, history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPEN_STAGES, OPPORTUNITY_STAGES, Opportunity
from app.models.sales import Customer
from app.schemas.crm import OpportunityIn, OpportunityUpdate


def list_opportunities(
    db: Session,
    context: RequestContext,
    *,
    q: str = "",
    stage: str = "",
    owner: str = "",
    closed_since: date | None = None,
    stale_only: bool = False,
    tag: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Opportunity], int]:
    """Deals matching the filters, newest first, and how many match in total.

    stage: a stage, "open" or "closed". closed_since: open deals plus those
    won/lost on or after that date. stale_only: open deals idle past their
    stage's limit."""

    stmt = (
        select(Opportunity)
        .join(Customer, Customer.id == Opportunity.customer_id)
        .options(contains_eager(Opportunity.customer))
        .where(Opportunity.tenant_id == context.tenant_id, Opportunity.company_id == context.company_id)
    )
    if stage == "open" or stale_only:
        stmt = stmt.where(Opportunity.stage.in_(OPEN_STAGES))
    elif stage == "closed":
        stmt = stmt.where(Opportunity.stage.notin_(OPEN_STAGES))
    elif stage:
        stmt = stmt.where(Opportunity.stage == stage)
    if closed_since is not None:
        since = datetime.combine(closed_since, time.min, timezone.utc)
        stmt = stmt.where(or_(Opportunity.stage.in_(OPEN_STAGES), Opportunity.stage_changed_at >= since))
    stmt = crm_service.filter_owner(stmt, Opportunity.owner_user_id, owner, context)
    if tag.strip():
        stmt = stmt.where(Opportunity.tags.contains([tag.strip().lower()]))
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Opportunity.name, Customer.name))
    if stale_only:
        stmt = crm_service.stale_only(stmt, context, crm_service.stale_limits(db, context))
    return crm_service.page(db, stmt.order_by(Opportunity.created_at.desc(), Opportunity.id), limit, offset)


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
        tags=fields.normalize_tags(body.tags),
        custom=fields.clean_custom(db, context, "opportunity", body.custom),
        owner_user_id=crm_service.resolve_owner(db, context, body.owner_user_id),
    )
    db.add(opp)
    db.flush()
    history.record(db, context, "opportunity", opp.id, "created", f"Deal created: {opp.name} (stage New)")
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
    extra = fields.apply_tags_and_custom(db, context, "opportunity", opp, data)
    changes = {**history.diff(opp, data), **extra}
    for field, value in data.items():
        setattr(opp, field, value)
    if changes:
        action = "stage_changed" if "stage" in changes else "updated"
        history.record(db, context, "opportunity", opp.id, action, history.describe(changes), changes)
    db.commit()
    db.refresh(opp)
    return opp


def assign_opportunity(
    db: Session, context: RequestContext, opportunity_id: UUID, owner_user_id: UUID | None
) -> Opportunity:
    opp = get_opportunity(db, context, opportunity_id)
    new_owner = crm_service.resolve_owner(db, context, owner_user_id)
    if new_owner != opp.owner_user_id:
        summary, changes = history.owner_change(db, opp.owner_user_id, new_owner)
        history.record(db, context, "opportunity", opp.id, "owner_changed", summary, changes)
    opp.owner_user_id = new_owner
    db.commit()
    db.refresh(opp)
    return opp
