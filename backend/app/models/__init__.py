"""Import every model module so Base.metadata is fully populated for create_all() / Alembic autogenerate."""

from app.models.audit import AuditEvent
from app.models.crm import Activity, Attachment, Notification, Contact, CrmEvent, CrmSettings, CustomField, Lead, Opportunity, SalesTarget, SavedView
from app.models.documents import (
    CreditNote, CreditNoteLine, DeliveryNote, DeliveryNoteLine, Invoice, InvoiceLine, Receipt, ReceiptAllocation, Refund,
    SalesOrder, SalesOrderLine, StockMovement,
)
from app.models.identity import Role, User
from app.models.sales import Customer, DocumentCounter, Item, PriceList, PriceListItem, Quotation, QuotationLine
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
    "PriceList",
    "PriceListItem",
    "SalesOrder",
    "SalesOrderLine",
    "DeliveryNote",
    "DeliveryNoteLine",
    "StockMovement",
    "Invoice",
    "InvoiceLine",
    "CreditNote",
    "CreditNoteLine",
    "Receipt",
    "ReceiptAllocation",
    "Refund",
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
