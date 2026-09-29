import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.core.database import Base

# Kept as plain strings rather than a DB enum: adding a pipeline stage should
# never require a migration, only a product decision. The API is the source
# of truth for which values are valid (see schemas/crm.py).
LEAD_STATUSES = ["New", "Contacted", "Qualified", "Converted", "Lost"]
OPPORTUNITY_STAGES = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
ACTIVITY_TYPES = ["Call", "WhatsApp", "Meeting", "Email", "Task", "Note"]
ACTIVITY_KINDS = ACTIVITY_TYPES
OPEN_STAGES = ("New", "Qualified", "Proposal", "Negotiation")
# Suggestions for the lost-reason picker; any non-empty text is accepted.
LOST_REASONS = ["Price too high", "Chose a competitor", "No budget", "No response", "Timing / postponed", "Requirement changed"]


class Lead(Base):
    """Raw, unqualified interest — the top of the funnel. Converts into a
    Customer (+ Contact, + optionally an Opportunity) via lead_service.convert_lead,
    never edited in place into one."""

    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))

    name: Mapped[str] = mapped_column(String(160))
    company_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="New")
    notes: Mapped[str] = mapped_column(Text, default="")
    # Lower-case labels for grouping and filtering (domain/fields.py normalizes them).
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    # Values of the company's custom fields for this record type, by field key.
    custom: Mapped[dict] = mapped_column(JSONB, default=dict)

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    converted_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )

    organization = synonym("company_name")
    owner_id = synonym("owner_user_id")
    converted_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", use_alter=True), nullable=True
    )
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_user_id])  # noqa: F821

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """A person at a Customer — distinct from the Customer (the account/company)
    itself. Created directly, or automatically when a Lead converts."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))

    name: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")

    customer: Mapped["Customer"] = relationship()  # noqa: F821


class Opportunity(Base):
    """A quantified, in-progress sales pursuit against a Customer — the
    pipeline. Distinct from a Quotation: an Opportunity is the deal being
    pursued: a Quotation is one priced document inside it."""

    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))

    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(20), default="New")
    value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    probability_pct: Mapped[int] = mapped_column(default=50)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Lower-case labels for grouping and filtering (domain/fields.py normalizes them).
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    # Values of the company's custom fields for this record type, by field key.
    custom: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Required when stage is Lost, cleared when the deal is reopened.
    lost_reason: Mapped[str] = mapped_column(String(200), default="")
    # When the stage last changed — Won/Lost date, and part of "last touched" for idle deals.
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    title = synonym("name")
    expected_value = synonym("value")
    expected_close = synonym("expected_close_date")
    owner_id = synonym("owner_user_id")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_user_id])  # noqa: F821

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped["Customer"] = relationship()  # noqa: F821


class Activity(Base):
    """A call, meeting, task or note logged against exactly one of Lead /
    Customer / Opportunity — the relationship timeline."""

    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))

    type: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)

    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True
    )

    kind = synonym("type")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])  # noqa: F821

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrmEvent(Base):
    """One entry in a record's history: who did what, when, and from where.

    Written by the domain services alongside the change itself (same
    transaction), for human edits as well as Ask ERP and imports — unlike
    AuditEvent, which records only AI-initiated tool calls.
    """

    __tablename__ = "crm_events"
    __table_args__ = (Index("ix_crm_events_record", "record_type", "record_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    record_type: Mapped[str] = mapped_column(String(20))  # lead | opportunity | customer
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="app")  # app | ask_erp | import
    action: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(400))
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)  # field -> [old, new]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrmSettings(Base):
    """Per-company CRM settings. A missing row means the defaults."""

    __tablename__ = "crm_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    # stage -> days an open deal may sit untouched before it's flagged; 0 = never
    stale_after_days: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"enabled": bool, "user_ids": [ordered ids], "last_user_id": id | None}
    lead_rotation: Mapped[dict] = mapped_column(JSONB, default=dict)


class SalesTarget(Base):
    """What one person should win in one month (value of deals closed Won)."""

    __tablename__ = "sales_targets"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "month", name="uq_sales_targets_user_month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    month: Mapped[date] = mapped_column(Date)  # first day of the month
    amount: Mapped[float] = mapped_column(Numeric(14, 2))


class CustomField(Base):
    """A company-defined field on leads, deals or customers. Archiving
    (active=False) hides it from forms but keeps the values already saved."""

    __tablename__ = "custom_fields"
    __table_args__ = (UniqueConstraint("company_id", "record_type", "key", name="uq_custom_fields_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    record_type: Mapped[str] = mapped_column(String(20))  # lead | opportunity | customer
    key: Mapped[str] = mapped_column(String(40))  # stable; values are stored under it
    label: Mapped[str] = mapped_column(String(80))
    field_type: Mapped[str] = mapped_column(String(20))  # text | number | date | select | checkbox
    options: Mapped[list[str]] = mapped_column(JSONB, default=list)  # select only
    position: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
