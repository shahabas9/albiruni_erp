import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    """A customer business on the platform. Every other table hangs off tenant_id."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)


class Company(Base):
    """A legal entity / branch within a tenant. Quotations, stock etc. are scoped per company."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    # Where the company is registered: decides its tax regime (regimes.py). Fixed once it has
    # issued a sales document.
    country: Mapped[str] = mapped_column(String(2), default="IN", server_default="IN")
    # First month of the financial year: 4 (April) in India, usually 1 in Saudi Arabia.
    fy_start_month: Mapped[int] = mapped_column(Integer, default=4, server_default="4")

    # Seller details printed on tax invoices (Sales → Company & Tax).
    legal_name: Mapped[str] = mapped_column(String(160), default="")
    gstin: Mapped[str] = mapped_column(String(15), default="")
    # GST state code; decides CGST+SGST (same state) versus IGST.
    state_code: Mapped[str] = mapped_column(String(2), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    # Saudi Arabia: VAT and Commercial Registration numbers, Arabic name, national address.
    vat_number: Mapped[str] = mapped_column(String(15), default="", server_default="")
    cr_number: Mapped[str] = mapped_column(String(20), default="", server_default="")
    name_ar: Mapped[str] = mapped_column(String(160), default="", server_default="")
    # Structured address (required on Saudi standard invoices; PIN / postal code in both countries).
    building_no: Mapped[str] = mapped_column(String(10), default="", server_default="")
    street: Mapped[str] = mapped_column(String(160), default="", server_default="")
    district: Mapped[str] = mapped_column(String(120), default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), default="", server_default="")
    postal_code: Mapped[str] = mapped_column(String(10), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    bank_details: Mapped[str] = mapped_column(Text, default="")
    invoice_terms: Mapped[str] = mapped_column(Text, default="")
    # Days until an invoice falls due when the customer has no terms of their own.
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    # How long a quotation's prices hold.
    quotation_validity_days: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    # Payment reminders emailed to customers: N days before the due date,
    # then on each listed day after it (comma-separated), while money is owed.
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    reminder_before_days: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    reminder_after_days: Mapped[str] = mapped_column(String(40), default="1,7,15,30", server_default="1,7,15,30")
    # Price list for customers without one of their own; None: item prices.
    default_price_list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_lists.id", use_alter=True), nullable=True
    )
    # Whether a delivery may take stock below zero.
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False)
