"""Tags and company-defined custom fields on leads, deals and customers.

Tags are lower-cased, trimmed and de-duplicated, so "VIP" and "vip " are one
tag. Custom field values live in each record's `custom` JSON under the
field's stable key; they're validated against the field's type here, the only
place that writes them.
"""

import re
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import CustomField, Lead, Opportunity
from app.models.sales import Customer

RECORD_TYPES = ("lead", "opportunity", "customer")
FIELD_TYPES = ("text", "number", "date", "select", "checkbox")
MODELS = {"lead": Lead, "opportunity": Opportunity, "customer": Customer}

MAX_TAGS = 20
MAX_TAG_LENGTH = 40
MAX_FIELDS = 30
MAX_OPTIONS = 50
MAX_TEXT = 500


# --- Tags ---------------------------------------------------------------------


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        tag = re.sub(r"\s+", " ", str(raw)).strip().lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ConflictError(f"Tags can be at most {MAX_TAG_LENGTH} characters (“{tag[:20]}…”).")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ConflictError(f"A record can have at most {MAX_TAGS} tags.")
    return out


def tag_counts(db: Session, context: RequestContext, record_type: str) -> list[dict]:
    """Every tag in use on this record type, most used first."""

    model = _model(record_type)
    tag = func.unnest(model.tags).label("tag")
    inner = select(tag).where(model.tenant_id == context.tenant_id, model.company_id == context.company_id).subquery()
    rows = db.execute(
        select(inner.c.tag, func.count()).group_by(inner.c.tag).order_by(func.count().desc(), inner.c.tag).limit(200)
    ).all()
    return [{"tag": t, "count": n} for t, n in rows]


# --- Field definitions ----------------------------------------------------------


def _model(record_type: str):
    if record_type not in MODELS:
        raise ConflictError(f"Record type must be one of: {', '.join(RECORD_TYPES)}.")
    return MODELS[record_type]


def list_fields(db: Session, context: RequestContext, record_type: str | None = None, *,
                include_archived: bool = False) -> list[CustomField]:
    stmt = select(CustomField).where(
        CustomField.tenant_id == context.tenant_id, CustomField.company_id == context.company_id
    )
    if record_type:
        _model(record_type)
        stmt = stmt.where(CustomField.record_type == record_type)
    if not include_archived:
        stmt = stmt.where(CustomField.active.is_(True))
    return list(db.execute(stmt.order_by(CustomField.record_type, CustomField.position, CustomField.created_at)).scalars())


def get_field(db: Session, context: RequestContext, field_id: UUID) -> CustomField:
    field = db.get(CustomField, field_id)
    if field is None or field.tenant_id != context.tenant_id or field.company_id != context.company_id:
        raise NotFoundError(f"No custom field with id {field_id}")
    return field


def _clean_options(options: list[str]) -> list[str]:
    out: list[str] = []
    for raw in options:
        option = str(raw).strip()
        if option and option not in out:
            if len(option) > 80:
                raise ConflictError("Each choice can be at most 80 characters.")
            out.append(option)
    if not out:
        raise ConflictError("A dropdown needs at least one choice.")
    if len(out) > MAX_OPTIONS:
        raise ConflictError(f"A dropdown can have at most {MAX_OPTIONS} choices.")
    return out


