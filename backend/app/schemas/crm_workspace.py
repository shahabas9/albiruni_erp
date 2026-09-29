from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.sales import QuotationLineIn, QuotationOut


class AssigneeOut(BaseModel):
    id: UUID
    display_name: str


class OwnerIn(BaseModel):
    """owner_id=None unassigns."""

    owner_id: UUID | None = None


class LeadIn(BaseModel):
    name: str
    organization: str = ""
    phone: str = ""
    email: str = ""
    source: str = "Other"
    owner_id: UUID | None = None


class LeadStatusIn(BaseModel):
    status: str


class ConvertLeadIn(BaseModel):
    title: str = ""
    expected_value: float = Field(default=0, ge=0)
    expected_close: date | None = None


class LeadOut(BaseModel):
    id: UUID
    name: str
    organization: str
    phone: str
    email: str
    source: str
    status: str
    owner_id: UUID | None
    owner_name: str | None
    converted_opportunity_id: UUID | None
    open_activities: int
    overdue_activities: int
    next_due_at: datetime | None
    created_at: datetime


class OpportunityIn(BaseModel):
    title: str
    customer_name: str
    expected_value: float = Field(default=0, ge=0)
    expected_close: date | None = None
    owner_id: UUID | None = None


class StageIn(BaseModel):
    stage: str


class OpportunityQuotationIn(BaseModel):
    """Quote raised from an opportunity: the customer comes from the
    opportunity, so the caller only supplies lines and discount."""

    lines: list[QuotationLineIn]
    discount_pct: float = Field(default=0, ge=0, le=100)


class OpportunityOut(BaseModel):
    id: UUID
    title: str
    customer_name: str
    lead_id: UUID | None
    stage: str
    expected_value: float
    expected_close: date | None
    owner_id: UUID | None
    owner_name: str | None
    open_activities: int
    overdue_activities: int
    next_due_at: datetime | None
    quotations: list[QuotationOut]
    created_at: datetime


class ActivityIn(BaseModel):
    kind: str = "Task"
    subject: str
    due_at: datetime
    lead_id: UUID | None = None
    opportunity_id: UUID | None = None
    owner_id: UUID | None = None


class ActivityOut(BaseModel):
    id: UUID
    kind: str
    subject: str
    due_at: datetime | None
    completed_at: datetime | None
    is_overdue: bool
    lead_id: UUID | None
    opportunity_id: UUID | None
    related_name: str
    owner_id: UUID | None
    owner_name: str | None
