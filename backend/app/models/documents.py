"""Sales documents after the quotation: orders, deliveries, invoices, credit
notes and payments, plus the stock movements deliveries and returns make.

Every document keeps its own copy of prices, tax rates, names and addresses
as they were when it was made, so a later change to an item or customer never
rewrites an issued document.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _money(default=0) -> Mapped[float]:
    return mapped_column(Numeric(14, 2), default=default)


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_sales_orders_tenant_number"),)

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True
    )
    order_date: Mapped[date] = mapped_column(Date)
    # The customer's own purchase order reference.
    customer_po: Mapped[str] = mapped_column(String(60), default="")
    # Draft, Confirmed, Partly delivered, Delivered, Cancelled.
    status: Mapped[str] = mapped_column(String(24), default="Draft")
    place_of_supply: Mapped[str] = mapped_column(String(2), default="")
    billing_address: Mapped[str] = mapped_column(Text, default="")
    shipping_address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    subtotal: Mapped[float] = _money()
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    total: Mapped[float] = _money()  # after discount, before GST
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()
    round_off: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[float] = _money()
    cancel_reason: Mapped[str] = mapped_column(String(200), default="")
    # Set when a manager approved the discount (here or on the quotation).
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderLine.position"
    )
    customer: Mapped["Customer"] = relationship()  # noqa: F821 — app.models.sales


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"

    id: Mapped[uuid.UUID] = _id()
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    description: Mapped[str] = mapped_column(String(200))
    hsn_code: Mapped[str] = mapped_column(String(8), default="")
    uom: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    # The item's list price when the line was made; a lower unit price needs approval.
    list_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    gst_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    amount: Mapped[float] = _money()  # qty × price
    taxable_value: Mapped[float] = _money()  # after discount
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()
    delivered_qty: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    invoiced_qty: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    order: Mapped["SalesOrder"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()  # noqa: F821 — app.models.sales
