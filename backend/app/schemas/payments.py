from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Mode = Literal["Cash", "UPI", "Bank transfer", "Cheque", "Card", "Other"]


class AllocationIn(BaseModel):
    invoice_id: UUID
    # Money received against this invoice.
    amount: float = Field(default=0, ge=0, le=1_000_000_000)
    # TDS the customer deducted on this invoice instead of paying it.
    tds_amount: float = Field(default=0, ge=0, le=1_000_000_000)


class ReceiptIn(BaseModel):
    customer_id: UUID
    amount: float = Field(gt=0, le=1_000_000_000)
    mode: Mode
    receipt_date: date | None = None
    # UTR for bank/UPI, cheque number for cheques.
    reference: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=2000)
    # Leave out to settle the oldest unpaid invoices first; [] keeps it all as an advance.
    allocations: list[AllocationIn] | None = Field(default=None, max_length=200)
    # Needed when allocations deduct TDS: 194Q, 194C, 194J…
    tds_section: str = Field(default="", max_length=10)


class AllocateIn(BaseModel):
    # Leave out for oldest unpaid invoices first.
    allocations: list[AllocationIn] | None = Field(default=None, max_length=200)


class AllocationOut(BaseModel):
    invoice_id: UUID
    invoice_number: str | None
    amount: float
    tds_amount: float = 0


class ReceiptOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    customer_name: str
    receipt_date: date
    amount: float
    mode: str
    reference: str
    notes: str
    status: str
    void_reason: str
    tds_amount: float = 0
    tds_section: str = ""
    tds_certificate_received: bool = False
    allocated: float
    unallocated: float
    refunded: float = 0
    amount_in_words: str
    created_by_name: str | None
    created_at: datetime
    allocations: list[AllocationOut]


class InvoicePaymentOut(BaseModel):
    receipt_id: UUID
    number: str
    receipt_date: date
    mode: str
    reference: str
    amount: float
    tds_amount: float = 0


class TdsCertificateIn(BaseModel):
    received: bool


class RefundIn(BaseModel):
    # One of these: an advance payment, or an invoice with a credit balance.
    receipt_id: UUID | None = None
    invoice_id: UUID | None = None
    amount: float = Field(gt=0)
    mode: Mode
    reference: str = Field(default="", max_length=60)
    reason: str = Field(min_length=1, max_length=200)
    refund_date: date | None = None


class RefundOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    customer_name: str
    refund_date: date
    amount: float
    mode: str
    reference: str
    reason: str
    status: str
    void_reason: str
    receipt_id: UUID | None
    invoice_id: UUID | None
    # The receipt or invoice number it was paid from.
    source_number: str
    created_by_name: str | None
    created_at: datetime
