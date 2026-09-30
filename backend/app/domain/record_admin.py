"""Deleting and merging CRM records, and finding duplicates to merge.

Deletes refuse whenever the record is history something else depends on
(a converted lead, a deal with quotations, a customer with deals, quotations
or converted leads) — the message says what to do instead. Every delete and
merge leaves a history entry. Files are unlinked only after the commit.
"""

from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import attachment_service, crm_service, fields, history
from app.domain.contact_service import get_contact
from app.domain.customer_service import get_customer
from app.domain.duplicates import phone_key
from app.domain.errors import ConflictError
from app.domain.lead_service import get_lead
from app.domain.opportunity_service import get_opportunity
from app.models.crm import Activity, Contact, CrmEvent, Lead, Opportunity
from app.models.sales import Customer, Quotation


def _unlink(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _label(lead: Lead) -> str:
    return f"{lead.company_name} ({lead.name})" if lead.company_name else lead.name


def _move_history(db: Session, context: RequestContext, record_type: str, from_id: UUID, to_id: UUID) -> None:
    db.execute(update(CrmEvent).where(
        CrmEvent.tenant_id == context.tenant_id, CrmEvent.record_type == record_type, CrmEvent.record_id == from_id,
    ).values(record_id=to_id))


# --- Delete ---------------------------------------------------------------------


def delete_lead(db: Session, context: RequestContext, lead_id: UUID) -> None:
    lead = get_lead(db, context, lead_id)
    if lead.status == "Converted":
        raise ConflictError("A converted lead is the history behind its customer and deal, so it can't be deleted.")
    db.execute(delete(Activity).where(Activity.lead_id == lead.id))
    paths = attachment_service.remove_for_record(db, context, "lead", lead.id)
    history.record(db, context, "lead", lead.id, "deleted", f"Lead deleted: {_label(lead)}")
    db.delete(lead)
    db.commit()
    _unlink(paths)


def delete_opportunity(db: Session, context: RequestContext, opportunity_id: UUID) -> None:
    opp = get_opportunity(db, context, opportunity_id)
    quotes = db.execute(select(func.count()).select_from(Quotation).where(Quotation.opportunity_id == opp.id)).scalar_one()
    if quotes:
        raise ConflictError(f"This deal has {quotes} quotation{'s' if quotes != 1 else ''} — mark it Lost instead of deleting it.")
    db.execute(delete(Activity).where(Activity.opportunity_id == opp.id))
    db.execute(update(Lead).where(Lead.converted_opportunity_id == opp.id).values(converted_opportunity_id=None))
    paths = attachment_service.remove_for_record(db, context, "opportunity", opp.id)
    history.record(db, context, "opportunity", opp.id, "deleted", f"Deal deleted: {opp.name}")
    db.delete(opp)
    db.commit()
    _unlink(paths)


def delete_contact(db: Session, context: RequestContext, contact_id: UUID) -> None:
    contact = get_contact(db, context, contact_id)
    history.record(db, context, "customer", contact.customer_id, "contact_deleted", f"Contact deleted: {contact.name}")
    db.delete(contact)
    db.commit()


def _customer_links(db: Session, customer_id: UUID) -> dict[str, int]:
    count = lambda model, column: db.execute(  # noqa: E731
        select(func.count()).select_from(model).where(column == customer_id)
    ).scalar_one()
    return {
        "deal": count(Opportunity, Opportunity.customer_id),
        "quotation": count(Quotation, Quotation.customer_id),
        "converted lead": count(Lead, Lead.converted_customer_id),
    }


def delete_customer(db: Session, context: RequestContext, customer_id: UUID) -> None:
    customer = get_customer(db, context, customer_id)
    links = {k: n for k, n in _customer_links(db, customer.id).items() if n}
    if links:
        what = ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in links.items())
        raise ConflictError(f"{customer.name} has {what} — merge it into another customer instead of deleting it.")
    db.execute(delete(Contact).where(Contact.customer_id == customer.id))
    db.execute(delete(Activity).where(Activity.customer_id == customer.id))
    paths = attachment_service.remove_for_record(db, context, "customer", customer.id)
    history.record(db, context, "customer", customer.id, "deleted", f"Customer deleted: {customer.name}")
    db.delete(customer)
    db.commit()
    _unlink(paths)


# --- Merge ----------------------------------------------------------------------


def _merge_values(keep, other, names: list[str]) -> list[str]:
    """Fills keep's blank fields from other; returns the ones filled."""

    filled = []
    for name in names:
        if not getattr(keep, name) and getattr(other, name):
            setattr(keep, name, getattr(other, name))
            filled.append(name)
    return filled


def _merged_tags(a: list[str], b: list[str]) -> list[str]:
    return fields.normalize_tags(list(dict.fromkeys([*(a or []), *(b or [])]))[: fields.MAX_TAGS])


