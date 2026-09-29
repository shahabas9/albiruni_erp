from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

# --- Lead ---------------------------------------------------------------


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    company_name: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    notes: str = ""


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    status: str | None = None
    notes: str | None = None
    owner_user_id: UUID | None = None


class LeadOut(BaseModel):
    id: UUID
    name: str
    company_name: str
    email: str
    phone: str
    source: str
    status: str
    notes: str
    owner_user_id: UUID | None
    converted_customer_id: UUID | None
    created_at: datetime


class ConvertLeadIn(BaseModel):
    create_opportunity: bool = True
    opportunity_value: float = 0


class ConvertLeadOut(BaseModel):
    lead_id: UUID
    customer_id: UUID
    contact_id: UUID
    opportunity_id: UUID | None


# --- Contact --------------------------------------------------------------


class ContactIn(BaseModel):
    customer_id: UUID
    name: str = Field(min_length=1, max_length=160)
    title: str = ""
    email: str = ""
    phone: str = ""


class ContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    title: str | None = None
    email: str | None = None
    phone: str | None = None


class ContactOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    name: str
    title: str
    email: str
    phone: str


# --- Opportunity ------------------------------------------------------------


class OpportunityIn(BaseModel):
    customer_id: UUID
    name: str = Field(min_length=1, max_length=160)
    value: float = 0
    probability_pct: int = Field(default=50, ge=0, le=100)
    expected_close_date: date | None = None
    notes: str = ""


class OpportunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    stage: str | None = None
    value: float | None = None
    probability_pct: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    notes: str | None = None
    owner_user_id: UUID | None = None


class OpportunityOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    name: str
    stage: str
    value: float
    probability_pct: int
    expected_close_date: date | None
    notes: str
    owner_user_id: UUID | None
    created_at: datetime


# --- Activity --------------------------------------------------------------


class ActivityIn(BaseModel):
    type: str
    subject: str = Field(min_length=1, max_length=200)
    notes: str = ""
    due_date: date | None = None
    lead_id: UUID | None = None
    customer_id: UUID | None = None
    opportunity_id: UUID | None = None


class ActivityUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    due_date: date | None = None
    done: bool | None = None


class ActivityOut(BaseModel):
    id: UUID
    type: str
    subject: str
    notes: str
    due_date: date | None
    done: bool
    lead_id: UUID | None
    customer_id: UUID | None
    opportunity_id: UUID | None
    related_label: str
    created_at: datetime
