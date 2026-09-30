"""Credit notes: the only way to take back part of an issued invoice.

- A **return** gives back quantities (at the invoice's own net price and tax
  rate) and can put the goods back into stock.
- A **price correction** gives back an amount of taxable value on a line,
  with its GST, and moves no stock.

Either way the credit counts against the invoice (amount_credited), so the
customer owes less, or — if they'd already paid — is owed money back. GST law
allows a credit note up to 30 November after the end of the invoice's
financial year; later ones are refused.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import crm_service, history, stock_service, tax
from app.domain.errors import ConflictError, NotFoundError
from app.domain.invoice_service import get_invoice
from app.domain.sales_service import next_document_number
from app.models.documents import CreditNote, CreditNoteLine
from app.models.sales import Customer

KINDS = ("Return", "Price correction")


def deadline(invoice_date: date) -> date:
    """30 November after the end of the invoice's financial year."""

    return date(tax.fy_start_year(invoice_date) + 1, 11, 30)


def get_credit_note(db: Session, context: RequestContext, note_id: UUID) -> CreditNote:
    note = db.execute(select(CreditNote).where(
        CreditNote.id == note_id, CreditNote.tenant_id == context.tenant_id,
        CreditNote.company_id == context.company_id,
    )).scalar_one_or_none()
    if note is None:
        raise NotFoundError(f"No credit note with id {note_id}")
    return note


def list_credit_notes(
    db: Session, context: RequestContext, *, invoice_id: UUID | None = None, customer_id: UUID | None = None,
    q: str = "", limit: int | None = None, offset: int = 0,
):
    stmt = (
        select(CreditNote)
        .join(Customer, Customer.id == CreditNote.customer_id)
        .where(CreditNote.tenant_id == context.tenant_id, CreditNote.company_id == context.company_id)
        .options(selectinload(CreditNote.lines), selectinload(CreditNote.invoice), selectinload(CreditNote.customer))
    )
    if invoice_id:
        stmt = stmt.where(CreditNote.invoice_id == invoice_id)
    if customer_id:
        stmt = stmt.where(CreditNote.customer_id == customer_id)
    if q.strip():
        stmt = stmt.where(crm_service.search(q, CreditNote.number, Customer.name, CreditNote.reason))
    return crm_service.page(db, stmt.order_by(CreditNote.note_date.desc(), CreditNote.number.desc()), limit, offset)


def _split(taxable: Decimal, rate: Decimal, interstate: bool) -> tuple[Decimal, Decimal, Decimal]:
    if interstate:
        return Decimal("0.00"), Decimal("0.00"), tax.money(taxable * rate / 100)
    half = tax.money(taxable * rate / 200)
    return half, half, Decimal("0.00")


