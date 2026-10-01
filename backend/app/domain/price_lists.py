"""Price lists: agreed prices per customer, with quantity breaks.

A customer's price comes from their own list, else the company's default
list, else the item's own price; a list switched off is skipped. Within a list an item can have several rows
(min_qty 1 at ₹420, min_qty 100 at ₹400): the row with the highest min_qty
not above the quantity ordered wins. That price is the "list price" a line is
compared with — going below it still needs a manager.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain.errors import ConflictError, NotFoundError
from app.models.sales import Customer, Item, PriceList, PriceListItem
from app.models.tenant import Company


def _active(db: Session, price_list_id: UUID | None) -> bool:
    return price_list_id is not None and bool(
        db.execute(select(PriceList.active).where(PriceList.id == price_list_id)).scalar_one_or_none())


def list_id_for(db: Session, context: RequestContext, customer: Customer | None) -> UUID | None:
    """The customer's own list, else the company default; a paused list is skipped."""

    if customer is not None and _active(db, customer.price_list_id):
        return customer.price_list_id
    default = db.get(Company, context.company_id).default_price_list_id
    return default if _active(db, default) else None


def _rows(db: Session, price_list_id: UUID | None, item_ids: set[UUID]) -> dict[UUID, list[tuple[Decimal, Decimal]]]:
    if price_list_id is None or not item_ids:
        return {}
    out: dict[UUID, list[tuple[Decimal, Decimal]]] = {}
    for row in db.execute(select(PriceListItem).where(PriceListItem.price_list_id == price_list_id,
                                                      PriceListItem.item_id.in_(item_ids))).scalars():
        out.setdefault(row.item_id, []).append((Decimal(str(row.min_qty)), Decimal(str(row.unit_price))))
    return out


def price_for(db: Session, context: RequestContext, customer: Customer | None, item: Item, qty) -> float:
    """The price this customer pays for `qty` of `item` before any discount."""

    breaks = _rows(db, list_id_for(db, context, customer), {item.id}).get(item.id, [])
    qty = Decimal(str(qty))
    eligible = [(m, p) for m, p in breaks if m <= qty]
    return float(max(eligible)[1]) if eligible else float(item.unit_price)


def prices_for_customer(db: Session, context: RequestContext, customer_id: UUID | None) -> dict:
    """{item_id: [{min_qty, unit_price}]} from the list that applies to this customer, for forms."""

    customer = db.get(Customer, customer_id) if customer_id else None
    if customer is not None and (customer.tenant_id != context.tenant_id or customer.company_id != context.company_id):
        raise NotFoundError("No such customer.")
    list_id = list_id_for(db, context, customer)
    if list_id is None:
        return {"price_list_id": None, "prices": {}}
    rows = db.execute(select(PriceListItem).where(PriceListItem.price_list_id == list_id)).scalars()
    prices: dict[str, list[dict]] = {}
    for r in rows:
        prices.setdefault(str(r.item_id), []).append({"min_qty": float(r.min_qty), "unit_price": float(r.unit_price)})
    for v in prices.values():
        v.sort(key=lambda r: r["min_qty"])
    return {"price_list_id": str(list_id), "prices": prices}


# --- Managing lists ---------------------------------------------------------------------


def get_list(db: Session, context: RequestContext, list_id: UUID) -> PriceList:
    row = db.execute(select(PriceList).options(selectinload(PriceList.rows)).where(
        PriceList.id == list_id, PriceList.tenant_id == context.tenant_id, PriceList.company_id == context.company_id,
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"No price list with id {list_id}")
    return row


def all_lists(db: Session, context: RequestContext) -> list[PriceList]:
    return list(db.execute(select(PriceList).options(selectinload(PriceList.rows)).where(
        PriceList.tenant_id == context.tenant_id, PriceList.company_id == context.company_id,
    ).order_by(PriceList.name)).scalars())


def save_list(db: Session, context: RequestContext, list_id: UUID | None, *, name: str, active: bool,
              rows: list[dict], is_default: bool | None = None) -> PriceList:
    """Creates or replaces a list. rows: [{item_id, min_qty, unit_price}]."""

    name = name.strip()
    if not name:
        raise ConflictError("Give the price list a name.")
    taken = db.execute(select(PriceList.id).where(
        PriceList.company_id == context.company_id, PriceList.name.ilike(name),
        *([PriceList.id != list_id] if list_id else []),
    )).first()
    if taken:
        raise ConflictError(f"There's already a price list called “{name}”.")
    item_ids = {UUID(str(r["item_id"])) for r in rows}
    known = {i for i in db.execute(select(Item.id).where(
        Item.id.in_(item_ids), Item.tenant_id == context.tenant_id, Item.company_id == context.company_id,
    )).scalars()}
    if known != item_ids:
        raise NotFoundError("An item on the list doesn't exist.")
    seen = set()
    for r in rows:
        key = (str(r["item_id"]), Decimal(str(r["min_qty"])))
        if key in seen:
            raise ConflictError("The same item and quantity appear twice.")
        seen.add(key)
        if Decimal(str(r["min_qty"])) <= 0 or Decimal(str(r["unit_price"])) < 0:
            raise ConflictError("Quantities must be above zero and prices not negative.")

    price_list = get_list(db, context, list_id) if list_id else PriceList(
        tenant_id=context.tenant_id, company_id=context.company_id, name=name, active=True)
    if not list_id:
        db.add(price_list)
    price_list.name, price_list.active = name, active
    price_list.rows.clear()
    db.flush()
    for r in rows:
        price_list.rows.append(PriceListItem(item_id=UUID(str(r["item_id"])), min_qty=r["min_qty"],
                                             unit_price=r["unit_price"]))
    company = db.get(Company, context.company_id)
    if is_default is True:
        company.default_price_list_id = price_list.id
    elif is_default is False and company.default_price_list_id == price_list.id:
        company.default_price_list_id = None
    db.commit()
    return get_list(db, context, price_list.id)


def delete_list(db: Session, context: RequestContext, list_id: UUID) -> None:
    price_list = get_list(db, context, list_id)
    users = db.execute(select(Customer.name).where(Customer.price_list_id == list_id).limit(3)).scalars().all()
    if users:
        raise ConflictError(f"{', '.join(users)} use this list — move them to another first.")
    company = db.get(Company, context.company_id)
    if company.default_price_list_id == list_id:
        company.default_price_list_id = None
    db.delete(price_list)
    db.commit()
