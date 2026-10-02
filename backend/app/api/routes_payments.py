from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, payment_service, refund_service, tax
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import Receipt, Refund
from app.models.tenant import Company
from app.models.identity import User
from app.schemas.orders import ReasonIn
from app.schemas.payments import (
    AllocateIn, AllocationOut, ReceiptIn, ReceiptOut, RefundIn, RefundOut, TdsCertificateIn,
)
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["payments"])

READ = "sales.payment.read"
WRITE = "sales.payment.write"


def _get(db: Session, context: RequestContext, receipt_id: UUID) -> Receipt:
    try:
        return payment_service.get_receipt(db, context, receipt_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def receipt_out(db: Session, r: Receipt) -> ReceiptOut:
    by = db.get(User, r.created_by)
    return ReceiptOut(
        id=r.id, number=r.number, customer_id=r.customer_id, customer_name=r.customer.name,
        receipt_date=r.receipt_date, amount=float(r.amount), mode=r.mode, reference=r.reference, notes=r.notes,
        status=r.status, void_reason=r.void_reason, tds_amount=float(r.tds_amount or 0), tds_section=r.tds_section,
        tds_certificate_received=r.tds_certificate_received, allocated=float(payment_service.allocated(r)),
        unallocated=float(payment_service.unallocated(r)), refunded=float(r.amount_refunded or 0),
        amount_in_words=tax.amount_in_words(r.amount, getattr(db.get(Company, r.company_id), "currency", None) or "INR"),
        created_by_name=by.display_name if by else None, created_at=r.created_at,
        allocations=[AllocationOut(invoice_id=a.invoice_id, invoice_number=a.invoice.number, amount=float(a.amount),
                                   tds_amount=float(a.tds_amount or 0)) for a in r.allocations],
    )


def _run(db: Session, context: RequestContext, tool: str, args: dict, text: str) -> dict:
    return execute_tool(db, context, tool, args, request_text=text, intent=tool.split(".")[1],
                        correlation_id=new_correlation_id(), confirmed=True)


@router.get("/payments", response_model=list[ReceiptOut])
def list_payments(
    response: Response,
    customer_id: UUID | None = None,
    invoice_id: UUID | None = None,
    q: str = "",
    with_advance: bool = False,
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Newest first. with_advance: only receipts with money not yet applied to an invoice."""

    rows, total = payment_service.list_receipts(db, context, customer_id=customer_id, invoice_id=invoice_id, q=q,
                                                with_advance=with_advance, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [receipt_out(db, r) for r in rows]


@router.get("/payments/{receipt_id}", response_model=ReceiptOut)
def get_payment(receipt_id: UUID, context: RequestContext = Depends(require_permission(READ)),
                db: Session = Depends(get_db)):
    return receipt_out(db, _get(db, context, receipt_id))


@router.post("/payments", response_model=ReceiptOut)
def record_payment(body: ReceiptIn, context: RequestContext = Depends(require_permission(WRITE)),
                   db: Session = Depends(get_db)):
    """Numbered RCT/26-27/00001. Without allocations, pays the oldest unpaid invoices first; the rest is an advance."""

    args = {
        "customer_id": str(body.customer_id), "amount": body.amount, "mode": body.mode,
        "receipt_date": body.receipt_date.isoformat() if body.receipt_date else None,
        "reference": body.reference, "notes": body.notes, "tds_section": body.tds_section,
        "allocations": None if body.allocations is None else [
            {"invoice_id": str(a.invoice_id), "amount": a.amount, "tds_amount": a.tds_amount} for a in body.allocations],
    }
    result = _run(db, context, "sales.record_payment.v1", args, "[form] Record payment")
    return receipt_out(db, _get(db, context, UUID(result["receipt_id"])))


@router.post("/payments/{receipt_id}/allocate", response_model=ReceiptOut)
def allocate_payment(receipt_id: UUID, body: AllocateIn, context: RequestContext = Depends(require_permission(WRITE)),
                     db: Session = Depends(get_db)):
    args = {"receipt_id": str(receipt_id), "allocations": None if body.allocations is None else [
        {"invoice_id": str(a.invoice_id), "amount": a.amount, "tds_amount": a.tds_amount} for a in body.allocations]}
    _run(db, context, "sales.allocate_payment.v1", args, "[form] Apply advance")
    return receipt_out(db, _get(db, context, receipt_id))


@router.post("/payments/{receipt_id}/void", response_model=ReceiptOut)
def void_payment(receipt_id: UUID, body: ReasonIn, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    _run(db, context, "sales.void_payment.v1", {"receipt_id": str(receipt_id), "reason": body.reason},
         "[form] Void payment")
    return receipt_out(db, _get(db, context, receipt_id))




@router.post("/payments/{receipt_id}/tds-certificate", response_model=ReceiptOut)
def tds_certificate(receipt_id: UUID, body: TdsCertificateIn, context: RequestContext = Depends(require_permission(WRITE)),
                    db: Session = Depends(get_db)):
    """Mark the customer's TDS certificate (Form 16A) for this payment as received, or not."""

    try:
        return receipt_out(db, payment_service.set_tds_certificate(db, context, receipt_id, body.received))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- Refunds -----------------------------------------------------------------------------


def refund_out(db: Session, f: Refund) -> RefundOut:
    by = db.get(User, f.created_by)
    return RefundOut(
        id=f.id, number=f.number, customer_id=f.customer_id, customer_name=f.customer.name, refund_date=f.refund_date,
        amount=float(f.amount), mode=f.mode, reference=f.reference, reason=f.reason, status=f.status,
        void_reason=f.void_reason, receipt_id=f.receipt_id, invoice_id=f.invoice_id,
        source_number=f.receipt.number if f.receipt else f.invoice.number,
        created_by_name=by.display_name if by else None, created_at=f.created_at,
    )


@router.get("/refunds", response_model=list[RefundOut])
def list_refunds(
    response: Response,
    customer_id: UUID | None = None,
    q: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    rows, total = refund_service.list_refunds(db, context, customer_id=customer_id, q=q, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [refund_out(db, f) for f in rows]


@router.get("/refundable")
def refundable(customer_id: UUID, context: RequestContext = Depends(require_permission(READ)),
               db: Session = Depends(get_db)):
    """Advances and invoice credit balances this customer could be paid back."""

    try:
        return refund_service.refundable(db, context, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refunds", response_model=RefundOut)
def create_refund(body: RefundIn, context: RequestContext = Depends(require_permission(WRITE)),
                  db: Session = Depends(get_db)):
    """Numbered RFD/26-27/00001; pays back an advance or an invoice's credit balance."""

    args = {
        "receipt_id": str(body.receipt_id) if body.receipt_id else None,
        "invoice_id": str(body.invoice_id) if body.invoice_id else None,
        "amount": body.amount, "mode": body.mode, "reference": body.reference, "reason": body.reason,
        "refund_date": body.refund_date.isoformat() if body.refund_date else None,
    }
    result = _run(db, context, "sales.create_refund.v1", args, "[form] Refund")
    return refund_out(db, refund_service.get_refund(db, context, UUID(result["refund_id"])))


@router.post("/refunds/{refund_id}/void", response_model=RefundOut)
def void_refund(refund_id: UUID, body: ReasonIn, context: RequestContext = Depends(require_permission(WRITE)),
                db: Session = Depends(get_db)):
    _run(db, context, "sales.void_refund.v1", {"refund_id": str(refund_id), "reason": body.reason}, "[form] Void refund")
    try:
        return refund_out(db, refund_service.get_refund(db, context, refund_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
