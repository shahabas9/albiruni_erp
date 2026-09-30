"""Tools for sales documents that commit the business to something: confirming
and cancelling orders (and, later, deliveries, invoices and payments). The
screens call these through execute_tool, so each one lands in the audit
trail with who did it and what it said."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import order_service
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


for name, purpose, handler in [
    ("sales.confirm_order.v1", "Confirm a draft sales order after discount and credit-limit checks.", confirm_order),
    ("sales.cancel_order.v1", "Cancel a sales order that has nothing delivered or invoiced.", cancel_order),
]:
    register_tool(ToolDefinition(name=name, purpose=purpose, permission="sales.order.write",
                                 risk_level="L3 Execute", handler=handler))
