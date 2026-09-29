"""CRM domain logic: leads, opportunities, follow-up activities and ownership.

Same rule as sales_service: no HTTP or AI concerns here, just the business
rules a form or a tool calls. Every lookup is scoped by tenant *and* company
from the RequestContext — an id from the client is never trusted on its own.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.sales_service import DomainValidationError
from app.models.crm import (
    ACTIVITY_KINDS,
    LEAD_STATUSES,
    OPEN_STAGES,
    OPPORTUNITY_STAGES,
    Contact,
    Activity,
    Lead,
    Opportunity,
)
from app.models.identity import User
from app.models.sales import Customer, Quotation

# A quotation raised against an opportunity still in an early stage moves it
# to Proposal — the quote *is* the proposal. Later stages are left alone.
_STAGES_BEFORE_PROPOSAL = ("New", "Qualified")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_overdue(activity: Activity, at: datetime | None = None) -> bool:
    return not activity.done and activity.due_at is not None and activity.due_at < (at or now_utc())


def _scoped(stmt, model, context: RequestContext):
    return stmt.where(model.tenant_id == context.tenant_id, model.company_id == context.company_id)


def get_lead(db: Session, context: RequestContext, lead_id: UUID) -> Lead:
    lead = db.execute(_scoped(select(Lead), Lead, context).where(Lead.id == lead_id)).scalar_one_or_none()
    if lead is None:
        raise DomainValidationError("Lead not found.")
    return lead


def get_opportunity(db: Session, context: RequestContext, opportunity_id: UUID) -> Opportunity:
    opp = db.execute(
        _scoped(select(Opportunity), Opportunity, context).where(Opportunity.id == opportunity_id)
    ).scalar_one_or_none()
    if opp is None:
        raise DomainValidationError("Opportunity not found.")
    return opp


def get_activity(db: Session, context: RequestContext, activity_id: UUID) -> Activity:
    activity = db.execute(
        _scoped(select(Activity), Activity, context).where(Activity.id == activity_id)
    ).scalar_one_or_none()
    if activity is None:
        raise DomainValidationError("Activity not found.")
    return activity


# --- Assignment -------------------------------------------------------------


def list_assignees(db: Session, context: RequestContext) -> list[User]:
    """Users a lead/opportunity can be assigned to: same tenant and company."""

    stmt = (
        select(User)
        .where(User.tenant_id == context.tenant_id, User.company_id == context.company_id)
        .order_by(User.display_name)
    )
    return list(db.execute(stmt).scalars().all())


def resolve_owner(db: Session, context: RequestContext, owner_id: UUID | None) -> UUID | None:
    """Validates an owner picked in the UI. None means 'unassigned'."""

    if owner_id is None:
        return None
    user = db.get(User, owner_id)
    if user is None or user.tenant_id != context.tenant_id or user.company_id != context.company_id:
        raise DomainValidationError("That user can't own records in this company.")
    return user.id


# --- Leads ------------------------------------------------------------------


def create_lead(
    db: Session,
    context: RequestContext,
    *,
    name: str,
    organization: str,
    phone: str,
    email: str,
    source: str,
    owner_id: UUID | None,
) -> Lead:
    if not name.strip():
        raise DomainValidationError("A lead needs a contact name.")
    lead = Lead(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        name=name.strip(),
        organization=organization.strip(),
        phone=phone.strip(),
        email=email.strip(),
        source=source.strip() or "Other",
        status="New",
        owner_id=resolve_owner(db, context, owner_id),
    )
    db.add(lead)
    db.flush()
    return lead


def set_lead_status(lead: Lead, status: str) -> None:
    if status not in LEAD_STATUSES or status == "Converted":
        raise DomainValidationError(f"Can't set a lead to '{status}' directly.")
    if lead.status == "Converted":
        raise DomainValidationError("This lead is already converted — work the opportunity instead.")
    lead.status = status


def _find_or_create_customer(db: Session, context: RequestContext, name: str) -> Customer:
    existing = db.execute(
        _scoped(select(Customer), Customer, context).where(func.lower(Customer.name) == name.strip().lower())
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    customer = Customer(tenant_id=context.tenant_id, company_id=context.company_id, name=name.strip(), credit_limit=0)
    db.add(customer)
    db.flush()
    return customer


def convert_lead(
    db: Session,
    context: RequestContext,
    lead: Lead,
    *,
    title: str,
    expected_value: float,
    expected_close: date | None,
) -> Opportunity:
    """Lead -> Customer (found by name, or created) + Opportunity. The
    opportunity inherits the lead's owner and any open follow-ups."""

    if lead.status == "Converted":
        raise DomainValidationError("This lead is already converted.")
    if lead.status == "Lost":
        raise DomainValidationError("Re-qualify this lead before converting it.")

    customer = _find_or_create_customer(db, context, lead.organization or lead.name)
    opp = Opportunity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        title=title.strip() or f"{customer.name} — new deal",
        customer_id=customer.id,
        lead_id=lead.id,
        stage="Qualified",
        expected_value=max(expected_value, 0),
        expected_close=expected_close,
        owner_id=lead.owner_id,
    )
    db.add(opp)
    db.flush()

    lead.status = "Converted"
    lead.converted_opportunity_id = opp.id
    lead.converted_customer_id = customer.id
    db.add(Contact(
        tenant_id=context.tenant_id, company_id=context.company_id,
        customer_id=customer.id, name=lead.name, email=lead.email, phone=lead.phone,
    ))
    open_followups = db.execute(
        select(Activity).where(Activity.lead_id == lead.id, Activity.done.is_(False))
    ).scalars()
    for activity in open_followups:
        activity.opportunity_id = opp.id
        activity.lead_id = None
    return opp


