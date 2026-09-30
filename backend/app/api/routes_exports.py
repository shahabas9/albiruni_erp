from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.domain.export_service import READ
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/exports", tags=["exports"])

FILTERS = {"q", "status", "owner", "tag", "stage", "stale", "customer_id", "closed_since", "active", "show",
           "lead_id", "opportunity_id"}


@router.get("/{kind}.csv")
def export_csv(
    kind: str,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """leads, opportunities, customers, contacts or activities as CSV, with the
    same filters (query parameters) and record visibility as the lists. Needs
    crm.export plus read permission on that list; every export is audited."""

    if kind not in READ:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Export one of: {', '.join(READ)}.")
    if not context.has_permission(READ[kind]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {READ[kind]}")
    filters = {k: v for k, v in request.query_params.items() if k in FILTERS}
    result = execute_tool(
        db, context, "crm.export_records.v1", {"kind": kind, "filters": filters},
        request_text=f"[export] {kind}", intent="crm.export", correlation_id=new_correlation_id(), confirmed=True,
    )
    # A byte-order mark so Excel opens UTF-8 (₹, Malayalam names) correctly.
    return Response(
        content="﻿" + result["csv"],
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"', "X-Row-Count": str(result["rows"])},
    )
