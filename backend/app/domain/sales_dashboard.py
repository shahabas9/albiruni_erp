"""Headline sales figures for the Overview page.

Each block appears only for someone who may read the documents behind it:
money (invoiced, collected, owed) needs sales.invoice.read, orders need
sales.order.read, quotations need sales.quotation.read.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import receivables, tax
from app.domain.order_service import OPEN_STATUSES
from app.models.documents import CreditNote, Invoice, Receipt, Refund, SalesOrder, SalesOrderLine
from app.models.sales import Customer, Quotation


def _month_start(day: date, back: int = 0) -> date:
    month = day.month - 1 - back
    return date(day.year + month // 12, month % 12 + 1, 1)


def _sum(db: Session, column, *where) -> float:
    return float(db.execute(select(func.coalesce(func.sum(column), 0)).where(*where)).scalar_one())


def dashboard(db: Session, context: RequestContext, today: date | None = None) -> dict:
    day = today or date.today()
    mine = lambda model: (model.tenant_id == context.tenant_id, model.company_id == context.company_id)  # noqa: E731
    out: dict = {"as_of": day}

    if context.has_permission("sales.invoice.read"):
        issued = (*mine(Invoice), Invoice.status == "Issued")

        def invoiced(start: date, end: date) -> float:
            sales = _sum(db, Invoice.grand_total, *issued, Invoice.invoice_date >= start, Invoice.invoice_date < end)
            credits = _sum(db, CreditNote.grand_total, *mine(CreditNote), CreditNote.note_date >= start,
                           CreditNote.note_date < end)
            return round(sales - credits, 2)

        months = [_month_start(day, back) for back in range(5, -1, -1)]
        series = [{"month": m.isoformat(), "label": f"{m:%b}",
                   "value": invoiced(m, _month_start(m, -1))} for m in months]
        this_start = months[-1]
        received = _sum(db, Receipt.amount, *mine(Receipt), Receipt.status == "Received",
                        Receipt.receipt_date >= this_start)
        refunded = _sum(db, Refund.amount, *mine(Refund), Refund.status == "Paid", Refund.refund_date >= this_start)
        aged = receivables.ageing(db, context, as_of=day)
        fy_start = date(tax.fy_start_year(day), 4, 1)
        top = db.execute(
            select(Customer.id, Customer.name, func.sum(Invoice.grand_total).label("value"))
            .join(Invoice, Invoice.customer_id == Customer.id)
            .where(*issued, Invoice.invoice_date >= fy_start)
            .group_by(Customer.id, Customer.name).order_by(func.sum(Invoice.grand_total).desc()).limit(5)
        ).all()
        out["money"] = {
            "invoiced_this_month": series[-1]["value"], "invoiced_last_month": series[-2]["value"],
            "collected_this_month": round(received - refunded, 2),
            "outstanding": aged["totals"]["invoiced_owed"], "overdue": aged["totals"]["overdue"],
            "advances": aged["totals"]["advance"],
            "overdue_customers": [
                {"customer_id": r["customer_id"], "name": r["customer_name"], "overdue": r["overdue"]}
                for r in aged["rows"] if r["overdue"] > 0][:5],
            "monthly": series,
            "top_customers": [{"customer_id": r.id, "name": r.name, "value": float(r.value)} for r in top],
            "fy_label": tax.fy_label(day),
        }

    if context.has_permission("sales.order.read"):
        pending = select(SalesOrderLine.order_id).where(SalesOrderLine.invoiced_qty < SalesOrderLine.qty)
        to_invoice = db.execute(select(func.count()).select_from(SalesOrder).where(
            *mine(SalesOrder), SalesOrder.status.in_(OPEN_STATUSES), SalesOrder.id.in_(pending),
        )).scalar_one()
        drafts = db.execute(select(func.count()).select_from(SalesOrder).where(
            *mine(SalesOrder), SalesOrder.status == "Draft")).scalar_one()
        out["orders"] = {"to_invoice": to_invoice, "drafts": drafts}

    if context.has_permission("sales.quotation.read"):
        sent = db.execute(select(func.count(), func.coalesce(func.sum(Quotation.total), 0)).where(
            *mine(Quotation), Quotation.status == "Sent",
            (Quotation.valid_until.is_(None)) | (Quotation.valid_until >= day),
        )).one()
        out["quotations"] = {"awaiting_reply": sent[0], "awaiting_value": float(Decimal(str(sent[1])))}
    return out
