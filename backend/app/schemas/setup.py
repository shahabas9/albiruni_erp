from typing import Literal

from pydantic import BaseModel, Field


class SetupStatus(BaseModel):
    needs_setup: bool


class BootstrapRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=120)
    company_name: str = Field(min_length=2, max_length=120)
    admin_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    # Where the first company is registered: IN (GST) or SA (VAT). Decides its tax regime.
    country: Literal["IN", "SA"] = "IN"
