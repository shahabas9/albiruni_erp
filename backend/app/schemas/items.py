from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain import tax


def _rate(value):
    return None if value is None else float(tax.clean_rate(value))


def _hsn(value):
    return None if value is None else tax.clean_hsn(value)


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    uom: str = Field(default="box", max_length=20)
    unit_price: float = Field(ge=0)
    stock_qty: float = Field(default=0, ge=0)
    kind: Literal["goods", "service"] = "goods"
    hsn_code: str = ""
    gst_rate: float | None = None

    _rate = field_validator("gst_rate")(_rate)
    _hsn = field_validator("hsn_code")(_hsn)


class ItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    uom: str | None = Field(default=None, max_length=20)
    unit_price: float | None = Field(default=None, ge=0)
    stock_qty: float | None = Field(default=None, ge=0)
    kind: Literal["goods", "service"] | None = None
    hsn_code: str | None = None
    gst_rate: float | None = None

    _rate = field_validator("gst_rate")(_rate)
    _hsn = field_validator("hsn_code")(_hsn)


class ItemOut(BaseModel):
    id: UUID
    sku: str
    name: str
    uom: str
    unit_price: float
    stock_qty: float
    kind: str
    hsn_code: str
    gst_rate: float | None
