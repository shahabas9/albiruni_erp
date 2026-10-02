from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates, fields, history, regimes
from app.domain.errors import ConflictError, NotFoundError
from app.models.sales import Customer, PriceList
from app.models.tenant import Company
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


def _check_price_list(db: Session, context: RequestContext, price_list_id: UUID | None) -> None:
    if price_list_id is None:
        return
    row = db.get(PriceList, price_list_id)
    if row is None or row.tenant_id != context.tenant_id or row.company_id != context.company_id:
        raise NotFoundError("No such price list.")


ADDRESS_FIELDS = ("country", "vat_number", "name_ar", "building_no", "street", "district", "city", "postal_code")


def _clean_identity(db: Session, context: RequestContext, data: dict) -> dict:
    """Country, VAT number and address parts, checked for the company's country (and the customer's)."""

    company = db.get(Company, context.company_id)
    regime = regimes.of(company)
    try:
        if "country" in data:
            data["country"] = regimes.clean_party_country(data["country"])
            if data["country"] == company.country:
                data["country"] = ""
        country = data.get("country") or company.country
        local = regimes.REGIMES.get(country)
        if data.get("vat_number") is not None:
            data["vat_number"] = (regimes.clean_vat_number(data["vat_number"]) if country == "SA"
                                  else data["vat_number"].strip().upper())
        if data.get("postal_code") is not None and local is not None:
            data["postal_code"] = regimes.clean_postal_code(local, data["postal_code"])
        if data.get("building_no") is not None and country == "SA":
            data["building_no"] = regimes.clean_building_no(data["building_no"])
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    for key in ("name_ar", "street", "district", "city"):
        if data.get(key) is not None:
            data[key] = data[key].strip()
    if regime.country != "IN":
        # GST fields belong to Indian companies.
        data.pop("gstin", None)
        data.pop("state_code", None)
    return data


def create_customer(db: Session, context: RequestContext, body: CustomerIn) -> Customer:
    _check_price_list(db, context, body.price_list_id)
    identity = _clean_identity(db, context, {k: getattr(body, k) for k in ADDRESS_FIELDS})
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
        price_list_id=body.price_list_id,
        **identity,
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
    if "price_list_id" in data:
        _check_price_list(db, context, data["price_list_id"])
    for key in ADDRESS_FIELDS:
        if key in data and data[key] is None:
            data.pop(key)
    data = _clean_identity(db, context, data)
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
        history.record(db, context, "customer", customer.id, action, history.describe(changes, context.currency), changes)
    for field, value in data.items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
