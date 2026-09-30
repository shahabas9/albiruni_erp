from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import stock_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.sales import Item
from app.schemas.items import ItemIn, ItemUpdate


def list_items(db: Session, context: RequestContext) -> list[Item]:
    stmt = (
        select(Item)
        .where(Item.tenant_id == context.tenant_id, Item.company_id == context.company_id)
        .order_by(Item.name)
    )
    return list(db.execute(stmt).scalars().all())


def get_item(db: Session, context: RequestContext, item_id: UUID) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.tenant_id != context.tenant_id or item.company_id != context.company_id:
        raise NotFoundError(f"No item with id {item_id}")
    return item


def _sku_taken(db: Session, context: RequestContext, sku: str, exclude_id: UUID | None = None) -> bool:
    stmt = select(Item).where(
        Item.tenant_id == context.tenant_id, Item.company_id == context.company_id, Item.sku == sku
    )
    existing = db.execute(stmt).scalar_one_or_none()
    return existing is not None and existing.id != exclude_id


def create_item(db: Session, context: RequestContext, body: ItemIn) -> Item:
    if _sku_taken(db, context, body.sku):
        raise ConflictError(f"SKU '{body.sku}' is already in use.")
    item = Item(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        sku=body.sku,
        name=body.name,
        uom=body.uom,
        unit_price=body.unit_price,
        stock_qty=0,
        kind=body.kind,
        hsn_code=body.hsn_code,
        gst_rate=body.gst_rate,
    )
    db.add(item)
    db.flush()
    if body.stock_qty:
        stock_service.move(db, context, item, body.stock_qty, "Opening", note="Opening stock")
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, context: RequestContext, item_id: UUID, body: ItemUpdate) -> Item:
    item = get_item(db, context, item_id)
    data = body.model_dump(exclude_unset=True)
    if "sku" in data and _sku_taken(db, context, data["sku"], exclude_id=item.id):
        raise ConflictError(f"SKU '{data['sku']}' is already in use.")
    counted = data.pop("stock_qty", None)
    for field, value in data.items():
        setattr(item, field, value)
    if counted is not None and float(counted) != float(item.stock_qty):
        if not context.has_permission("inventory.stock.adjust"):
            raise ConflictError("Changing stock needs the inventory.stock.adjust permission.")
        # Stock only changes through a movement, so the ledger always adds up.
        db.flush()
        item = stock_service.lock_items(db, context, {item.id})[item.id]
        stock_service.move(db, context, item, float(counted) - float(item.stock_qty), "Adjustment",
                           note="Set on the item form", allow_negative=True)
    db.commit()
    db.refresh(item)
    return item
