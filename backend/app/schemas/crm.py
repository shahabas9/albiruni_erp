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
    # Create even though a lead with the same phone or email exists.
    allow_duplicate: bool = False


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
    # Link to this existing customer; None creates a new one. Never guessed by name.
    customer_id: UUID | None = None
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
    # Required when moving to Lost (unless one is already recorded).
    lost_reason: str | None = Field(default=None, max_length=200)


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
    lost_reason: str
    stage_changed_at: datetime
    owner_user_id: UUID | None
    owner_name: str | None
    quotations: list[QuotationOut]
    # Idle-deal signal: last stage change, follow-up or quotation on the deal.
    last_touch_at: datetime
    idle_days: int
    is_stale: bool
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
    # Log something that already happened (e.g. a call just made) instead of scheduling it.
    done: bool = False


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


class CustomerMatchOut(BaseModel):
    """An existing customer a lead might really be, and why."""

    id: UUID
    name: str
    gstin: str
    reasons: list[str]


class TimelineEntry(BaseModel):
    id: UUID
    at: datetime
    record_type: str
    action: str
    summary: str
    changes: dict
    source: str
    actor_name: str | None


class StaleLimits(BaseModel):
    New: int = Field(ge=0, le=365)
    Qualified: int = Field(ge=0, le=365)
    Proposal: int = Field(ge=0, le=365)
    Negotiation: int = Field(ge=0, le=365)


class StageTotal(BaseModel):
    stage: str
    count: int
    value: float


class CrmSummary(BaseModel):
    """Headline CRM numbers for the dashboard, sidebar and bell — computed on
    the server so those screens never need every lead, deal and follow-up.
    Sections the caller can't read come back empty/zero."""

    open_deals: int = 0
    open_value: float = 0
    weighted_value: float = 0
    by_stage: list[StageTotal] = []
    stale_deals: int = 0
    stale_value: float = 0
    won_deals: int = 0
    won_value: float = 0
    lost_deals: int = 0
    won_this_month_value: float = 0
    unassigned: int = 0
    open_followups: int = 0
    overdue_followups: int = 0
    overdue_items: list[ActivityOut] = []
