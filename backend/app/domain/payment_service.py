"""Payments received.

A receipt records money in; allocations split it across the customer's
issued invoices (raising each invoice's amount_paid). Anything not allocated
is an advance — it stays on the receipt and can be applied to invoices later.
Voiding a receipt (a bounced cheque, a mistaken entry) takes its allocations
back off the invoices.

Invoices are locked in id order while allocations change, so two receipts
can't both pay the last rupee of the same invoice.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import crm_service, history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.invoice_service import balance
from app.domain.sales_service import next_document_number
from app.models.documents import Invoice, Receipt, ReceiptAllocation
from app.models.sales import Customer

MODES = ("Cash", "UPI", "Bank transfer", "Cheque", "Card", "Other")
# Section 269ST of the Income Tax Act: no cash receipt of ₹2 lakh or more.
CASH_LIMIT = Decimal("200000")
ZERO = Decimal("0.00")


def allocated(receipt: Receipt) -> Decimal:
    return sum((Decimal(str(a.amount)) for a in receipt.allocations), ZERO)


def unallocated(receipt: Receipt) -> Decimal:
    return ZERO if receipt.status == "Voided" else Decimal(str(receipt.amount)) - allocated(receipt)


def get_receipt(db: Session, context: RequestContext, receipt_id: UUID, *, lock: bool = False) -> Receipt:
    stmt = select(Receipt).where(
        Receipt.id == receipt_id, Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    receipt = db.execute(stmt).scalar_one_or_none()
    if receipt is None:
        raise NotFoundError(f"No payment with id {receipt_id}")
    return receipt


def list_receipts(
    db: Session, context: RequestContext, *, customer_id: UUID | None = None, invoice_id: UUID | None = None,
    q: str = "", with_advance: bool = False, limit: int | None = None, offset: int = 0,
):
    stmt = (
        select(Receipt)
        .join(Customer, Customer.id == Receipt.customer_id)
        .where(Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id)
        .options(selectinload(Receipt.allocations).selectinload(ReceiptAllocation.invoice),
                 selectinload(Receipt.customer))
    )
    if customer_id:
        stmt = stmt.where(Receipt.customer_id == customer_id)
    if invoice_id:
        stmt = stmt.where(Receipt.id.in_(
            select(ReceiptAllocation.receipt_id).where(ReceiptAllocation.invoice_id == invoice_id)))
    if with_advance:
        used = (select(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
                .where(ReceiptAllocation.receipt_id == Receipt.id).scalar_subquery())
        stmt = stmt.where(Receipt.status == "Received", Receipt.amount > used)
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Receipt.number, Customer.name, Receipt.reference))
    return crm_service.page(db, stmt.order_by(Receipt.receipt_date.desc(), Receipt.number.desc()), limit, offset)


def open_invoices(db: Session, context: RequestContext, customer_id: UUID, *, lock: bool = False) -> list[Invoice]:
    """Issued invoices with something still owed, oldest due first. With lock,
    rows are locked in id order (like every other invoice lock) before sorting."""

    stmt = select(Invoice).where(
        Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
        Invoice.customer_id == customer_id, Invoice.status == "Issued",
        Invoice.grand_total - Invoice.amount_paid - Invoice.amount_credited > 0,
    )
    if lock:
        stmt = stmt.order_by(Invoice.id).with_for_update()
    rows = [i for i in db.execute(stmt).scalars() if balance(i) > 0]
    return sorted(rows, key=lambda i: (i.due_date, i.number or ""))


def _apply(db: Session, context: RequestContext, receipt: Receipt, allocations: list[dict] | None) -> list[tuple]:
    """Allocates receipt money to invoices. allocations None: oldest due first.
    Returns [(invoice, amount)] applied."""

    available = unallocated(receipt)
    if allocations is None:
        plan = []
        for invoice in open_invoices(db, context, receipt.customer_id, lock=True):
            if available <= 0:
                break
            take = min(available, balance(invoice))
            plan.append((invoice, take))
            available -= take
        return [_allocate(db, receipt, inv, amt) for inv, amt in plan]

    wanted: dict[UUID, Decimal] = {}
    for raw in allocations:
        amount = Decimal(str(raw["amount"])).quantize(Decimal("0.01"))
        if amount > 0:
            key = UUID(str(raw["invoice_id"]))
            wanted[key] = wanted.get(key, ZERO) + amount
    if sum(wanted.values(), ZERO) > available:
        raise ConflictError(f"Only ₹{float(available):,.2f} of this payment is left to allocate.")
    invoices = db.execute(
        select(Invoice).where(Invoice.id.in_(wanted), Invoice.tenant_id == context.tenant_id,
                              Invoice.company_id == context.company_id).order_by(Invoice.id).with_for_update()
    ).scalars().all()
    by_id = {i.id: i for i in invoices}
    applied = []
    for invoice_id, amount in wanted.items():
        invoice = by_id.get(invoice_id)
        if invoice is None:
            raise NotFoundError("That invoice doesn't exist.")
        if invoice.customer_id != receipt.customer_id:
            raise ConflictError(f"{invoice.number} belongs to another customer.")
        if invoice.status != "Issued":
            raise ConflictError("Payments go against issued invoices, not drafts.")
        if amount > balance(invoice):
            raise ConflictError(f"{invoice.number} only has ₹{float(balance(invoice)):,.2f} left to pay.")
        applied.append(_allocate(db, receipt, invoice, amount))
    return applied


def _allocate(db: Session, receipt: Receipt, invoice: Invoice, amount: Decimal) -> tuple:
    receipt.allocations.append(ReceiptAllocation(invoice_id=invoice.id, amount=amount))
    invoice.amount_paid = Decimal(str(invoice.amount_paid)) + amount
    return invoice, amount


def _record_history(db: Session, context: RequestContext, receipt: Receipt, applied: list[tuple]) -> None:
    for invoice, amount in applied:
        history.record(db, context, "invoice", invoice.id, "paid",
                       f"₹{float(amount):,.2f} received on {receipt.number} ({receipt.mode})")


def record_receipt(
    db: Session, context: RequestContext, *, customer_id: UUID, amount: float, mode: str, receipt_date: date | None,
    reference: str = "", notes: str = "", allocations: list[dict] | None = None,
) -> Receipt:
    customer = get_customer(db, context, customer_id)
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    if value <= 0:
        raise ConflictError("The amount must be more than zero.")
    if mode not in MODES:
        raise ConflictError(f"Mode must be one of: {', '.join(MODES)}.")
    if mode == "Cash" and value >= CASH_LIMIT:
        raise ConflictError("Cash receipts of ₹2,00,000 or more aren't allowed (Income Tax Act, section 269ST).")
    if mode in ("Cheque", "Bank transfer", "UPI") and not reference.strip():
        raise ConflictError(f"Enter the {'cheque number' if mode == 'Cheque' else 'transaction reference (UTR)'}.")
    day = receipt_date or date.today()
    if day > date.today():
        raise ConflictError("A payment can't be dated in the future.")
    receipt = Receipt(
        tenant_id=context.tenant_id, company_id=context.company_id,
        number=next_document_number(db, context, "receipt", "RCT", day), customer_id=customer.id,
        receipt_date=day, amount=value, mode=mode, reference=reference.strip()[:60], notes=notes.strip(),
        status="Received", created_by=context.user.id,
    )
    db.add(receipt)
    db.flush()
    applied = _apply(db, context, receipt, allocations)
    _record_history(db, context, receipt, applied)
    left = unallocated(receipt)
    history.record(db, context, "customer", customer.id, "payment",
                   f"Payment {receipt.number}: ₹{float(value):,.2f} by {mode.lower()}"
                   + (f", ₹{float(left):,.2f} kept as advance" if left > 0 else ""))
    db.flush()
    return receipt


def allocate(db: Session, context: RequestContext, receipt_id: UUID, allocations: list[dict] | None) -> Receipt:
    receipt = get_receipt(db, context, receipt_id, lock=True)
    if receipt.status == "Voided":
        raise ConflictError(f"{receipt.number} is voided.")
    if unallocated(receipt) <= 0:
        raise ConflictError(f"All of {receipt.number} is already allocated.")
    applied = _apply(db, context, receipt, allocations)
    if not applied:
        raise ConflictError("Nothing to allocate — this customer has no unpaid invoices.")
    _record_history(db, context, receipt, applied)
    db.flush()
    return receipt


def void_receipt(db: Session, context: RequestContext, receipt_id: UUID, reason: str) -> Receipt:
    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the payment is being voided (e.g. cheque bounced).")
    receipt = get_receipt(db, context, receipt_id, lock=True)
    if receipt.status == "Voided":
        raise ConflictError(f"{receipt.number} is already voided.")
    ids = sorted({a.invoice_id for a in receipt.allocations})
    invoices = {i.id: i for i in db.execute(
        select(Invoice).where(Invoice.id.in_(ids)).order_by(Invoice.id).with_for_update()).scalars()}
    for a in receipt.allocations:
        invoice = invoices[a.invoice_id]
        invoice.amount_paid = Decimal(str(invoice.amount_paid)) - Decimal(str(a.amount))
        history.record(db, context, "invoice", invoice.id, "payment_voided",
                       f"Payment {receipt.number} voided — {reason}; ₹{float(a.amount):,.2f} owed again")
    receipt.allocations.clear()
    receipt.status, receipt.void_reason = "Voided", reason[:200]
    history.record(db, context, "customer", receipt.customer_id, "payment_voided",
                   f"Payment {receipt.number} (₹{float(receipt.amount):,.2f}) voided — {reason}")
    db.flush()
    return receipt


def invoice_payments(db: Session, invoice_id: UUID) -> list[tuple[ReceiptAllocation, Receipt]]:
    return list(db.execute(
        select(ReceiptAllocation, Receipt).join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
        .where(ReceiptAllocation.invoice_id == invoice_id).order_by(Receipt.receipt_date, Receipt.number)
    ).all())
