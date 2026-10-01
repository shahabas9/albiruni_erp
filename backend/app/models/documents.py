"""Sales documents after the quotation: orders, deliveries, invoices, credit
notes and payments, plus the stock movements deliveries and returns make.

Every document keeps its own copy of prices, tax rates, names and addresses
as they were when it was made, so a later change to an item or customer never
rewrites an issued document.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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


class StockMovement(Base):
    """One change to an item's stock. Stock is never edited in place: the
    item's stock_qty is the running sum of these."""

    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), index=True)
    # Opening, Adjustment, Delivery, Delivery cancelled, Return.
    kind: Mapped[str] = mapped_column(String(24))
    qty: Mapped[float] = mapped_column(Numeric(14, 2))  # + in, − out
    balance_after: Mapped[float] = mapped_column(Numeric(14, 2))
    ref_type: Mapped[str] = mapped_column(String(24), default="")
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ref_number: Mapped[str] = mapped_column(String(30), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_delivery_notes_tenant_number"),)

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str] = mapped_column(String(30))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    delivery_date: Mapped[date] = mapped_column(Date)
    # Delivered or Cancelled.
    status: Mapped[str] = mapped_column(String(16), default="Delivered")
    shipping_address: Mapped[str] = mapped_column(Text, default="")
    vehicle_no: Mapped[str] = mapped_column(String(20), default="")
    transporter: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    cancel_reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["DeliveryNoteLine"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")
    order: Mapped["SalesOrder"] = relationship()
    customer: Mapped["Customer"] = relationship()  # noqa: F821


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[uuid.UUID] = _id()
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_notes.id", ondelete="CASCADE")
    )
    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_order_lines.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    description: Mapped[str] = mapped_column(String(200))
    uom: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Numeric(14, 2))

    delivery: Mapped["DeliveryNote"] = relationship(back_populates="lines")


class Invoice(Base):
    """A GST tax invoice. A draft has no number; issuing gives it the next
    INV/yy-yy/n and locks it — from then on only credit notes and payments
    change what's owed on it."""

    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_invoices_tenant_number"),)

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    # Draft or Issued.
    status: Mapped[str] = mapped_column(String(16), default="Draft")
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    place_of_supply: Mapped[str] = mapped_column(String(2), default="")
    # Seller and buyer as printed, fixed when issued.
    seller_name: Mapped[str] = mapped_column(String(160), default="")
    seller_gstin: Mapped[str] = mapped_column(String(15), default="")
    seller_state: Mapped[str] = mapped_column(String(2), default="")
    seller_address: Mapped[str] = mapped_column(Text, default="")
    buyer_name: Mapped[str] = mapped_column(String(160), default="")
    buyer_gstin: Mapped[str] = mapped_column(String(15), default="")
    buyer_state: Mapped[str] = mapped_column(String(2), default="")
    billing_address: Mapped[str] = mapped_column(Text, default="")
    shipping_address: Mapped[str] = mapped_column(Text, default="")
    customer_po: Mapped[str] = mapped_column(String(60), default="")
    subtotal: Mapped[float] = _money()
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    total: Mapped[float] = _money()  # taxable value
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()
    round_off: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[float] = _money()
    # Running totals kept in step with receipts and credit notes.
    amount_paid: Mapped[float] = _money()
    amount_credited: Mapped[float] = _money()
    # Tax the customer deducted at source (TDS) instead of paying it to us.
    amount_tds: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    bank_details: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    issued_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Reminder stages already sent to the customer, as days from the due date (−3, 1, 7…).
    reminder_offsets_sent: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, server_default="{}")
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.position"
    )
    order: Mapped["SalesOrder"] = relationship()

    @classmethod
    def left_expr(cls):
        """What's still owed, as SQL: total − paid − credited − TDS deducted."""

        return cls.grand_total - cls.amount_paid - cls.amount_credited - cls.amount_tds
    customer: Mapped["Customer"] = relationship()  # noqa: F821


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = _id()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_order_lines.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    description: Mapped[str] = mapped_column(String(200))
    hsn_code: Mapped[str] = mapped_column(String(8), default="")
    uom: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    gst_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    amount: Mapped[float] = _money()
    taxable_value: Mapped[float] = _money()
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()
    # How much of this line credit notes have taken back: returned quantity,
    # and taxable value (returns and price corrections together).
    credited_qty: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    credited_value: Mapped[float] = _money()

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()  # noqa: F821


class CreditNote(Base):
    """Takes back part of an issued invoice: goods returned (optionally back
    into stock) or a price corrected. Issued as soon as it's made."""

    __tablename__ = "credit_notes"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_credit_notes_tenant_number"),)

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str] = mapped_column(String(16))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    note_date: Mapped[date] = mapped_column(Date)
    # Return or Price correction.
    kind: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200))
    restocked: Mapped[bool] = mapped_column(default=False)
    total: Mapped[float] = _money()  # taxable value
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()
    round_off: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[float] = _money()
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["CreditNoteLine"]] = relationship(back_populates="credit_note", cascade="all, delete-orphan")
    invoice: Mapped["Invoice"] = relationship()
    customer: Mapped["Customer"] = relationship()  # noqa: F821


class CreditNoteLine(Base):
    __tablename__ = "credit_note_lines"

    id: Mapped[uuid.UUID] = _id()
    credit_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_notes.id", ondelete="CASCADE")
    )
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice_lines.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    description: Mapped[str] = mapped_column(String(200))
    hsn_code: Mapped[str] = mapped_column(String(8), default="")
    uom: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Numeric(14, 2), default=0)  # 0 for a price correction
    gst_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    taxable_value: Mapped[float] = _money()
    cgst: Mapped[float] = _money()
    sgst: Mapped[float] = _money()
    igst: Mapped[float] = _money()

    credit_note: Mapped["CreditNote"] = relationship(back_populates="lines")


class Receipt(Base):
    """Money received from a customer. Split across invoices by allocations;
    whatever isn't allocated is an advance that can be applied later."""

    __tablename__ = "receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_receipts_tenant_number"),)

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    number: Mapped[str] = mapped_column(String(16))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    receipt_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = _money()
    # Cash, UPI, Bank transfer, Cheque, Card, Other.
    mode: Mapped[str] = mapped_column(String(20))
    # UTR, cheque number, card slip…
    reference: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # Received or Voided (a bounced cheque, a mistaken entry).
    status: Mapped[str] = mapped_column(String(12), default="Received")
    void_reason: Mapped[str] = mapped_column(String(200), default="")
    # TDS the customer deducted from this payment (on top of `amount`), its section, and
    # whether their TDS certificate (Form 16A) has come in.
    tds_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    tds_section: Mapped[str] = mapped_column(String(10), default="", server_default="")
    tds_certificate_received: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    allocations: Mapped[list["ReceiptAllocation"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )
    customer: Mapped["Customer"] = relationship()  # noqa: F821


class ReceiptAllocation(Base):
    __tablename__ = "receipt_allocations"

    id: Mapped[uuid.UUID] = _id()
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), index=True)
    amount: Mapped[float] = _money()
    tds_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    receipt: Mapped["Receipt"] = relationship(back_populates="allocations")
    invoice: Mapped["Invoice"] = relationship()
