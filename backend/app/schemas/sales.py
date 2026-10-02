from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class QuotationLineIn(BaseModel):
    # One of: item_name (Ask ERP, typed names) or item_id (forms).
    item_name: str | None = None
    item_id: UUID | None = None
    qty: float = Field(gt=0)
    # Leave out for the customer's agreed price; below it needs approval.
    unit_price: float | None = Field(default=None, ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _one_item(self):
        if not self.item_name and not self.item_id:
            raise ValueError("Each line needs an item.")
        return self


class CreateQuotationIn(BaseModel):
    """Direct, form-based creation — the conventional-UI path. It runs through
    the exact same tool as the Ask ERP path, just with confirmation implicit
    in the button the user clicked."""

    customer_name: str | None = None
    customer_id: UUID | None = None
    lines: list[QuotationLineIn] = Field(min_length=1, max_length=200)
    discount_pct: float = Field(default=0, ge=0, le=100)
    # Defaults to today + the company's quotation validity.
    valid_until: date | None = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _one_customer(self):
        if not self.customer_name and not self.customer_id:
            raise ValueError("Choose a customer.")
        return self


class QuotationUpdate(BaseModel):
    """Drafts (and ones awaiting approval) only; lines, when sent, replace all lines.
    valid_until can also be extended on a sent quotation."""

    lines: list[QuotationLineIn] | None = Field(default=None, min_length=1, max_length=200)
    discount_pct: float | None = Field(default=None, ge=0, le=100)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class QuotationLineOut(BaseModel):
    item_id: UUID | None = None
    item_name: str
    uom: str = ""
    qty: float
    unit_price: float
    line_total: float
    hsn_code: str = ""
    gst_rate: float = 0
    tax_category: str = ""
    discount_pct: float = 0
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
    vat: float = 0
    round_off: float = 0
    grand_total: float = 0
    status: str
    status_note: str = ""
    valid_until: date | None = None
    # Draft or sent, and past valid_until.
    is_expired: bool = False
    notes: str = ""
    customer_gstin: str = ""
    billing_address: str = ""
    created_by_name: str | None = None
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
    # Where the company is registered; decides its tax regime. Fixed once it has sales documents.
    country: str = "IN"
    currency: str = "INR"
    fy_start_month: int = Field(default=4, ge=1, le=12)
    country_locked: bool = False
    # What this country's regime uses, for forms: tax name, rates, categories, rounding.
    regime: dict = {}
    legal_name: str = Field(default="", max_length=160)
    name_ar: str = Field(default="", max_length=160)
    gstin: str = ""
    state_code: str = ""
    vat_number: str = ""
    cr_number: str = ""
    address: str = Field(default="", max_length=600)
    building_no: str = ""
    street: str = Field(default="", max_length=160)
    district: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=120)
    postal_code: str = ""
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=160)
    bank_details: str = Field(default="", max_length=600)
    invoice_terms: str = Field(default="", max_length=1500)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    quotation_validity_days: int = Field(default=15, ge=0, le=365)
    allow_negative_stock: bool = False
    reminders_enabled: bool = False
    reminder_before_days: int = Field(default=3, ge=0, le=60)
    reminder_after_days: str = "1,7,15,30"


class CompanyProfileUpdate(BaseModel):
    country: str | None = None
    fy_start_month: int | None = Field(default=None, ge=1, le=12)
    legal_name: str | None = Field(default=None, max_length=160)
    name_ar: str | None = Field(default=None, max_length=160)
    gstin: str | None = None
    state_code: str | None = None
    vat_number: str | None = None
    cr_number: str | None = None
    address: str | None = Field(default=None, max_length=600)
    building_no: str | None = None
    street: str | None = Field(default=None, max_length=160)
    district: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    bank_details: str | None = Field(default=None, max_length=600)
    invoice_terms: str | None = Field(default=None, max_length=1500)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    quotation_validity_days: int | None = Field(default=None, ge=0, le=365)
    allow_negative_stock: bool | None = None
    reminders_enabled: bool | None = None
    reminder_before_days: int | None = Field(default=None, ge=0, le=60)
    reminder_after_days: str | None = Field(default=None, max_length=40)


class StateOut(BaseModel):
    code: str
    name: str
