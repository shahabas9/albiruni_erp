"""A quotation's life after it's drafted: approval, sending, the customer's answer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import history
from app.domain.errors import ConflictError, NotFoundError
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
