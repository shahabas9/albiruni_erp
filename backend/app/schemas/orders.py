from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocLineIn(BaseModel):
    item_id: UUID
    qty: float = Field(gt=0, le=10_000_000)
    # Leave out to use the item's list price. Below list price needs approval.
    unit_price: float | None = Field(default=None, ge=0)


class OrderIn(BaseModel):
    customer_id: UUID
    lines: list[DocLineIn] = Field(min_length=1, max_length=200)
    discount_pct: float = Field(default=0, ge=0, le=100)
    customer_po: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=2000)
    order_date: date | None = None


class OrderUpdate(BaseModel):
    """Drafts only. Lines, when sent, replace all the order's lines."""

    lines: list[DocLineIn] | None = Field(default=None, min_length=1, max_length=200)
    discount_pct: float | None = Field(default=None, ge=0, le=100)
    customer_po: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=2000)
    order_date: date | None = None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class DocLineOut(BaseModel):
    id: UUID
    item_id: UUID
    description: str
    hsn_code: str
    uom: str
    qty: float
    unit_price: float
    list_price: float
    gst_rate: float
    amount: float
    taxable_value: float
    cgst: float
    sgst: float
    igst: float
    delivered_qty: float
    invoiced_qty: float


class OrderOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    customer_name: str
    customer_gstin: str
    quotation_id: UUID | None
    quotation_number: str | None
    opportunity_id: UUID | None
    order_date: date
    customer_po: str
    status: str
    # Not invoiced, Partly invoiced, Invoiced.
    invoice_status: str
    place_of_supply: str
    billing_address: str
    shipping_address: str
    notes: str
    subtotal: float
    discount_pct: float
    total: float
    cgst: float
    sgst: float
    igst: float
    round_off: float
    grand_total: float
    needs_approval: bool
    approved_by_name: str | None
    cancel_reason: str
    created_by_name: str | None
    created_at: datetime
    confirmed_at: datetime | None
    lines: list[DocLineOut]
    # Only on create/update responses: low stock and the like.
    warnings: list[str] = []
