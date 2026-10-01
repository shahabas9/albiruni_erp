from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.payments import InvoicePaymentOut


class InvoiceLineIn(BaseModel):
    order_line_id: UUID
    qty: float = Field(ge=0, le=10_000_000)


class InvoiceDraftIn(BaseModel):
    # Leave out for what's delivered and not yet invoiced (services: everything not invoiced).
    lines: list[InvoiceLineIn] | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=2000)


class IssueIn(BaseModel):
    # Defaults to today; can't be in the future or before the last issued invoice this year.
    invoice_date: date | None = None


class InvoiceLineOut(BaseModel):
    id: UUID
    order_line_id: UUID
    item_id: UUID
    description: str
    hsn_code: str
    uom: str
    qty: float
    unit_price: float
    gst_rate: float
    discount_pct: float = 0
    amount: float
    taxable_value: float
    cgst: float
    sgst: float
    igst: float
    credited_qty: float
    credited_value: float


class HsnRow(BaseModel):
    hsn_code: str
    gst_rate: float
    qty: float
    taxable_value: float
    cgst: float
    sgst: float
    igst: float


class InvoiceOut(BaseModel):
    id: UUID
    number: str | None
    status: str
    # Draft, Unpaid, Partly paid, Paid or Overdue.
    payment_status: str
    order_id: UUID
    order_number: str
    customer_id: UUID
    customer_name: str
    invoice_date: date
    due_date: date
    place_of_supply: str
    place_of_supply_name: str
    seller_name: str
    seller_gstin: str
    seller_state: str
    seller_state_name: str
    seller_address: str
    buyer_name: str
    buyer_gstin: str
    buyer_state: str
    billing_address: str
    shipping_address: str
    customer_po: str
    subtotal: float
    discount_pct: float
    total: float
    cgst: float
    sgst: float
    igst: float
    round_off: float
    grand_total: float
    amount_in_words: str
    amount_paid: float
    amount_credited: float
    # TDS the customer deducted (settles the invoice like a payment).
    amount_tds: float = 0
    balance: float
    notes: str
    terms: str
    bank_details: str
    created_at: datetime
    issued_at: datetime | None
    issued_by_name: str | None
    lines: list[InvoiceLineOut]
    hsn_summary: list[HsnRow]
    # Receipts applied to this invoice (only on the single-invoice endpoint).
    payments: list["InvoicePaymentOut"] = []


class CreditLineIn(BaseModel):
    invoice_line_id: UUID
    # Returns: the quantity coming back.
    qty: float = Field(default=0, ge=0, le=10_000_000)
    # Price corrections: taxable value to take off (GST is added on top).
    amount: float = Field(default=0, ge=0, le=1_000_000_000)


class CreditNoteIn(BaseModel):
    kind: Literal["Return", "Price correction"]
    reason: str = Field(min_length=1, max_length=200)
    lines: list[CreditLineIn] = Field(min_length=1, max_length=200)
    # Returns only: put the goods back into stock.
    restock: bool = False
    note_date: date | None = None


class CreditNoteLineOut(BaseModel):
    invoice_line_id: UUID
    item_id: UUID
    description: str
    hsn_code: str
    uom: str
    qty: float
    gst_rate: float
    taxable_value: float
    cgst: float
    sgst: float
    igst: float


class CreditNoteOut(BaseModel):
    id: UUID
    number: str
    invoice_id: UUID
    invoice_number: str
    invoice_date: date
    customer_id: UUID
    customer_name: str
    buyer_gstin: str
    billing_address: str
    place_of_supply: str
    place_of_supply_name: str
    seller_name: str
    seller_gstin: str
    seller_address: str
    note_date: date
    kind: str
    reason: str
    restocked: bool
    total: float
    cgst: float
    sgst: float
    igst: float
    round_off: float
    grand_total: float
    amount_in_words: str
    created_by_name: str | None
    created_at: datetime
    lines: list[CreditNoteLineOut]
