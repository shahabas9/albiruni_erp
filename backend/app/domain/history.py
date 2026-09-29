"""Record history: who changed what on a lead, deal or customer, and when.

Services call record() in the same transaction as the change they make, so a
change and its history entry are committed (or rolled back) together.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.models.crm import CrmEvent
from app.models.identity import User

# Human labels for the fields a history entry may mention.
LABELS = {
    "name": "Name",
    "company_name": "Company",
    "email": "Email",
    "phone": "Phone",
    "source": "Source",
    "status": "Status",
    "notes": "Notes",
    "stage": "Stage",
    "value": "Value",
    "probability_pct": "Probability",
    "expected_close_date": "Expected close",
    "lost_reason": "Lost reason",
}


def _plain(value: Any) -> Any:
    """JSON-safe form of a column value."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _show(field: str, value: Any) -> str:
    if value in (None, ""):
        return "—"
    if field == "value":
        return f"₹{float(value):,.0f}"
    if field == "probability_pct":
        return f"{value}%"
    if field == "notes":
        return "updated"
    return str(_plain(value))


def diff(record: Any, data: dict[str, Any]) -> dict[str, list[Any]]:
    """Fields in `data` whose value differs from `record`'s, as {field: [old, new]}."""

    changes = {}
    for field, new in data.items():
        old = getattr(record, field, None)
        if _plain(old) != _plain(new) and not (old in (None, "") and new in (None, "")):
            changes[field] = [_plain(old), _plain(new)]
    return changes


def describe(changes: dict[str, list[Any]]) -> str:
    parts = []
    for field, (old, new) in changes.items():
        label = LABELS.get(field, field.replace("_", " ").capitalize())
        if field == "notes":
            parts.append("Notes updated")
        else:
            parts.append(f"{label}: {_show(field, old)} → {_show(field, new)}")
    return "; ".join(parts)


def owner_change(db: Session, old: UUID | None, new: UUID | None) -> tuple[str, dict[str, list[Any]]]:
    ids = {i for i in (old, new) if i}
    names = {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}
    before, after = names.get(old, "Unassigned"), names.get(new, "Unassigned")
    return f"Owner: {before} → {after}", {"owner": [before, after]}


def record(
    db: Session,
    context: RequestContext,
    record_type: str,
    record_id: UUID,
    action: str,
    summary: str,
    changes: dict[str, list[Any]] | None = None,
) -> None:
    db.add(CrmEvent(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        record_type=record_type,
        record_id=record_id,
        actor_user_id=context.user.id,
        source=context.channel,
        action=action,
        summary=summary[:400],
        changes=changes or {},
        # Wall-clock, not the DB's now() (fixed per transaction), so several
        # entries from one change keep their order.
        created_at=datetime.now(timezone.utc),
    ))


def timeline(db: Session, context: RequestContext, refs: list[tuple[str, UUID]]) -> list[dict[str, Any]]:
    """History for one or more records (e.g. a deal plus the lead it came from), newest first."""

    if not refs:
        return []
    events = []
    for record_type, record_id in refs:
        events += db.execute(
            select(CrmEvent).where(
                CrmEvent.tenant_id == context.tenant_id,
                CrmEvent.company_id == context.company_id,
                CrmEvent.record_type == record_type,
                CrmEvent.record_id == record_id,
            )
        ).scalars().all()
    actor_ids = {e.actor_user_id for e in events if e.actor_user_id}
    names = (
        {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(actor_ids))).scalars()}
        if actor_ids else {}
    )
    events.sort(key=lambda e: e.created_at, reverse=True)
    return [
        {
            "id": str(e.id),
            "at": e.created_at,
            "record_type": e.record_type,
            "action": e.action,
            "summary": e.summary,
            "changes": e.changes,
            "source": e.source,
            "actor_name": names.get(e.actor_user_id),
        }
        for e in events
    ]
