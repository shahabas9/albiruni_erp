"""Sharing documents with customers, and the public page a share link opens."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context, require_any_permission
from app.domain import (
    credit_note_service, invoice_service, payment_service, quotation_service, receivables, sales_settings,
    share_service, tax,
)
from app.domain.errors import ConflictError, NotFoundError
from app.toolgateway.executor import execute_tool

router = APIRouter(tags=["sharing"])


class ShareIn(BaseModel):
    kind: Literal["invoice", "quotation", "credit_note", "receipt", "statement"]
    # The document's id; for a statement, the customer's.
    id: UUID
    # Send the link by email to this address (needs SMTP); leave out for just the link.
    email: str = Field(default="", max_length=160)
    date_from: date | None = None
    date_to: date | None = None


def describe(db: Session, context: RequestContext, body: ShareIn) -> tuple[UUID, str, str]:
    """(customer id, title, one-line summary) for the document being shared."""

    money = lambda v: f"₹{float(v):,.2f}"  # noqa: E731
    if body.kind == "invoice":
        inv = invoice_service.get_invoice(db, context, body.id)
        if inv.status != "Issued":
            raise ConflictError("Issue the invoice before sending it.")
        return inv.customer_id, f"Invoice {inv.number}", (
            f"Please find our invoice {inv.number} dated {inv.invoice_date:%d %b %Y} for {money(inv.grand_total)}, "
            f"due on {inv.due_date:%d %b %Y}."
            + (f" {money(invoice_service.balance(inv))} is still to be paid." if 0 < invoice_service.balance(inv)
               < inv.grand_total else ""))
    if body.kind == "quotation":
        q = quotation_service.get_quotation(db, context, body.id)
        if q.status in ("Pending approval", "Rejected"):
            raise ConflictError(f"{q.number} is {q.status.lower()} and can't be sent.")
        valid = f", valid until {q.valid_until:%d %b %Y}" if q.valid_until else ""
        return q.customer_id, f"Quotation {q.number}", f"Please find our quotation {q.number} for {money(q.grand_total)}{valid}."
    if body.kind == "credit_note":
        n = credit_note_service.get_credit_note(db, context, body.id)
        return n.customer_id, f"Credit note {n.number}", (
            f"Please find credit note {n.number} for {money(n.grand_total)} against invoice {n.invoice.number}.")
    if body.kind == "receipt":
        r = payment_service.get_receipt(db, context, body.id)
        if r.status != "Received":
            raise ConflictError(f"{r.number} is voided.")
        return r.customer_id, f"Receipt {r.number}", f"Thank you for your payment of {money(r.amount)} ({r.mode})."
    today = date.today()
    start = body.date_from or date(tax.fy_start_year(today), 4, 1)
    end = body.date_to or today
    st = receivables.statement(db, context, body.id, start, end)
    body.date_from, body.date_to = start, end
    return body.id, "Statement of account", (
        f"Please find your statement of account from {start:%d %b %Y} to {end:%d %b %Y}. "
        f"Balance due: {money(st['closing_balance'])}.")


@router.post("/api/sales/share")
def share_document(body: ShareIn, context: RequestContext = Depends(get_current_context),
                   db: Session = Depends(get_db)):
    """A 30-day share link and a ready message (with a WhatsApp-encoded copy); emails it if `email` is given."""

    try:
        customer_id, title, summary = describe(db, context, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    args = {"kind": body.kind, "id": str(body.id), "customer_id": str(customer_id), "title": title,
            "summary": summary, "email": body.email,
            "date_from": body.date_from.isoformat() if body.date_from else None,
            "date_to": body.date_to.isoformat() if body.date_to else None}
    return execute_tool(db, context, f"sales.share_{body.kind}.v1", args, request_text=f"[form] Send {title}",
                        intent="share_document", correlation_id=new_correlation_id(), confirmed=True)


@router.get("/api/sales/share/recipients")
def share_recipients(customer_id: UUID,
                     context: RequestContext = Depends(require_any_permission(*{p for p, _ in share_service.KINDS.values()})),
                     db: Session = Depends(get_db)):
    return share_service.recipients(db, context, customer_id)


# --- Public: what a share link opens --------------------------------------------------


@router.get("/api/public/documents/{token}")
def public_document(token: str, db: Session = Depends(get_db)):
    """The shared document, for the customer's browser. No login: the signed token is the permission."""

    from app.api.routes_invoices import credit_note_out, invoice_out
    from app.api.routes_payments import receipt_out
    from app.api.routes_sales import orders_for, to_quotation_out

    try:
        payload = share_service.read_token(token)
        context = share_service.public_context(payload)
        kind, doc_id = payload["kind"], UUID(payload["id"])
        if kind == "invoice":
            doc = invoice_out(db, invoice_service.get_invoice(db, context, doc_id))
        elif kind == "quotation":
            q = quotation_service.get_quotation(db, context, doc_id)
            doc = to_quotation_out(q, orders_for(db, [q.id]).get(q.id))
        elif kind == "credit_note":
            doc = credit_note_out(db, credit_note_service.get_credit_note(db, context, doc_id))
        elif kind == "receipt":
            doc = receipt_out(db, payment_service.get_receipt(db, context, doc_id))
        else:
            doc = receivables.statement(db, context, doc_id, date.fromisoformat(payload["from"]),
                                        date.fromisoformat(payload["to"]))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    profile = sales_settings.profile(db, context)
    company = {k: getattr(profile, k) for k in ("name", "legal_name", "gstin", "state_code", "address", "phone",
                                                  "email", "bank_details", "invoice_terms")}
    return {"kind": kind, "document": doc, "company": company, "expires": payload["exp"]}
