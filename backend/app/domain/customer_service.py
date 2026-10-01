from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates, fields, history
from app.domain.errors import ConflictError, NotFoundError
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


def state_for(gstin: str, state_code: str) -> str:
    """A registered customer's state is the one in their GSTIN."""

    if gstin:
        if state_code and state_code != gstin[:2]:
            raise ConflictError(f"The GSTIN is registered in state {gstin[:2]}, not {state_code}.")
        return gstin[:2]
    return state_code


def create_customer(db: Session, context: RequestContext, body: CustomerIn) -> Customer:
    if body.email.strip() and "@" not in body.email:
        raise ConflictError("That email address doesn't look right.")
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
        billing_address=body.billing_address.strip(),
        shipping_address=body.shipping_address.strip(),
        state_code=state_for(body.gstin, body.state_code),
        payment_terms_days=body.payment_terms_days,
        email=body.email.strip().lower(),
        phone=body.phone.strip(),
    )
    db.add(customer)
    db.flush()
    history.record(db, context, "customer", customer.id, "created", f"Customer created: {customer.name}")
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(db: Session, context: RequestContext, customer_id: UUID, body: CustomerUpdate) -> Customer:
    customer = get_customer(db, context, customer_id)
    data = body.model_dump(exclude_unset=True)
    for key in ("tags", "custom", "billing_address", "shipping_address", "state_code", "email", "phone"):
        if key in data and data[key] is None:
            data.pop(key)
    if data.get("email") is not None:
        data["email"] = data["email"].strip().lower()
    if data.get("email") and "@" not in data["email"]:
        raise ConflictError("That email address doesn't look right.")
    if "gstin" in data or "state_code" in data:
        gstin = data.get("gstin", customer.gstin) or ""
        # A new GSTIN brings its own state; otherwise keep (or set) the one given.
        wanted = data.get("state_code", "" if "gstin" in data and gstin else customer.state_code) or ""
        data["state_code"] = state_for(gstin, wanted)
    changes = fields.apply_tags_and_custom(db, context, "customer", customer, data)
    changes = {**history.diff(customer, data), **changes}
    if changes:
        action = "status_changed" if list(changes) == ["active"] else "updated"
        history.record(db, context, "customer", customer.id, action, history.describe(changes), changes)
    for field, value in data.items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
