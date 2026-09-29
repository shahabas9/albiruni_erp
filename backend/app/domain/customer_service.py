from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates
from app.domain.errors import NotFoundError
from app.models.sales import Customer
from app.schemas.customers import CustomerIn, CustomerUpdate


def list_customers(
    db: Session,
    context: RequestContext,
    *,
    q: str = "",
    active: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Customer], int]:
    """Customers by name, and how many match. q: every word in the name or GSTIN."""

    stmt = select(Customer).where(Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id)
    if active is not None:
        stmt = stmt.where(Customer.active.is_(active))
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Customer.name, Customer.gstin))
    return crm_service.page(db, stmt.order_by(Customer.name, Customer.id), limit, offset)


def get_customer(db: Session, context: RequestContext, customer_id: UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.tenant_id != context.tenant_id or customer.company_id != context.company_id:
        raise NotFoundError(f"No customer with id {customer_id}")
    return customer


def create_customer(db: Session, context: RequestContext, body: CustomerIn) -> Customer:
    if not body.allow_duplicate:
        matches = duplicates.customer_matches(db, context, name=body.name, gstin=body.gstin)
        if matches:
            raise duplicates.DuplicateError(
                "A customer with this name or GSTIN already exists.", duplicates.describe_customers(matches)
            )
    customer = Customer(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        name=body.name.strip(),
        credit_limit=body.credit_limit,
        gstin=body.gstin,
        active=True,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(db: Session, context: RequestContext, customer_id: UUID, body: CustomerUpdate) -> Customer:
    customer = get_customer(db, context, customer_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
