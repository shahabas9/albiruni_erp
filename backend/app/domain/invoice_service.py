"""GST tax invoices, raised against sales orders.

A draft is made from an order (what's delivered and not yet invoiced, by
default) and can be looked over or thrown away. Issuing gives it the next
number in the financial year, copies the seller's and buyer's details onto
it as they are that day, and locks it: after that, only a credit note can
take anything back and only payments settle it.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import crm_service, history, tax
from app.domain.errors import ConflictError, NotFoundError
from app.domain.order_service import OPEN_STATUSES, get_order
from app.domain.sales_service import next_document_number
from app.models.documents import Invoice, InvoiceLine
from app.models.sales import Customer
from app.models.tenant import Company


def balance(invoice: Invoice) -> Decimal:
    return (Decimal(str(invoice.grand_total)) - Decimal(str(invoice.amount_paid))
            - Decimal(str(invoice.amount_credited)) - Decimal(str(invoice.amount_tds or 0))
            + Decimal(str(invoice.amount_refunded or 0)))


def payment_status(invoice: Invoice, today: date | None = None) -> str:
    """Draft, Paid, Credited (cancelled by credit notes), Overdue, Partly paid or Unpaid."""

    if invoice.status != "Issued":
        return invoice.status
    left = balance(invoice)
    if left <= 0:
        return "Credited" if Decimal(str(invoice.amount_paid)) <= 0 else "Paid"
    if invoice.due_date < (today or date.today()):
        return "Overdue"
    return "Partly paid" if Decimal(str(invoice.amount_paid)) > 0 else "Unpaid"


def get_invoice(db: Session, context: RequestContext, invoice_id: UUID, *, lock: bool = False) -> Invoice:
    stmt = select(Invoice).where(
        Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
    )
    if lock:
        stmt = stmt.with_for_update().options(selectinload(Invoice.lines)).execution_options(populate_existing=True)
    invoice = db.execute(stmt).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError(f"No invoice with id {invoice_id}")
    return invoice


def list_invoices(
    db: Session, context: RequestContext, *, status: str = "", customer_id: UUID | None = None,
    order_id: UUID | None = None, q: str = "", limit: int | None = None, offset: int = 0,
):
    """status: Draft, Issued, or a payment state — unpaid (anything still owed), overdue, paid."""

    left = Invoice.left_expr()
    stmt = (
        select(Invoice)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id)
        .options(selectinload(Invoice.lines), selectinload(Invoice.customer), selectinload(Invoice.order))
    )
    if status in ("Draft", "Issued"):
        stmt = stmt.where(Invoice.status == status)
    elif status == "unpaid":
        stmt = stmt.where(Invoice.status == "Issued", left > 0)
    elif status == "overdue":
        stmt = stmt.where(Invoice.status == "Issued", left > 0, Invoice.due_date < date.today())
    elif status == "paid":
        stmt = stmt.where(Invoice.status == "Issued", left <= 0)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if order_id:
        stmt = stmt.where(Invoice.order_id == order_id)
    if q.strip():
        stmt = stmt.where(crm_service.search(q, Invoice.number, Customer.name, Invoice.customer_po))
    order = (Invoice.status == "Draft").desc(), Invoice.invoice_date.desc(), Invoice.number.desc(), Invoice.id
    return crm_service.page(db, stmt.order_by(*order), limit, offset)


def _default_qty(line) -> Decimal:
    """Goods: what's been delivered and not invoiced (or, before any delivery,
    everything not invoiced). Services: everything not invoiced."""

    ordered, delivered, invoiced = (Decimal(str(v)) for v in (line.qty, line.delivered_qty, line.invoiced_qty))
    if line.item.kind == "service":
        return ordered - invoiced
    delivered_left = delivered - invoiced
    return delivered_left if delivered_left > 0 else (ordered - invoiced if delivered == 0 else Decimal(0))


def _price(invoice: Invoice, company: Company) -> None:
    interstate = bool(company.state_code) and bool(invoice.place_of_supply) and (
        invoice.place_of_supply != company.state_code
    )
    worked = tax.compute(
        [tax.LineIn(Decimal(str(l.qty)), Decimal(str(l.unit_price)), Decimal(str(l.gst_rate)),
                    Decimal(str(l.discount_pct or 0))) for l in invoice.lines],
        invoice.discount_pct, interstate,
    )
    for line, parts in zip(invoice.lines, worked.lines):
        line.amount, line.taxable_value = parts.amount, parts.taxable
        line.cgst, line.sgst, line.igst = parts.cgst, parts.sgst, parts.igst
    invoice.subtotal, invoice.total = worked.subtotal, worked.taxable
    invoice.cgst, invoice.sgst, invoice.igst = worked.cgst, worked.sgst, worked.igst
    invoice.round_off, invoice.grand_total = worked.round_off, worked.grand_total


def create_draft(db: Session, context: RequestContext, order_id: UUID, lines: list[dict] | None = None,
                 notes: str = "", *, commit: bool = True) -> Invoice:
    """lines: [{order_line_id, qty}]; leave out for the default quantities."""

    order = get_order(db, context, order_id, lock=True)
    if order.status not in OPEN_STATUSES:
        raise ConflictError(f"{order.number} is {order.status.lower()} — only confirmed orders can be invoiced.")
    by_id = {l.id: l for l in order.lines}
    if lines is None:
        wanted = {l.id: _default_qty(l) for l in order.lines}
    else:
        wanted = {}
        for raw in lines:
            line_id = UUID(str(raw["order_line_id"]))
            if line_id not in by_id:
                raise NotFoundError("That line isn't on this order.")
            wanted[line_id] = wanted.get(line_id, Decimal(0)) + Decimal(str(raw["qty"]))
    wanted = {k: v for k, v in wanted.items() if v > 0}
    if not wanted:
        raise ConflictError("Nothing left to invoice on this order" + (
            " — deliver the goods first, or pick the quantities yourself." if lines is None else "."))
    for line_id, qty in wanted.items():
        line = by_id[line_id]
        left = Decimal(str(line.qty)) - Decimal(str(line.invoiced_qty))
        if qty > left:
            raise ConflictError(f"Only {float(left):g} {line.uom} of {line.description} are left to invoice.")

    customer = db.get(Customer, order.customer_id)
    company = db.get(Company, context.company_id)
    terms = customer.payment_terms_days if customer.payment_terms_days is not None else company.payment_terms_days
    today = date.today()
    invoice = Invoice(
        tenant_id=context.tenant_id, company_id=context.company_id, order_id=order.id, customer_id=customer.id,
        status="Draft", invoice_date=today, due_date=today + timedelta(days=terms or 0),
        place_of_supply=order.place_of_supply, customer_po=order.customer_po, discount_pct=order.discount_pct,
        billing_address=order.billing_address, shipping_address=order.shipping_address, notes=notes.strip(),
        created_by=context.user.id,
    )
    for position, (line_id, qty) in enumerate(sorted(wanted.items(), key=lambda kv: by_id[kv[0]].position)):
        line = by_id[line_id]
        invoice.lines.append(InvoiceLine(
            position=position, order_line_id=line.id, item_id=line.item_id, description=line.description,
            hsn_code=line.hsn_code, uom=line.uom, qty=qty, unit_price=line.unit_price, gst_rate=line.gst_rate,
            discount_pct=line.discount_pct, credited_qty=0,
        ))
    _price(invoice, company)
    db.add(invoice)
    db.flush()
    history.record(db, context, "invoice", invoice.id, "created", f"Draft invoice for order {order.number}")
    if commit:
        db.commit()
    return invoice


def delete_draft(db: Session, context: RequestContext, invoice_id: UUID) -> None:
    invoice = get_invoice(db, context, invoice_id, lock=True)
    if invoice.status != "Draft":
        raise ConflictError(f"{invoice.number} is issued — issued invoices are corrected with a credit note.")
    db.delete(invoice)
    db.commit()


def missing_seller_details(company: Company) -> list[str]:
    return [label for label, value in (
        ("legal name", company.legal_name), ("GSTIN", company.gstin), ("state", company.state_code),
        ("address", company.address),
    ) if not value]


def issue(db: Session, context: RequestContext, invoice_id: UUID, invoice_date: date | None = None) -> Invoice:
    invoice = get_invoice(db, context, invoice_id)
    order = get_order(db, context, invoice.order_id, lock=True)  # order first, as deliveries lock it
    db.refresh(invoice, with_for_update=True)
    if invoice.status != "Draft":
        raise ConflictError(f"{invoice.number} is already issued.")
    if order.status not in OPEN_STATUSES:
        raise ConflictError(f"{order.number} is {order.status.lower()}.")
    company = db.get(Company, context.company_id)
    missing = missing_seller_details(company)
    if missing:
        raise ConflictError(f"Fill in your company's {', '.join(missing)} (Sales → Company & GST) before issuing.")
    day = invoice_date or date.today()
    if day > date.today():
        raise ConflictError("An invoice can't be dated in the future.")
    last = db.execute(select(func.max(Invoice.invoice_date)).where(
        Invoice.tenant_id == context.tenant_id, Invoice.status == "Issued",
    )).scalar_one()
    if last and tax.fy_start_year(last) == tax.fy_start_year(day) and day < last:
        raise ConflictError(f"Invoices are numbered in date order; the last one is dated {last:%d %b %Y}.")

    by_id = {l.id: l for l in order.lines}
    for line in invoice.lines:
        order_line = by_id[line.order_line_id]
        left = Decimal(str(order_line.qty)) - Decimal(str(order_line.invoiced_qty))
        if Decimal(str(line.qty)) > left:
            raise ConflictError(
                f"Only {float(left):g} {order_line.uom} of {order_line.description} are left to invoice — "
                "another invoice took the rest. Delete this draft and make a new one."
            )
    for line in invoice.lines:
        order_line = by_id[line.order_line_id]
        order_line.invoiced_qty = Decimal(str(order_line.invoiced_qty)) + Decimal(str(line.qty))

    customer = db.get(Customer, invoice.customer_id)
    terms_days = (invoice.due_date - invoice.invoice_date).days
    invoice.invoice_date, invoice.due_date = day, day + timedelta(days=terms_days)
    invoice.number = next_document_number(db, context, "invoice", "INV", day)
    invoice.status = "Issued"
    invoice.issued_by, invoice.issued_at = context.user.id, crm_service.now_utc()
    invoice.seller_name, invoice.seller_gstin = company.legal_name, company.gstin
    invoice.seller_state, invoice.seller_address = company.state_code, company.address
    invoice.buyer_name, invoice.buyer_gstin, invoice.buyer_state = customer.name, customer.gstin or "", customer.state_code or ""
    invoice.terms, invoice.bank_details = company.invoice_terms, company.bank_details
    _price(invoice, company)  # the company's state could have been set since the draft

    history.record(db, context, "invoice", invoice.id, "status_changed", f"Issued as {invoice.number}",
                   {"status": ["Draft", "Issued"]})
    history.record(db, context, "sales_order", order.id, "invoiced",
                   f"Invoice {invoice.number} issued (₹{float(invoice.grand_total):,.2f})")
    history.record(db, context, "customer", customer.id, "invoiced",
                   f"Invoice {invoice.number} issued — ₹{float(invoice.grand_total):,.0f}, due {invoice.due_date:%d %b %Y}")
    db.flush()
    return invoice


def hsn_summary(invoice: Invoice) -> list[dict]:
    """Taxable value and tax per HSN code and rate, as printed under the lines."""

    rows: dict[tuple[str, float], dict] = {}
    for l in invoice.lines:
        key = (l.hsn_code or "—", float(l.gst_rate))
        row = rows.setdefault(key, {"hsn_code": key[0], "gst_rate": key[1], "qty": 0.0, "taxable_value": 0.0,
                                    "cgst": 0.0, "sgst": 0.0, "igst": 0.0})
        row["qty"] += float(l.qty)
        for k in ("taxable_value", "cgst", "sgst", "igst"):
            row[k] = round(row[k] + float(getattr(l, k)), 2)
    return list(rows.values())

