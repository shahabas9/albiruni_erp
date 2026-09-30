from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import crm_service, history, invoice_service, tax
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import Invoice
from app.models.identity import User
from app.schemas.invoices import HsnRow, InvoiceDraftIn, InvoiceLineOut, InvoiceOut, IssueIn
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["invoices"])

READ = "sales.invoice.read"
WRITE = "sales.invoice.write"


def _errors(fn):
    try:
        return fn()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def invoice_out(db: Session, inv: Invoice) -> InvoiceOut:
    issued_by = db.get(User, inv.issued_by) if inv.issued_by else None
    return InvoiceOut(
        id=inv.id, number=inv.number, status=inv.status, payment_status=invoice_service.payment_status(inv),
        order_id=inv.order_id, order_number=inv.order.number, customer_id=inv.customer_id,
        customer_name=inv.customer.name, invoice_date=inv.invoice_date, due_date=inv.due_date,
        place_of_supply=inv.place_of_supply, place_of_supply_name=tax.state_name(inv.place_of_supply),
        seller_name=inv.seller_name, seller_gstin=inv.seller_gstin, seller_state=inv.seller_state,
        seller_state_name=tax.state_name(inv.seller_state), seller_address=inv.seller_address,
        buyer_name=inv.buyer_name or inv.customer.name, buyer_gstin=inv.buyer_gstin or inv.customer.gstin or "",
        buyer_state=inv.buyer_state or inv.customer.state_code or "", billing_address=inv.billing_address,
        shipping_address=inv.shipping_address, customer_po=inv.customer_po, subtotal=float(inv.subtotal),
        discount_pct=float(inv.discount_pct), total=float(inv.total), cgst=float(inv.cgst), sgst=float(inv.sgst),
        igst=float(inv.igst), round_off=float(inv.round_off), grand_total=float(inv.grand_total),
        amount_in_words=tax.amount_in_words(inv.grand_total), amount_paid=float(inv.amount_paid),
        amount_credited=float(inv.amount_credited), balance=float(invoice_service.balance(inv)), notes=inv.notes,
        terms=inv.terms, bank_details=inv.bank_details, created_at=inv.created_at, issued_at=inv.issued_at,
        issued_by_name=issued_by.display_name if issued_by else None,
        lines=[InvoiceLineOut(
            id=l.id, order_line_id=l.order_line_id, item_id=l.item_id, description=l.description,
            hsn_code=l.hsn_code, uom=l.uom, qty=float(l.qty), unit_price=float(l.unit_price),
            gst_rate=float(l.gst_rate), amount=float(l.amount), taxable_value=float(l.taxable_value),
            cgst=float(l.cgst), sgst=float(l.sgst), igst=float(l.igst), credited_qty=float(l.credited_qty),
        ) for l in inv.lines],
        hsn_summary=[HsnRow(**row) for row in invoice_service.hsn_summary(inv)],
    )


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(
    response: Response,
    status: str = "",
    customer_id: UUID | None = None,
    order_id: UUID | None = None,
    q: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Drafts first, then newest. status: Draft, Issued, unpaid, overdue or paid."""

    rows, total = invoice_service.list_invoices(db, context, status=status, customer_id=customer_id,
                                                order_id=order_id, q=q, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [invoice_out(db, i) for i in rows]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: UUID, context: RequestContext = Depends(require_permission(READ)),
                db: Session = Depends(get_db)):
    return invoice_out(db, _errors(lambda: invoice_service.get_invoice(db, context, invoice_id)))


@router.get("/invoices/{invoice_id}/timeline")
def invoice_timeline(invoice_id: UUID, context: RequestContext = Depends(require_permission(READ)),
                     db: Session = Depends(get_db)):
    invoice = _errors(lambda: invoice_service.get_invoice(db, context, invoice_id))
    return history.timeline(db, context, [("invoice", invoice.id)])


@router.post("/orders/{order_id}/invoices", response_model=InvoiceOut)
def create_draft(order_id: UUID, body: InvoiceDraftIn, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    lines = None if body.lines is None else [l.model_dump() for l in body.lines]
    return invoice_out(db, _errors(lambda: invoice_service.create_draft(db, context, order_id, lines, body.notes)))


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_draft(invoice_id: UUID, context: RequestContext = Depends(require_permission(WRITE)),
                 db: Session = Depends(get_db)):
    _errors(lambda: invoice_service.delete_draft(db, context, invoice_id))
    return Response(status_code=204)


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceOut)
def issue_invoice(invoice_id: UUID, body: IssueIn, context: RequestContext = Depends(require_permission(WRITE)),
                  db: Session = Depends(get_db)):
    """Numbers the invoice (INV/26-27/00001) and locks it. Needs the company's GST details filled in."""

    args = {"invoice_id": str(invoice_id), "invoice_date": body.invoice_date.isoformat() if body.invoice_date else None}
    execute_tool(db, context, "sales.issue_invoice.v1", args, request_text="[form] Issue invoice",
                 intent="issue_invoice", correlation_id=new_correlation_id(), confirmed=True)
    return invoice_out(db, _errors(lambda: invoice_service.get_invoice(db, context, invoice_id)))
