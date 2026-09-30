"""Bulk actions on leads, deals and customers.

Each record goes through the same service call a single edit would —
validation, visibility, history — so bulk can't do anything one-at-a-time
couldn't. Records a rule refuses are skipped and reported, not fatal.
Targets are explicit ids, or "everything matching these filters" (capped).
"""

from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import customer_service, lead_service, notifications, opportunity_service
from app.domain.errors import ConflictError, NotFoundError
from app.schemas.crm import LeadUpdate, OpportunityUpdate
from app.schemas.customers import CustomerUpdate

MAX_IDS = 500
MAX_MATCHING = 2000

# action -> permission, per record type
ACTIONS = {
    "lead": {"assign": "crm.lead.assign", "add_tag": "crm.lead.write", "remove_tag": "crm.lead.write",
             "status": "crm.lead.write", "delete": "crm.lead.delete"},
    "opportunity": {"assign": "crm.opportunity.assign", "add_tag": "crm.opportunity.write",
                    "remove_tag": "crm.opportunity.write", "stage": "crm.opportunity.write",
                    "delete": "crm.opportunity.delete"},
    "customer": {"add_tag": "sales.customer.write", "remove_tag": "sales.customer.write",
                 "activate": "sales.customer.write", "deactivate": "sales.customer.write",
                 "delete": "sales.customer.delete"},
}


def _targets(db: Session, context: RequestContext, record_type: str, ids: list[UUID] | None,
             filters: dict[str, Any] | None) -> list:
    if ids is not None:
        if len(ids) > MAX_IDS:
            raise ConflictError(f"At most {MAX_IDS} records at once — or use “all matching”.")
        get = {"lead": lead_service.get_lead, "opportunity": opportunity_service.get_opportunity,
               "customer": customer_service.get_customer}[record_type]
        found = []
        for i in dict.fromkeys(ids):
            try:
                found.append(get(db, context, i))
            except NotFoundError:
                pass  # not theirs to see: silently not a target
        return found
    f = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
    if record_type == "lead":
        rows, total = lead_service.list_leads(db, context, q=f.get("q", ""), status=f.get("status", ""),
                                              owner=f.get("owner", ""), tag=f.get("tag", ""), limit=None)
    elif record_type == "opportunity":
        rows, total = opportunity_service.list_opportunities(
            db, context, q=f.get("q", ""), stage=f.get("stage", ""), owner=f.get("owner", ""), tag=f.get("tag", ""),
            stale_only=bool(f.get("stale")), limit=None,
        )
    else:
        active = f.get("active")
        rows, total = customer_service.list_customers(db, context, q=f.get("q", ""), tag=f.get("tag", ""),
                                                      active=None if active is None else bool(active), limit=None)
    if total > MAX_MATCHING:
        raise ConflictError(f"{total:,} records match — narrow the filters to at most {MAX_MATCHING:,}.")
    return rows


def _label(record) -> str:
    return getattr(record, "company_name", "") or record.name


def run(db: Session, context: RequestContext, record_type: str, action: str, *, ids: list[UUID] | None = None,
        filters: dict[str, Any] | None = None, value: Any = None, lost_reason: str = "") -> dict:
    if action not in ACTIONS.get(record_type, {}):
        raise ConflictError(f"Unknown action “{action}” for {record_type}s.")
    permission = ACTIONS[record_type][action]
    if not context.has_permission(permission):
        raise PermissionError(f"Missing permission: {permission}")
    if (ids is None) == (filters is None):
        raise ConflictError("Send either ids or filters.")
    if action in ("add_tag", "remove_tag"):
        value = str(value or "").strip().lower()
        if not value:
            raise ConflictError("Which tag?")

    from app.domain import record_admin  # imported here: record_admin imports the services too

    step: Callable[[Any], None]
    if record_type == "lead":
        if action == "assign":
            owner = UUID(str(value)) if value else None
            step = lambda r: lead_service.assign_lead(db, context, r.id, owner, notify=False)  # noqa: E731
        elif action == "status":
            step = lambda r: lead_service.update_lead(db, context, r.id, LeadUpdate(status=value))  # noqa: E731
        elif action == "delete":
            step = lambda r: record_admin.delete_lead(db, context, r.id)  # noqa: E731
        else:
            step = lambda r: lead_service.update_lead(db, context, r.id, LeadUpdate(tags=_retag(r.tags, action, value)))  # noqa: E731
    elif record_type == "opportunity":
        if action == "assign":
            owner = UUID(str(value)) if value else None
            step = lambda r: opportunity_service.assign_opportunity(db, context, r.id, owner, notify=False)  # noqa: E731
        elif action == "stage":
            body = OpportunityUpdate(stage=value, **({"lost_reason": lost_reason} if value == "Lost" else {}))
            step = lambda r: opportunity_service.update_opportunity(db, context, r.id, body)  # noqa: E731
        elif action == "delete":
            step = lambda r: record_admin.delete_opportunity(db, context, r.id)  # noqa: E731
        else:
            step = lambda r: opportunity_service.update_opportunity(  # noqa: E731
                db, context, r.id, OpportunityUpdate(tags=_retag(r.tags, action, value)))
    else:
        if action in ("activate", "deactivate"):
            step = lambda r: customer_service.update_customer(  # noqa: E731
                db, context, r.id, CustomerUpdate(active=action == "activate"))
        elif action == "delete":
            step = lambda r: record_admin.delete_customer(db, context, r.id)  # noqa: E731
        else:
            step = lambda r: customer_service.update_customer(  # noqa: E731
                db, context, r.id, CustomerUpdate(tags=_retag(r.tags, action, value)))

    targets = _targets(db, context, record_type, ids, filters)
    done, reassigned, skipped = 0, 0, []
    for record in targets:
        label = _label(record)
        owner_before = getattr(record, "owner_user_id", None)
        try:
            step(record)
            done += 1
            if action == "assign" and str(owner_before or "") != str(value or ""):
                reassigned += 1
        except (ConflictError, NotFoundError, ValueError) as exc:
            db.rollback()
            skipped.append({"id": str(record.id), "label": label, "reason": str(exc)})

    if action == "assign" and value and reassigned:
        # One alert for the lot, instead of one per record.
        noun = "lead" if record_type == "lead" else "deal"
        link = "/leads?owner=mine" if record_type == "lead" else "/opportunities"
        notifications.notify(db, context, UUID(str(value)), f"{noun}_assigned",
                             f"{reassigned} {noun}{'s' if reassigned != 1 else ''} assigned to you", "", link)
        db.commit()
    return {"done": done, "skipped": skipped, "matched": len(targets)}


def _retag(tags: list[str], action: str, tag: str) -> list[str]:
    tags = list(tags or [])
    if action == "add_tag":
        return tags if tag in tags else [*tags, tag]
    return [t for t in tags if t != tag]
