from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Mode = Literal["Cash", "UPI", "Bank transfer", "Cheque", "Card", "Other"]


class AllocationIn(BaseModel):
    invoice_id: UUID
    amount: float = Field(gt=0, le=1_000_000_000)


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


class AllocateIn(BaseModel):
    # Leave out for oldest unpaid invoices first.
    allocations: list[AllocationIn] | None = Field(default=None, max_length=200)


class AllocationOut(BaseModel):
    invoice_id: UUID
    invoice_number: str | None
    amount: float


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
    allocated: float
    unallocated: float
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
