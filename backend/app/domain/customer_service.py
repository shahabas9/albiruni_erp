from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import NotFoundError
from app.models.sales import Customer
from app.schemas.customers import CustomerIn, CustomerUpdate


def list_customers(db: Session, context: RequestContext) -> list[Customer]:
    stmt = (
        select(Customer)
        .where(Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id)
        .order_by(Customer.name)
    )
    return list(db.execute(stmt).scalars().all())


def get_customer(db: Session, context: RequestContext, customer_id: UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.tenant_id != context.tenant_id or customer.company_id != context.company_id:
        raise NotFoundError(f"No customer with id {customer_id}")
    return customer


def create_customer(db: Session, context: RequestContext, body: CustomerIn) -> Customer:
    customer = Customer(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        name=body.name,
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
