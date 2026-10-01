"""Sales orders: what a customer has agreed to buy.

A draft can be edited freely. Confirming locks it and checks two policies a
salesperson can't wave through alone: a discount beyond the auto-approve
limit (or a price below list) needs someone with sales.quotation.approve, and
an order that takes the customer past their credit limit needs
sales.credit.override. Confirming also marks the linked CRM deal Won.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import crm_service, history, receivables, tax
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.sales_service import (
    DISCOUNT_AUTO_APPROVE_LIMIT_PCT, DomainValidationError, PricedLine, apply_tax, company_of, next_document_number,
)
from app.models.crm import Opportunity
from app.models.documents import SalesOrder, SalesOrderLine
from app.models.sales import Customer, Item, Quotation
from app.schemas.orders import DocLineIn, OrderIn, OrderUpdate

APPROVE = "sales.quotation.approve"
CREDIT_OVERRIDE = "sales.credit.override"
OPEN_STATUSES = ("Confirmed", "Partly delivered", "Delivered")
STATUSES = ("Draft", "Confirmed", "Partly delivered", "Delivered", "Cancelled")


def get_order(db: Session, context: RequestContext, order_id: UUID, *, lock: bool = False) -> SalesOrder:
    stmt = select(SalesOrder).where(
        SalesOrder.id == order_id, SalesOrder.tenant_id == context.tenant_id,
        SalesOrder.company_id == context.company_id,
    )
    if lock:
        # populate_existing: rows (and lines) this session loaded earlier are
        # re-read once the lock is held, never trusted from before it.
        stmt = stmt.with_for_update().options(selectinload(SalesOrder.lines)).execution_options(populate_existing=True)
    order = db.execute(stmt).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"No sales order with id {order_id}")
    return order


def list_orders(
    db: Session, context: RequestContext, *, status: str = "", customer_id: UUID | None = None, q: str = "",
    to_invoice: bool = False, limit: int | None = None, offset: int = 0,
) -> tuple[list[SalesOrder], int]:
    stmt = (
        select(SalesOrder)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .where(SalesOrder.tenant_id == context.tenant_id, SalesOrder.company_id == context.company_id)
        .options(selectinload(SalesOrder.lines), selectinload(SalesOrder.customer))
    )
    if status == "open":
        stmt = stmt.where(SalesOrder.status.in_(OPEN_STATUSES))
    elif status:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if to_invoice:
        pending = select(SalesOrderLine.order_id).where(SalesOrderLine.invoiced_qty < SalesOrderLine.qty)
        stmt = stmt.where(SalesOrder.status.in_(OPEN_STATUSES), SalesOrder.id.in_(pending))
    if q.strip():
        stmt = stmt.where(crm_service.search(q, SalesOrder.number, Customer.name, SalesOrder.customer_po))
    return crm_service.page(db, stmt.order_by(SalesOrder.created_at.desc(), SalesOrder.id), limit, offset)


def invoice_status(order: SalesOrder) -> str:
    invoiced = sum(float(l.invoiced_qty) for l in order.lines)
    if invoiced <= 0:
        return "Not invoiced"
    return "Invoiced" if all(float(l.invoiced_qty) >= float(l.qty) for l in order.lines) else "Partly invoiced"


def needs_approval(order: SalesOrder) -> bool:
    if order.approved_by:
        return False
    if float(order.discount_pct) > DISCOUNT_AUTO_APPROVE_LIMIT_PCT:
        return True
    return any(float(l.unit_price) < float(l.list_price) for l in order.lines)


def _items(db: Session, context: RequestContext, ids: list[UUID]) -> dict[UUID, Item]:
    found = db.execute(select(Item).where(
        Item.id.in_(ids), Item.tenant_id == context.tenant_id, Item.company_id == context.company_id,
    )).scalars().all()
    by_id = {i.id: i for i in found}
    missing = [str(i) for i in ids if i not in by_id]
    if missing:
        raise NotFoundError(f"No item with id {missing[0]}")
    return by_id


def price_lines(
    db: Session, context: RequestContext, order: SalesOrder, customer: Customer, lines_in: list[dict],
    discount_pct: float,
) -> list[str]:
    """Replaces the order's lines and totals. lines_in: {item, qty, unit_price}.
    Returns warnings. Every item needs a GST rate: an order becomes an invoice."""

    warnings: list[str] = []
    priced = [
        PricedLine(item=l["item"], qty=float(l["qty"]), unit_price=float(l["unit_price"]),
                   line_total=float(tax.money(Decimal(str(l["qty"])) * Decimal(str(l["unit_price"])))))
        for l in lines_in
    ]
    try:
        worked, pos, _ = apply_tax(company_of(db, context), customer, priced, discount_pct, warnings,
                                   rates_required=True)
    except DomainValidationError as exc:
        raise ConflictError(str(exc)) from exc
    order.lines.clear()
    db.flush()
    for position, (line, line_in, parts) in enumerate(zip(priced, lines_in, worked.lines)):
        item = line.item
        order.lines.append(SalesOrderLine(
            position=position, item_id=item.id, description=item.name, hsn_code=item.hsn_code or "", uom=item.uom,
            qty=line.qty, unit_price=line.unit_price, list_price=float(item.unit_price), gst_rate=line.gst_rate,
            amount=float(parts.amount), taxable_value=float(parts.taxable), cgst=float(parts.cgst),
            sgst=float(parts.sgst), igst=float(parts.igst), delivered_qty=0, invoiced_qty=0,
        ))
        if item.kind != "service" and float(item.stock_qty) < line.qty:
            warnings.append(f"{item.name}: only {float(item.stock_qty):g} {item.uom} in stock, {line.qty:g} ordered.")
    order.place_of_supply = pos
    order.subtotal = float(worked.subtotal)
    order.discount_pct = discount_pct
    order.total = float(worked.taxable)
    order.cgst, order.sgst, order.igst = float(worked.cgst), float(worked.sgst), float(worked.igst)
    order.round_off = float(worked.round_off)
    order.grand_total = float(worked.grand_total)
    return warnings


def _lines_from(db: Session, context: RequestContext, lines: list[DocLineIn]) -> list[dict]:
    items = _items(db, context, list({l.item_id for l in lines}))
    return [
        {"item": items[l.item_id], "qty": l.qty,
         "unit_price": items[l.item_id].unit_price if l.unit_price is None else l.unit_price}
        for l in lines
    ]


def _new_order(db: Session, context: RequestContext, customer: Customer, **fields) -> SalesOrder:
    if not customer.active:
        raise ConflictError(f"{customer.name} is inactive — reactivate them before taking an order.")
    order_date = fields.pop("order_date", None) or date.today()
    order = SalesOrder(
        tenant_id=context.tenant_id, company_id=context.company_id, customer_id=customer.id,
        number=next_document_number(db, context, "sales_order", "SO", order_date), order_date=order_date,
        status="Draft", billing_address=customer.billing_address or "",
        shipping_address=customer.shipping_address or customer.billing_address or "",
        created_by=context.user.id, **fields,
    )
    db.add(order)
    return order


def create_order(
    db: Session, context: RequestContext, body: OrderIn, *, commit: bool = True,
) -> tuple[SalesOrder, list[str]]:
    customer = get_customer(db, context, body.customer_id)
    order = _new_order(db, context, customer, order_date=body.order_date, customer_po=body.customer_po.strip(),
                       notes=body.notes.strip())
    warnings = price_lines(db, context, order, customer, _lines_from(db, context, body.lines), body.discount_pct)
    db.flush()
    history.record(db, context, "sales_order", order.id, "created", f"Order {order.number} drafted")
    if commit:
        db.commit()
    return order, warnings


def order_from_quotation(db: Session, context: RequestContext, quotation_id: UUID) -> tuple[SalesOrder, list[str]]:
    quotation = db.execute(select(Quotation).where(
        Quotation.id == quotation_id, Quotation.tenant_id == context.tenant_id,
        Quotation.company_id == context.company_id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if quotation is None:
        raise NotFoundError(f"No quotation with id {quotation_id}")
    if quotation.status in ("Pending approval", "Rejected"):
        raise ConflictError(f"{quotation.number} is {quotation.status.lower()} — it can't become an order.")
    existing = db.execute(select(SalesOrder.number).where(
        SalesOrder.quotation_id == quotation.id, SalesOrder.status != "Cancelled",
    )).scalar_one_or_none()
    if existing:
        raise ConflictError(f"{quotation.number} is already on order {existing}.")
    customer = get_customer(db, context, quotation.customer_id)
    order = _new_order(db, context, customer, quotation_id=quotation.id, opportunity_id=quotation.opportunity_id,
                       approved_by=quotation.approved_by)
    lines = [{"item": l.item, "qty": float(l.qty), "unit_price": float(l.unit_price)} for l in quotation.lines]
    warnings = price_lines(db, context, order, customer, lines, float(quotation.discount_pct))
    # The quote's discount was within policy (or approved) when it was made.
    if float(quotation.discount_pct) <= DISCOUNT_AUTO_APPROVE_LIMIT_PCT and not order.approved_by:
        for line in order.lines:
            line.list_price = min(float(line.list_price), float(line.unit_price))
    before = quotation.status
    quotation.status = "Accepted"
    db.flush()
    history.record(db, context, "sales_order", order.id, "created", f"Order {order.number} made from {quotation.number}")
    history.record(db, context, "quotation", quotation.id, "status_changed",
                   f"Status: {before} → Accepted (order {order.number})", {"status": [before, "Accepted"]})
    db.commit()
    return order, warnings


def _draft(db: Session, context: RequestContext, order_id: UUID) -> SalesOrder:
    order = get_order(db, context, order_id, lock=True)
    if order.status != "Draft":
        raise ConflictError(f"{order.number} is {order.status.lower()} — only drafts can be changed.")
    return order


def update_order(db: Session, context: RequestContext, order_id: UUID, body: OrderUpdate) -> tuple[SalesOrder, list[str]]:
    order = _draft(db, context, order_id)
    data = body.model_dump(exclude_unset=True)
    for key in ("customer_po", "notes"):
        if data.get(key) is not None:
            setattr(order, key, data[key].strip())
    if data.get("order_date"):
        order.order_date = data["order_date"]
    warnings: list[str] = []
    if body.lines is not None or body.discount_pct is not None:
        lines = (
            _lines_from(db, context, body.lines) if body.lines is not None
            else [{"item": l.item, "qty": float(l.qty), "unit_price": float(l.unit_price)} for l in order.lines]
        )
        discount = float(order.discount_pct) if body.discount_pct is None else body.discount_pct
        warnings = price_lines(db, context, order, order.customer, lines, discount)
        order.approved_by = None  # a changed price needs approving again
    history.record(db, context, "sales_order", order.id, "updated", f"Order {order.number} edited")
    db.commit()
    return order, warnings


def delete_order(db: Session, context: RequestContext, order_id: UUID) -> None:
    order = _draft(db, context, order_id)
    db.delete(order)
    db.commit()


def open_order_exposure(db: Session, context: RequestContext, customer_id: UUID, exclude: UUID | None = None) -> float:
    """What confirmed orders will still bill this customer (with GST), not yet invoiced."""

    share = (SalesOrderLine.qty - SalesOrderLine.invoiced_qty) / SalesOrderLine.qty
    value = SalesOrderLine.taxable_value + SalesOrderLine.cgst + SalesOrderLine.sgst + SalesOrderLine.igst
    stmt = (
        select(func.coalesce(func.sum(share * value), 0))
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
        .where(
            SalesOrder.tenant_id == context.tenant_id, SalesOrder.company_id == context.company_id,
            SalesOrder.customer_id == customer_id, SalesOrder.status.in_(OPEN_STATUSES),
            SalesOrderLine.invoiced_qty < SalesOrderLine.qty,
        )
    )
    if exclude:
        stmt = stmt.where(SalesOrder.id != exclude)
    return float(db.execute(stmt).scalar_one())


def credit_exposure(db: Session, context: RequestContext, customer_id: UUID, exclude: UUID | None = None) -> float:
    """What the customer owes (unpaid invoices less advances) plus what confirmed orders will still bill."""

    return open_order_exposure(db, context, customer_id, exclude) + float(
        receivables.net_owed(db, context, customer_id)
    )


def confirm_order(db: Session, context: RequestContext, order_id: UUID) -> SalesOrder:
    order = _draft(db, context, order_id)
    if not order.lines:
        raise ConflictError("An order needs at least one line.")
    if needs_approval(order):
        if not context.has_permission(APPROVE):
            raise ConflictError(
                f"{order.number} has a discount over {DISCOUNT_AUTO_APPROVE_LIMIT_PCT:g}% or a price below list — "
                "a manager (sales.quotation.approve) has to confirm it."
            )
        order.approved_by = context.user.id
    customer = db.get(Customer, order.customer_id)
    limit = float(customer.credit_limit or 0)
    if limit:
        exposure = credit_exposure(db, context, customer.id, exclude=order.id) + float(order.grand_total)
        if exposure > limit and not context.has_permission(CREDIT_OVERRIDE):
            raise ConflictError(
                f"This takes {customer.name} to ₹{exposure:,.0f} owed or on order, over their ₹{limit:,.0f} "
                "credit limit. Collect a payment first, or ask someone with sales.credit.override."
            )
    order.status = "Confirmed"
    order.confirmed_by = context.user.id
    order.confirmed_at = crm_service.now_utc()
    history.record(db, context, "sales_order", order.id, "status_changed", f"Order {order.number} confirmed",
                   {"status": ["Draft", "Confirmed"]})
    history.record(db, context, "customer", customer.id, "order_confirmed",
                   f"Order {order.number} confirmed (₹{float(order.grand_total):,.0f})")
    if order.opportunity_id:
        opp = db.get(Opportunity, order.opportunity_id)
        if opp is not None and opp.stage not in ("Won", "Lost"):
            before = opp.stage
            opp.stage, opp.lost_reason, opp.stage_changed_at = "Won", "", crm_service.now_utc()
            history.record(db, context, "opportunity", opp.id, "stage_changed",
                           f"Stage: {before} → Won (order {order.number} confirmed)", {"stage": [before, "Won"]})
    db.flush()
    return order


def cancel_order(db: Session, context: RequestContext, order_id: UUID, reason: str) -> SalesOrder:
    order = get_order(db, context, order_id, lock=True)
    if order.status == "Cancelled":
        raise ConflictError(f"{order.number} is already cancelled.")
    if any(float(l.delivered_qty) or float(l.invoiced_qty) for l in order.lines):
        raise ConflictError(f"{order.number} has deliveries or invoices — return or credit them instead.")
    before = order.status
    order.status = "Cancelled"
    order.cancel_reason = reason.strip()[:200]
    history.record(db, context, "sales_order", order.id, "status_changed",
                   f"Order {order.number} cancelled — {order.cancel_reason}", {"status": [before, "Cancelled"]})
    db.flush()
    return order

