"""Delivery notes: goods leaving the warehouse against a confirmed order.

A delivery takes stock out and counts towards the order's delivered
quantities; an order is Delivered once every goods line is. Services on an
order are never delivered — they're simply invoiced. Cancelling a delivery
(a wrong entry, goods that never left) puts the stock back.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import crm_service, history, stock_service
from app.domain.errors import ConflictError, NotFoundError
from app.domain.order_service import get_order
from app.domain.sales_service import next_document_number
from app.models.documents import DeliveryNote, DeliveryNoteLine, SalesOrder
from app.models.sales import Customer

DELIVERABLE = ("Confirmed", "Partly delivered")


def refresh_order_status(order: SalesOrder) -> None:
    """Confirmed / Partly delivered / Delivered from the goods lines' delivered quantities."""

    if order.status not in ("Confirmed", "Partly delivered", "Delivered"):
        return
    goods = [l for l in order.lines if l.item.kind != "service"]
    delivered = [Decimal(str(l.delivered_qty)) for l in goods]
    if goods and all(d >= Decimal(str(l.qty)) for d, l in zip(delivered, goods)):
        order.status = "Delivered"
    elif any(d > 0 for d in delivered):
        order.status = "Partly delivered"
    else:
        order.status = "Confirmed"


def get_delivery(db: Session, context: RequestContext, delivery_id: UUID) -> DeliveryNote:
    delivery = db.execute(select(DeliveryNote).where(
        DeliveryNote.id == delivery_id, DeliveryNote.tenant_id == context.tenant_id,
        DeliveryNote.company_id == context.company_id,
    )).scalar_one_or_none()
    if delivery is None:
        raise NotFoundError(f"No delivery note with id {delivery_id}")
    return delivery


def list_deliveries(
    db: Session, context: RequestContext, *, order_id: UUID | None = None, q: str = "", limit: int | None = None,
    offset: int = 0,
):
    stmt = (
        select(DeliveryNote)
        .join(Customer, Customer.id == DeliveryNote.customer_id)
        .join(SalesOrder, SalesOrder.id == DeliveryNote.order_id)
        .where(DeliveryNote.tenant_id == context.tenant_id, DeliveryNote.company_id == context.company_id)
        .options(selectinload(DeliveryNote.lines), selectinload(DeliveryNote.customer), selectinload(DeliveryNote.order))
    )
    if order_id:
        stmt = stmt.where(DeliveryNote.order_id == order_id)
    if q.strip():
        stmt = stmt.where(crm_service.search(q, DeliveryNote.number, Customer.name, SalesOrder.number,
                                             DeliveryNote.vehicle_no))
    return crm_service.page(db, stmt.order_by(DeliveryNote.created_at.desc(), DeliveryNote.id), limit, offset)


def create_delivery(
    db: Session, context: RequestContext, order_id: UUID, lines: list[dict], *, delivery_date: date | None = None,
    vehicle_no: str = "", transporter: str = "", notes: str = "",
) -> DeliveryNote:
    """lines: [{order_line_id, qty}] — any goods lines of the order, up to what's left to deliver."""

    order = get_order(db, context, order_id, lock=True)
    if order.status not in DELIVERABLE:
        raise ConflictError(f"{order.number} is {order.status.lower()} — only confirmed orders can be delivered.")
    by_id = {l.id: l for l in order.lines}
    wanted: dict[UUID, Decimal] = {}
    for raw in lines:
        line = by_id.get(UUID(str(raw["order_line_id"])))
        if line is None:
            raise NotFoundError("That line isn't on this order.")
        qty = Decimal(str(raw["qty"]))
        if qty <= 0:
            continue
        if line.item.kind == "service":
            raise ConflictError(f"{line.description} is a service — services are invoiced, not delivered.")
        wanted[line.id] = wanted.get(line.id, Decimal(0)) + qty
    if not wanted:
        raise ConflictError("Enter a quantity for at least one line.")
    for line_id, qty in wanted.items():
        line = by_id[line_id]
        left = Decimal(str(line.qty)) - Decimal(str(line.delivered_qty))
        if qty > left:
            raise ConflictError(f"Only {float(left):g} {line.uom} of {line.description} are left to deliver.")

    day = delivery_date or date.today()
    delivery = DeliveryNote(
        tenant_id=context.tenant_id, company_id=context.company_id,
        number=next_document_number(db, context, "delivery_note", "DN", day), order_id=order.id,
        customer_id=order.customer_id, delivery_date=day, status="Delivered",
        shipping_address=order.shipping_address or order.billing_address, vehicle_no=vehicle_no.strip().upper()[:20],
        transporter=transporter.strip()[:120], notes=notes.strip(), created_by=context.user.id,
    )
    db.add(delivery)
    db.flush()
    items = stock_service.lock_items(db, context, {by_id[i].item_id for i in wanted})
    for line_id, qty in wanted.items():
        line = by_id[line_id]
        delivery.lines.append(DeliveryNoteLine(
            order_line_id=line.id, item_id=line.item_id, description=line.description, uom=line.uom, qty=qty,
        ))
        stock_service.move(db, context, items[line.item_id], -qty, "Delivery", ref_type="delivery_note",
                           ref_id=delivery.id, ref_number=delivery.number, note=f"Order {order.number}")
        line.delivered_qty = Decimal(str(line.delivered_qty)) + qty
    before = order.status
    refresh_order_status(order)
    summary = ", ".join(f"{float(q):g} {by_id[i].uom} {by_id[i].description}" for i, q in wanted.items())
    history.record(db, context, "sales_order", order.id, "delivered",
                   f"Delivered on {delivery.number}: {summary}"
                   + (f" (now {order.status.lower()})" if order.status != before else ""),
                   {"status": [before, order.status]} if order.status != before else None)
    history.record(db, context, "delivery_note", delivery.id, "created", f"{delivery.number} for order {order.number}")
    db.flush()
    return delivery


def cancel_delivery(db: Session, context: RequestContext, delivery_id: UUID, reason: str) -> DeliveryNote:
    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the delivery is being cancelled.")
    delivery = get_delivery(db, context, delivery_id)
    order = get_order(db, context, delivery.order_id, lock=True)
    db.refresh(delivery, with_for_update=True)
    if delivery.status == "Cancelled":
        raise ConflictError(f"{delivery.number} is already cancelled.")
    by_id = {l.id: l for l in order.lines}
    items = stock_service.lock_items(db, context, {l.item_id for l in delivery.lines})
    for dl in delivery.lines:
        line = by_id[dl.order_line_id]
        line.delivered_qty = Decimal(str(line.delivered_qty)) - Decimal(str(dl.qty))
        stock_service.move(db, context, items[dl.item_id], dl.qty, "Delivery cancelled", ref_type="delivery_note",
                           ref_id=delivery.id, ref_number=delivery.number, note=reason)
    delivery.status = "Cancelled"
    delivery.cancel_reason = reason[:200]
    before = order.status
    refresh_order_status(order)
    history.record(db, context, "sales_order", order.id, "delivery_cancelled",
                   f"Delivery {delivery.number} cancelled — {reason}; stock returned",
                   {"status": [before, order.status]} if order.status != before else None)
    history.record(db, context, "delivery_note", delivery.id, "status_changed", f"Cancelled — {reason}")
    db.flush()
    return delivery
