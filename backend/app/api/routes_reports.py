from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import sales_reports
from app.domain.errors import ConflictError
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales/reports", tags=["sales reports"])

READ = "sales.reports.read"


def _run(fn):
    try:
        return fn()
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/register")
def sales_register(date_from: date, date_to: date, context: RequestContext = Depends(require_permission(READ)),
                   db: Session = Depends(get_db)):
    """Issued invoices and credit notes (as negatives) dated in the period, with totals."""

    return _run(lambda: sales_reports.sales_register(db, context, date_from, date_to))


@router.get("/gstr1")
def gstr1(date_from: date, date_to: date, context: RequestContext = Depends(require_permission(READ)),
          db: Session = Depends(get_db)):
    """GSTR-1 sections (b2b, b2cl, b2cs, cdnr, cdnur, hsn, docs) and a summary of each."""

    return _run(lambda: sales_reports.gstr1(db, context, date_from, date_to))


@router.get("/tds")
def tds(date_from: date, date_to: date, context: RequestContext = Depends(require_permission(READ)),
        db: Session = Depends(get_db)):
    """TDS customers deducted, per invoice, with whether the certificate came in."""

    return _run(lambda: sales_reports.tds_report(db, context, date_from, date_to))


@router.get("/{kind}.csv")
def report_csv(
    kind: Literal["register", "tds", "b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn", "docs"],
    date_from: date,
    date_to: date,
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """A CSV for the accountant (with a BOM so Excel reads ₹ and names correctly). Every download is audited."""

    result = execute_tool(
        db, context, "sales.export_report.v1",
        {"kind": kind, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        request_text=f"[form] Download {kind} report", intent="export_report",
        correlation_id=new_correlation_id(), confirmed=True,
    )
    prefix = {"register": "sales-register", "tds": "tds-deducted"}.get(kind, f"gstr1-{kind}")
    name = f"{prefix}-{date_from}-to-{date_to}.csv"
    return Response(
        content=result["csv"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Row-Count": str(result["rows"])},
    )
