from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates, fields, history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import LEAD_STATUSES, Activity, Contact, Lead, Opportunity
from app.models.sales import Customer
from app.schemas.crm import ConvertLeadIn, LeadIn, LeadUpdate


def _label(lead: Lead) -> str:
    return lead.company_name or lead.name


def list_leads(
    db: Session,
    context: RequestContext,
    *,
    q: str = "",
    status: str = "",
    owner: str = "",
    tag: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Lead], int]:
    """Leads matching the filters, newest first, and how many match in total.

    status: a status, or "open" (not Converted/Lost). owner: "me",
    "unassigned" or a user id. q: name, company, phone or email."""

    stmt = select(Lead).where(Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id)
    stmt = crm_service.only_visible(stmt, Lead.owner_user_id, context)
    if status == "open":
        stmt = stmt.where(Lead.status.notin_(("Converted", "Lost")))
    elif status:
        stmt = stmt.where(Lead.status == status)
    stmt = crm_service.filter_owner(stmt, Lead.owner_user_id, owner, context)
    if tag.strip():
        stmt = stmt.where(Lead.tags.contains([tag.strip().lower()]))
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Lead.name, Lead.company_name, Lead.email, Lead.phone))
    return crm_service.page(db, stmt.order_by(Lead.created_at.desc(), Lead.id), limit, offset)


