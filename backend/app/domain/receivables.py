"""What customers owe: outstanding invoices, advances, ageing and statements."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import CreditNote, Invoice, Receipt, ReceiptAllocation
from app.models.sales import Customer


def invoices_owed(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """Sum of issued invoices' balances (a credited-back invoice can count below zero)."""

    total = db.execute(select(func.coalesce(
        func.sum(Invoice.grand_total - Invoice.amount_paid - Invoice.amount_credited), 0,
    )).where(
        Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
        Invoice.customer_id == customer_id, Invoice.status == "Issued",
    )).scalar_one()
    return Decimal(str(total))


def advances(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """Money received and not yet applied to an invoice."""

    used = (select(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
            .where(ReceiptAllocation.receipt_id == Receipt.id).scalar_subquery())
    total = db.execute(select(func.coalesce(func.sum(Receipt.amount - used), 0)).where(
        Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
        Receipt.customer_id == customer_id, Receipt.status == "Received",
    )).scalar_one()
    return Decimal(str(total))


def net_owed(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """What the customer owes after their advances; negative when we owe them."""

    return invoices_owed(db, context, customer_id) - advances(db, context, customer_id)


BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")


def ageing(db: Session, context: RequestContext, *, as_of: date | None = None, q: str = "",
           customer_id: UUID | None = None) -> dict:
    """Per customer: what's owed, split by how long it's been overdue, less advances.
    Customers owing nothing and holding no advance are left out."""

    day = as_of or date.today()
    left = Invoice.grand_total - Invoice.amount_paid - Invoice.amount_credited
    late = func.greatest(0, literal(day) - Invoice.due_date)

    def bucket(condition):
        return func.coalesce(func.sum(case((condition, left), else_=0)), 0)

    owed = (
        select(
            Invoice.customer_id.label("customer_id"),
            bucket(Invoice.due_date >= day).label("not_due"),
            bucket(and_(late >= 1, late <= 30)).label("d1_30"),
            bucket(and_(late >= 31, late <= 60)).label("d31_60"),
            bucket(and_(late >= 61, late <= 90)).label("d61_90"),
            bucket(late > 90).label("d90_plus"),
            func.min(case((left > 0, Invoice.due_date))).label("oldest_due"),
            func.count(case((left > 0, 1))).label("open_invoices"),
        )
        .where(Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
               Invoice.status == "Issued", left != 0)
        .group_by(Invoice.customer_id)
        .subquery()
    )
    used = (select(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
            .where(ReceiptAllocation.receipt_id == Receipt.id).scalar_subquery())
    adv = (
        select(Receipt.customer_id.label("customer_id"), func.sum(Receipt.amount - used).label("advance"))
        .where(Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
               Receipt.status == "Received")
        .group_by(Receipt.customer_id)
        .subquery()
    )
    stmt = (
        select(Customer, owed, adv.c.advance)
        .outerjoin(owed, owed.c.customer_id == Customer.id)
        .outerjoin(adv, adv.c.customer_id == Customer.id)
        .where(Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id,
               or_(owed.c.customer_id.is_not(None), func.coalesce(adv.c.advance, 0) > 0))
    )
    if customer_id:
        stmt = stmt.where(Customer.id == customer_id)
    if q.strip():
        words = [w.replace("%", r"\%").replace("_", r"\_") for w in q.split()]
        stmt = stmt.where(and_(*(or_(Customer.name.ilike(f"%{w}%"), Customer.gstin.ilike(f"%{w}%")) for w in words)))
    rows = []
    for row in db.execute(stmt).all():
        customer = row[0]
        amounts = {b: Decimal(str(getattr(row, b) or 0)) for b in BUCKETS}
        advance = Decimal(str(row.advance or 0))
        owed_total = sum(amounts.values(), Decimal(0))
        rows.append({
            "customer_id": customer.id, "customer_name": customer.name, "gstin": customer.gstin or "",
            "credit_limit": float(customer.credit_limit or 0), **{b: float(v) for b, v in amounts.items()},
            "overdue": float(owed_total - amounts["not_due"]), "invoiced_owed": float(owed_total),
            "advance": float(advance), "net": float(owed_total - advance),
            "oldest_due": row.oldest_due, "open_invoices": int(row.open_invoices or 0),
        })
    rows.sort(key=lambda r: (-r["overdue"], -r["net"], r["customer_name"]))
    totals = {k: round(sum(r[k] for r in rows), 2) for k in (*BUCKETS, "overdue", "invoiced_owed", "advance", "net")}
    return {"as_of": day, "rows": rows, "totals": totals}


def statement(db: Session, context: RequestContext, customer_id: UUID, date_from: date, date_to: date) -> dict:
    """Invoices (debit), credit notes and payments (credit) between two dates,
    with the balance brought forward and a running balance. Voided payments
    are left out, as if they never happened."""

    if date_from > date_to:
        raise ConflictError("The start date is after the end date.")

    def entries(before: date | None, start: date | None, end: date | None):
        def window(col):
            parts = []
            if before is not None:
                parts.append(col < before)
            if start is not None:
                parts.append(col >= start)
            if end is not None:
                parts.append(col <= end)
            return and_(*parts)

        base = dict(tenant=context.tenant_id, company=context.company_id)
        invoices = db.execute(select(Invoice).where(
            Invoice.tenant_id == base["tenant"], Invoice.company_id == base["company"],
            Invoice.customer_id == customer_id, Invoice.status == "Issued", window(Invoice.invoice_date),
        )).scalars().all()
        notes = db.execute(select(CreditNote).options(selectinload(CreditNote.invoice)).where(
            CreditNote.tenant_id == base["tenant"], CreditNote.company_id == base["company"],
            CreditNote.customer_id == customer_id, window(CreditNote.note_date),
        )).scalars().all()
        receipts = db.execute(select(Receipt).options(selectinload(Receipt.allocations).selectinload(
            ReceiptAllocation.invoice)).where(
            Receipt.tenant_id == base["tenant"], Receipt.company_id == base["company"],
            Receipt.customer_id == customer_id, Receipt.status == "Received", window(Receipt.receipt_date),
        )).scalars().all()
        out = [{"date": i.invoice_date, "kind": "Invoice", "number": i.number, "id": i.id,
                "details": f"Due {i.due_date:%d %b %Y}", "debit": Decimal(str(i.grand_total)), "credit": Decimal(0)}
               for i in invoices]
        out += [{"date": n.note_date, "kind": "Credit note", "number": n.number, "id": n.id,
                 "details": f"{n.kind} against {n.invoice.number}: {n.reason}", "debit": Decimal(0),
                 "credit": Decimal(str(n.grand_total))} for n in notes]
        out += [{"date": r.receipt_date, "kind": "Payment", "number": r.number, "id": r.id,
                 "details": f"{r.mode}{' ' + r.reference if r.reference else ''}"
                            + (f" — for {', '.join(a.invoice.number for a in r.allocations)}" if r.allocations else
                               " — advance"),
                 "debit": Decimal(0), "credit": Decimal(str(r.amount))} for r in receipts]
        order = {"Invoice": 0, "Credit note": 1, "Payment": 2}
        return sorted(out, key=lambda e: (e["date"], order[e["kind"]], e["number"] or ""))

    customer = db.get(Customer, customer_id)
    if customer is None or customer.tenant_id != context.tenant_id or customer.company_id != context.company_id:
        raise NotFoundError(f"No customer with id {customer_id}")
    opening = sum((e["debit"] - e["credit"] for e in entries(date_from, None, None)), Decimal(0))
    running = opening
    lines = []
    for e in entries(None, date_from, date_to):
        running += e["debit"] - e["credit"]
        lines.append({**e, "debit": float(e["debit"]), "credit": float(e["credit"]), "balance": float(running)})
    return {
        "customer_id": customer.id, "customer_name": customer.name, "gstin": customer.gstin or "",
        "billing_address": customer.billing_address or "", "date_from": date_from, "date_to": date_to,
        "opening_balance": float(opening), "closing_balance": float(running),
        "total_debit": float(sum(Decimal(str(l["debit"])) for l in lines)),
        "total_credit": float(sum(Decimal(str(l["credit"])) for l in lines)), "lines": lines,
    }
