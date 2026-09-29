from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import LEAD_STATUSES, Activity, Lead
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
        name=body.name,
        company_name=body.company_name,
        email=body.email,
        phone=body.phone,
        source=body.source,
        notes=body.notes,
        status="New",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def update_lead(db: Session, context: RequestContext, lead_id: UUID, body: LeadUpdate) -> Lead:
    lead = get_lead(db, context, lead_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in LEAD_STATUSES:
        raise ConflictError(f"'{data['status']}' is not a valid lead status. Use one of: {', '.join(LEAD_STATUSES)}.")
    if lead.status == "Converted" and data:
        raise ConflictError("This lead has already been converted and can no longer be edited.")
    for field, value in data.items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


def convert_lead(
    db: Session, context: RequestContext, lead_id: UUID, body: ConvertLeadIn
) -> tuple[Lead, Customer, "Contact", "Opportunity | None"]:  # noqa: F821
    from app.models.crm import Contact, Opportunity  # local import avoids a circular module load at startup

    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("This lead has already been converted.")

    customer = Customer(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        name=lead.company_name or lead.name,
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
            name=f"{customer.name} — new opportunity",
            lead_id=lead.id,
            owner_user_id=lead.owner_user_id,
            stage="New",
            value=body.opportunity_value,
        )
        db.add(opportunity)
        db.flush()
        lead.converted_opportunity_id = opportunity.id
        for activity in db.execute(select(Activity).where(
            Activity.lead_id == lead.id, Activity.done.is_(False)
        )).scalars():
            activity.opportunity_id = opportunity.id
            activity.lead_id = None

    lead.status = "Converted"
    lead.converted_customer_id = customer.id

    db.commit()
    db.refresh(lead)
    db.refresh(customer)
    db.refresh(contact)
    if opportunity is not None:
        db.refresh(opportunity)

    return lead, customer, contact, opportunity