def get_lead(db: Session, context: RequestContext, lead_id: UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if (lead is None or lead.tenant_id != context.tenant_id or lead.company_id != context.company_id
            or not crm_service.can_see(lead.owner_user_id, context)):
        raise NotFoundError(f"No lead with id {lead_id}")
    return lead


def create_lead(db: Session, context: RequestContext, body: LeadIn) -> Lead:
    if not body.allow_duplicate:
        matches = duplicates.lead_matches(db, context, phone=body.phone, email=body.email)
        if matches:
            raise duplicates.DuplicateError(
                "A lead with this phone or email already exists.", duplicates.describe_leads(matches, context)
            )
    lead = Lead(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        name=body.name.strip(),
        company_name=body.company_name.strip(),
        email=body.email.strip(),
        phone=body.phone.strip(),
        source=body.source.strip(),
        notes=body.notes,
        status="New",
        tags=fields.normalize_tags(body.tags),
        custom=fields.clean_custom(db, context, "lead", body.custom),
    )
    rotated = crm_service.next_rotation_owner(db, context) if body.assign_by_rotation else None
    lead.owner_user_id = rotated.id if rotated else crm_service.resolve_owner(db, context, body.owner_user_id)
    db.add(lead)
    db.flush()
    by = f" — assigned by rotation to {rotated.display_name}" if rotated else ""
    history.record(db, context, "lead", lead.id, "created", f"Lead created: {_label(lead)}{by}")
    db.commit()
    db.refresh(lead)
    return lead


def update_lead(db: Session, context: RequestContext, lead_id: UUID, body: LeadUpdate) -> Lead:
    lead = get_lead(db, context, lead_id)
    data = body.model_dump(exclude_unset=True)
    if lead.status == "Converted" and data:
        raise ConflictError("This lead has already been converted and can no longer be edited.")
    if "status" in data:
        if data["status"] not in LEAD_STATUSES:
            raise ConflictError(f"'{data['status']}' is not a valid lead status. Use one of: {', '.join(LEAD_STATUSES)}.")
        if data["status"] == "Converted":
            raise ConflictError("Use Convert to turn a lead into a customer — it can't be set to Converted directly.")
    changes = fields.apply_tags_and_custom(db, context, "lead", lead, data)
    changes = {**history.diff(lead, data), **changes}
    for field, value in data.items():
        setattr(lead, field, value)
    if changes:
        action = "status_changed" if list(changes) == ["status"] else "updated"
        history.record(db, context, "lead", lead.id, action, history.describe(changes), changes)
    db.commit()
    db.refresh(lead)
    return lead


def assign_lead(db: Session, context: RequestContext, lead_id: UUID, owner_user_id: UUID | None) -> Lead:
    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("This lead has already been converted — reassign its opportunity instead.")
    new_owner = crm_service.resolve_owner(db, context, owner_user_id)
    if new_owner != lead.owner_user_id:
        summary, changes = history.owner_change(db, lead.owner_user_id, new_owner)
        history.record(db, context, "lead", lead.id, "owner_changed", summary, changes)
    lead.owner_user_id = new_owner
    db.commit()
    db.refresh(lead)
    return lead


def convert_lead(
    db: Session, context: RequestContext, lead_id: UUID, body: ConvertLeadIn
) -> tuple[Lead, Customer, Contact, Opportunity | None]:
    """Lead -> Customer + Contact, and optionally an Opportunity that inherits
    the lead's owner and open follow-ups. The customer is the one the user
    picked (body.customer_id) or a new one — never matched by name, since two
    businesses can share one. Atomic: all of it commits or none does."""

    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("This lead has already been converted.")
    if lead.status == "Lost":
        raise ConflictError("This lead is marked Lost — re-qualify it before converting.")

    if body.customer_id is not None:
        customer = get_customer(db, context, body.customer_id)
        if not customer.active:
            raise ConflictError(f"{customer.name} is inactive — reactivate it or create a new customer.")
    else:
        customer = Customer(
            tenant_id=context.tenant_id,
            company_id=context.company_id,
            name=_label(lead).strip(),
            credit_limit=0,
            active=True,
        )
        db.add(customer)
        db.flush()
    contact = Contact(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        customer_id=customer.id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
    )
    db.add(contact)

    opportunity = None
    if body.create_opportunity:
        opportunity = Opportunity(
            tenant_id=context.tenant_id,
            company_id=context.company_id,
            customer_id=customer.id,
            name=body.opportunity_name.strip() or f"{customer.name} — new opportunity",
            lead_id=lead.id,
            owner_user_id=lead.owner_user_id,
            # A converted lead is qualified by definition.
            stage="Qualified",
            value=body.opportunity_value,
            expected_close_date=body.expected_close_date,
        )
        db.add(opportunity)
        db.flush()
        lead.converted_opportunity_id = opportunity.id
        history.record(
            db, context, "opportunity", opportunity.id, "created",
            f"Deal created from lead {_label(lead)} (stage Qualified)",
        )
        open_followups = select(Activity).where(Activity.lead_id == lead.id, Activity.done.is_(False))
        for activity in db.execute(open_followups).scalars():
            activity.opportunity_id = opportunity.id
            activity.lead_id = None

    lead.status = "Converted"
    lead.converted_customer_id = customer.id
    linked = "linked to existing customer" if body.customer_id else "new customer"
    history.record(db, context, "lead", lead.id, "converted", f"Converted — {linked} {customer.name}")

    db.commit()
    for record in (lead, customer, contact, opportunity):
        if record is not None:
            db.refresh(record)
    return lead, customer, contact, opportunity


def customer_matches(db: Session, context: RequestContext, lead_id: UUID) -> list[dict]:
    """Existing customers this lead might already be: same name, or a contact
    with the same phone or email. Shown at conversion so the user decides."""

    lead = get_lead(db, context, lead_id)
    reasons: dict[UUID, list[str]] = {}
    found: dict[UUID, Customer] = {}

    def add(customer: Customer, reason: str) -> None:
        found[customer.id] = customer
        if reason not in reasons.setdefault(customer.id, []):
            reasons[customer.id].append(reason)

    for c in duplicates.customer_matches(db, context, name=_label(lead)):
        add(c, "Same name")
    key, email = duplicates.phone_key(lead.phone), (lead.email or "").strip().lower()
    conditions = []
    if key:
        conditions.append(func.right(func.regexp_replace(Contact.phone, r"\D", "", "g"), 10) == key)
    if email:
        conditions.append(func.lower(Contact.email) == email)
    if conditions:
        rows = db.execute(
            select(Contact, Customer)
            .join(Customer, Customer.id == Contact.customer_id)
            .where(Contact.tenant_id == context.tenant_id, Contact.company_id == context.company_id, or_(*conditions))
            .limit(20)
        ).all()
        for contact, customer in rows:
            if key and duplicates.phone_key(contact.phone) == key:
                add(customer, f"Contact {contact.name} has this phone")
            if email and (contact.email or "").strip().lower() == email:
                add(customer, f"Contact {contact.name} has this email")
    return [
        {"id": c.id, "name": c.name, "gstin": c.gstin or "", "reasons": reasons[c.id]}
        for c in sorted(found.values(), key=lambda c: c.name.lower())
        if c.active
    ]
