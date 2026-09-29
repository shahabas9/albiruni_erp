from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.sales import QuotationLineIn, QuotationOut

# --- Lead ---------------------------------------------------------------


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    company_name: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    notes: str = ""
    # Assigning someone other than yourself needs crm.lead.assign.
    owner_user_id: UUID | None = None


class LeadUpdate(BaseModel):
    """Owner changes go through PATCH /{id}/owner (crm.lead.assign), and
    "Converted" is only reachable through POST /{id}/convert."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    status: str | None = None
    notes: str | None = None


class OwnerIn(BaseModel):
    """owner_user_id=None unassigns."""

    owner_user_id: UUID | None = None


class FollowUpSummary(BaseModel):
    open_activities: int
    overdue_activities: int
    next_due_at: datetime | None


class LeadOut(FollowUpSummary):
    id: UUID
    name: str
    company_name: str
    email: str
    phone: str
    source: str
    status: str
    notes: str
    owner_user_id: UUID | None
    owner_name: str | None
    converted_customer_id: UUID | None
    converted_opportunity_id: UUID | None
    created_at: datetime


class ConvertLeadIn(BaseModel):
    create_opportunity: bool = True
    opportunity_name: str = ""
    opportunity_value: float = Field(default=0, ge=0)
    expected_close_date: date | None = None


class ConvertLeadOut(BaseModel):
    lead_id: UUID
    customer_id: UUID
    contact_id: UUID
    opportunity_id: UUID | None


class AssigneeOut(BaseModel):
    id: UUID
    display_name: str


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
    name: str = Field(min_length=1, max_length=200)
    value: float = Field(default=0, ge=0)
    probability_pct: int = Field(default=50, ge=0, le=100)
    expected_close_date: date | None = None
    notes: str = ""
    # Assigning someone other than yourself needs crm.opportunity.assign.
    owner_user_id: UUID | None = None


class OpportunityUpdate(BaseModel):
    """Owner changes go through PATCH /{id}/owner (crm.opportunity.assign)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    stage: str | None = None
    value: float | None = Field(default=None, ge=0)
    probability_pct: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    notes: str | None = None


class OpportunityQuotationIn(BaseModel):
    """Quote raised from an opportunity: the customer comes from the
    opportunity, so the caller only supplies lines and discount."""

    lines: list[QuotationLineIn]
    discount_pct: float = Field(default=0, ge=0, le=100)


class OpportunityOut(FollowUpSummary):
    id: UUID
    customer_id: UUID
    customer_name: str
    lead_id: UUID | None
    name: str
    stage: str
    value: float
    probability_pct: int
    expected_close_date: date | None
    notes: str
    owner_user_id: UUID | None
    owner_name: str | None
    quotations: list[QuotationOut]
    created_at: datetime


# --- Activity --------------------------------------------------------------


class ActivityIn(BaseModel):
    """Give either due_date (due by the end of that day) or due_at (a
    specific time); due_at wins if both are sent."""

    type: str
    subject: str = Field(min_length=1, max_length=200)
    notes: str = ""
    due_date: date | None = None
    due_at: datetime | None = None
    lead_id: UUID | None = None
    customer_id: UUID | None = None
    opportunity_id: UUID | None = None
    # Defaults to the parent record's owner, else the creator.
    owner_id: UUID | None = None


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
    due_at: datetime | None
    done: bool
    completed_at: datetime | None
    is_overdue: bool
    lead_id: UUID | None
    customer_id: UUID | None
    opportunity_id: UUID | None
    related_label: str
    owner_id: UUID | None
    owner_name: str | None
    created_at: datetime