def create_credit_note(
    db: Session, context: RequestContext, invoice_id: UUID, *, kind: str, reason: str, lines: list[dict],
    restock: bool = False, note_date: date | None = None,
) -> CreditNote:
    """lines: returns [{invoice_line_id, qty}]; price corrections [{invoice_line_id, amount}] (taxable value)."""

    if kind not in KINDS:
        raise ConflictError(f"A credit note is a {' or a '.join(k.lower() for k in KINDS)}.")
    reason = reason.strip()
    if not reason:
        raise ConflictError("Say why the credit note is being issued.")
    invoice = get_invoice(db, context, invoice_id, lock=True)
    if invoice.status != "Issued":
        raise ConflictError("Only issued invoices can be credited — delete the draft instead.")
    day = note_date or date.today()
    if day > date.today() or day < invoice.invoice_date:
        raise ConflictError("The credit note's date must be between the invoice date and today.")
    if day > deadline(invoice.invoice_date):
        raise ConflictError(
            f"GST allows credit notes against {invoice.number} only until {deadline(invoice.invoice_date):%d %b %Y}."
        )

    by_id = {l.id: l for l in invoice.lines}
    interstate = Decimal(str(invoice.igst)) > 0 or (
        bool(invoice.seller_state) and invoice.place_of_supply != invoice.seller_state
    )
    note = CreditNote(
        tenant_id=context.tenant_id, company_id=context.company_id,
        number=next_document_number(db, context, "credit_note", "CN", day), invoice_id=invoice.id,
        customer_id=invoice.customer_id, note_date=day, kind=kind, reason=reason[:200],
        restocked=bool(restock and kind == "Return"), created_by=context.user.id,
    )
    restock_qty: dict[UUID, Decimal] = {}
    for raw in lines:
        line = by_id.get(UUID(str(raw["invoice_line_id"])))
        if line is None:
            raise NotFoundError("That line isn't on this invoice.")
        line_qty, line_taxable = Decimal(str(line.qty)), Decimal(str(line.taxable_value))
        value_left = line_taxable - Decimal(str(line.credited_value))
        if kind == "Return":
            qty = Decimal(str(raw.get("qty") or 0))
            if qty <= 0:
                continue
            qty_left = line_qty - Decimal(str(line.credited_qty))
            if qty > qty_left:
                raise ConflictError(f"Only {float(qty_left):g} {line.uom} of {line.description} can still be returned.")
            taxable = tax.money(line_taxable * qty / line_qty) if qty < qty_left else value_left
            line.credited_qty = Decimal(str(line.credited_qty)) + qty
            if line.item.kind != "service":
                restock_qty[line.item_id] = restock_qty.get(line.item_id, Decimal(0)) + qty
        else:
            qty = Decimal(0)
            taxable = tax.money(Decimal(str(raw.get("amount") or 0)))
            if taxable <= 0:
                continue
        if taxable > value_left:
            raise ConflictError(
                f"Only ₹{float(value_left):,.2f} of {line.description}'s value is left to credit."
            )
        line.credited_value = Decimal(str(line.credited_value)) + taxable
        rate = Decimal(str(line.gst_rate))
        cgst, sgst, igst = _split(taxable, rate, interstate)
        note.lines.append(CreditNoteLine(
            invoice_line_id=line.id, item_id=line.item_id, description=line.description, hsn_code=line.hsn_code,
            uom=line.uom, qty=qty, gst_rate=rate, taxable_value=taxable, cgst=cgst, sgst=sgst, igst=igst,
        ))
    if not note.lines:
        raise ConflictError("Enter a quantity or an amount for at least one line.")

    taxable = sum((Decimal(str(l.taxable_value)) for l in note.lines), Decimal("0.00"))
    cgst = sum((Decimal(str(l.cgst)) for l in note.lines), Decimal("0.00"))
    sgst = sum((Decimal(str(l.sgst)) for l in note.lines), Decimal("0.00"))
    igst = sum((Decimal(str(l.igst)) for l in note.lines), Decimal("0.00"))
    exact = taxable + cgst + sgst + igst
    grand = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    # A last credit that clears the invoice matches its total to the paisa.
    credited_before = Decimal(str(invoice.amount_credited))
    if credited_before + grand > Decimal(str(invoice.grand_total)):
        grand = Decimal(str(invoice.grand_total)) - credited_before
    note.total, note.cgst, note.sgst, note.igst = taxable, cgst, sgst, igst
    note.round_off, note.grand_total = grand - exact, grand
    invoice.amount_credited = credited_before + grand
    db.add(note)
    db.flush()

    if note.restocked and restock_qty:
        items = stock_service.lock_items(db, context, set(restock_qty))
        for item_id, qty in restock_qty.items():
            stock_service.move(db, context, items[item_id], qty, "Return", ref_type="credit_note", ref_id=note.id,
                               ref_number=note.number, note=f"Returned against {invoice.number}")

    what = f"{kind.lower()} — {reason}" + (" (goods back in stock)" if note.restocked else "")
    history.record(db, context, "invoice", invoice.id, "credited",
                   f"Credit note {note.number} for ₹{float(grand):,.2f}: {what}")
    history.record(db, context, "credit_note", note.id, "created", f"Against {invoice.number}: {what}")
    history.record(db, context, "customer", invoice.customer_id, "credited",
                   f"Credit note {note.number} for ₹{float(grand):,.0f} against {invoice.number}")
    db.flush()
    return note

