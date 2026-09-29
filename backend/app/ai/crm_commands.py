"""Turns an understood CRM request into either a direct answer (reads) or a
confirmable action plan (writes). Never writes anything itself.

Understand (crm_parser) -> Resolve (crm_resolver) -> Authorize -> Validate
-> Preview. The confirm step in api/routes_ask.py runs the tool.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ai import crm_parser, crm_resolver
from app.core.deps import RequestContext
from app.models.crm import OPEN_STAGES, Opportunity
from app.toolgateway.registry import get_tool


@dataclass
class ActionPlan:
    tool_name: str
    args: dict[str, Any]
    title: str
    lines: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReadPlan:
    tool_name: str
    args: dict[str, Any]


@dataclass
class Reply:
    """A response that needs no tool: a question back, a refusal, or help."""

    type: str  # "clarify" | "denied" | "error" | "message"
    message: str
    options: list[str] = field(default_factory=list)


EXAMPLES = [
    "What's overdue today?",
    "Log a call with Rahman Traders — no answer",
    "Remind me to call Nisha tomorrow at 3pm",
    "Move the Al Faisal deal to negotiation",
    "Which deals are going stale?",
]


def _owns_open_deals(db: Session, context: RequestContext) -> bool:
    return db.execute(select(exists().where(
        Opportunity.tenant_id == context.tenant_id,
        Opportunity.owner_user_id == context.user.id,
        Opportunity.stage.in_(OPEN_STAGES),
    ))).scalar_one()


def _pick_target(db: Session, context: RequestContext, text: str) -> tuple[dict[str, Any] | None, str, Reply | None]:
    """Which record an activity belongs on: a single open deal beats its customer;
    a customer with several open deals gets the activity on the account."""

    matches = crm_resolver.find(db, context, text, kinds=("lead", "customer", "opportunity"))
    best = crm_resolver.top(matches)
    if not best:
        return None, "", Reply("clarify", "Who is this about? I couldn't find a lead, customer or deal with that name.")

    def key(m: crm_resolver.Match):
        return ("lead", m.id) if m.kind == "lead" else ("customer", m.customer_id)

    keys = {key(m) for m in best}
    if len(keys) > 1:
        labels = sorted({m.label for m in best})[:4]
        return None, "", Reply(
            "clarify",
            f"Did you mean {', '.join(labels[:-1])} or {labels[-1]}?" if len(labels) > 1 else f"Did you mean {labels[0]}?",
            options=[f"{text} ({label})" for label in labels],
        )

    only = best[0]
    if only.kind == "lead":
        return {"lead_id": str(only.id)}, f"Lead: {only.label}", None

    open_opps = [m for m in best if m.kind == "opportunity" and m.open]
    if len(open_opps) == 1:
        return {"opportunity_id": str(open_opps[0].id)}, f"Deal: {open_opps[0].label}", None
    deals = crm_resolver.open_deals_for_customer(db, context, only.customer_id)
    if len(deals) == 1:
        return {"opportunity_id": str(deals[0].id)}, f"Deal: {deals[0].name}", None
    customer_label = next((m.label for m in best if m.kind == "customer"), None) or (
        deals[0].customer.name if deals else only.label
    )
    return {"customer_id": str(only.customer_id)}, f"Customer: {customer_label}", None


def plan(db: Session, context: RequestContext, text: str, intent: str, timezone: str) -> ActionPlan | ReadPlan | Reply:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(tz).replace(tzinfo=None)

    # --- Reads -------------------------------------------------------------
    if intent in ("crm.overdue", "crm.stale", "crm.pipeline"):
        tool_name = {
            "crm.overdue": "crm.list_due_followups.v1",
            "crm.stale": "crm.list_stale_deals.v1",
            "crm.pipeline": "crm.pipeline_summary.v1",
        }[intent]
        everyone = crm_parser.wants_everyone(text)
        if intent != "crm.overdue" and not everyone and not _owns_open_deals(db, context):
            everyone = True  # nothing of your own to report — show the team's
        return ReadPlan(tool_name, {"everyone": everyone, "timezone": timezone})

    # --- Writes ------------------------------------------------------------
    if intent == "crm.move_stage":
        stage = crm_parser.target_stage(text)
        matches = crm_resolver.find(db, context, text, kinds=("opportunity", "customer"))
        best = crm_resolver.top(matches)
        deal_ids: dict = {}
        for m in best:
            if m.kind == "opportunity":
                deal_ids[m.id] = m.label
            else:
                for o in crm_resolver.open_deals_for_customer(db, context, m.customer_id):
                    deal_ids[o.id] = o.name
        if not deal_ids:
            return Reply("clarify", "Which deal? I couldn't find an opportunity with that name.")
        if len(deal_ids) > 1:
            labels = sorted(deal_ids.values())[:4]
            return Reply("clarify", "Which deal do you mean?", options=[f"Move {label} to {stage}" for label in labels])
        opp_id, label = next(iter(deal_ids.items()))
        opp = db.get(Opportunity, opp_id)
        reason = crm_parser.lost_reason(text) if stage == "Lost" else ""
        if stage == "Lost" and not reason:
            return Reply(
                "clarify",
                f"Why was “{label}” lost? Add the reason after a dash.",
                options=[f"Mark {label} lost — {r}" for r in ("Price too high", "Chose a competitor", "No response")],
            )
        if opp.stage == stage:
            return Reply("message", f"“{label}” is already {stage}.")
        lines = [
            {"label": "Deal", "value": label},
            {"label": "Customer", "value": opp.customer.name},
            {"label": "Stage", "value": f"{opp.stage} → {stage}"},
        ]
        if reason:
            lines.append({"label": "Lost reason", "value": reason})
        return ActionPlan(
            "crm.move_opportunity_stage.v1",
            {"opportunity_id": str(opp_id), "stage": stage, "lost_reason": reason},
            f"Move deal to {stage}",
            lines,
        )

    if intent in ("crm.log_activity", "crm.schedule_followup"):
        target, target_label, reply = _pick_target(db, context, text)
        if reply:
            return reply
        name = target_label.split(": ", 1)[1]
        kind = crm_parser.activity_type(text, default="Task" if intent == "crm.schedule_followup" else "Note")
        note = crm_parser.trailing_note(text)

        if intent == "crm.log_activity":
            verb = {"Call": "Call with", "WhatsApp": "WhatsApp with", "Meeting": "Meeting with", "Email": "Email to"}.get(kind, "Note on")
            subject = f"{verb} {name}" + (f" — {note}" if note and len(note) <= 60 else "")
            return ActionPlan(
                "crm.log_activity.v1",
                {"type": kind, "subject": subject[:200], "notes": note or text, **target},
                f"Log {kind.lower() if kind != 'WhatsApp' else 'WhatsApp'}",
                [
                    {"label": "On", "value": target_label},
                    {"label": "Type", "value": kind},
                    {"label": "Note", "value": note or text},
                    {"label": "When", "value": "Just now (logged as done)"},
                ],
            )

        when, problem = crm_parser.parse_when(text, now_local)
        if problem:
            return Reply("error", problem)
        if when is None:
            return Reply(
                "clarify",
                f"When should I remind you about {name}?",
                options=[f"{text} tomorrow at 10am", f"{text} on Friday"],
            )
        due = when.at.replace(tzinfo=tz)
        verb = {"Call": "Call", "WhatsApp": "WhatsApp", "Meeting": "Meeting with", "Email": "Email"}.get(kind, "Follow up with")
        subject = f"{verb} {name}" + (f" — {note}" if note and len(note) <= 60 else "")
        due_label = due.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
        warnings = ["That time is already in the past."] if due < datetime.now(tz) else []
        return ActionPlan(
            "crm.schedule_followup.v1",
            {"type": kind, "subject": subject[:200], "notes": note, "due_at": due.isoformat(), "due_label": due_label, **target},
            "Schedule follow-up",
            [
                {"label": "On", "value": target_label},
                {"label": "Type", "value": kind},
                {"label": "Due", "value": due_label},
                *([{"label": "Note", "value": note}] if note else []),
            ],
            warnings,
        )

    return Reply("message", "I can help with quotations and your CRM. Try: " + " · ".join(f"“{e}”" for e in EXAMPLES))


def tool_permission_reply(context: RequestContext, tool_name: str) -> Reply | None:
    tool = get_tool(tool_name)
    if tool is not None and not context.has_permission(tool.permission):
        return Reply("denied", f"You don't have permission ({tool.permission}) for that.")
    return None
