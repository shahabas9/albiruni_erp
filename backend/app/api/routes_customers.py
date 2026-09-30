from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, customer_service, record_admin
from app.api.routes_leads import http_error
from app.domain.errors import ConflictError, NotFoundError
from app.schemas.crm import MergeIn
from app.schemas.customers import CustomerIn, CustomerOut, CustomerUpdate

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _to_out(c) -> CustomerOut:
    return CustomerOut(
        id=c.id, name=c.name, credit_limit=float(c.credit_limit), active=c.active, gstin=c.gstin,
        tags=list(c.tags or []), custom=dict(c.custom or {}),
    )


@router.get("", response_model=list[CustomerOut])
def list_customers(
    response: Response,
    q: str = "",
    active: bool | None = None,
    tag: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """By name. The total matching count is in the X-Total-Count header."""

    customers, total = customer_service.list_customers(
        db, context, q=q, active=active, tag=tag, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_out(c) for c in customers]


@router.get("/duplicates")
def customer_duplicates(
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """Groups of customers sharing a name or GSTIN — candidates to merge."""

    return [
        {"reason": g["reason"], "customers": [_to_out(c) for c in g["customers"]]}
        for g in record_admin.customer_duplicate_groups(db, context)
    ]


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.get_customer(db, context, customer_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("", response_model=CustomerOut)
def create_customer(
    body: CustomerIn,
    context: RequestContext = Depends(require_permission("sales.customer.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.create_customer(db, context, body))
    except ConflictError as exc:  # duplicates, bad tags or custom values
        raise http_error(exc) from exc


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID,
    body: CustomerUpdate,
    context: RequestContext = Depends(require_permission("sales.customer.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.update_customer(db, context, customer_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.delete")),
    db: Session = Depends(get_db),
):
    """Only customers with no deals, quotations or converted leads — merge the others."""

    try:
        record_admin.delete_customer(db, context, customer_id)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.post("/{customer_id}/merge", response_model=CustomerOut)
def merge_customer(
    customer_id: UUID,
    body: MergeIn,
    context: RequestContext = Depends(require_permission("sales.customer.delete")),
    db: Session = Depends(get_db),
):
    """Moves everything of customer `remove_id` (contacts, deals, quotations,
    follow-ups, files, history) onto this one, then removes it."""

    try:
        return _to_out(record_admin.merge_customers(db, context, customer_id, body.remove_id))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc
