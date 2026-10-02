from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import item_service
from app.domain.errors import ConflictError, NotFoundError
from app.schemas.items import ItemIn, ItemOut, ItemUpdate

router = APIRouter(prefix="/api/items", tags=["items"])


def _to_out(i) -> ItemOut:
    return ItemOut(
        id=i.id, sku=i.sku, name=i.name, uom=i.uom, unit_price=float(i.unit_price), stock_qty=float(i.stock_qty),
        kind=i.kind, hsn_code=i.hsn_code or "", gst_rate=None if i.gst_rate is None else float(i.gst_rate),
        tax_category=i.tax_category or "", exemption_reason=i.exemption_reason or "",
    )


@router.get("", response_model=list[ItemOut])
def list_items(
    context: RequestContext = Depends(require_permission("inventory.item.read")),
    db: Session = Depends(get_db),
):
    return [_to_out(i) for i in item_service.list_items(db, context)]


@router.post("", response_model=ItemOut)
def create_item(
    body: ItemIn,
    context: RequestContext = Depends(require_permission("inventory.item.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(item_service.create_item(db, context, body))
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: UUID,
    body: ItemUpdate,
    context: RequestContext = Depends(require_permission("inventory.item.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(item_service.update_item(db, context, item_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
