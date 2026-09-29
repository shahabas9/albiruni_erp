from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.routes_activities import activities_out
from app.api.routes_leads import http_error
from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import activity_service, crm_service
from app.domain.errors import ConflictError
from app.models.crm import OPEN_STAGES, Activity, Lead, Opportunity
from app.schemas.crm import CrmSummary, StaleLimits, StageTotal

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/settings", response_model=StaleLimits)
def get_settings(
    context: RequestContext = Depends(require_any_permission("crm.opportunity.read", "crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Days a deal may sit untouched in each open stage before it's flagged
    stale; 0 means never."""

    return crm_service.stale_limits(db, context)


@router.put("/settings", response_model=StaleLimits)
def put_settings(
    body: StaleLimits,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        return crm_service.set_stale_limits(db, context, body.model_dump())
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.get("/summary", response_model=CrmSummary)
def summary(
    context: RequestContext = Depends(
        require_any_permission("crm.lead.read", "crm.opportunity.read", "crm.activity.read")
    ),
    db: Session = Depends(get_db),
):
    out = CrmSummary()
    scope = lambda model: (model.tenant_id == context.tenant_id, model.company_id == context.company_id)  # noqa: E731

    if context.has_permission("crm.opportunity.read"):
        rows = db.execute(
            select(Opportunity.stage, func.count(), func.coalesce(func.sum(Opportunity.value), 0),
                   func.coalesce(func.sum(Opportunity.value * Opportunity.probability_pct / 100), 0))
            .where(*scope(Opportunity)).group_by(Opportunity.stage)
        ).all()
        by_stage = {stage: (count, float(value), float(weighted)) for stage, count, value, weighted in rows}
        out.by_stage = [StageTotal(stage=s, count=by_stage.get(s, (0, 0, 0))[0], value=by_stage.get(s, (0, 0, 0))[1])
                        for s in OPEN_STAGES]
        out.open_deals = sum(by_stage.get(s, (0,))[0] for s in OPEN_STAGES)
        out.open_value = sum(by_stage.get(s, (0, 0))[1] for s in OPEN_STAGES)
        out.weighted_value = sum(by_stage.get(s, (0, 0, 0))[2] for s in OPEN_STAGES)
        out.won_deals, out.won_value = by_stage.get("Won", (0, 0, 0))[:2]
        out.lost_deals = by_stage.get("Lost", (0,))[0]

        month_start = crm_service.now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        out.won_this_month_value = float(db.execute(
            select(func.coalesce(func.sum(Opportunity.value), 0))
            .where(*scope(Opportunity), Opportunity.stage == "Won", Opportunity.stage_changed_at >= month_start)
        ).scalar_one())

        # Staleness needs each open deal's last touch; the open pipeline is
        # the bounded part of the data, so this stays cheap.
        open_deals = list(db.execute(
            select(Opportunity).where(*scope(Opportunity), Opportunity.stage.in_(OPEN_STAGES))
        ).scalars())
        touches = crm_service.last_touches(db, context, open_deals)
        limits = crm_service.stale_limits(db, context)
        stale = [o for o in open_deals if crm_service.idle_status(o, touches[o.id], limits)["is_stale"]]
        out.stale_deals, out.stale_value = len(stale), sum(float(o.value) for o in stale)
        out.unassigned += sum(1 for o in open_deals if o.owner_user_id is None)

    if context.has_permission("crm.lead.read"):
        out.unassigned += db.execute(
            select(func.count()).select_from(Lead)
            .where(*scope(Lead), Lead.owner_user_id.is_(None), Lead.status.notin_(("Converted", "Lost")))
        ).scalar_one()

    if context.has_permission("crm.activity.read"):
        now = crm_service.now_utc()
        open_count, overdue_count = db.execute(
            select(func.count(), func.count(case((Activity.due_at < now, 1))))
            .where(*scope(Activity), Activity.done.is_(False))
        ).one()
        out.open_followups, out.overdue_followups = open_count, overdue_count
        overdue, _ = activity_service.list_activities(db, context, show="overdue", limit=5)
        out.overdue_items = activities_out(db, context, overdue)

    return out
