from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import contact_service, crm_service, record_admin
from app.domain.errors import NotFoundError
from app.models.crm import Contact
from app.schemas.crm import ContactIn, ContactOut, ContactUpdate

router = APIRouter(prefix="/api/contacts", tags=["crm"])


def _to_out(c: Contact) -> ContactOut:
    return ContactOut(
        id=c.id, customer_id=c.customer_id, customer_name=c.customer.name, name=c.name,
        title=c.title, email=c.email, phone=c.phone,
    )


@router.get("", response_model=list[ContactOut])
def list_contacts(
    response: Response,
    q: str = "",
    customer_id: UUID | None = None,
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("crm.contact.read")),
    db: Session = Depends(get_db),
):
    """By name. The total matching count is in the X-Total-Count header."""

    contacts, total = contact_service.list_contacts(
        db, context, q=q, customer_id=customer_id, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_out(c) for c in contacts]


@router.post("", response_model=ContactOut)
def create_contact(
    body: ContactIn,
    context: RequestContext = Depends(require_permission("crm.contact.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(contact_service.create_contact(db, context, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: UUID,
    body: ContactUpdate,
    context: RequestContext = Depends(require_permission("crm.contact.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(contact_service.update_contact(db, context, contact_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: UUID,
    context: RequestContext = Depends(require_permission("crm.contact.write")),
    db: Session = Depends(get_db),
):
    try:
        record_admin.delete_contact(db, context, contact_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
