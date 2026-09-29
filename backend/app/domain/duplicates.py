"""What counts as a duplicate — one definition for the forms and CSV import.

Leads: the same phone number (last 10 digits, so "+91 94460 44556" and
"09446044556" match) or the same email. Customers: the same name (ignoring
case) or the same GSTIN.
"""

import re
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import ConflictError
from app.models.crm import Lead
from app.models.sales import Customer


class DuplicateError(ConflictError):
    """A create would duplicate existing records; `matches` says which.
    Callers show them and let the user create anyway (allow_duplicate)."""

    def __init__(self, message: str, matches: list[dict]):
        super().__init__(message)
        self.matches = matches


def phone_key(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else ""


def lead_matches(db: Session, context: RequestContext, *, phone: str, email: str, exclude: UUID | None = None) -> list[Lead]:
    key, email = phone_key(phone), (email or "").strip().lower()
    if not key and not email:
        return []
    conditions = []
    if key:
        # Compare digits only; stored numbers keep whatever formatting was typed.
        conditions.append(func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), 10) == key)
    if email:
        conditions.append(func.lower(Lead.email) == email)
    stmt = select(Lead).where(Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id, or_(*conditions))
    if exclude:
        stmt = stmt.where(Lead.id != exclude)
    return list(db.execute(stmt.limit(5)).scalars())


def customer_matches(
    db: Session, context: RequestContext, *, name: str, gstin: str = "", exclude: UUID | None = None
) -> list[Customer]:
    conditions = [func.lower(Customer.name) == name.strip().lower()]
    if gstin:
        conditions.append(Customer.gstin == gstin)
    stmt = select(Customer).where(
        Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id, or_(*conditions)
    )
    if exclude:
        stmt = stmt.where(Customer.id != exclude)
    return list(db.execute(stmt.limit(5)).scalars())


def describe_leads(leads: list[Lead]) -> list[dict]:
    return [
        {
            "id": str(lead.id),
            "label": f"{lead.company_name} ({lead.name})" if lead.company_name else lead.name,
            "detail": " · ".join(filter(None, [lead.status, lead.phone, lead.email])),
        }
        for lead in leads
    ]


def describe_customers(customers: list[Customer]) -> list[dict]:
    return [
        {"id": str(c.id), "label": c.name, "detail": " · ".join(filter(None, [c.gstin, "active" if c.active else "inactive"]))}
        for c in customers
    ]
