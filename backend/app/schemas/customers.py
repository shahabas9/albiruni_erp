from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.gstin import normalize_gstin


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    credit_limit: float = 0
    gstin: str = ""

    _gstin = field_validator("gstin")(normalize_gstin)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    credit_limit: float | None = None
    active: bool | None = None
    gstin: str | None = None

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
