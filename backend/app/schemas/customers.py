from uuid import UUID

from pydantic import BaseModel, Field


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    credit_limit: float = 0


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    credit_limit: float | None = None
    active: bool | None = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    credit_limit: float
    active: bool
