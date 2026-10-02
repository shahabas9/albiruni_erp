from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import regimes, stock_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.sales import Item
from app.models.tenant import Company
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


def _tax_fields(db: Session, context: RequestContext, rate, category, reason, current: Item | None = None) -> dict:
    """Rate, category and exemption reason checked against the company's country."""

    regime = regimes.of(db.get(Company, context.company_id))
    try:
        rate = None if rate is None else regimes.clean_rate(regime, rate)
        category = regimes.clean_category(regime, category, rate)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    reason = (reason or "").strip().upper()
    if category in ("Z", "E", "O"):
        if reason and reason not in regimes.EXEMPTION_REASONS:
            raise ConflictError(f"'{reason}' isn't a ZATCA exemption reason code.")
    else:
        reason = ""
    return {"gst_rate": rate, "tax_category": category, "exemption_reason": reason}


def create_item(db: Session, context: RequestContext, body: ItemIn) -> Item:
    taxes = _tax_fields(db, context, body.gst_rate, body.tax_category, body.exemption_reason)
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
        **taxes,
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
    if {"gst_rate", "tax_category", "exemption_reason"} & set(data):
        data.update(_tax_fields(
            db, context, data.pop("gst_rate", item.gst_rate),
            data.pop("tax_category", None) if "tax_category" in data else item.tax_category,
            data.pop("exemption_reason", None) if "exemption_reason" in data else item.exemption_reason,
        ))
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
