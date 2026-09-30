from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain import tax
from app.domain.gstin import normalize_gstin


def _state(value):
    return None if value is None else tax.clean_state(value)


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    credit_limit: float = 0
    gstin: str = ""
    # Create even though a customer with the same name or GSTIN exists.
    allow_duplicate: bool = False
    tags: list[str] = []
    custom: dict[str, Any] = {}
    billing_address: str = Field(default="", max_length=600)
    shipping_address: str = Field(default="", max_length=600)
    # Taken from the GSTIN when there is one.
    state_code: str = ""
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)

    _gstin = field_validator("gstin")(normalize_gstin)
    _state = field_validator("state_code")(_state)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    credit_limit: float | None = None
    active: bool | None = None
    gstin: str | None = None
    tags: list[str] | None = None
    # Only the keys sent change; null or "" clears one.
    custom: dict[str, Any] | None = None
    billing_address: str | None = Field(default=None, max_length=600)
    shipping_address: str | None = Field(default=None, max_length=600)
    state_code: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)

    _state = field_validator("state_code")(_state)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, value: str | None) -> str | None:
        return None if value is None else normalize_gstin(value)


class CustomerOut(BaseModel):
    id: UUID
    name: str
    credit_limit: float
    active: bool
    gstin: str
    tags: list[str]
    custom: dict[str, Any]
    billing_address: str = ""
    shipping_address: str = ""
    state_code: str = ""
    payment_terms_days: int | None = None
