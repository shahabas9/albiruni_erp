"""A quotation's life after it's drafted: approval, sending, the customer's answer."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import history
from app.domain.errors import ConflictError, NotFoundError
from app.domain.sales_service import DomainValidationError, price_quotation, replace_lines
from app.models.documents import SalesOrder
from app.models.sales import Quotation

# action: (statuses it can start from, status it leads to)
TRANSITIONS = {
    "approve": (("Pending approval",), "Draft"),
    "send": (("Draft",), "Sent"),
    "accept": (("Draft", "Sent"), "Accepted"),
    "reject": (("Draft", "Sent", "Pending approval"), "Rejected"),
    "reopen": (("Rejected",), "Draft"),
}

DONE = {"approve": "approved", "send": "sent", "accept": "accepted", "reject": "rejected", "reopen": "reopened"}


def get_quotation(db: Session, context: RequestContext, quotation_id: UUID, *, lock: bool = False) -> Quotation:
    stmt = select(Quotation).where(
        Quotation.id == quotation_id, Quotation.tenant_id == context.tenant_id,
        Quotation.company_id == context.company_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    quotation = db.execute(stmt).scalar_one_or_none()
    if quotation is None:
        raise NotFoundError(f"No quotation with id {quotation_id}")
    return quotation


def change_status(db: Session, context: RequestContext, quotation_id: UUID, action: str, note: str = "") -> Quotation:
    if action not in TRANSITIONS:
        raise ConflictError(f"Unknown action '{action}'.")
    quotation = get_quotation(db, context, quotation_id, lock=True)
    allowed, target = TRANSITIONS[action]
    if action in ("send", "accept") and is_expired(quotation):
        raise ConflictError(f"{quotation.number} expired on {quotation.valid_until:%d %b %Y} — extend its validity first.")
    if quotation.status not in allowed:
        raise ConflictError(f"{quotation.number} is {quotation.status.lower()} — it can't be {DONE[action]} now.")
    if action == "approve" and not context.has_permission("sales.quotation.approve"):
        raise PermissionError("Missing permission: sales.quotation.approve")
    if action == "reject" and not note.strip():
        raise ConflictError("Say why the quotation was rejected.")
    before = quotation.status
    quotation.status = target
    if action == "approve":
        quotation.approved_by = context.user.id
        quotation.status_note = f"Discount approved by {context.user.display_name}"
    elif action == "reject":
        quotation.status_note = note.strip()[:200]
    elif action == "reopen":
        quotation.status_note = ""
    summary = f"Status: {before} → {target}" + (f" — {note.strip()}" if note.strip() else "")
    history.record(db, context, "quotation", quotation.id, "status_changed", summary, {"status": [before, target]})
    db.commit()
    return quotation


def is_expired(quotation: Quotation, today: date | None = None) -> bool:
    return (quotation.status in ("Draft", "Sent", "Pending approval") and quotation.valid_until is not None
            and quotation.valid_until < (today or date.today()))


EDITABLE = ("Draft", "Pending approval")


def update_quotation(db: Session, context: RequestContext, quotation_id: UUID, body) -> tuple[Quotation, list[str]]:
    quotation = get_quotation(db, context, quotation_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    changes_content = any(k in data for k in ("lines", "discount_pct", "notes"))
    if changes_content and quotation.status not in EDITABLE:
        raise ConflictError(f"{quotation.number} is {quotation.status.lower()} — only drafts can be changed "
                            "(a sent quotation can have its validity extended).")
    if quotation.status in ("Accepted", "Rejected"):
        raise ConflictError(f"{quotation.number} is {quotation.status.lower()}.")
    if db.execute(select(SalesOrder.id).where(SalesOrder.quotation_id == quotation.id,
                                              SalesOrder.status != "Cancelled")).first():
        raise ConflictError(f"{quotation.number} is already on an order.")
    warnings: list[str] = []
    if "valid_until" in data and data["valid_until"] is not None:
        if data["valid_until"] < date.today():
            raise ConflictError("The validity date is in the past.")
        quotation.valid_until = data["valid_until"]
    if data.get("notes") is not None:
        quotation.notes = data["notes"].strip()
    if "lines" in data or "discount_pct" in data:
        lines = ([l.model_dump(exclude_none=True) for l in body.lines] if body.lines is not None
                 else [{"item_id": l.item_id, "qty": float(l.qty), "unit_price": float(l.unit_price),
                        "discount_pct": float(l.discount_pct or 0)} for l in quotation.lines])
        discount = float(quotation.discount_pct) if body.discount_pct is None else body.discount_pct
        try:
            pricing = price_quotation(db, context, None, lines, discount, customer_id=quotation.customer_id)
        except DomainValidationError as exc:
            raise ConflictError(str(exc)) from exc
        replace_lines(quotation, pricing)
        warnings = pricing.warnings
        before = quotation.status
        quotation.status = "Pending approval" if pricing.requires_approval else "Draft"
        quotation.approved_by = None
        quotation.status_note = ""
        if before != quotation.status:
            history.record(db, context, "quotation", quotation.id, "status_changed",
                           f"Status: {before} → {quotation.status} (edited)", {"status": [before, quotation.status]})
    history.record(db, context, "quotation", quotation.id, "updated", f"{quotation.number} edited")
    db.commit()
    return quotation, warnings
