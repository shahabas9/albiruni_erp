from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QuotationLineIn(BaseModel):
    item_name: str
    qty: float = Field(gt=0)


class CreateQuotationIn(BaseModel):
    """Direct, form-based creation — the conventional-UI path. It runs through
    the exact same tool as the Ask ERP path, just with confirmation implicit
    in the button the user clicked."""

    customer_name: str
    lines: list[QuotationLineIn]
    discount_pct: float = 0


class QuotationLineOut(BaseModel):
    item_name: str
    qty: float
    unit_price: float
    line_total: float
    hsn_code: str = ""
    gst_rate: float = 0
    taxable_value: float = 0
    tax_amount: float = 0


class QuotationOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID | None = None
    customer_name: str
    opportunity_id: UUID | None = None
    opportunity_title: str | None = None
    subtotal: float
    discount_pct: float
    total: float
    place_of_supply: str = ""
    cgst: float = 0
    sgst: float = 0
    igst: float = 0
    round_off: float = 0
    grand_total: float = 0
    status: str
    status_note: str = ""
    created_at: datetime
    lines: list[QuotationLineOut]
    order_id: UUID | None = None
    order_number: str | None = None


class QuotationActionIn(BaseModel):
    note: str = Field(default="", max_length=200)


class ItemOut(BaseModel):
    id: UUID
    sku: str
    name: str
    uom: str
    unit_price: float
    stock_qty: float
    kind: str = "goods"
    hsn_code: str = ""
    gst_rate: float | None = None


class CompanyProfile(BaseModel):
    """The seller's details printed on tax invoices, plus sales defaults."""

    name: str
    legal_name: str = Field(default="", max_length=160)
    gstin: str = ""
    state_code: str = ""
    address: str = Field(default="", max_length=600)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=160)
    bank_details: str = Field(default="", max_length=600)
    invoice_terms: str = Field(default="", max_length=1500)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    allow_negative_stock: bool = False


class CompanyProfileUpdate(BaseModel):
    legal_name: str | None = Field(default=None, max_length=160)
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=600)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    bank_details: str | None = Field(default=None, max_length=600)
    invoice_terms: str | None = Field(default=None, max_length=1500)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    allow_negative_stock: bool | None = None


class StateOut(BaseModel):
    code: str
    name: str
