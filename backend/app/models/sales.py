import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_tags", "tags", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(160))
    credit_limit: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    active: Mapped[bool] = mapped_column(default=True)
    # Indian GST registration number; empty for unregistered customers.
    gstin: Mapped[str] = mapped_column(String(15), default="")
    # Lower-case labels for grouping and filtering (domain/fields.py normalizes them).
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    # Values of the company's custom fields for this record type, by field key.
    custom: Mapped[dict] = mapped_column(JSONB, default=dict)
    billing_address: Mapped[str] = mapped_column(Text, default="")
    shipping_address: Mapped[str] = mapped_column(Text, default="")
    # GST state code (place of supply). Taken from the GSTIN when there is one.
    state_code: Mapped[str] = mapped_column(String(2), default="")
    # Days to pay; None falls back to the company's default terms.
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    uom: Mapped[str] = mapped_column(String(20), default="box")
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    stock_qty: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # "goods" move stock when delivered; "service" never does.
    kind: Mapped[str] = mapped_column(String(10), default="goods")
    hsn_code: Mapped[str] = mapped_column(String(8), default="")
    # None until someone sets it; invoices refuse items without a rate.
    gst_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)


class Quotation(Base):
    __tablename__ = "quotations"
    # Numbers restart per tenant: every business has its own QT-2026-00001.
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_quotations_tenant_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    # Set when the quotation was raised from a CRM opportunity; null for walk-in quotes.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True
    )
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    # Value after discount, before GST (what the CRM counts as the deal's worth).
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    place_of_supply: Mapped[str] = mapped_column(String(2), default="")
    cgst: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sgst: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    igst: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    round_off: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    # What the customer pays: total + GST, rounded to the rupee.
    grand_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # Draft, Pending approval, Sent, Accepted, Rejected.
    status: Mapped[str] = mapped_column(String(24), default="Draft")
    # Why it was rejected, or who approved the discount.
    status_note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["QuotationLine"]] = relationship(back_populates="quotation", cascade="all, delete-orphan")
    customer: Mapped["Customer"] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship()  # noqa: F821 — app.models.crm


class QuotationLine(Base):
    __tablename__ = "quotation_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quotation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))
    hsn_code: Mapped[str] = mapped_column(String(8), default="")
    gst_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    taxable_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    quotation: Mapped["Quotation"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()


class DocumentCounter(Base):
    """Last number handed out per tenant, document kind and year. Incremented
    with an upsert that holds the row lock until commit, so two quotations
    created at the same moment can't get the same number."""

    __tablename__ = "document_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)
