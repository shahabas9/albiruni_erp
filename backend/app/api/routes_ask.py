from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.orchestrator import (
    PendingPreview,
    classify_intent,
    new_correlation_id,
    parse_quotation_request,
    pop_preview,
    store_preview,
)
from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.domain.sales_service import DomainValidationError, price_quotation
from app.schemas.ask import AskRequest, ConfirmRequest
from app.toolgateway.executor import execute_tool
from app.toolgateway.registry import get_tool

router = APIRouter(prefix="/api/ask", tags=["ask-erp"])

CLARIFY_HINT = (
    'Try: "Create a quotation for <customer>: 50 boxes <Item> and 20 boxes <Item>. Give 3% discount."'
)


@router.post("")
def ask(
    body: AskRequest,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Understand -> Resolve -> Authorize -> Enrich -> Validate -> Preview.

    Mirrors Appendix A's numbered flow up to (but not including) execution:
    this endpoint never writes to the database. It only returns a bound,
    confirmable preview — POST /api/ask/confirm is the only path that acts.
    """

    intent = classify_intent(body.text)  # Understand

    if intent != "sales.create_quotation":
        return {"type": "message", "message": f"I can help create a quotation right now. {CLARIFY_HINT}"}

    tool = get_tool("sales.create_quotation_draft.v1")
    assert tool is not None

    if not context.has_permission(tool.permission):  # Authorize
        return {
            "type": "denied",
            "message": f"You don't have permission ({tool.permission}) to create quotations.",
        }

    parsed = parse_quotation_request(body.text)  # Resolve (entity extraction)
    if not parsed.customer_name or not parsed.lines:
        return {"type": "clarify", "message": f"I couldn't find a customer and item lines in that request. {CLARIFY_HINT}"}

    try:
        pricing = price_quotation(  # Enrich + Validate
            db, context, parsed.customer_name, parsed.lines, parsed.discount_pct
        )
    except DomainValidationError as exc:
        return {"type": "error", "message": str(exc)}

    correlation_id = new_correlation_id()
    args = {
        "customer_name": parsed.customer_name,
        "lines": parsed.lines,
        "discount_pct": parsed.discount_pct,
        "expected_total": pricing.total,
    }
    preview = PendingPreview(
        user_id=context.user.id,
        tenant_id=context.tenant_id,
        tool_name=tool.name,
        intent=intent,
        request_text=body.text,
        correlation_id=correlation_id,
        args=args,
    )
    token = store_preview(preview)  # Preview

    return {
        "type": "preview",
        "preview_token": token,
        "correlation_id": correlation_id,
        "tool_name": tool.name,
        "risk_level": tool.risk_level,
        "customer": pricing.customer.name,
        "lines": [
            {
                "item_name": line.item.name,
                "qty": line.qty,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
            }
            for line in pricing.lines
        ],
        "subtotal": pricing.subtotal,
        "discount_pct": pricing.discount_pct,
        "discount_amount": pricing.discount_amount,
        "total": pricing.total,
        "requires_approval": pricing.requires_approval,
        "warnings": pricing.warnings,
    }


@router.post("/confirm")
def confirm(
    body: ConfirmRequest,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Confirm -> Execute -> Audit -> Respond. The only step that writes."""

    preview = pop_preview(body.preview_token)
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This preview has expired or was already used — please ask again for a fresh one.",
        )
    if preview.user_id != context.user.id or preview.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Preview does not belong to this user")

    return execute_tool(
        db,
        context,
        preview.tool_name,
        preview.args,
        request_text=preview.request_text,
        intent=preview.intent,
        correlation_id=preview.correlation_id,
        confirmed=True,
    )
