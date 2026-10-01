from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import price_lists
from app.domain.errors import ConflictError, NotFoundError
from app.models.sales import Customer, Item
from app.models.tenant import Company

router = APIRouter(prefix="/api/sales", tags=["price lists"])

READ = require_any_permission("sales.quotation.read", "sales.order.read", "sales.settings.write")


class PriceRowIn(BaseModel):
    item_id: UUID
    min_qty: float = Field(default=1, gt=0)
    unit_price: float = Field(ge=0)


class PriceListIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    active: bool = True
    # Applies to customers without a list of their own.
    is_default: bool = False
    rows: list[PriceRowIn] = Field(default=[], max_length=2000)


class PriceRowOut(BaseModel):
    item_id: UUID
    item_name: str
    sku: str
    item_price: float
    min_qty: float
    unit_price: float


class PriceListOut(BaseModel):
    id: UUID
    name: str
    active: bool
    is_default: bool
    customers: int
    rows: list[PriceRowOut]


def _out(db: Session, context: RequestContext, pl) -> PriceListOut:
    default_id = db.get(Company, context.company_id).default_price_list_id
    items = {i.id: i for i in db.execute(select(Item).where(Item.id.in_({r.item_id for r in pl.rows}))).scalars()}
    customers = db.execute(select(func.count()).select_from(Customer).where(Customer.price_list_id == pl.id)).scalar_one()
    return PriceListOut(
        id=pl.id, name=pl.name, active=pl.active, is_default=pl.id == default_id, customers=customers,
        rows=[PriceRowOut(item_id=r.item_id, item_name=items[r.item_id].name, sku=items[r.item_id].sku,
                          item_price=float(items[r.item_id].unit_price), min_qty=float(r.min_qty),
                          unit_price=float(r.unit_price))
              for r in sorted(pl.rows, key=lambda r: (items[r.item_id].name, r.min_qty))],
    )


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/price-lists", response_model=list[PriceListOut])
def list_price_lists(context: RequestContext = Depends(READ), db: Session = Depends(get_db)):
    return [_out(db, context, pl) for pl in price_lists.all_lists(db, context)]


@router.post("/price-lists", response_model=PriceListOut, status_code=201)
def create_price_list(
    body: PriceListIn,
    context: RequestContext = Depends(require_permission("sales.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        pl = price_lists.save_list(db, context, None, name=body.name, active=body.active, is_default=body.is_default,
                                   rows=[r.model_dump() for r in body.rows])
    except (ConflictError, NotFoundError) as exc:
        raise _err(exc) from exc
    return _out(db, context, pl)


@router.put("/price-lists/{list_id}", response_model=PriceListOut)
def update_price_list(
    list_id: UUID,
    body: PriceListIn,
    context: RequestContext = Depends(require_permission("sales.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        pl = price_lists.save_list(db, context, list_id, name=body.name, active=body.active,
                                   is_default=body.is_default, rows=[r.model_dump() for r in body.rows])
    except (ConflictError, NotFoundError) as exc:
        raise _err(exc) from exc
    return _out(db, context, pl)


@router.delete("/price-lists/{list_id}", status_code=204)
def delete_price_list(
    list_id: UUID,
    context: RequestContext = Depends(require_permission("sales.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        price_lists.delete_list(db, context, list_id)
    except (ConflictError, NotFoundError) as exc:
        raise _err(exc) from exc


@router.get("/prices")
def customer_prices(customer_id: UUID | None = None, context: RequestContext = Depends(READ),
                    db: Session = Depends(get_db)):
    """The agreed prices that apply to this customer (or the default list), for line editors."""

    try:
        return price_lists.prices_for_customer(db, context, customer_id)
    except NotFoundError as exc:
        raise _err(exc) from exc
