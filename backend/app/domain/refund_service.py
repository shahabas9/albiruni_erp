"""Refunds: paying money back to a customer.

Two things can be owed back:
- an **advance** — the part of a payment not applied to any invoice
  (receipts.amount_refunded grows, so less is left to apply);
- an invoice's **credit balance** — a credit note raised after the invoice
  was paid takes its balance below zero (invoices.amount_refunded brings it
  back towards zero).

Each refund draws on exactly one of them, so it's always clear what was
repaid. Voiding a refund (entered by mistake) puts the amount back.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.regimes import cur
from app.core.deps import RequestContext
from app.domain import crm_service, history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.invoice_service import balance, get_invoice
from app.domain.payment_service import MODES, get_receipt, unallocated
from app.domain.sales_service import next_document_number
from app.models.documents import Invoice, Receipt, Refund
from app.models.sales import Customer

ZERO = Decimal("0.00")


def refundable(db: Session, context: RequestContext, customer_id: UUID) -> dict:
    """What this customer could be paid back, by source."""

    get_customer(db, context, customer_id)
    receipts = db.execute(select(Receipt).options(selectinload(Receipt.allocations)).where(
        Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
        Receipt.customer_id == customer_id, Receipt.status == "Received",
    ).order_by(Receipt.receipt_date, Receipt.number)).scalars().all()
    invoices = db.execute(select(Invoice).where(
        Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
        Invoice.customer_id == customer_id, Invoice.status == "Issued", Invoice.left_expr() < 0,
    ).order_by(Invoice.invoice_date, Invoice.number)).scalars().all()
    advances = [{"receipt_id": r.id, "number": r.number, "date": r.receipt_date, "available": float(unallocated(r))}
                for r in receipts if unallocated(r) > 0]
    credits = [{"invoice_id": i.id, "number": i.number, "date": i.invoice_date, "available": float(-balance(i))}
               for i in invoices]
    return {"advances": advances, "credits": credits,
            "total": round(sum(a["available"] for a in advances) + sum(c["available"] for c in credits), 2)}


def get_refund(db: Session, context: RequestContext, refund_id: UUID, *, lock: bool = False) -> Refund:
    stmt = select(Refund).where(
        Refund.id == refund_id, Refund.tenant_id == context.tenant_id, Refund.company_id == context.company_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    refund = db.execute(stmt).scalar_one_or_none()
    if refund is None:
        raise NotFoundError(f"No refund with id {refund_id}")
    return refund


def list_refunds(db: Session, context: RequestContext, *, customer_id: UUID | None = None, q: str = "",
                 limit: int | None = None, offset: int = 0):
    stmt = (
        select(Refund).join(Customer, Customer.id == Refund.customer_id)
        .options(selectinload(Refund.customer), selectinload(Refund.receipt), selectinload(Refund.invoice))
        .where(Refund.tenant_id == context.tenant_id, Refund.company_id == context.company_id)
    )
    if customer_id:
        stmt = stmt.where(Refund.customer_id == customer_id)
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Refund.number, Customer.name, Refund.reference))
    return crm_service.page(db, stmt.order_by(Refund.refund_date.desc(), Refund.number.desc()), limit, offset)


def create_refund(
    db: Session, context: RequestContext, *, amount: float, mode: str, reason: str, reference: str = "",
    refund_date: date | None = None, receipt_id: UUID | None = None, invoice_id: UUID | None = None,
) -> Refund:
    if (receipt_id is None) == (invoice_id is None):
        raise ConflictError("Refund either an advance payment or an invoice's credit balance.")
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    if value <= 0:
        raise ConflictError("The amount must be more than zero.")
    if mode not in MODES:
        raise ConflictError(f"Mode must be one of: {', '.join(MODES)}.")
    if mode in ("Cheque", "Bank transfer", "UPI") and not reference.strip():
        raise ConflictError(f"Enter the {'cheque number' if mode == 'Cheque' else 'transaction reference (UTR)'}.")
    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the money is being paid back.")
    day = refund_date or date.today()
    if day > date.today():
        raise ConflictError("A refund can't be dated in the future.")

    if receipt_id is not None:
        source = get_receipt(db, context, receipt_id, lock=True)
        if source.status == "Voided":
            raise ConflictError(f"{source.number} is voided.")
        available, source_date, customer_id = unallocated(source), source.receipt_date, source.customer_id
        what = f"advance on {source.number}"
    else:
        source = get_invoice(db, context, invoice_id, lock=True)
        if source.status != "Issued":
            raise ConflictError(f"{source.number} isn't issued.")
        available, source_date, customer_id = -balance(source), source.invoice_date, source.customer_id
        what = f"credit balance on {source.number}"
    if available <= 0:
        raise ConflictError(f"Nothing is owed back on {source.number}.")
    if value > available:
        raise ConflictError(f"Only {cur(context)}{float(available):,.2f} can be refunded from {source.number}.")
    if day < source_date:
        raise ConflictError(f"A refund can't be dated before {source.number}.")

    source.amount_refunded = Decimal(str(source.amount_refunded or 0)) + value
    refund = Refund(
        tenant_id=context.tenant_id, company_id=context.company_id,
        number=next_document_number(db, context, "refund", "RFD", day), customer_id=customer_id,
        receipt_id=receipt_id, invoice_id=invoice_id, refund_date=day, amount=value, mode=mode,
        reference=reference.strip()[:60], reason=reason[:200], status="Paid", created_by=context.user.id,
    )
    db.add(refund)
    db.flush()
    summary = f"Refund {refund.number}: {cur(context)}{float(value):,.2f} by {mode.lower()} from the {what} — {reason}"
    history.record(db, context, "customer", customer_id, "refunded", summary)
    history.record(db, context, "receipt" if receipt_id else "invoice", source.id, "refunded", summary)
    db.flush()
    return refund


def void_refund(db: Session, context: RequestContext, refund_id: UUID, reason: str) -> Refund:
    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the refund is being voided.")
    refund = get_refund(db, context, refund_id, lock=True)
    if refund.status == "Voided":
        raise ConflictError(f"{refund.number} is already voided.")
    source = (get_receipt(db, context, refund.receipt_id, lock=True) if refund.receipt_id
              else get_invoice(db, context, refund.invoice_id, lock=True))
    source.amount_refunded = Decimal(str(source.amount_refunded)) - Decimal(str(refund.amount))
    refund.status, refund.void_reason = "Voided", reason[:200]
    summary = f"Refund {refund.number} ({cur(context)}{float(refund.amount):,.2f}) voided — {reason}"
    history.record(db, context, "customer", refund.customer_id, "refund_voided", summary)
    history.record(db, context, "receipt" if refund.receipt_id else "invoice", source.id, "refund_voided", summary)
    db.flush()
    return refund
