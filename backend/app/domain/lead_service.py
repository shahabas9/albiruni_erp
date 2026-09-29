from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import LEAD_STATUSES, Activity, Contact, Lead, Opportunity
from app.models.sales import Customer
from app.schemas.crm import ConvertLeadIn, LeadIn, LeadUpdate


def list_leads(db: Session, context: RequestContext) -> list[Lead]:
    stmt = (
        select(Lead)
        .where(Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id)
        .order_by(Lead.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_lead(db: Session, context: RequestContext, lead_id: UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != context.tenant_id or lead.company_id != context.company_id:
        raise NotFoundError(f"No lead with id {lead_id}")
    return lead


def create_lead(db: Session, context: RequestContext, body: LeadIn) -> Lead:
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
        owner_user_id=crm_service.resolve_owner(db, context, body.owner_user_id),
    )
    db.add(lead)
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
    for field, value in data.items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


def assign_lead(db: Session, context: RequestContext, lead_id: UUID, owner_user_id: UUID | None) -> Lead:
    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("This lead has already been converted — reassign its opportunity instead.")
    lead.owner_user_id = crm_service.resolve_owner(db, context, owner_user_id)
    db.commit()
    db.refresh(lead)
    return lead


def convert_lead(
    db: Session, context: RequestContext, lead_id: UUID, body: ConvertLeadIn
) -> tuple[Lead, Customer, Contact, Opportunity | None]:
    """Lead -> Customer (reused if one with the same name exists) + Contact,
    and optionally an Opportunity that inherits the lead's owner and open
    follow-ups. Atomic: all of it commits or none does."""

    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("This lead has already been converted.")
    if lead.status == "Lost":
        raise ConflictError("This lead is marked Lost — re-qualify it before converting.")

    customer = crm_service.find_or_create_customer(db, context, lead.company_name or lead.name)
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
        open_followups = select(Activity).where(Activity.lead_id == lead.id, Activity.done.is_(False))
        for activity in db.execute(open_followups).scalars():
            activity.opportunity_id = opportunity.id
            activity.lead_id = None

    lead.status = "Converted"
    lead.converted_customer_id = customer.id

    db.commit()
    for record in (lead, customer, contact, opportunity):
        if record is not None:
            db.refresh(record)
    return lead, customer, contact, opportunity
