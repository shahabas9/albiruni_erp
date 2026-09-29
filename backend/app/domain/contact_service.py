from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.customer_service import get_customer
from app.domain.errors import NotFoundError
from app.models.crm import Contact
from app.schemas.crm import ContactIn, ContactUpdate


def list_contacts(db: Session, context: RequestContext) -> list[Contact]:
    stmt = (
        select(Contact)
        .where(Contact.tenant_id == context.tenant_id, Contact.company_id == context.company_id)
        .order_by(Contact.name)
    )
    return list(db.execute(stmt).scalars().all())


def get_contact(db: Session, context: RequestContext, contact_id: UUID) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None or contact.tenant_id != context.tenant_id or contact.company_id != context.company_id:
        raise NotFoundError(f"No contact with id {contact_id}")
    return contact


def create_contact(db: Session, context: RequestContext, body: ContactIn) -> Contact:
    get_customer(db, context, body.customer_id)  # 404s if not this tenant's
    contact = Contact(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        customer_id=body.customer_id,
        name=body.name,
        title=body.title,
        email=body.email,
        phone=body.phone,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact(db: Session, context: RequestContext, contact_id: UUID, body: ContactUpdate) -> Contact:
    contact = get_contact(db, context, contact_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact
