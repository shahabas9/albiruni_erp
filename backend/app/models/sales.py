import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
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
    # "" = the company's own country; else a two-letter code (sales abroad are exports).
    country: Mapped[str] = mapped_column(String(2), default="", server_default="")
    # Saudi VAT registration number (15 digits) and Arabic name for bilingual invoices.
    vat_number: Mapped[str] = mapped_column(String(15), default="", server_default="")
    name_ar: Mapped[str] = mapped_column(String(160), default="", server_default="")
    # Structured address (required on Saudi standard invoices; PIN / postal code in both countries).
    building_no: Mapped[str] = mapped_column(String(10), default="", server_default="")
    street: Mapped[str] = mapped_column(String(160), default="", server_default="")
    district: Mapped[str] = mapped_column(String(120), default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), default="", server_default="")
    postal_code: Mapped[str] = mapped_column(String(10), default="", server_default="")
    # GST state code (place of supply). Taken from the GSTIN when there is one.
    state_code: Mapped[str] = mapped_column(String(2), default="")
    # Where invoices, statements and payment reminders go.
    email: Mapped[str] = mapped_column(String(160), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    # Agreed prices for this customer; None uses the company's default list, then item prices.
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_lists.id"), nullable=True
    )
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
    # The item's tax rate (GST in India, VAT in Saudi Arabia). None until someone
    # sets it; invoices refuse items without a rate.
    gst_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Saudi Arabia: S standard, Z zero-rated, E exempt, O out of scope, and for
    # Z/E/O the ZATCA exemption reason code. Unused in India.
    tax_category: Mapped[str] = mapped_column(String(1), default="", server_default="")
    exemption_reason: Mapped[str] = mapped_column(String(20), default="", server_default="")


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
    vat: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")  # Saudi VAT
    round_off: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    # What the customer pays: total + GST, rounded to the rupee.
    grand_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # Draft, Pending approval, Sent, Accepted, Rejected.
    status: Mapped[str] = mapped_column(String(24), default="Draft")
    # Why it was rejected, or who approved the discount.
    status_note: Mapped[str] = mapped_column(String(200), default="")
    # Prices hold until this day; None for quotations from before validity existed.
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["QuotationLine"]] = relationship(back_populates="quotation", cascade="all, delete-orphan")
    customer: Mapped["Customer"] = relationship()
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])  # noqa: F821 — app.models.identity
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
    # ZATCA category (S, Z, E, O) in Saudi Arabia; "" in India.
    tax_category: Mapped[str] = mapped_column(String(1), default="", server_default="")
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    taxable_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    quotation: Mapped["Quotation"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()


class PriceList(Base):
    """Agreed prices: per item, with quantity breaks (₹420 from 1 box, ₹400 from 100)."""

    __tablename__ = "price_lists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rows: Mapped[list["PriceListItem"]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan", order_by="PriceListItem.min_qty"
    )


class PriceListItem(Base):
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "item_id", "min_qty", name="uq_price_list_item_qty"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("price_lists.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), index=True)
    # This price applies from this quantity up (until a higher break).
    min_qty: Mapped[float] = mapped_column(Numeric(14, 2), default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))

    price_list: Mapped["PriceList"] = relationship(back_populates="rows")
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
