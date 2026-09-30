from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import receivables, tax
from app.domain.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/api/sales/receivables", tags=["receivables"])

READ = "sales.invoice.read"


@router.get("")
def ageing(as_of: date | None = None, q: str = "", context: RequestContext = Depends(require_permission(READ)),
           db: Session = Depends(get_db)):
    """Per customer: owed by age (not yet due, 1–30, 31–60, 61–90, 90+ days overdue), advances and net.
    Most overdue first."""

    return receivables.ageing(db, context, as_of=as_of, q=q)


@router.get("/{customer_id}/statement")
def statement(customer_id: UUID, date_from: date | None = None, date_to: date | None = None,
              context: RequestContext = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    """Account statement. Defaults: the current financial year to date."""

    today = date.today()
    start = date_from or date(tax.fy_start_year(today), 4, 1)
    end = date_to or today
    if end - start > timedelta(days=3 * 366):
        raise HTTPException(status_code=409, detail="A statement can cover at most three years.")
    try:
        return receivables.statement(db, context, customer_id, start, end)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
