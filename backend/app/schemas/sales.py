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


class QuotationOut(BaseModel):
    id: UUID
    number: str
    customer_name: str
    opportunity_id: UUID | None = None
    opportunity_title: str | None = None
    subtotal: float
    discount_pct: float
    total: float
    status: str
    created_at: datetime
    lines: list[QuotationLineOut]


class ItemOut(BaseModel):
    id: UUID
    sku: str
    name: str
    uom: str
    unit_price: float
    stock_qty: float
