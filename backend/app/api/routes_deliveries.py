from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, delivery_service, history, stock_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import DeliveryNote
from app.models.identity import User
from app.schemas.orders import DeliveryIn, DeliveryLineOut, DeliveryOut, ReasonIn, StockAdjustIn, StockMovementOut
from app.toolgateway.executor import execute_tool

router = APIRouter(tags=["deliveries and stock"])


def _errors(fn):
    try:
        return fn()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def delivery_out(d: DeliveryNote) -> DeliveryOut:
    return DeliveryOut(
        id=d.id, number=d.number, order_id=d.order_id, order_number=d.order.number, customer_id=d.customer_id,
        customer_name=d.customer.name, delivery_date=d.delivery_date, status=d.status,
        shipping_address=d.shipping_address, vehicle_no=d.vehicle_no, transporter=d.transporter, notes=d.notes,
        cancel_reason=d.cancel_reason, created_at=d.created_at,
        lines=[DeliveryLineOut(order_line_id=l.order_line_id, item_id=l.item_id, description=l.description,
                               uom=l.uom, qty=float(l.qty)) for l in d.lines],
    )


@router.get("/api/sales/deliveries", response_model=list[DeliveryOut])
def list_deliveries(
    response: Response,
    order_id: UUID | None = None,
    q: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("sales.order.read")),
    db: Session = Depends(get_db),
):
    rows, total = delivery_service.list_deliveries(db, context, order_id=order_id, q=q, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [delivery_out(d) for d in rows]


@router.get("/api/sales/deliveries/{delivery_id}", response_model=DeliveryOut)
def get_delivery(delivery_id: UUID, context: RequestContext = Depends(require_permission("sales.order.read")),
                 db: Session = Depends(get_db)):
    return delivery_out(_errors(lambda: delivery_service.get_delivery(db, context, delivery_id)))


@router.post("/api/sales/orders/{order_id}/deliveries", response_model=DeliveryOut)
def create_delivery(order_id: UUID, body: DeliveryIn,
                    context: RequestContext = Depends(require_permission("sales.delivery.write")),
                    db: Session = Depends(get_db)):
    """Takes the goods out of stock (refused if that would go below zero, unless the company allows it)."""

    args = {
        "order_id": str(order_id), "lines": [{"order_line_id": str(l.order_line_id), "qty": l.qty} for l in body.lines],
        "delivery_date": body.delivery_date.isoformat() if body.delivery_date else None,
        "vehicle_no": body.vehicle_no, "transporter": body.transporter, "notes": body.notes,
    }
    result = execute_tool(db, context, "sales.create_delivery.v1", args, request_text="[form] Deliver order",
                          intent="create_delivery", correlation_id=new_correlation_id(), confirmed=True)
    return delivery_out(delivery_service.get_delivery(db, context, UUID(result["delivery_id"])))


@router.post("/api/sales/deliveries/{delivery_id}/cancel", response_model=DeliveryOut)
def cancel_delivery(delivery_id: UUID, body: ReasonIn,
                    context: RequestContext = Depends(require_permission("sales.delivery.write")),
                    db: Session = Depends(get_db)):
    execute_tool(db, context, "sales.cancel_delivery.v1", {"delivery_id": str(delivery_id), "reason": body.reason},
                 request_text="[form] Cancel delivery", intent="cancel_delivery",
                 correlation_id=new_correlation_id(), confirmed=True)
    return delivery_out(_errors(lambda: delivery_service.get_delivery(db, context, delivery_id)))


# --- Stock --------------------------------------------------------------------------


@router.get("/api/items/{item_id}/stock", response_model=list[StockMovementOut])
def stock_ledger(
    item_id: UUID,
    response: Response,
    limit: int | None = Query(50, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("inventory.item.read")),
    db: Session = Depends(get_db),
):
    """Every change to the item's stock, newest first."""

    _, rows, total = _errors(lambda: stock_service.ledger(db, context, item_id, limit, offset))
    ids = {m.created_by for m in rows if m.created_by}
    names = {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}
    response.headers["X-Total-Count"] = str(total)
    return [
        StockMovementOut(id=m.id, kind=m.kind, qty=float(m.qty), balance_after=float(m.balance_after),
                         ref_type=m.ref_type, ref_id=m.ref_id, ref_number=m.ref_number, note=m.note,
                         created_by_name=names.get(m.created_by), created_at=m.created_at)
        for m in rows
    ]


@router.post("/api/items/{item_id}/adjust", status_code=204)
def adjust_stock(item_id: UUID, body: StockAdjustIn,
                 context: RequestContext = Depends(require_permission("inventory.stock.adjust")),
                 db: Session = Depends(get_db)):
    """Sets stock to a counted quantity; the difference is recorded with the reason."""

    _errors(lambda: stock_service.adjust(db, context, item_id, body.counted_qty, body.reason))
    return Response(status_code=204)


@router.get("/api/sales/deliveries/{delivery_id}/timeline")
def delivery_timeline(delivery_id: UUID, context: RequestContext = Depends(require_permission("sales.order.read")),
                      db: Session = Depends(get_db)):
    delivery = _errors(lambda: delivery_service.get_delivery(db, context, delivery_id))
    return history.timeline(db, context, [("delivery_note", delivery.id)])
