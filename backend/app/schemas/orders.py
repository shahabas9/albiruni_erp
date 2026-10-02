from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocLineIn(BaseModel):
    item_id: UUID
    qty: float = Field(gt=0, le=10_000_000)
    # Leave out for the customer's agreed price (price list, else item price). Below it needs approval.
    unit_price: float | None = Field(default=None, ge=0)
    # This line's own discount; with the document's, over the limit needs approval.
    discount_pct: float = Field(default=0, ge=0, le=100)


class OrderIn(BaseModel):
    customer_id: UUID
    lines: list[DocLineIn] = Field(min_length=1, max_length=200)
    discount_pct: float = Field(default=0, ge=0, le=100)
    customer_po: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=2000)
    order_date: date | None = None
    # Who the sale counts for; the person entering it when left out.
    salesperson_id: UUID | None = None


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
    # goods or service; only goods are delivered.
    item_kind: str
    description: str
    hsn_code: str
    uom: str
    qty: float
    unit_price: float
    list_price: float
    gst_rate: float
    tax_category: str = ""
    discount_pct: float = 0
    amount: float
    taxable_value: float
    cgst: float
    sgst: float
    igst: float
    vat: float = 0
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
    vat: float = 0
    round_off: float
    grand_total: float
    needs_approval: bool
    approved_by_name: str | None
    cancel_reason: str
    salesperson_id: UUID | None = None
    salesperson_name: str | None = None
    created_by_name: str | None
    created_at: datetime
    confirmed_at: datetime | None
    lines: list[DocLineOut]
    # Only on create/update responses: low stock and the like.
    warnings: list[str] = []


class DeliveryLineIn(BaseModel):
    order_line_id: UUID
    qty: float = Field(ge=0, le=10_000_000)


class DeliveryIn(BaseModel):
    lines: list[DeliveryLineIn] = Field(min_length=1, max_length=200)
    delivery_date: date | None = None
    vehicle_no: str = Field(default="", max_length=20)
    transporter: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)


class DeliveryLineOut(BaseModel):
    order_line_id: UUID
    item_id: UUID
    description: str
    uom: str
    qty: float


class DeliveryOut(BaseModel):
    id: UUID
    number: str
    order_id: UUID
    order_number: str
    customer_id: UUID
    customer_name: str
    delivery_date: date
    status: str
    shipping_address: str
    vehicle_no: str
    transporter: str
    notes: str
    cancel_reason: str
    created_at: datetime
    lines: list[DeliveryLineOut]


class StockMovementOut(BaseModel):
    id: UUID
    kind: str
    qty: float
    balance_after: float
    ref_type: str
    ref_id: UUID | None
    ref_number: str
    note: str
    created_by_name: str | None
    created_at: datetime


class StockAdjustIn(BaseModel):
    counted_qty: float = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=1, max_length=200)


class QuickPaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000_000)
    mode: str = Field(max_length=20)
    reference: str = Field(default="", max_length=60)


class QuickSaleIn(BaseModel):
    # Leave out for the company's walk-in customer.
    customer_id: UUID | None = None
    lines: list[DocLineIn] = Field(min_length=1, max_length=200)
    discount_pct: float = Field(default=0, ge=0, le=100)
    notes: str = Field(default="", max_length=2000)
    # Leave out when the customer pays later.
    payment: QuickPaymentIn | None = None


class QuickSaleOut(BaseModel):
    order_id: UUID
    invoice_id: UUID
    receipt_id: UUID | None


class SalespersonIn(BaseModel):
    # null: counts for nobody.
    user_id: UUID | None = None
