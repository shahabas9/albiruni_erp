from uuid import UUID

from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    uom: str = Field(default="box", max_length=20)
    unit_price: float = Field(ge=0)
    stock_qty: float = Field(default=0, ge=0)


class ItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    uom: str | None = Field(default=None, max_length=20)
    unit_price: float | None = Field(default=None, ge=0)
    stock_qty: float | None = Field(default=None, ge=0)


class ItemOut(BaseModel):
    id: UUID
    sku: str
    name: str
    uom: str
    unit_price: float
    stock_qty: float
