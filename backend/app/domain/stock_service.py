"""Stock: every change is a movement row, and an item's stock_qty is their
running total. Deliveries take stock out, returns and cancelled deliveries
put it back, and a hand count is an adjustment with a reason.

move() locks the item row, so two deliveries of the last few boxes can't both
succeed; callers moving several items lock them in id order (lock_items) so
two such transactions can't deadlock each other.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import StockMovement
from app.models.sales import Item
from app.models.tenant import Company


def lock_items(db: Session, context: RequestContext, item_ids: set[UUID]) -> dict[UUID, Item]:
    rows = db.execute(
        select(Item)
        .where(Item.id.in_(item_ids), Item.tenant_id == context.tenant_id, Item.company_id == context.company_id)
        .order_by(Item.id)
        .with_for_update()
    ).scalars().all()
    found = {i.id: i for i in rows}
    if len(found) != len(item_ids):
        raise NotFoundError("An item on this document no longer exists.")
    return found


def move(
    db: Session, context: RequestContext, item: Item, qty: float | Decimal, kind: str, *, ref_type: str = "",
    ref_id: UUID | None = None, ref_number: str = "", note: str = "", allow_negative: bool | None = None,
) -> StockMovement | None:
    """Changes the (already locked) item's stock by qty. Services have no stock: None."""

    if item.kind == "service":
        return None
    qty = Decimal(str(qty))
    after = Decimal(str(item.stock_qty)) + qty
    if qty < 0 and after < 0:
        if allow_negative is None:
            allow_negative = bool(db.get(Company, context.company_id).allow_negative_stock)
        if not allow_negative:
            raise ConflictError(
                f"Only {float(item.stock_qty):g} {item.uom} of {item.name} in stock — can't take out {float(-qty):g}."
            )
    item.stock_qty = after
    movement = StockMovement(
        tenant_id=context.tenant_id, company_id=context.company_id, item_id=item.id, kind=kind, qty=qty,
        balance_after=after, ref_type=ref_type, ref_id=ref_id, ref_number=ref_number, note=note[:200],
        created_by=context.user.id if context.user else None, created_at=crm_service.now_utc(),
    )
    db.add(movement)
    return movement


def adjust(db: Session, context: RequestContext, item_id: UUID, counted: float, reason: str) -> StockMovement | None:
    """Sets stock to a counted quantity, recording the difference."""

    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the stock is being adjusted (e.g. 'Stock count 30 Sep', 'Damaged').")
    if counted < 0:
        raise ConflictError("Stock can't be counted below zero.")
    item = lock_items(db, context, {item_id})[item_id]
    if item.kind == "service":
        raise ConflictError(f"{item.name} is a service — it has no stock.")
    change = Decimal(str(counted)) - Decimal(str(item.stock_qty))
    if change == 0:
        raise ConflictError(f"{item.name} already has {counted:g} {item.uom} in stock.")
    movement = move(db, context, item, change, "Adjustment", note=reason, allow_negative=True)
    db.commit()
    return movement


def ledger(db: Session, context: RequestContext, item_id: UUID, limit: int | None, offset: int):
    item = db.get(Item, item_id)
    if item is None or item.tenant_id != context.tenant_id or item.company_id != context.company_id:
        raise NotFoundError(f"No item with id {item_id}")
    stmt = (
        select(StockMovement)
        .where(StockMovement.item_id == item_id, StockMovement.tenant_id == context.tenant_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
    )
    return item, *crm_service.page(db, stmt, limit, offset)
