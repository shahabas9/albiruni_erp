from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import customer_service
from app.domain.errors import NotFoundError
from app.schemas.customers import CustomerIn, CustomerOut, CustomerUpdate

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _to_out(c) -> CustomerOut:
    return CustomerOut(id=c.id, name=c.name, credit_limit=float(c.credit_limit), active=c.active)


@router.get("", response_model=list[CustomerOut])
def list_customers(
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    return [_to_out(c) for c in customer_service.list_customers(db, context)]


@router.post("", response_model=CustomerOut)
def create_customer(
    body: CustomerIn,
    context: RequestContext = Depends(require_permission("sales.customer.write")),
    db: Session = Depends(get_db),
):
    return _to_out(customer_service.create_customer(db, context, body))


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
