from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, history, order_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.identity import User
from app.models.documents import SalesOrder
from app.models.sales import Quotation
from app.schemas.orders import DocLineOut, OrderIn, OrderOut, OrderUpdate, QuickSaleIn, QuickSaleOut, ReasonIn
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["sales orders"])

READ = "sales.order.read"
WRITE = "sales.order.write"


def _errors(fn):
    try:
        return fn()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def order_out(db: Session, order: SalesOrder) -> OrderOut:
    user_ids = {u for u in (order.created_by, order.approved_by) if u}
    names = {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars()}
    quotation_number = (
        db.execute(select(Quotation.number).where(Quotation.id == order.quotation_id)).scalar_one_or_none()
        if order.quotation_id else None
    )
    return OrderOut(
        id=order.id, number=order.number, customer_id=order.customer_id, customer_name=order.customer.name,
        customer_gstin=order.customer.gstin or "", quotation_id=order.quotation_id,
        quotation_number=quotation_number, opportunity_id=order.opportunity_id, order_date=order.order_date,
        customer_po=order.customer_po, status=order.status, invoice_status=order_service.invoice_status(order),
        place_of_supply=order.place_of_supply, billing_address=order.billing_address,
        shipping_address=order.shipping_address, notes=order.notes, subtotal=float(order.subtotal),
        discount_pct=float(order.discount_pct), total=float(order.total), cgst=float(order.cgst),
        sgst=float(order.sgst), igst=float(order.igst), round_off=float(order.round_off),
        grand_total=float(order.grand_total), needs_approval=order_service.needs_approval(order),
        approved_by_name=names.get(order.approved_by), cancel_reason=order.cancel_reason,
        created_by_name=names.get(order.created_by), created_at=order.created_at, confirmed_at=order.confirmed_at,
        lines=[line_out(l) for l in order.lines],
    )


def line_out(l) -> DocLineOut:
    return DocLineOut(
        id=l.id, item_id=l.item_id, item_kind=l.item.kind, description=l.description, hsn_code=l.hsn_code, uom=l.uom, qty=float(l.qty),
        unit_price=float(l.unit_price), list_price=float(l.list_price), gst_rate=float(l.gst_rate),
        amount=float(l.amount), taxable_value=float(l.taxable_value), cgst=float(l.cgst), sgst=float(l.sgst),
        igst=float(l.igst), delivered_qty=float(l.delivered_qty), invoiced_qty=float(l.invoiced_qty),
    )


def _with_warnings(db: Session, response: Response, order: SalesOrder, warnings: list[str]) -> OrderOut:
    out = order_out(db, order)
    out.warnings = warnings
    return out


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    response: Response,
    status: str = "",
    customer_id: UUID | None = None,
    q: str = "",
    to_invoice: bool = False,
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Newest first. status: one status, or "open" (confirmed, not cancelled).
    to_invoice: only orders with something left to invoice."""

    orders, total = order_service.list_orders(db, context, status=status, customer_id=customer_id, q=q,
                                              to_invoice=to_invoice, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [order_out(db, o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: UUID, context: RequestContext = Depends(require_permission(READ)),
              db: Session = Depends(get_db)):
    return order_out(db, _errors(lambda: order_service.get_order(db, context, order_id)))


@router.get("/orders/{order_id}/timeline")
def order_timeline(order_id: UUID, context: RequestContext = Depends(require_permission(READ)),
                   db: Session = Depends(get_db)):
    order = _errors(lambda: order_service.get_order(db, context, order_id))
    refs = [("sales_order", order.id)] + ([("quotation", order.quotation_id)] if order.quotation_id else [])
    return history.timeline(db, context, refs)


@router.post("/orders", response_model=OrderOut)
def create_order(body: OrderIn, response: Response, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    """A draft order. `warnings` lists anything worth a second look (low stock)."""

    order, warnings = _errors(lambda: order_service.create_order(db, context, body))
    return _with_warnings(db, response, order, warnings)


@router.post("/quotations/{quotation_id}/order", response_model=OrderOut)
def order_from_quotation(quotation_id: UUID, response: Response,
                         context: RequestContext = Depends(require_permission(WRITE)),
                         db: Session = Depends(get_db)):
    """A draft order with the quotation's lines, prices and discount; the quotation becomes Accepted."""

    order, warnings = _errors(lambda: order_service.order_from_quotation(db, context, quotation_id))
    return _with_warnings(db, response, order, warnings)


@router.patch("/orders/{order_id}", response_model=OrderOut)
def update_order(order_id: UUID, body: OrderUpdate, response: Response,
                 context: RequestContext = Depends(require_permission(WRITE)), db: Session = Depends(get_db)):
    order, warnings = _errors(lambda: order_service.update_order(db, context, order_id, body))
    return _with_warnings(db, response, order, warnings)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: UUID, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    _errors(lambda: order_service.delete_order(db, context, order_id))
    return Response(status_code=204)


def _run(db: Session, context: RequestContext, tool: str, order_id: UUID, text: str, **args) -> OrderOut:
    execute_tool(db, context, tool, {"order_id": str(order_id), **args}, request_text=text,
                 intent=tool.split(".")[1], correlation_id=new_correlation_id(), confirmed=True)
    return order_out(db, _errors(lambda: order_service.get_order(db, context, order_id)))


@router.post("/orders/{order_id}/confirm", response_model=OrderOut)
def confirm_order(order_id: UUID, context: RequestContext = Depends(require_permission(WRITE)),
                  db: Session = Depends(get_db)):
    """Locks the order. A discount over the limit needs sales.quotation.approve; going over the customer's
    credit limit needs sales.credit.override. Marks the linked deal Won."""

    return _run(db, context, "sales.confirm_order.v1", order_id, "[form] Confirm sales order")


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: UUID, body: ReasonIn, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    return _run(db, context, "sales.cancel_order.v1", order_id, "[form] Cancel sales order", reason=body.reason)


@router.post("/quick-sale", response_model=QuickSaleOut)
def quick_sale(body: QuickSaleIn, context: RequestContext = Depends(require_permission("sales.invoice.write")),
               db: Session = Depends(get_db)):
    """Counter sale: order, delivery, issued invoice and payment in one go — all or nothing.
    Needs the order, delivery and invoice permissions (and payment, when paid)."""

    args = {
        "customer_id": str(body.customer_id) if body.customer_id else None,
        "lines": [{"item_id": str(l.item_id), "qty": l.qty, **({"unit_price": l.unit_price} if l.unit_price is not None else {})}
                  for l in body.lines],
        "discount_pct": body.discount_pct, "notes": body.notes,
        "payment": body.payment.model_dump() if body.payment else None,
    }
    result = execute_tool(db, context, "sales.quick_sale.v1", args, request_text="[form] Counter sale",
                          intent="quick_sale", correlation_id=new_correlation_id(), confirmed=True)
    return QuickSaleOut(order_id=result["order_id"], invoice_id=result["invoice_id"], receipt_id=result["receipt_id"])
