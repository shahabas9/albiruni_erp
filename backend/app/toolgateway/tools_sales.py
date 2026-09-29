"""Sales tools: the only entry points the AI orchestrator has into the Sales
domain. Each wraps app.domain.sales_service and declares its own permission
and risk level, per the "Tool & API Contract Blueprint" (Section 12).
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.sales_service import DomainValidationError, persist_quotation, price_quotation
from app.toolgateway.registry import ToolDefinition, ToolValidationError, register_tool


def create_quotation_draft(db: Session, context: RequestContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        pricing = price_quotation(
            db,
            context,
            customer_name=args["customer_name"],
            requested_lines=args["lines"],
            discount_pct=float(args.get("discount_pct", 0)),
        )
    except DomainValidationError as exc:
        raise ToolValidationError(str(exc)) from exc

    expected_total = args.get("expected_total")
    if expected_total is not None and abs(float(expected_total) - pricing.total) > 0.01:
        raise ToolValidationError(
            "Figures changed since this was previewed (price or stock moved) — please ask again for a fresh preview."
        )

    quotation = persist_quotation(db, context, pricing, created_by=context.user.id)

    return {
        "quotation_id": str(quotation.id),
        "number": quotation.number,
        "status": quotation.status,
        "customer": pricing.customer.name,
        "subtotal": pricing.subtotal,
        "discount_pct": pricing.discount_pct,
        "total": pricing.total,
        "warnings": pricing.warnings,
        "requires_approval": pricing.requires_approval,
    }


register_tool(
    ToolDefinition(
        name="sales.create_quotation_draft.v1",
        purpose="Create a priced, validated quotation draft for a customer; routes to approval if outside policy.",
        permission="sales.quotation.create",
        risk_level="L2 Prepare",
        handler=create_quotation_draft,
    )
)
