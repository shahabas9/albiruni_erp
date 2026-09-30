"""Import every model module so Base.metadata is fully populated for create_all() / Alembic autogenerate."""

from app.models.audit import AuditEvent
from app.models.crm import Activity, Attachment, Notification, Contact, CrmEvent, CrmSettings, CustomField, Lead, Opportunity, SalesTarget, SavedView
from app.models.documents import SalesOrder, SalesOrderLine
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
    "SalesOrder",
    "SalesOrderLine",
    "Company",
    "Tenant",
    "Lead",
    "Notification",
    "Contact",
    "Opportunity",
    "SalesTarget",
    "SavedView",
    "Activity",
    "Attachment",
    "CrmEvent",
    "CrmSettings",
    "CustomField",
]
