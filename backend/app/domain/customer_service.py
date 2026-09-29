from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates, fields
from app.domain.errors import NotFoundError
from app.models.sales import Customer
from app.schemas.customers import CustomerIn, CustomerUpdate


def list_customers(
    db: Session,
    context: RequestContext,
    *,
    q: str = "",
    active: bool | None = None,
    tag: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Customer], int]:
    """Customers by name, and how many match. q: every word in the name or GSTIN."""

    stmt = select(Customer).where(Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id)
    if active is not None:
        stmt = stmt.where(Customer.active.is_(active))
    if tag.strip():
        stmt = stmt.where(Customer.tags.contains([tag.strip().lower()]))
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
        tags=fields.normalize_tags(body.tags),
        custom=fields.clean_custom(db, context, "customer", body.custom),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(db: Session, context: RequestContext, customer_id: UUID, body: CustomerUpdate) -> Customer:
    customer = get_customer(db, context, customer_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("tags") is not None:
        customer.tags = fields.normalize_tags(data["tags"])
    if data.get("custom") is not None:
        customer.custom = fields.clean_custom(db, context, "customer", data["custom"], dict(customer.custom or {}))
    data.pop("tags", None)
    data.pop("custom", None)
    for field, value in data.items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