def create_field(db: Session, context: RequestContext, *, record_type: str, label: str, field_type: str,
                 options: list[str]) -> CustomField:
    _model(record_type)
    label = label.strip()
    if not label:
        raise ConflictError("Give the field a name.")
    if field_type not in FIELD_TYPES:
        raise ConflictError(f"Field type must be one of: {', '.join(FIELD_TYPES)}.")
    existing = list_fields(db, context, record_type, include_archived=True)
    if len(existing) >= MAX_FIELDS:
        raise ConflictError(f"At most {MAX_FIELDS} custom fields per record type.")
    if any(f.label.lower() == label.lower() for f in existing):
        raise ConflictError(f"There's already a field called “{label}”.")
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:32] or "field"
    key, n = base, 2
    taken = {f.key for f in existing}
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    field = CustomField(
        tenant_id=context.tenant_id, company_id=context.company_id, record_type=record_type, key=key,
        label=label, field_type=field_type, options=_clean_options(options) if field_type == "select" else [],
        position=max((f.position for f in existing), default=-1) + 1, active=True,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


def update_field(db: Session, context: RequestContext, field_id: UUID, data: dict[str, Any]) -> CustomField:
    """Label, choices, position and archiving can change; type and key can't
    (saved values depend on them)."""

    field = get_field(db, context, field_id)
    if "label" in data and data["label"] is not None:
        label = data["label"].strip()
        if not label:
            raise ConflictError("Give the field a name.")
        others = list_fields(db, context, field.record_type, include_archived=True)
        if any(f.id != field.id and f.label.lower() == label.lower() for f in others):
            raise ConflictError(f"There's already a field called “{label}”.")
        field.label = label
    if data.get("options") is not None:
        if field.field_type != "select":
            raise ConflictError("Only dropdown fields have choices.")
        field.options = _clean_options(data["options"])
    if data.get("position") is not None:
        field.position = int(data["position"])
    if data.get("active") is not None:
        field.active = bool(data["active"])
    db.commit()
    db.refresh(field)
    return field


# --- Values -------------------------------------------------------------------


def _coerce(field: CustomField, value: Any) -> Any:
    label = field.label
    if field.field_type == "text":
        text = str(value).strip()
        if len(text) > MAX_TEXT:
            raise ConflictError(f"{label}: at most {MAX_TEXT} characters.")
        return text
    if field.field_type == "number":
        if isinstance(value, bool):
            raise ConflictError(f"{label} must be a number.")
        try:
            number = float(str(value).replace(",", "").strip())
        except ValueError as exc:
            raise ConflictError(f"{label} must be a number.") from exc
        if number != number or abs(number) > 1e15:  # NaN or absurd
            raise ConflictError(f"{label} must be a number.")
        return int(number) if number.is_integer() else number
    if field.field_type == "date":
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError as exc:
            raise ConflictError(f"{label} must be a date (YYYY-MM-DD).") from exc
    if field.field_type == "select":
        if str(value) not in field.options:
            raise ConflictError(f"{label} must be one of: {', '.join(field.options)}.")
        return str(value)
    if field.field_type == "checkbox":
        if not isinstance(value, bool):
            raise ConflictError(f"{label} must be yes or no.")
        return value
    raise ConflictError(f"{label} has an unknown type.")


def clean_custom(db: Session, context: RequestContext, record_type: str, incoming: dict[str, Any],
                 current: dict[str, Any] | None = None) -> dict[str, Any]:
    """`current` with `incoming` merged in: each value checked against its
    field's type; None, "" or false-for-no clears a field. Values of archived
    fields already on the record are kept untouched."""

    fields = {f.key: f for f in list_fields(db, context, record_type)}
    merged = dict(current or {})
    for key, value in incoming.items():
        field = fields.get(key)
        if field is None:
            raise ConflictError(f"“{key}” isn't a field on {record_type}s here.")
        if value is None or value == "" or (field.field_type == "checkbox" and value is False):
            merged.pop(key, None)
        else:
            merged[key] = _coerce(field, value)
    return merged


def custom_changes(db: Session, context: RequestContext, record_type: str, old: dict[str, Any],
                   new: dict[str, Any]) -> dict[str, list[Any]]:
    """History entries for changed custom values, keyed "custom:<label>"."""

    labels = {f.key: f.label for f in list_fields(db, context, record_type, include_archived=True)}
    changes = {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changes[f"custom:{labels.get(key, key)}"] = [old.get(key), new.get(key)]
    return changes


def apply_tags_and_custom(db: Session, context: RequestContext, record_type: str, record, data: dict) -> dict:
    """Pops tags/custom from an update's data, applies them to `record` and
    returns their history changes; the rest of `data` is plain fields."""

    changes = {}
    tags = data.pop("tags", None)
    if tags is not None:
        tags = normalize_tags(tags)
        if tags != list(record.tags or []):
            changes["tags"] = [list(record.tags or []), tags]
            record.tags = tags
    custom = data.pop("custom", None)
    if custom is not None:
        before = dict(record.custom or {})
        after = clean_custom(db, context, record_type, custom, before)
        changes.update(custom_changes(db, context, record_type, before, after))
        record.custom = after
    return changes
