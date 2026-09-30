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
from app.domain import order_service, payment_service, receivables
from app.models.crm import OPEN_STAGES, Opportunity
from app.models.sales import Customer
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
    "How am I doing against my target?",
    "Show VIP leads",
    "Who owes us money?",
    "Received ₹25,000 from Rahman Traders by UPI, UTR 998877",
    "Invoice Coastal Traders' order",
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

    if intent == "crm.targets":
        return ReadPlan("crm.target_progress.v1", {"everyone": crm_parser.wants_everyone(text)})

    if intent == "crm.find":
        kind = crm_parser.record_kind(text) or "lead"
        tool_name = {"lead": "crm.find_leads.v1", "opportunity": "crm.find_deals.v1", "customer": "crm.find_customers.v1"}[kind]
        return ReadPlan(tool_name, {"kind": kind, "text": text})

    # --- Sales ---------------------------------------------------------------
    if intent.startswith("sales."):
        return _sales_plan(db, context, text, intent)

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


def _customer(db: Session, context: RequestContext, text: str, verb: str) -> tuple[Any, Reply | None]:
    """The one customer the text names, or a question back."""

    best = crm_resolver.top(crm_resolver.find(db, context, text, kinds=("customer",)))
    ids = {m.customer_id for m in best}
    if not ids:
        return None, Reply("clarify", f"Which customer {verb}? I couldn't find one with that name.")
    if len(ids) > 1:
        labels = sorted({m.label for m in best})[:4]
        return None, Reply("clarify", "Which customer do you mean?", options=[f"{text} ({label})" for label in labels])
    return db.get(Customer, next(iter(ids))), None


def _sales_plan(db: Session, context: RequestContext, text: str, intent: str) -> ActionPlan | ReadPlan | Reply:
    if intent == "sales.receivables":
        names_someone = bool(crm_resolver.top(crm_resolver.find(db, context, text, kinds=("customer",))))
        if not names_someone:
            return ReadPlan("sales.receivables_summary.v1", {})
        customer, reply = _customer(db, context, text, "do you mean")
        if reply:
            return reply
        return ReadPlan("sales.receivables_summary.v1", {"customer_id": str(customer.id), "customer_name": customer.name})

    if intent == "sales.invoice_order":
        customer, reply = _customer(db, context, text, "should I invoice")
        if reply:
            return reply
        orders, _ = order_service.list_orders(db, context, customer_id=customer.id, to_invoice=True, limit=10)
        if not orders:
            return Reply("message", f"{customer.name} has no confirmed order waiting to be invoiced.")
        if len(orders) > 1:
            return Reply("clarify", f"{customer.name} has {len(orders)} orders to invoice — open one from Sales → Orders.",
                         options=[])
        order = orders[0]
        lines = [{"label": "Order", "value": f"{order.number} ({order.status.lower()})"},
                 {"label": "Customer", "value": customer.name}]
        for l in order.lines:
            if float(l.invoiced_qty) < float(l.qty):
                lines.append({"label": l.description,
                              "value": f"{float(l.delivered_qty):g} delivered, {float(l.invoiced_qty):g} invoiced of {float(l.qty):g}"})
        return ActionPlan("sales.draft_invoice.v1", {"order_id": str(order.id)}, "Draft an invoice", lines,
                          ["It's saved as a draft: check it, then issue it from the invoice page."])

    if intent == "sales.record_payment":
        customer, reply = _customer(db, context, text, "paid")
        if reply:
            return reply
        amount = crm_parser.parse_amount(text)
        mode = crm_parser.payment_mode(text)
        reference = crm_parser.payment_reference(text)
        if mode is None:
            return Reply("clarify", "How was it paid?",
                         options=[f"{text} by {m}" for m in ("UPI", "cash", "bank transfer", "cheque")])
        if mode in ("UPI", "Bank transfer", "Cheque") and not reference:
            what = "cheque number" if mode == "Cheque" else "UTR / transaction reference"
            return Reply("clarify", f"What's the {what}? Add it like “{'cheque no' if mode == 'Cheque' else 'UTR'} 123456”.")
        owed = receivables.invoices_owed(db, context, customer.id)
        open_invoices = payment_service.open_invoices(db, context, customer.id)
        applies = ", ".join(i.number for i in open_invoices[:4]) or "nothing yet — kept as an advance"
        warnings = []
        if amount > float(owed) > 0:
            warnings.append(f"That's more than the ₹{float(owed):,.2f} owed — the rest is kept as an advance.")
        if mode == "Cash" and amount >= 200000:
            warnings.append("Cash of ₹2,00,000 or more isn't allowed (section 269ST) — this will be refused.")
        return ActionPlan(
            "sales.record_payment.v1",
            {"customer_id": str(customer.id), "amount": amount, "mode": mode, "reference": reference,
             "receipt_date": None, "notes": text[:500], "allocations": None},
            "Record payment",
            [{"label": "From", "value": customer.name}, {"label": "Amount", "value": f"₹{amount:,.2f}"},
             {"label": "Mode", "value": mode + (f" · {reference}" if reference else "")},
             {"label": "Owed now", "value": f"₹{float(owed):,.2f}"},
             {"label": "Applies to", "value": f"Oldest first: {applies}"}],
            warnings,
        )

    return Reply("message", "I can help with quotations, sales and your CRM. Try: " + " · ".join(f"“{e}”" for e in EXAMPLES))
