from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.routes_activities import activities_out
from app.api.routes_leads import http_error
from app.api.routes_opportunities import opportunity_rows
from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import activity_service, crm_service, fields, target_service, web_form
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPEN_STAGES, Activity, Lead, Opportunity
from app.schemas.crm import CrmSummary, CustomFieldIn, CustomFieldOut, CustomFieldUpdate, TagCount, LostReasonCount, RotationIn, RotationOut, StaleLimits, StageTotal, TargetBasisIn, TargetReport, TargetsIn, WebFormIn, WebFormOut

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


@router.get("/rotation", response_model=RotationOut)
def get_rotation(
    context: RequestContext = Depends(require_any_permission("crm.lead.read", "crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Who new leads go to in turn, and who's next. Leads use it when created
    with assign_by_rotation, from CSV rows with no Owner, and from the web
    enquiry form."""

    return crm_service.rotation_status(db, context)


@router.put("/rotation", response_model=RotationOut)
def put_rotation(
    body: RotationIn,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        return crm_service.set_rotation(db, context, body.enabled, body.user_ids)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.get("/targets", response_model=TargetReport)
def get_targets(
    month: str = Query("", description="YYYY-MM; this month when blank"),
    context: RequestContext = Depends(require_permission("crm.opportunity.read")),
    db: Session = Depends(get_db),
):
    """Each person's target for the month against the deals they won."""

    try:
        when = target_service.parse_month(month) if month else crm_service.now_utc().date().replace(day=1)
        return target_service.report(db, context, when)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.put("/targets", response_model=TargetReport)
def put_targets(
    body: TargetsIn,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Sets targets for the month; an amount of 0 removes that person's target."""

    try:
        when = target_service.parse_month(body.month)
        target_service.set_targets(db, context, when, [(t.user_id, t.amount) for t in body.targets])
        return target_service.report(db, context, when)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.put("/targets/basis", response_model=TargetReport)
def put_target_basis(
    body: TargetBasisIn,
    month: str = Query(""),
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Measure targets on deals won or on sales invoiced (by each invoice's salesperson)."""

    target_service.set_basis(db, context, body.basis)
    return get_targets(month, context, db)


@router.get("/fields", response_model=list[CustomFieldOut])
def list_custom_fields(
    record_type: str = "",
    include_archived: bool = False,
    context: RequestContext = Depends(require_any_permission(
        "crm.lead.read", "crm.opportunity.read", "sales.customer.read", "crm.settings.write",
    )),
    db: Session = Depends(get_db),
):
    """The company's custom fields (for one record type when given), in form order."""

    try:
        return fields.list_fields(db, context, record_type or None, include_archived=include_archived)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.post("/fields", response_model=CustomFieldOut)
def create_custom_field(
    body: CustomFieldIn,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        return fields.create_field(db, context, record_type=body.record_type, label=body.label,
                                   field_type=body.field_type, options=body.options)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.patch("/fields/{field_id}", response_model=CustomFieldOut)
def update_custom_field(
    field_id: UUID,
    body: CustomFieldUpdate,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Rename, change choices, reorder or archive. Archiving keeps saved values."""

    try:
        return fields.update_field(db, context, field_id, body.model_dump(exclude_unset=True))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.get("/tags", response_model=list[TagCount])
def list_tags(
    record_type: str = Query(..., description="lead, opportunity or customer"),
    context: RequestContext = Depends(require_any_permission(
        "crm.lead.read", "crm.opportunity.read", "sales.customer.read",
    )),
    db: Session = Depends(get_db),
):
    """Tags in use on a record type, most used first — for filters and suggestions."""

    try:
        return fields.tag_counts(db, context, record_type)
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.get("/web-form", response_model=WebFormOut)
def get_web_form(
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """The public enquiry form's settings, including its secret key."""

    return web_form.settings_for(db, context)


@router.put("/web-form", response_model=WebFormOut)
def put_web_form(
    body: WebFormIn,
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Turning it on for the first time creates the secret key."""

    try:
        return web_form.update_settings(db, context, **body.model_dump(exclude_unset=True))
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.post("/web-form/new-key", response_model=WebFormOut)
def new_web_form_key(
    context: RequestContext = Depends(require_permission("crm.settings.write")),
    db: Session = Depends(get_db),
):
    """Replaces the secret link; the old one stops working at once."""

    return web_form.regenerate_key(db, context)


@router.get("/summary", response_model=CrmSummary)
def summary(
    owner: str = Query("", description='Deal figures for "me", "unassigned" or a user id only'),
    closed_days: int = Query(90, ge=1, le=366),
    context: RequestContext = Depends(
        require_any_permission("crm.lead.read", "crm.opportunity.read", "crm.activity.read")
    ),
    db: Session = Depends(get_db),
):
    """Every figure is an aggregate query, so this stays fast however many
    leads, deals and follow-ups there are. `owner` narrows the deal figures
    (the pipeline board's owner filter); lead and follow-up figures are
    company-wide."""

    out = CrmSummary(closed_days=closed_days)
    scope = lambda model: (model.tenant_id == context.tenant_id, model.company_id == context.company_id)  # noqa: E731
    now = crm_service.now_utc()

    if context.has_permission("crm.opportunity.read"):
        def deals(*columns):
            stmt = select(*columns).select_from(Opportunity).where(*scope(Opportunity))
            stmt = crm_service.only_visible(stmt, Opportunity.owner_user_id, context)
            try:
                return crm_service.filter_owner(stmt, Opportunity.owner_user_id, owner, context)
            except ConflictError as exc:
                raise http_error(exc) from exc

        value = func.coalesce(func.sum(Opportunity.value), 0)
        rows = db.execute(
            deals(Opportunity.stage, func.count(), value,
                  func.coalesce(func.sum(Opportunity.value * Opportunity.probability_pct / 100), 0))
            .group_by(Opportunity.stage)
        ).all()
        by_stage = {stage: (count, float(total), float(weighted)) for stage, count, total, weighted in rows}
        empty = (0, 0.0, 0.0)
        out.by_stage = [StageTotal(stage=s, count=by_stage.get(s, empty)[0], value=by_stage.get(s, empty)[1],
                                   weighted=by_stage.get(s, empty)[2]) for s in OPEN_STAGES]
        out.open_deals = sum(by_stage.get(s, empty)[0] for s in OPEN_STAGES)
        out.open_value = sum(by_stage.get(s, empty)[1] for s in OPEN_STAGES)
        out.weighted_value = sum(by_stage.get(s, empty)[2] for s in OPEN_STAGES)
        out.won_deals, out.won_value = by_stage.get("Won", empty)[:2]
        out.lost_deals = by_stage.get("Lost", empty)[0]

        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        out.won_this_month_value = float(db.execute(
            deals(value).where(Opportunity.stage == "Won", Opportunity.stage_changed_at >= month_start)
        ).scalar_one())

        since = now - timedelta(days=closed_days)
        recent = deals(Opportunity.stage, func.count(), value).where(
            Opportunity.stage.in_(("Won", "Lost")), Opportunity.stage_changed_at >= since
        ).group_by(Opportunity.stage)
        closed = {stage: (count, float(total)) for stage, count, total in db.execute(recent)}
        out.recent_won, out.recent_won_value = closed.get("Won", (0, 0.0))
        out.recent_lost, out.recent_lost_value = closed.get("Lost", (0, 0.0))
        reason = func.coalesce(func.nullif(Opportunity.lost_reason, ""), "No reason recorded")
        out.lost_reasons = [
            LostReasonCount(reason=r, count=n)
            for r, n in db.execute(
                deals(reason, func.count())
                .where(Opportunity.stage == "Lost", Opportunity.stage_changed_at >= since)
                .group_by(reason).order_by(func.count().desc(), reason).limit(8)
            )
        ]
        latest = db.execute(
            deals(Opportunity).where(Opportunity.stage.in_(("Won", "Lost")), Opportunity.stage_changed_at >= since)
            .order_by(Opportunity.stage_changed_at.desc()).limit(6)
        ).scalars().all()
        out.recently_closed = opportunity_rows(db, context, list(latest))

        limits = crm_service.stale_limits(db, context)
        out.stale_deals, stale_value = db.execute(
            crm_service.stale_only(deals(func.count(), value).where(Opportunity.stage.in_(OPEN_STAGES)), context, limits)
        ).one()
        out.stale_value = float(stale_value)
        if not owner:
            out.unassigned += db.execute(
                deals(func.count()).where(Opportunity.stage.in_(OPEN_STAGES), Opportunity.owner_user_id.is_(None))
            ).scalar_one()

    if context.has_permission("crm.lead.read") and not owner and crm_service.sees_all(context):
        out.unassigned += db.execute(
            select(func.count()).select_from(Lead)
            .where(*scope(Lead), Lead.owner_user_id.is_(None), Lead.status.notin_(("Converted", "Lost")))
        ).scalar_one()

    if context.has_permission("crm.activity.read"):
        open_count, overdue_count = db.execute(crm_service.visible_activities(
            select(func.count(), func.count(case((Activity.due_at < now, 1))))
            .where(*scope(Activity), Activity.done.is_(False)),
            context,
        )).one()
        out.open_followups, out.overdue_followups = open_count, overdue_count
        overdue, _ = activity_service.list_activities(db, context, show="overdue", limit=5)
        out.overdue_items = activities_out(db, context, overdue)

    return out
