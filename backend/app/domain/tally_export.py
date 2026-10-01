"""Tally XML: the period's sales, credit notes, receipts and refunds as
vouchers TallyPrime (or Tally.ERP 9) imports — Gateway of Tally → Import →
Transactions.

Customers become ledgers under Sundry Debtors (created if missing, with their
GSTIN and state). The other ledgers must already exist in Tally with these
names — the usual ones in a GST-enabled company:

  Sales, Output CGST, Output SGST, Output IGST, Round Off, Cash, Bank,
  TDS Receivable

Tally's sign convention: debits are negative amounts with
ISDEEMEDPOSITIVE=Yes, credits positive with No. Every voucher balances to
zero. Voided payments and refunds are left out.
"""

from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import tax
from app.domain.sales_reports import _documents, _period
from app.models.documents import Receipt, Refund
from app.models.sales import Customer
from app.models.tenant import Company

LEDGERS = {
    "sales": "Sales", "cgst": "Output CGST", "sgst": "Output SGST", "igst": "Output IGST", "round_off": "Round Off",
    "cash": "Cash", "bank": "Bank", "tds": "TDS Receivable",
}
ZERO = Decimal("0.00")


def _d(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(ZERO)


def _x(text) -> str:
    return escape(str(text or ""))


def _day(day: date) -> str:
    return f"{day:%Y%m%d}"


def _entry(ledger: str, amount: Decimal) -> str:
    """amount > 0 is a credit, < 0 a debit (Tally's own convention)."""

    return (f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{_x(ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'Yes' if amount < 0 else 'No'}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{amount:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")


def _voucher(kind: str, number: str, day: date, party: str, narration: str, entries: list[tuple[str, Decimal]],
             reference: str = "") -> str:
    entries = [(ledger, amount) for ledger, amount in entries if amount != 0]
    if sum((a for _, a in entries), ZERO) != 0:
        raise ValueError(f"{number} doesn't balance")
    return (
        f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="{kind}" ACTION="Create">'
        f"<DATE>{_day(day)}</DATE><VOUCHERTYPENAME>{kind}</VOUCHERTYPENAME>"
        f"<VOUCHERNUMBER>{_x(number)}</VOUCHERNUMBER><REFERENCE>{_x(reference or number)}</REFERENCE>"
        f"<PARTYLEDGERNAME>{_x(party)}</PARTYLEDGERNAME><NARRATION>{_x(narration)}</NARRATION>"
        f"<PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>"
        + "".join(_entry(l, a) for l, a in entries)
        + "</VOUCHER></TALLYMESSAGE>"
    )


def _ledger(customer: Customer) -> str:
    state = tax.state_name(customer.state_code or "")
    return (
        f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{_x(customer.name)}" ACTION="Create">'
        f"<NAME.LIST><NAME>{_x(customer.name)}</NAME></NAME.LIST><PARENT>Sundry Debtors</PARENT>"
        f"<ISBILLWISEON>Yes</ISBILLWISEON>"
        + (f"<PARTYGSTIN>{_x(customer.gstin)}</PARTYGSTIN><GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>"
           if customer.gstin else "<GSTREGISTRATIONTYPE>Unregistered</GSTREGISTRATIONTYPE>")
        + (f"<LEDSTATENAME>{_x(state)}</LEDSTATENAME>" if state else "")
        + (f"<ADDRESS.LIST><ADDRESS>{_x(customer.billing_address)}</ADDRESS></ADDRESS.LIST>"
           if customer.billing_address else "")
        + "</LEDGER></TALLYMESSAGE>"
    )


def build(db: Session, context: RequestContext, date_from: date, date_to: date) -> tuple[str, dict]:
    """(XML text, counts per voucher type)."""

    _period(date_from, date_to)
    company = db.get(Company, context.company_id)
    invoices, notes = _documents(db, context, date_from, date_to)
    receipts = db.execute(select(Receipt).options(selectinload(Receipt.customer)).where(
        Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
        Receipt.status == "Received", Receipt.receipt_date >= date_from, Receipt.receipt_date <= date_to,
    ).order_by(Receipt.receipt_date, Receipt.number)).scalars().all()
    refunds = db.execute(select(Refund).options(selectinload(Refund.customer)).where(
        Refund.tenant_id == context.tenant_id, Refund.company_id == context.company_id, Refund.status == "Paid",
        Refund.refund_date >= date_from, Refund.refund_date <= date_to,
    ).order_by(Refund.refund_date, Refund.number)).scalars().all()

    customer_ids = ({i.customer_id for i in invoices} | {n.customer_id for n in notes}
                    | {r.customer_id for r in receipts} | {f.customer_id for f in refunds})
    customers = {c.id: c for c in db.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars()}
    name = lambda customer_id: customers[customer_id].name  # noqa: E731
    money_ledger = lambda mode: LEDGERS["cash"] if mode == "Cash" else LEDGERS["bank"]  # noqa: E731

    messages = [_ledger(c) for c in sorted(customers.values(), key=lambda c: c.name)]
    for inv in invoices:
        messages.append(_voucher("Sales", inv.number, inv.invoice_date, name(inv.customer_id),
                                 f"Order {inv.order.number if inv.order else ''} · due {inv.due_date:%d-%m-%Y}".strip(), [
            (name(inv.customer_id), -_d(inv.grand_total)), (LEDGERS["sales"], _d(inv.total)),
            (LEDGERS["cgst"], _d(inv.cgst)), (LEDGERS["sgst"], _d(inv.sgst)), (LEDGERS["igst"], _d(inv.igst)),
            (LEDGERS["round_off"], _d(inv.round_off)),
        ]))
    for note in notes:
        messages.append(_voucher("Credit Note", note.number, note.note_date, name(note.customer_id),
                                 f"{note.kind} against {note.invoice.number}: {note.reason}", [
            (name(note.customer_id), _d(note.grand_total)), (LEDGERS["sales"], -_d(note.total)),
            (LEDGERS["cgst"], -_d(note.cgst)), (LEDGERS["sgst"], -_d(note.sgst)), (LEDGERS["igst"], -_d(note.igst)),
            (LEDGERS["round_off"], -_d(note.round_off)),
        ], reference=note.invoice.number))
    for r in receipts:
        tds = _d(r.tds_amount)
        messages.append(_voucher("Receipt", r.number, r.receipt_date, name(r.customer_id),
                                 f"{r.mode} {r.reference}".strip() + (f" · TDS {r.tds_section}" if tds else ""), [
            (money_ledger(r.mode), -_d(r.amount)), (LEDGERS["tds"], -tds), (name(r.customer_id), _d(r.amount) + tds),
        ], reference=r.reference))
    for f in refunds:
        messages.append(_voucher("Payment", f.number, f.refund_date, name(f.customer_id),
                                 f"Refund: {f.reason}", [
            (name(f.customer_id), -_d(f.amount)), (money_ledger(f.mode), _d(f.amount)),
        ], reference=f.reference))

    xml = (
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
        "<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES>"
        f"<SVCURRENTCOMPANY>{_x(company.legal_name or company.name)}</SVCURRENTCOMPANY>"
        "</STATICVARIABLES></REQUESTDESC><REQUESTDATA>"
        + "\n".join(messages)
        + "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>\n"
    )
    counts = {"ledgers": len(customers), "sales": len(invoices), "credit_notes": len(notes),
              "receipts": len(receipts), "refunds": len(refunds)}
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml, counts
