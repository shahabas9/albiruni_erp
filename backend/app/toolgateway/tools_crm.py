"""CRM tools: what Ask ERP (or, later, an LLM) is allowed to do in the CRM.

Writes are L2 Prepare — Ask ERP previews them and only the confirm step runs
them. Reads are L1 and answer straight away. Every call, read or write, goes
through the executor, so it is permission-checked and audited like the
quotation tool. Handlers take resolved ids, never names, and re-check tenant
scope through the domain services.
"""

import re
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.ai import crm_parser
from app.core.deps import RequestContext
from app.domain import activity_service, crm_service, export_service, fields, opportunity_service, target_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPEN_STAGES, Activity, Lead, Opportunity
from app.models.sales import Customer
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
    # Without "see all" there is no team view to ask for.
    return not args.get("everyone") or not crm_service.sees_all(context)


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

def export_records(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        filename, text, count = export_service.build(db, context, args["kind"], args.get("filters", {}))
    except (ConflictError, PermissionError, ValueError) as exc:
        raise ToolValidationError(str(exc)) from exc
    filters = ", ".join(f"{k}={v}" for k, v in sorted(args.get("filters", {}).items()) if v not in (None, "")) or "none"
    return {"filename": filename, "csv": text, "rows": count,
            "result_summary": f"Exported {count} {args['kind']} (filters: {filters})"}


def _inr(value: float) -> str:
    return f"₹{value:,.0f}"


def target_progress(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    month = crm_service.now_utc().date().replace(day=1)
    report = target_service.report(db, context, month)
    label = f"{month:%B}"
    link = {"label": "Open targets", "to": "/crm/targets"}
    if _mine(context, args):
        me = next((r for r in report["rows"] if r["user_id"] == context.user.id), None)
        won, target, forecast = (me["won_value"], me["target"], me["forecast"]) if me else (0.0, 0.0, 0.0)
        if target:
            gap = max(target - won, 0)
            message = (f"You've won {_inr(won)} of your {_inr(target)} target for {label} ({round(won / target * 100)}%)."
                       + (f" {_inr(gap)} to go; deals expected to close this month add {_inr(forecast)} (weighted)."
                          if gap else " Target reached. 🎉"))
        else:
            message = f"No target is set for you in {label}. You've won {_inr(won)} so far."
        return {"message": message, "items": [], "link": link, "result_summary": message}
    rows = sorted(report["rows"], key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))
    team = report["team_pct"]
    message = (f"The team has won {_inr(report['team_won'])} of {_inr(report['team_target'])} for {label} ({team}%)."
               if report["team_target"] else f"No targets set for {label}; the team has won {_inr(report['team_won'])}.")
    items = [
        {"title": r["name"], "subtitle": f"{_inr(r['won_value'])} of {_inr(r['target'])}" + (f" · {r['pct']}%" if r["pct"] is not None else " · no target"),
         "tone": None if (r["pct"] or 0) >= 60 else "bad", "link": "/crm/targets"}
        for r in rows[:12]
    ]
    return {"message": message, "items": items, "link": link, "result_summary": message}


_MODELS = {"lead": Lead, "opportunity": Opportunity, "customer": Customer}
_LIST_PAGE = {"lead": "/leads", "opportunity": "/opportunities", "customer": "/customers"}
_NOUN = {"lead": "lead", "opportunity": "deal", "customer": "customer"}


def find_records(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    """Records of one kind matching tags / dropdown values / stage or status named in the question."""

    kind, text = args["kind"], args["text"]
    model = _MODELS[kind]
    stmt = select(model).where(model.tenant_id == context.tenant_id, model.company_id == context.company_id)
    if kind != "customer":
        stmt = crm_service.only_visible(stmt, model.owner_user_id, context)
        if re.search(r"\b(my|mine)\b", text.lower()):
            stmt = stmt.where(model.owner_user_id == context.user.id)
    criteria = []

    tags = [t["tag"] for t in fields.tag_counts(db, context, kind)]
    for tag in sorted(tags, key=len, reverse=True):
        if crm_parser.mentions(text, tag):
            stmt = stmt.where(model.tags.contains([tag]))
            criteria.append(f"tagged {tag}")
    for field in fields.list_fields(db, context, kind):
        if field.field_type != "select":
            continue
        for option in field.options:
            if crm_parser.mentions(text, option):
                stmt = stmt.where(model.custom[field.key].astext == option)
                criteria.append(f"{field.label} {option}")
                break
    if kind == "opportunity":
        stage = crm_parser.target_stage(text)
        if stage:
            stmt = stmt.where(Opportunity.stage == stage)
            criteria.append(f"in {stage}")
        elif re.search(r"\bopen\b", text.lower()):
            stmt = stmt.where(Opportunity.stage.in_(OPEN_STAGES))
            criteria.append("open")
    if kind == "lead":
        for status in ("New", "Contacted", "Qualified", "Lost"):
            if crm_parser.mentions(text, status):
                stmt = stmt.where(Lead.status == status)
                criteria.append(status.lower())
                break

    noun = _NOUN[kind]
    if not criteria:
        hint = f" Tags in use: {', '.join(tags[:8])}." if tags else ""
        message = (f"Which {noun}s? I can find them by tag, by a dropdown field (like City), "
                   f"{'or by stage' if kind == 'opportunity' else 'or by status' if kind == 'lead' else ''}.{hint}")
        return {"message": message, "items": [], "link": {"label": f"Open {noun}s", "to": _LIST_PAGE[kind]},
                "result_summary": f"No criteria for {noun}s"}

    rows = list(db.execute(stmt.order_by(model.created_at.desc() if kind != "customer" else model.name).limit(200)).scalars())
    what = f"{noun}s " + ", ".join(criteria)
    if not rows:
        message = f"No {what}."
    else:
        message = f"{len(rows) if len(rows) < 200 else '200+'} {noun}{'s' if len(rows) != 1 else ''} " + ", ".join(criteria) + "."
    items = []
    for r in rows[:12]:
        if kind == "lead":
            items.append({"title": r.company_name or r.name, "subtitle": " · ".join(filter(None, [r.status, r.phone])),
                          "tone": None, "link": f"/leads?lead={r.id}"})
        elif kind == "opportunity":
            items.append({"title": r.name, "subtitle": f"{r.stage} · {_inr(float(r.value))}", "tone": None,
                          "link": f"/crm?opp={r.id}"})
        else:
            items.append({"title": r.name, "subtitle": ", ".join(r.tags or []) or "—", "tone": None,
                          "link": f"/customers/{r.id}"})
    first_tag = next((c[len("tagged "):] for c in criteria if c.startswith("tagged ")), "")
    to = _LIST_PAGE[kind] + (f"?tag={first_tag}" if first_tag else "")
    return {"message": message, "items": items, "link": {"label": f"Open {noun}s", "to": to}, "result_summary": message}


for definition in (
    ToolDefinition("crm.log_activity.v1", "Log a call, WhatsApp, meeting or note that already happened.",
                   "crm.activity.write", "L2 Prepare", log_activity),
    ToolDefinition("crm.schedule_followup.v1", "Schedule a follow-up (call, meeting, task) at a date/time.",
                   "crm.activity.write", "L2 Prepare", schedule_followup),
    ToolDefinition("crm.target_progress.v1", "How you (or the team) are doing against this month's sales target.",
                   "crm.opportunity.read", "L1 Read", target_progress),
    ToolDefinition("crm.find_leads.v1", "List leads by tag, dropdown field value or status.",
                   "crm.lead.read", "L1 Read", find_records),
    ToolDefinition("crm.find_deals.v1", "List deals by tag, dropdown field value or stage.",
                   "crm.opportunity.read", "L1 Read", find_records),
    ToolDefinition("crm.find_customers.v1", "List customers by tag or dropdown field value.",
                   "sales.customer.read", "L1 Read", find_records),
    ToolDefinition("crm.export_records.v1", "Download a CRM list as CSV (with the screen's filters).",
                   "crm.export", "L1 Read", export_records),
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