def merge_leads(db: Session, context: RequestContext, keep_id: UUID, remove_id: UUID) -> Lead:
    """`remove` is folded into `keep`: blank details filled in, notes, tags and
    custom values combined, follow-ups, files and history moved; then removed."""

    if keep_id == remove_id:
        raise ConflictError("Pick two different leads to merge.")
    keep, other = get_lead(db, context, keep_id), get_lead(db, context, remove_id)
    if "Converted" in (keep.status, other.status):
        raise ConflictError("Converted leads can't be merged — they're the history behind a customer.")
    _merge_values(keep, other, ["company_name", "email", "phone", "source"])
    if other.notes and other.notes not in (keep.notes or ""):
        keep.notes = f"{keep.notes}\n\n{other.notes}".strip() if keep.notes else other.notes
    keep.tags = _merged_tags(keep.tags, other.tags)
    keep.custom = {**(other.custom or {}), **(keep.custom or {})}
    if keep.owner_user_id is None:
        keep.owner_user_id = other.owner_user_id

    db.execute(update(Activity).where(Activity.lead_id == other.id).values(lead_id=keep.id))
    attachment_service.move_to_record(db, context, "lead", other.id, keep.id)
    _move_history(db, context, "lead", other.id, keep.id)
    history.record(db, context, "lead", keep.id, "merged", f"Merged in lead {_label(other)}")
    db.flush()
    db.delete(other)
    db.commit()
    db.refresh(keep)
    return keep


def merge_customers(db: Session, context: RequestContext, keep_id: UUID, remove_id: UUID) -> Customer:
    """Everything that pointed at `remove` — contacts, deals, quotations,
    follow-ups, converted leads, files, history — moves to `keep`."""

    if keep_id == remove_id:
        raise ConflictError("Pick two different customers to merge.")
    keep, other = get_customer(db, context, keep_id), get_customer(db, context, remove_id)
    _merge_values(keep, other, ["gstin"])
    keep.tags = _merged_tags(keep.tags, other.tags)
    keep.custom = {**(other.custom or {}), **(keep.custom or {})}
    keep.active = keep.active or other.active
    for model, column in ((Contact, Contact.customer_id), (Opportunity, Opportunity.customer_id),
                          (Quotation, Quotation.customer_id), (Activity, Activity.customer_id)):
        db.execute(update(model).where(column == other.id).values({column.key: keep.id}))
    db.execute(update(Lead).where(Lead.converted_customer_id == other.id).values(converted_customer_id=keep.id))
    attachment_service.move_to_record(db, context, "customer", other.id, keep.id)
    _move_history(db, context, "customer", other.id, keep.id)
    history.record(db, context, "customer", keep.id, "merged", f"Merged in customer {other.name}")
    db.flush()
    db.delete(other)
    db.commit()
    db.refresh(keep)
    return keep


# --- Finding duplicates ---------------------------------------------------------------


def lead_duplicate_groups(db: Session, context: RequestContext, limit: int = 50) -> list[dict]:
    """Open leads (visible to the caller) sharing a phone number or an email."""

    stmt = select(Lead).where(
        Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id, Lead.status != "Converted",
    )
    leads = list(db.execute(crm_service.only_visible(stmt, Lead.owner_user_id, context)).scalars())
    by_key: dict[tuple[str, str], list[Lead]] = {}
    for lead in leads:
        if phone_key(lead.phone):
            by_key.setdefault(("phone", phone_key(lead.phone)), []).append(lead)
        if lead.email.strip():
            by_key.setdefault(("email", lead.email.strip().lower()), []).append(lead)
    groups, seen = [], set()
    for (kind, value), members in by_key.items():
        ids = frozenset(m.id for m in members)
        if len(members) < 2 or ids in seen:
            continue
        seen.add(ids)
        groups.append({"reason": f"Same {kind}: {value}", "leads": sorted(members, key=lambda m: m.created_at)})
    return groups[:limit]


def customer_duplicate_groups(db: Session, context: RequestContext, limit: int = 50) -> list[dict]:
    """Customers sharing a name (ignoring case and spacing) or a GSTIN."""

    customers = db.execute(select(Customer).where(
        Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id,
    )).scalars().all()
    by_key: dict[tuple[str, str], list[Customer]] = {}
    for c in customers:
        by_key.setdefault(("name", " ".join(c.name.lower().split())), []).append(c)
        if c.gstin:
            by_key.setdefault(("GSTIN", c.gstin), []).append(c)
    groups, seen = [], set()
    for (kind, value), members in by_key.items():
        ids = frozenset(m.id for m in members)
        if len(members) < 2 or ids in seen:
            continue
        seen.add(ids)
        groups.append({"reason": f"Same {kind}: {value}", "customers": sorted(members, key=lambda m: m.name)})
    return groups[:limit]
