"""Sending documents to customers: signed share links, by email or WhatsApp.

A share link is a signed token naming one document (or a customer's
statement for a period) and the company it belongs to. Anyone holding it can
view and print that document — nothing else — until it expires (30 days).
The token is signed with the app's secret, so it can't be altered to point at
another document, and changing JWT_SECRET revokes every link at once.

Email goes out through the same SMTP settings as notifications; WhatsApp is a
wa.me link with the message filled in, sent from the user's own phone or
WhatsApp Web (there's no WhatsApp Business provider wired in).
"""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import RequestContext
from app.domain import history, notifications
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Contact
from app.models.sales import Customer
from app.models.tenant import Company

KINDS = {
    # kind: (permission to share it, history record type)
    "invoice": ("sales.invoice.read", "invoice"),
    "quotation": ("sales.quotation.read", "quotation"),
    "credit_note": ("sales.invoice.read", "credit_note"),
    "receipt": ("sales.payment.read", "receipt"),
    "statement": ("sales.invoice.read", "customer"),
}
LINK_DAYS = 30
PURPOSE = "document-share"


def make_token(context: RequestContext, kind: str, doc_id: UUID, extra: dict | None = None) -> str:
    payload = {
        "purpose": PURPOSE, "kind": kind, "id": str(doc_id), "tid": str(context.tenant_id),
        "cid": str(context.company_id), "exp": datetime.now(timezone.utc) + timedelta(days=LINK_DAYS),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise NotFoundError("This link has expired or isn't valid — ask for a new one.") from exc
    if payload.get("purpose") != PURPOSE or payload.get("kind") not in KINDS:
        raise NotFoundError("This link isn't valid.")
    return payload


def public_context(payload: dict) -> RequestContext:
    """A read-only context for the document's company; no user, no permissions."""

    return RequestContext(user=None, tenant_id=UUID(payload["tid"]), company_id=UUID(payload["cid"]),
                          permissions=[], locale="en-IN", channel="share")


def link(token: str) -> str:
    return f"{settings.app_url.rstrip('/')}/d/{token}"


def recipients(db: Session, context: RequestContext, customer_id: UUID) -> list[dict]:
    """The customer's contacts with an email or phone, to pick whom to send to."""

    customer = db.get(Customer, customer_id)
    rows = db.execute(select(Contact).where(
        Contact.tenant_id == context.tenant_id, Contact.company_id == context.company_id,
        Contact.customer_id == customer_id,
    ).order_by(Contact.name)).scalars()
    billing = ([{"name": f"{customer.name} (billing)", "email": customer.email or "", "phone": customer.phone or ""}]
               if customer and (customer.email or customer.phone) else [])
    return billing + [{"name": c.name, "email": c.email or "", "phone": c.phone or ""} for c in rows
                      if c.email or c.phone]


def share(
    db: Session, context: RequestContext, *, kind: str, doc_id: UUID, customer_id: UUID, title: str, summary: str,
    email: str = "", date_from: date | None = None, date_to: date | None = None,
) -> dict:
    """A share link plus a ready message; emails it when an address is given."""

    if kind not in KINDS:
        raise ConflictError(f"'{kind}' can't be shared.")
    permission, record_type = KINDS[kind]
    if not context.has_permission(permission):
        raise PermissionError(f"Missing permission: {permission}")
    company = db.get(Company, context.company_id)
    customer = db.get(Customer, customer_id)
    extra = {"from": date_from.isoformat(), "to": date_to.isoformat()} if kind == "statement" else None
    url = link(make_token(context, kind, doc_id, extra))
    seller = company.legal_name or company.name
    message = f"Dear {customer.name},\n\n{summary}\n\nView or download it here: {url}\n\n— {seller}"
    sent_to = ""
    email = email.strip()
    if email:
        if "@" not in email or len(email) > 160:
            raise ConflictError("That email address doesn't look right.")
        if not notifications.smtp_configured():
            raise ConflictError("Email isn't set up on this server (SMTP settings) — use WhatsApp or copy the link.")
        try:
            notifications._send(email, f"{title} from {seller}", message)
        except Exception as exc:  # noqa: BLE001 — report the mail server's refusal to the user
            raise ConflictError(f"The email couldn't be sent: {exc}") from exc
        sent_to = email
    history.record(db, context, record_type, customer_id if kind == "statement" else doc_id, "shared",
                   f"{title} emailed to {sent_to}" if sent_to else f"Share link made for {title}")
    db.commit()
    return {"url": url, "message": message, "subject": f"{title} from {seller}",
            "whatsapp_text": quote(message), "emailed_to": sent_to or None,
            "expires": (datetime.now(timezone.utc) + timedelta(days=LINK_DAYS)).date()}
