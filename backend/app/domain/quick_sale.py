"""A counter sale in one step: order, delivery, tax invoice and (optionally)
payment, all in one transaction — any refusal along the way (stock, credit
limit, a missing GST rate) and nothing is saved.

Each step runs the same rules as doing it by hand: a big discount still needs
a manager, stock can't go negative unless allowed, the invoice gets the next
number. A sale with no customer goes on the company's "Walk-in customer".
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.regimes import cur
from app.core.deps import RequestContext
from app.domain import crm_service, delivery_service, invoice_service, order_service, payment_service
from app.domain.errors import ConflictError
from app.models.documents import Invoice, Receipt, SalesOrder
from app.schemas.orders import DocLineIn, OrderIn

WALK_IN = "Walk-in customer"
NEEDS = ("sales.order.write", "sales.delivery.write", "sales.invoice.write")


def quick_sale(
    db: Session, context: RequestContext, *, customer_id: UUID | None, lines: list[dict], discount_pct: float = 0,
    notes: str = "", payment: dict | None = None,
) -> tuple[SalesOrder, Invoice, Receipt | None]:
    missing = [p for p in (*NEEDS, *(("sales.payment.write",) if payment else ())) if not context.has_permission(p)]
    if missing:
        raise PermissionError(f"Missing permission: {', '.join(missing)}")
    if customer_id is None:
        customer_id = crm_service.find_or_create_customer(db, context, WALK_IN).id

    order, _ = order_service.create_order(db, context, OrderIn(
        customer_id=customer_id, lines=[DocLineIn(**l) for l in lines], discount_pct=discount_pct,
        notes=notes, order_date=date.today(),
    ), commit=False)
    order_service.confirm_order(db, context, order.id)
    goods = [l for l in order.lines if l.item.kind != "service"]
    if goods:
        delivery_service.create_delivery(db, context, order.id,
                                         [{"order_line_id": l.id, "qty": l.qty} for l in goods],
                                         notes="Counter sale")
    invoice = invoice_service.create_draft(db, context, order.id, commit=False)
    invoice_service.issue(db, context, invoice.id)

    receipt = None
    if payment:
        amount = Decimal(str(payment["amount"])).quantize(Decimal("0.01"))
        total = Decimal(str(invoice.grand_total))
        # The screen's estimate can be a paisa/halala off the exact tax per line: take the bill.
        if total < amount <= total + Decimal("0.05"):
            amount = total
        if amount > total:
            raise ConflictError(f"The bill is {cur(context)}{float(total):,.2f} — give change for the rest rather than recording it.")
        receipt = payment_service.record_receipt(
            db, context, customer_id=customer_id, amount=float(amount), mode=payment["mode"], receipt_date=None,
            reference=payment.get("reference", ""), notes="Counter sale",
            allocations=[{"invoice_id": invoice.id, "amount": float(amount)}],
        )
    db.flush()
    return order, invoice, receipt
