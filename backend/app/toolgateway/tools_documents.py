"""Tools for sales documents that commit the business to something: confirming
and cancelling orders (and, later, deliveries, invoices and payments). The
screens call these through execute_tool, so each one lands in the audit
trail with who did it and what it said."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import credit_note_service, delivery_service, invoice_service, order_service
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


for name, purpose, permission, handler in [
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
