"""The tool gateway's execution boundary.

This is the single choke point the blueprint's architecture diagram calls
out: every AI-initiated write passes through here, and here alone permission
is re-checked and an audit event is written — success, validation failure or
permission denial alike. Nothing else in the codebase writes to AuditEvent.
"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.models.audit import AuditEvent
from app.toolgateway.registry import ToolValidationError, get_tool


def execute_tool(
    db: Session,
    context: RequestContext,
    tool_name: str,
    args: dict[str, Any],
    *,
    request_text: str,
    intent: str,
    correlation_id: str,
    confirmed: bool,
) -> dict[str, Any]:
    tool = get_tool(tool_name)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown tool: {tool_name}")

    def _write_audit(validation_result: str, result_summary: str) -> None:
        db.add(
            AuditEvent(
                tenant_id=context.tenant_id,
                company_id=context.company_id,
                actor_user_id=context.user.id,
                correlation_id=correlation_id,
                request_text=request_text,
                intent=intent,
                risk_level=tool.risk_level,
                tool_name=tool.name,
                context={"company_id": str(context.company_id), "locale": context.locale},
                arguments=args,
                validation_result=validation_result,
                confirmed=confirmed,
                result_summary=result_summary,
            )
        )
        db.commit()

    if not context.has_permission(tool.permission):
        _write_audit("DENIED", f"Missing permission: {tool.permission}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {tool.permission}")

    try:
        result = tool.handler(db, context, args)
    except ToolValidationError as exc:
        db.rollback()
        _write_audit("FAIL", f"Rejected: {exc}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    _write_audit("PASS", result.get("result_summary", f"{tool.name} succeeded"))
    return result
