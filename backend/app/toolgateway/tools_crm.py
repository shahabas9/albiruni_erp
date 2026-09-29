"""CRM tools: what Ask ERP (or, later, an LLM) is allowed to do in the CRM.

Writes are L2 Prepare — Ask ERP previews them and only the confirm step runs
them. Reads are L1 and answer straight away. Every call, read or write, goes
through the executor, so it is permission-checked and audited like the
quotation tool. Handlers take resolved ids, never names, and re-check tenant
scope through the domain services.
"""

from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import activity_service, crm_service, opportunity_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPEN_STAGES, Activity, Opportunity
from app.schemas.crm import ActivityIn, OpportunityUpdate
from app.toolgateway.registry import ToolDefinition, ToolValidationError, register_tool

_TARGETS = ("lead_id", "customer_id", "opportunity_id")


def _target(args: dict[str, Any]) -> dict[str, UUID]:
    return {k: UUID(str(args[k])) for k in _TARGETS if args.get(k)}


def _link_for(target: dict[str, UUID]) -> dict[str, str]:
    if "opportunity_id" in target:
        return {"label": "Open deal", "to": f"/crm?opp={target['opportunity_id']}"}
    if "lead_id" in target:
        return {"label": "Open leads", "to": "/leads"}
    return {"label": "Open activities", "to": "/activities"}


# --- Writes (L2) ----------------------------------------------------------------


