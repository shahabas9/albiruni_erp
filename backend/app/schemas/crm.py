from datetime import date, datetime
from typing import Any, Literal
from decimal import Decimal
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
    # Give it to the next person in the lead rotation (owner_user_id is then ignored).
    assign_by_rotation: bool = False
    tags: list[str] = []
    # Custom field values by key; see GET /api/crm/fields.
    custom: dict[str, Any] = {}


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
    tags: list[str] | None = None
    # Only the keys sent change; null or "" clears one.
    custom: dict[str, Any] | None = None


class MergeIn(BaseModel):
    """Fold the record `remove_id` into the one in the URL."""

    remove_id: UUID


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
    tags: list[str]
    custom: dict[str, Any]
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
    tags: list[str] = []
    # Custom field values by key; see GET /api/crm/fields.
    custom: dict[str, Any] = {}


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
    tags: list[str] | None = None
    # Only the keys sent change; null or "" clears one.
    custom: dict[str, Any] | None = None


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
    tags: list[str]
    custom: dict[str, Any]
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
    weighted: float = 0


class LostReasonCount(BaseModel):
    reason: str
    count: int


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
    # Deals closed in the last `closed_days` days (the pipeline board's window).
    closed_days: int = 90
    recent_won: int = 0
    recent_won_value: float = 0
    recent_lost: int = 0
    recent_lost_value: float = 0
    lost_reasons: list[LostReasonCount] = []
    recently_closed: list[OpportunityOut] = []
    unassigned: int = 0
    open_followups: int = 0
    overdue_followups: int = 0
    overdue_items: list[ActivityOut] = []


class RotationIn(BaseModel):
    enabled: bool
    user_ids: list[UUID]


class RotationOut(BaseModel):
    enabled: bool
    user_ids: list[UUID]
    next_user_id: UUID | None
    next_user_name: str | None


class TargetRow(BaseModel):
    user_id: UUID
    name: str
    active: bool
    target: float
    won_value: float
    won_count: int
    invoiced_value: float = 0
    invoiced_count: int = 0
    forecast: float
    pct: int | None


class TargetReport(BaseModel):
    month: str
    # What pct measures: "won" deals or "invoiced" sales.
    basis: str = "won"
    rows: list[TargetRow]
    team_target: float
    team_won: float
    team_invoiced: float = 0
    team_pct: int | None
    unowned_won_value: float
    unowned_won_count: int


class TargetIn(BaseModel):
    user_id: UUID
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class TargetsIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    targets: list[TargetIn]


class CustomFieldIn(BaseModel):
    record_type: str
    label: str = Field(min_length=1, max_length=80)
    field_type: str
    options: list[str] = []


class CustomFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    options: list[str] | None = None
    position: int | None = None
    active: bool | None = None


class CustomFieldOut(BaseModel):
    id: UUID
    record_type: str
    key: str
    label: str
    field_type: str
    options: list[str]
    position: int
    active: bool


class TagCount(BaseModel):
    tag: str
    count: int


class AttachmentOut(BaseModel):
    id: UUID
    record_type: str
    record_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_name: str | None
    created_at: datetime


class WebFormIn(BaseModel):
    enabled: bool | None = None
    source: str | None = Field(default=None, max_length=60)
    thank_you: str | None = Field(default=None, max_length=300)


class WebFormOut(BaseModel):
    enabled: bool
    key: str | None
    source: str
    thank_you: str


class BulkIn(BaseModel):
    """A bulk action on explicit ids, or on everything matching `filters`
    (the list's own filter parameters)."""

    action: str
    ids: list[UUID] | None = None
    filters: dict[str, Any] | None = None
    # assign: user id or null; status/stage: the new one; add_tag/remove_tag: the tag.
    value: Any = None
    lost_reason: str = Field(default="", max_length=200)


class BulkOut(BaseModel):
    matched: int
    done: int
    skipped: list[dict]


class TargetBasisIn(BaseModel):
    basis: Literal["won", "invoiced"]