# --- Opportunities ------------------------------------------------------------


def create_opportunity(
    db: Session,
    context: RequestContext,
    *,
    title: str,
    customer_name: str,
    expected_value: float,
    expected_close: date | None,
    owner_id: UUID | None,
) -> Opportunity:
    if not title.strip():
        raise DomainValidationError("An opportunity needs a title.")
    if not customer_name.strip():
        raise DomainValidationError("An opportunity needs a customer.")
    customer = _find_or_create_customer(db, context, customer_name)
    opp = Opportunity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        title=title.strip(),
        customer_id=customer.id,
        stage="New",
        expected_value=max(expected_value, 0),
        expected_close=expected_close,
        owner_id=resolve_owner(db, context, owner_id),
    )
    db.add(opp)
    db.flush()
    return opp


def set_stage(opp: Opportunity, stage: str) -> None:
    if stage not in OPPORTUNITY_STAGES:
        raise DomainValidationError(f"Unknown stage '{stage}'.")
    opp.stage = stage


def advance_on_quotation(opp: Opportunity) -> None:
    if opp.stage in _STAGES_BEFORE_PROPOSAL:
        opp.stage = "Proposal"


def assert_quotable(opp: Opportunity) -> None:
    if opp.stage not in OPEN_STAGES:
        raise DomainValidationError(f"This opportunity is {opp.stage} — reopen it before quoting.")


def quotations_for(db: Session, opportunity_ids: list[UUID]) -> dict[UUID, list[Quotation]]:
    if not opportunity_ids:
        return {}
    rows = db.execute(
        select(Quotation).where(Quotation.opportunity_id.in_(opportunity_ids)).order_by(Quotation.created_at.desc())
    ).scalars()
    grouped: dict[UUID, list[Quotation]] = {}
    for q in rows:
        grouped.setdefault(q.opportunity_id, []).append(q)
    return grouped


# --- Activities -------------------------------------------------------------


def create_activity(
    db: Session,
    context: RequestContext,
    *,
    kind: str,
    subject: str,
    due_at: datetime,
    lead_id: UUID | None,
    opportunity_id: UUID | None,
    owner_id: UUID | None,
) -> Activity:
    if kind not in ACTIVITY_KINDS:
        raise DomainValidationError(f"Unknown activity type '{kind}'.")
    if not subject.strip():
        raise DomainValidationError("An activity needs a subject.")
    if (lead_id is None) == (opportunity_id is None):
        raise DomainValidationError("An activity belongs to exactly one lead or one opportunity.")

    # Default the owner to whoever owns the parent record, else the creator.
    default_owner: UUID | None = context.user.id
    if lead_id is not None:
        default_owner = get_lead(db, context, lead_id).owner_id or default_owner
    if opportunity_id is not None:
        default_owner = get_opportunity(db, context, opportunity_id).owner_id or default_owner

    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)

    activity = Activity(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        kind=kind,
        subject=subject.strip(),
        due_at=due_at,
        due_date=due_at.date(),
        created_by=context.user.id,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        owner_id=resolve_owner(db, context, owner_id) if owner_id else default_owner,
    )
    db.add(activity)
    db.flush()
    return activity


def list_activities(db: Session, context: RequestContext, *, open_only: bool) -> list[Activity]:
    stmt = _scoped(select(Activity), Activity, context).order_by(Activity.due_at)
    if open_only:
        stmt = stmt.where(Activity.done.is_(False))
    return list(db.execute(stmt).scalars().all())