def log_activity(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    target = _target(args)
    try:
        activity = activity_service.create_activity(db, context, ActivityIn(
            type=args["type"], subject=args["subject"], notes=args.get("notes", ""), done=True, **target,
        ))
    except (NotFoundError, ConflictError) as exc:
        raise ToolValidationError(str(exc)) from exc
    return {
        "activity_id": str(activity.id),
        "result_summary": f"Logged: {activity.subject}",
        "link": _link_for(target),
    }


def schedule_followup(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    target = _target(args)
    try:
        activity = activity_service.create_activity(db, context, ActivityIn(
            type=args["type"], subject=args["subject"], notes=args.get("notes", ""),
            due_at=datetime.fromisoformat(args["due_at"]), **target,
        ))
    except (NotFoundError, ConflictError) as exc:
        raise ToolValidationError(str(exc)) from exc
    return {
        "activity_id": str(activity.id),
        "result_summary": f"Scheduled: {activity.subject} ({args.get('due_label', args['due_at'])})",
        "link": _link_for(target),
    }


def move_opportunity_stage(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        opp = opportunity_service.update_opportunity(db, context, UUID(str(args["opportunity_id"])), OpportunityUpdate(
            stage=args["stage"], **({"lost_reason": args["lost_reason"]} if args.get("lost_reason") else {}),
        ))
    except (NotFoundError, ConflictError) as exc:
        raise ToolValidationError(str(exc)) from exc
    reason = f" — {opp.lost_reason}" if opp.stage == "Lost" else ""
    return {
        "opportunity_id": str(opp.id),
        "result_summary": f"Moved “{opp.name}” to {opp.stage}{reason}",
        "link": {"label": "Open deal", "to": f"/crm?opp={opp.id}"},
    }


# --- Reads (L1) -----------------------------------------------------------------


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _mine(context: RequestContext, args: dict[str, Any]) -> bool:
    return not args.get("everyone")


def list_due_followups(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    tz = ZoneInfo(args.get("timezone") or "UTC")
    now = crm_service.now_utc()
    end_of_today = datetime.combine(now.astimezone(tz).date(), time(23, 59, 59), tz)
    stmt = select(Activity).where(
        Activity.tenant_id == context.tenant_id,
        Activity.company_id == context.company_id,
        Activity.done.is_(False),
        Activity.due_at.is_not(None),
        Activity.due_at <= end_of_today,
    ).order_by(Activity.due_at)
    if _mine(context, args):
        stmt = stmt.where(Activity.owner_id == context.user.id)
    rows = list(db.execute(stmt).scalars())
    labels = activity_service.related_labels(db, context, rows)
    overdue = [a for a in rows if crm_service.is_overdue(a, now)]
    today = [a for a in rows if a not in overdue]

    items = []
    for a in [*overdue, *today]:
        late = a in overdue
        days = (now - a.due_at).days
        when = (f"{days} day{'s' if days != 1 else ''} overdue" if days >= 1 else "overdue since earlier today") if late else (
            f"due today at {a.due_at.astimezone(tz):%H:%M}")
        items.append({
            "title": a.subject,
            "subtitle": f"{labels[a.id]} · {when}",
            "tone": "bad" if late else None,
            "link": f"/crm?opp={a.opportunity_id}" if a.opportunity_id else "/activities?show=overdue",
        })
    whose = "The team has" if not _mine(context, args) else "You have"
    if not items:
        message = f"{whose} nothing overdue or due today. 🎉" if _mine(context, args) else "Nothing overdue or due today across the team."
    else:
        message = f"{whose} {len(overdue)} overdue and {len(today)} due today."
    return {
        "message": message,
        "items": items[:12],
        "link": {"label": "All follow-ups", "to": "/activities?show=overdue"},
        "result_summary": message,
    }


def _open_deals_query(context: RequestContext, args: dict[str, Any], *columns) -> Select:
    stmt = select(*columns).select_from(Opportunity).where(
        Opportunity.tenant_id == context.tenant_id,
        Opportunity.company_id == context.company_id,
        Opportunity.stage.in_(OPEN_STAGES),
    )
    if _mine(context, args):
        stmt = stmt.where(Opportunity.owner_user_id == context.user.id)
    return stmt



def list_stale_deals(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    limits = crm_service.stale_limits(db, context)
    open_count = db.execute(_open_deals_query(context, args, func.count())).scalar_one()
    stale_deals = list(db.execute(
        crm_service.stale_only(_open_deals_query(context, args, Opportunity), context, limits)
    ).scalars())
    touches = crm_service.last_touches(db, context, stale_deals)
    stale = sorted(
        ((o, crm_service.idle_status(o, touches[o.id], limits)) for o in stale_deals),
        key=lambda pair: pair[1]["idle_days"],
        reverse=True,
    )
    whose = "your" if _mine(context, args) else "the team's"
    message = (
        f"{len(stale)} of {whose} {_n(open_count, 'open deal')} {'is' if len(stale) == 1 else 'are'} going stale." if stale
        else f"None of {whose} {_n(open_count, 'open deal')} are going stale."
    )
    return {
        "message": message,
        "items": [
            {
                "title": o.name,
                "subtitle": f"{o.stage} · ₹{float(o.value):,.0f} · idle {s['idle_days']} days",
                "tone": "warn",
                "link": f"/crm?opp={o.id}",
            }
            for o, s in stale[:12]
        ],
        "link": {"label": "Open pipeline", "to": "/crm"},
        "result_summary": message,
    }


def pipeline_summary(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    rows = db.execute(
        _open_deals_query(context, args, Opportunity.stage, func.count(), func.coalesce(func.sum(Opportunity.value), 0),
                          func.coalesce(func.sum(Opportunity.value * Opportunity.probability_pct / 100), 0))
        .group_by(Opportunity.stage)
    ).all()
    by_stage = {stage: (count, float(value)) for stage, count, value, _ in rows}
    open_count = sum(count for count, _ in by_stage.values())
    total = sum(value for _, value in by_stage.values())
    weighted = sum(float(w) for *_, w in rows)
    since = crm_service.now_utc() - timedelta(days=30)
    closed = dict(db.execute(
        select(Opportunity.stage, func.count()).where(
            Opportunity.tenant_id == context.tenant_id,
            Opportunity.company_id == context.company_id,
            Opportunity.stage.in_(("Won", "Lost")),
            Opportunity.stage_changed_at >= since,
            *((Opportunity.owner_user_id == context.user.id,) if _mine(context, args) else ()),
        ).group_by(Opportunity.stage)
    ).all())
    whose = "Your" if _mine(context, args) else "The team's"
    message = (
        f"{whose} pipeline: {_n(open_count, 'open deal')} worth ₹{total:,.0f}, weighted forecast ₹{weighted:,.0f}. "
        f"Last 30 days: {closed.get('Won', 0)} won, {closed.get('Lost', 0)} lost."
    )
    items = [
        {
            "title": stage,
            "subtitle": f"{count} deal{'s' if count != 1 else ''} · ₹{value:,.0f}",
            "tone": None,
            "link": "/crm",
        }
        for stage in OPEN_STAGES
        for count, value in [by_stage.get(stage, (0, 0.0))]
        if count
    ]
    return {"message": message, "items": items, "link": {"label": "Open pipeline", "to": "/crm"}, "result_summary": message}

for definition in (
    ToolDefinition("crm.log_activity.v1", "Log a call, WhatsApp, meeting or note that already happened.",
                   "crm.activity.write", "L2 Prepare", log_activity),
    ToolDefinition("crm.schedule_followup.v1", "Schedule a follow-up (call, meeting, task) at a date/time.",
                   "crm.activity.write", "L2 Prepare", schedule_followup),
    ToolDefinition("crm.move_opportunity_stage.v1", "Move a deal to another stage, or close it as Won/Lost.",
                   "crm.opportunity.write", "L2 Prepare", move_opportunity_stage),
    ToolDefinition("crm.list_due_followups.v1", "Follow-ups that are overdue or due today.",
                   "crm.activity.read", "L1 Read", list_due_followups),
    ToolDefinition("crm.list_stale_deals.v1", "Open deals nobody has touched for too long.",
                   "crm.opportunity.read", "L1 Read", list_stale_deals),
    ToolDefinition("crm.pipeline_summary.v1", "Open pipeline, weighted forecast and recent wins/losses.",
                   "crm.opportunity.read", "L1 Read", pipeline_summary),
):
    register_tool(definition)
