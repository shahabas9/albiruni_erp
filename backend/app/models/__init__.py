"""Import every model module so Base.metadata is fully populated for create_all() / Alembic autogenerate."""

from app.models.audit import AuditEvent
from app.models.crm import Activity, Attachment, Contact, CrmEvent, CrmSettings, CustomField, Lead, Opportunity, SalesTarget
from app.models.identity import Role, User
from app.models.sales import Customer, DocumentCounter, Item, Quotation, QuotationLine
from app.models.tenant import Company, Tenant

__all__ = [
    "AuditEvent",
    "Role",
    "User",
    "Customer",
    "Item",
    "DocumentCounter",
    "Quotation",
    "QuotationLine",
    "Company",
    "Tenant",
    "Lead",
    "Contact",
    "Opportunity",
    "SalesTarget",
    "Activity",
    "Attachment",
    "CrmEvent",
    "CrmSettings",
    "CustomField",
]
