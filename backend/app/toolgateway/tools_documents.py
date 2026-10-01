"""Tools for sales documents that commit the business to something: confirming
and cancelling orders (and, later, deliveries, invoices and payments). The
screens call these through execute_tool, so each one lands in the audit
trail with who did it and what it said."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import (
    credit_note_service, delivery_service, invoice_service, order_service, payment_service, refund_service,
    sales_reports, share_service, tally_export,
)
from app.domain.errors import ConflictError, NotFoundError
from app.toolgateway.registry import ToolDefinition, ToolValidationError, register_tool


def _guard(fn):
    def handler(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return fn(db, context, args)
        except (ConflictError, NotFoundError) as exc:
            raise ToolValidationError(str(exc)) from exc
    return handler


@_guard
def confirm_order(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    order = order_service.confirm_order(db, context, UUID(str(args["order_id"])))
    return {"order_id": str(order.id), "number": order.number, "status": order.status,
            "result_summary": f"Confirmed order {order.number} (₹{float(order.grand_total):,.2f})"}


@_guard
def cancel_order(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    order = order_service.cancel_order(db, context, UUID(str(args["order_id"])), str(args.get("reason", "")))
    return {"order_id": str(order.id), "number": order.number, "status": order.status,
            "result_summary": f"Cancelled order {order.number}: {order.cancel_reason}"}


@_guard
def create_delivery(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    delivery = delivery_service.create_delivery(
        db, context, UUID(str(args["order_id"])), args["lines"],
        delivery_date=date.fromisoformat(args["delivery_date"]) if args.get("delivery_date") else None,
        vehicle_no=args.get("vehicle_no", ""), transporter=args.get("transporter", ""), notes=args.get("notes", ""),
    )
    return {"delivery_id": str(delivery.id), "number": delivery.number,
            "result_summary": f"Delivered {delivery.number} against order {delivery.order.number}"}


@_guard
def cancel_delivery(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    delivery = delivery_service.cancel_delivery(db, context, UUID(str(args["delivery_id"])), str(args.get("reason", "")))
    return {"delivery_id": str(delivery.id), "number": delivery.number,
            "result_summary": f"Cancelled delivery {delivery.number}; stock returned"}


@_guard
def issue_invoice(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    invoice = invoice_service.issue(
        db, context, UUID(str(args["invoice_id"])),
        date.fromisoformat(args["invoice_date"]) if args.get("invoice_date") else None,
    )
    return {"invoice_id": str(invoice.id), "number": invoice.number,
            "result_summary": f"Issued invoice {invoice.number} to {invoice.buyer_name} "
                              f"(₹{float(invoice.grand_total):,.2f})"}


@_guard
def create_credit_note(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    note = credit_note_service.create_credit_note(
        db, context, UUID(str(args["invoice_id"])), kind=args["kind"], reason=str(args.get("reason", "")),
        lines=args["lines"], restock=bool(args.get("restock")),
        note_date=date.fromisoformat(args["note_date"]) if args.get("note_date") else None,
    )
    return {"credit_note_id": str(note.id), "number": note.number,
            "result_summary": f"Credit note {note.number} for ₹{float(note.grand_total):,.2f} "
                              f"against {note.invoice.number} ({note.kind.lower()})"}


@_guard
def record_payment(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    receipt = payment_service.record_receipt(
        db, context, customer_id=UUID(str(args["customer_id"])), amount=float(args["amount"]), mode=args["mode"],
        receipt_date=date.fromisoformat(args["receipt_date"]) if args.get("receipt_date") else None,
        reference=args.get("reference", ""), notes=args.get("notes", ""), allocations=args.get("allocations"),
        tds_section=args.get("tds_section", ""),
    )
    left = payment_service.unallocated(receipt)
    return {"receipt_id": str(receipt.id), "number": receipt.number,
            "link": {"label": "Open payments", "to": "/sales/payments"},
            "result_summary": f"Recorded payment {receipt.number}: ₹{float(receipt.amount):,.2f} from "
                              f"{receipt.customer.name}" + (f" (₹{float(left):,.2f} advance)" if left > 0 else "")}


@_guard
def allocate_payment(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    receipt = payment_service.allocate(db, context, UUID(str(args["receipt_id"])), args.get("allocations"))
    return {"receipt_id": str(receipt.id), "number": receipt.number,
            "result_summary": f"Applied {receipt.number} to invoices"}


@_guard
def void_payment(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    receipt = payment_service.void_receipt(db, context, UUID(str(args["receipt_id"])), str(args.get("reason", "")))
    return {"receipt_id": str(receipt.id), "number": receipt.number,
            "result_summary": f"Voided payment {receipt.number}: {receipt.void_reason}"}


@_guard
def create_refund(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    refund = refund_service.create_refund(
        db, context, amount=float(args["amount"]), mode=args["mode"], reason=str(args.get("reason", "")),
        reference=args.get("reference", ""),
        refund_date=date.fromisoformat(args["refund_date"]) if args.get("refund_date") else None,
        receipt_id=UUID(str(args["receipt_id"])) if args.get("receipt_id") else None,
        invoice_id=UUID(str(args["invoice_id"])) if args.get("invoice_id") else None,
    )
    return {"refund_id": str(refund.id), "number": refund.number,
            "result_summary": f"Refunded ₹{float(refund.amount):,.2f} to {refund.customer.name} ({refund.number})"}


@_guard
def void_refund(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    refund = refund_service.void_refund(db, context, UUID(str(args["refund_id"])), str(args.get("reason", "")))
    return {"refund_id": str(refund.id), "number": refund.number,
            "result_summary": f"Voided refund {refund.number}: {refund.void_reason}"}


for name, purpose, permission, handler in [
    ("sales.create_refund.v1", "Pay a customer back from an advance or an invoice's credit balance.",
     "sales.payment.write", create_refund),
    ("sales.void_refund.v1", "Void a refund entered by mistake; the amount is owed back again.",
     "sales.payment.write", void_refund),
    ("sales.record_payment.v1", "Record money received and apply it to invoices.", "sales.payment.write",
     record_payment),
    ("sales.allocate_payment.v1", "Apply an advance payment to invoices.", "sales.payment.write", allocate_payment),
    ("sales.void_payment.v1", "Void a payment (e.g. a bounced cheque); its invoices are owed again.",
     "sales.payment.write", void_payment),
    ("sales.create_credit_note.v1", "Credit part of an issued invoice: a return or a price correction.",
     "sales.credit_note.write", create_credit_note),
    ("sales.issue_invoice.v1", "Issue a draft tax invoice: number it and lock it.", "sales.invoice.write",
     issue_invoice),
    ("sales.confirm_order.v1", "Confirm a draft sales order after discount and credit-limit checks.",
     "sales.order.write", confirm_order),
    ("sales.cancel_order.v1", "Cancel a sales order that has nothing delivered or invoiced.",
     "sales.order.write", cancel_order),
    ("sales.create_delivery.v1", "Deliver goods against a confirmed order, taking them out of stock.",
     "sales.delivery.write", create_delivery),
    ("sales.cancel_delivery.v1", "Cancel a delivery note and put its goods back in stock.",
     "sales.delivery.write", cancel_delivery),
]:
    register_tool(ToolDefinition(name=name, purpose=purpose, permission=permission, risk_level="L3 Execute",
                                 handler=handler))


@_guard
def export_report(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    kind = args["kind"]
    start, end = date.fromisoformat(args["date_from"]), date.fromisoformat(args["date_to"])
    if kind == "register":
        rows = sales_reports.sales_register(db, context, start, end)["rows"]
    elif kind == "tds":
        rows = sales_reports.tds_report(db, context, start, end)["rows"]
    elif kind in sales_reports.SECTIONS:
        rows = sales_reports.gstr1(db, context, start, end)[kind]
    else:
        raise ConflictError(f"Unknown report '{kind}'.")
    return {"csv": sales_reports.to_csv(kind, rows), "rows": len(rows),
            "result_summary": f"Downloaded {kind} report for {start:%d %b %Y} – {end:%d %b %Y} ({len(rows)} rows)"}


register_tool(ToolDefinition(
    name="sales.export_report.v1", purpose="Download a sales register or GSTR-1 section as CSV.",
    permission="sales.reports.read", risk_level="L1 Read", handler=export_report,
))


# --- Ask ERP: reads and drafts ---------------------------------------------------------


def receivables_summary(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    from app.domain import receivables

    customer_id = UUID(str(args["customer_id"])) if args.get("customer_id") else None
    report = receivables.ageing(db, context, customer_id=customer_id)
    if customer_id:
        row = next(iter(report["rows"]), None)
        name = args.get("customer_name", "This customer")
        if row is None or (row["invoiced_owed"] <= 0 and row["advance"] <= 0):
            message = f"{name} doesn't owe anything right now."
            items = []
        else:
            open_invoices, _ = invoice_service.list_invoices(db, context, status="unpaid", customer_id=customer_id,
                                                            limit=8)
            message = (
                f"{name} owes ₹{row['invoiced_owed']:,.0f} on {row['open_invoices']} invoice"
                f"{'' if row['open_invoices'] == 1 else 's'}"
                + (f", ₹{row['overdue']:,.0f} of it overdue" if row["overdue"] > 0 else ", none of it overdue yet")
                + (f". They also have ₹{row['advance']:,.0f} in advance." if row["advance"] > 0 else ".")
            )
            items = [{
                "title": f"{i.number} — ₹{float(invoice_service.balance(i)):,.0f} left",
                "subtitle": f"Due {i.due_date:%d %b %Y}", "tone": "bad" if invoice_service.payment_status(i) == "Overdue" else None,
                "link": f"/sales/invoices/{i.id}",
            } for i in open_invoices]
        return {"message": message, "items": items,
                "link": {"label": "Open statement", "to": f"/sales/receivables/{customer_id}"},
                "result_summary": f"Receivables for {name}"}
    rows = [r for r in report["rows"] if r["net"] > 0]
    totals = report["totals"]
    if not rows:
        message = "Nobody owes you anything right now."
    else:
        message = (f"Customers owe ₹{totals['invoiced_owed']:,.0f} in all; ₹{totals['overdue']:,.0f} is overdue"
                   + (f" (₹{totals['d90_plus']:,.0f} for more than 90 days)." if totals["d90_plus"] > 0 else "."))
    items = [{
        "title": f"{r['customer_name']} — ₹{r['net']:,.0f}",
        "subtitle": (f"₹{r['overdue']:,.0f} overdue" if r["overdue"] > 0 else "Not due yet")
                    + (f" · oldest due {r['oldest_due']:%d %b}" if r["oldest_due"] else ""),
        "tone": "bad" if r["d61_90"] + r["d90_plus"] > 0 else ("warn" if r["overdue"] > 0 else None),
        "link": f"/sales/receivables/{r['customer_id']}",
    } for r in rows[:8]]
    return {"message": message, "items": items, "link": {"label": "Open receivables", "to": "/sales/receivables"},
            "result_summary": "Receivables summary"}


@_guard
def draft_invoice(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    invoice = invoice_service.create_draft(db, context, UUID(str(args["order_id"])))
    return {"invoice_id": str(invoice.id), "result_summary": f"Drafted an invoice for order {invoice.order.number} "
                                                             f"(₹{float(invoice.grand_total):,.2f}) — check it and issue it",
            "link": {"label": "Open the draft", "to": f"/sales/invoices/{invoice.id}"}}


register_tool(ToolDefinition(
    name="sales.receivables_summary.v1", purpose="Who owes what: all customers, or one customer's open invoices.",
    permission="sales.invoice.read", risk_level="L1 Read", handler=receivables_summary,
))
register_tool(ToolDefinition(
    name="sales.draft_invoice.v1", purpose="Draft an invoice for what's delivered and not yet invoiced on an order.",
    permission="sales.invoice.write", risk_level="L2 Prepare", handler=draft_invoice,
))


def quick_sale(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    from app.domain import quick_sale as qs

    try:
        order, invoice, receipt = qs.quick_sale(
            db, context, customer_id=UUID(args["customer_id"]) if args.get("customer_id") else None,
            lines=args["lines"], discount_pct=float(args.get("discount_pct") or 0), notes=args.get("notes", ""),
            payment=args.get("payment"),
        )
    except (ConflictError, NotFoundError, PermissionError) as exc:
        raise ToolValidationError(str(exc)) from exc
    paid = f", ₹{float(receipt.amount):,.2f} received" if receipt else ", not paid yet"
    return {"order_id": str(order.id), "invoice_id": str(invoice.id),
            "receipt_id": str(receipt.id) if receipt else None,
            "result_summary": f"Counter sale: {invoice.number} for {invoice.buyer_name} "
                              f"(₹{float(invoice.grand_total):,.2f}){paid}"}


register_tool(ToolDefinition(
    name="sales.quick_sale.v1", purpose="Counter sale: order, delivery, invoice and payment in one step.",
    permission="sales.invoice.write", risk_level="L3 Execute", handler=quick_sale,
))


def share_document(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = share_service.share(
            db, context, kind=args["kind"], doc_id=UUID(args["id"]), customer_id=UUID(args["customer_id"]),
            title=args["title"], summary=args["summary"], email=args.get("email", ""),
            date_from=date.fromisoformat(args["date_from"]) if args.get("date_from") else None,
            date_to=date.fromisoformat(args["date_to"]) if args.get("date_to") else None,
        )
    except (ConflictError, NotFoundError, PermissionError) as exc:
        raise ToolValidationError(str(exc)) from exc
    sent = f"emailed to {result['emailed_to']}" if result["emailed_to"] else "share link made"
    return {**result, "result_summary": f"{args['title']}: {sent}"}


for kind, (permission, _) in share_service.KINDS.items():
    register_tool(ToolDefinition(
        name=f"sales.share_{kind}.v1", purpose=f"Send a customer a link to a {kind.replace('_', ' ')}, by email or WhatsApp.",
        permission=permission, risk_level="L2 Prepare", handler=share_document,
    ))


@_guard
def export_tally(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    start, end = date.fromisoformat(args["date_from"]), date.fromisoformat(args["date_to"])
    xml, counts = tally_export.build(db, context, start, end)
    vouchers = counts["sales"] + counts["credit_notes"] + counts["receipts"] + counts["refunds"]
    return {"xml": xml, "counts": counts,
            "result_summary": f"Exported {vouchers} vouchers to Tally for {start:%d %b %Y} – {end:%d %b %Y}"}


register_tool(ToolDefinition(
    name="sales.export_tally.v1", purpose="Download a period's sales, credit notes, receipts and refunds as Tally XML.",
    permission="sales.reports.read", risk_level="L1 Read", handler=export_tally,
))
