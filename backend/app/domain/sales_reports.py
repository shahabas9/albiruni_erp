"""Sales reports for the accountant: a sales register and a GSTR-1 summary.

Both read issued invoices and credit notes dated in a period. GSTR-1 sections
follow the GST portal's tables:
- b2b: invoices to registered buyers, one row per invoice and tax rate.
- b2cl: invoices to unregistered buyers in another state worth more than
  ₹1,00,000 (the limit since August 2024).
- b2cs: all other sales to unregistered buyers, totalled by place of supply
  and rate (their credit notes are netted in here).
- cdnr / cdnur: credit notes to registered buyers / against B2CL invoices.
- hsn: quantities and values per HSN code and rate, split B2B and B2C.
- docs: the first and last number of each document series used.

These are figures to file from, not a filing: check them before uploading.
"""

import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import RequestContext
from app.domain import regimes, tax
from app.domain.errors import ConflictError
from app.domain.gst_portal import uqc
from app.models.documents import CreditNote, Invoice
from app.models.tenant import Company

B2CL_LIMIT = Decimal("100000")
SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn", "docs")


def _pos(code: str) -> str:
    return f"{code}-{tax.state_name(code)}" if code else ""


def _period(date_from: date, date_to: date) -> None:
    if date_from > date_to:
        raise ConflictError("The start date is after the end date.")
    if (date_to - date_from).days > 400:
        raise ConflictError("Reports cover at most a year at a time.")


def _documents(db: Session, context: RequestContext, date_from: date, date_to: date):
    invoices = db.execute(
        select(Invoice).options(selectinload(Invoice.lines))
        .where(Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
               Invoice.status == "Issued", Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        .order_by(Invoice.invoice_date, Invoice.number)
    ).scalars().all()
    notes = db.execute(
        select(CreditNote).options(selectinload(CreditNote.lines), selectinload(CreditNote.invoice))
        .where(CreditNote.tenant_id == context.tenant_id, CreditNote.company_id == context.company_id,
               CreditNote.note_date >= date_from, CreditNote.note_date <= date_to)
        .order_by(CreditNote.note_date, CreditNote.number)
    ).scalars().all()
    return invoices, notes


def _is_b2cl(invoice: Invoice) -> bool:
    interstate = bool(invoice.seller_state) and invoice.place_of_supply != invoice.seller_state
    return not invoice.buyer_gstin and interstate and Decimal(str(invoice.grand_total)) > B2CL_LIMIT


def _by_rate(lines) -> dict[float, dict[str, Decimal]]:
    out: dict[float, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for l in lines:
        row = out[float(l.gst_rate)]
        for key in ("taxable_value", "cgst", "sgst", "igst"):
            row[key] += Decimal(str(getattr(l, key)))
    return out


def _f(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def india_only(db: Session, context: RequestContext, what: str) -> None:
    if regimes.of(db.get(Company, context.company_id)).country != "IN":
        raise ConflictError(f"{what} is an Indian GST return — this company is registered in another country.")


def sales_register(db: Session, context: RequestContext, date_from: date, date_to: date) -> dict:
    _period(date_from, date_to)
    invoices, notes = _documents(db, context, date_from, date_to)
    rows = [{
        "date": i.invoice_date, "type": "Invoice", "number": i.number, "customer": i.buyer_name,
        "gstin": i.buyer_gstin, "place_of_supply": _pos(i.place_of_supply), "taxable_value": _f(i.total),
        "cgst": _f(i.cgst), "sgst": _f(i.sgst), "igst": _f(i.igst), "vat": _f(i.vat),
        "vat_number": i.buyer_vat_number or "", "round_off": _f(i.round_off), "total": _f(i.grand_total), "id": i.id,
    } for i in invoices] + [{
        "date": n.note_date, "type": "Credit note", "number": n.number, "customer": n.invoice.buyer_name,
        "gstin": n.invoice.buyer_gstin, "place_of_supply": _pos(n.invoice.place_of_supply),
        "taxable_value": -_f(n.total), "cgst": -_f(n.cgst), "sgst": -_f(n.sgst), "igst": -_f(n.igst),
        "vat": -_f(n.vat), "vat_number": n.invoice.buyer_vat_number or "", "round_off": -_f(n.round_off),
        "total": -_f(n.grand_total), "id": n.id,
    } for n in notes]
    rows.sort(key=lambda r: (r["date"], r["type"], r["number"]))
    keys = ("taxable_value", "cgst", "sgst", "igst", "vat", "round_off", "total")
    totals = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    return {"date_from": date_from, "date_to": date_to, "rows": rows, "totals": totals,
            "invoices": len(invoices), "credit_notes": len(notes)}


def gstr1(db: Session, context: RequestContext, date_from: date, date_to: date) -> dict:
    india_only(db, context, "GSTR-1")
    _period(date_from, date_to)
    invoices, notes = _documents(db, context, date_from, date_to)
    b2b, b2cl, cdnr, cdnur = [], [], [], []
    b2cs: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    hsn: dict[tuple, dict] = {}

    def add_hsn(kind: str, line, sign: int):
        key = (kind, line.hsn_code or "", float(line.gst_rate), uqc(line.uom))
        row = hsn.setdefault(key, {"type": kind, "hsn_code": key[1], "description": line.description,
                                   "uqc": key[3], "gst_rate": key[2], "qty": Decimal(0), "taxable_value": Decimal(0),
                                   "igst": Decimal(0), "cgst": Decimal(0), "sgst": Decimal(0)})
        row["qty"] += sign * Decimal(str(line.qty))
        for k in ("taxable_value", "igst", "cgst", "sgst"):
            row[k] += sign * Decimal(str(getattr(line, k)))

    for inv in invoices:
        registered = bool(inv.buyer_gstin)
        for line in inv.lines:
            add_hsn("B2B" if registered else "B2C", line, 1)
        for rate, sums in sorted(_by_rate(inv.lines).items()):
            base = {"invoice_number": inv.number, "invoice_date": inv.invoice_date,
                    "invoice_value": _f(inv.grand_total), "place_of_supply": _pos(inv.place_of_supply),
                    "rate": rate, "taxable_value": _f(sums["taxable_value"]), "igst": _f(sums["igst"]),
                    "cgst": _f(sums["cgst"]), "sgst": _f(sums["sgst"]), "cess": 0.0}
            if registered:
                b2b.append({"gstin": inv.buyer_gstin, "receiver_name": inv.buyer_name, **base,
                            "reverse_charge": "N", "invoice_type": "Regular B2B"})
            elif _is_b2cl(inv):
                b2cl.append(base)
            else:
                row = b2cs[(inv.place_of_supply, rate)]
                for k in ("taxable_value", "igst", "cgst", "sgst"):
                    row[k] += sums[k]

    for note in notes:
        inv = note.invoice
        registered = bool(inv.buyer_gstin)
        for line in note.lines:
            add_hsn("B2B" if registered else "B2C", line, -1)
        for rate, sums in sorted(_by_rate(note.lines).items()):
            base = {"note_number": note.number, "note_date": note.note_date, "note_type": "C",
                    "note_value": _f(note.grand_total), "place_of_supply": _pos(inv.place_of_supply), "rate": rate,
                    "taxable_value": _f(sums["taxable_value"]), "igst": _f(sums["igst"]), "cgst": _f(sums["cgst"]),
                    "sgst": _f(sums["sgst"]), "cess": 0.0, "invoice_number": inv.number,
                    "invoice_date": inv.invoice_date}
            if registered:
                cdnr.append({"gstin": inv.buyer_gstin, "receiver_name": inv.buyer_name, **base,
                             "reverse_charge": "N"})
            elif _is_b2cl(inv):
                cdnur.append({"ur_type": "B2CL", **base})
            else:
                row = b2cs[(inv.place_of_supply, rate)]
                for k in ("taxable_value", "igst", "cgst", "sgst"):
                    row[k] -= sums[k]

    b2cs_rows = [{"type": "OE", "place_of_supply": _pos(pos), "rate": rate, **{k: _f(v) for k, v in sums.items()},
                  "cess": 0.0} for (pos, rate), sums in sorted(b2cs.items())]
    hsn_rows = [{**r, **{k: _f(r[k]) for k in ("qty", "taxable_value", "igst", "cgst", "sgst")}}
                for r in sorted(hsn.values(), key=lambda r: (r["type"], r["hsn_code"], r["gst_rate"]))]
    docs = []
    for label, numbers in (("Invoices for outward supply", [i.number for i in invoices]),
                           ("Credit notes", [n.number for n in notes])):
        if numbers:
            docs.append({"nature": label, "from": min(numbers), "to": max(numbers), "total": len(numbers),
                         "cancelled": 0, "net_issued": len(numbers)})

    summary = {
        name: {"count": len(rows), "taxable_value": round(sum(r.get("taxable_value", 0) for r in rows), 2),
               "tax": round(sum(r.get("igst", 0) + r.get("cgst", 0) + r.get("sgst", 0) for r in rows), 2)}
        for name, rows in (("b2b", b2b), ("b2cl", b2cl), ("b2cs", b2cs_rows), ("cdnr", cdnr), ("cdnur", cdnur),
                           ("hsn", hsn_rows))
    }
    summary["docs"] = {"count": len(docs), "taxable_value": 0, "tax": 0}
    return {"date_from": date_from, "date_to": date_to, "summary": summary, "b2b": b2b, "b2cl": b2cl,
            "b2cs": b2cs_rows, "cdnr": cdnr, "cdnur": cdnur, "hsn": hsn_rows, "docs": docs}


def tds_report(db: Session, context: RequestContext, date_from: date, date_to: date) -> dict:
    """TDS customers deducted on payments dated in the period, one row per invoice, to
    reconcile with Form 26AS and chase missing TDS certificates (Form 16A)."""

    from app.models.documents import Receipt, ReceiptAllocation
    from app.models.sales import Customer

    india_only(db, context, "The TDS report")
    _period(date_from, date_to)
    rows = db.execute(
        select(ReceiptAllocation, Receipt, Invoice, Customer)
        .join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
        .join(Invoice, Invoice.id == ReceiptAllocation.invoice_id)
        .join(Customer, Customer.id == Receipt.customer_id)
        .where(Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
               Receipt.status == "Received", ReceiptAllocation.tds_amount > 0,
               Receipt.receipt_date >= date_from, Receipt.receipt_date <= date_to)
        .order_by(Receipt.receipt_date, Receipt.number)
    ).all()
    out = [{
        "date": r.receipt_date, "receipt_number": r.number, "receipt_id": r.id, "customer": c.name,
        # A GSTIN's characters 3–12 are the holder's PAN, which the TDS return quotes.
        "customer_pan": (c.gstin or "")[2:12], "section": r.tds_section, "invoice_number": i.number,
        "invoice_value": _f(i.grand_total), "amount_received": _f(a.amount), "tds_amount": _f(a.tds_amount),
        "certificate_received": "Yes" if r.tds_certificate_received else "No",
    } for a, r, i, c in rows]
    missing = round(sum(row["tds_amount"] for row in out if row["certificate_received"] == "No"), 2)
    return {"date_from": date_from, "date_to": date_to, "rows": out,
            "total_tds": round(sum(row["tds_amount"] for row in out), 2), "certificates_missing": missing}


COLUMNS = {
    "register": [("date", "Date"), ("type", "Type"), ("number", "Number"), ("customer", "Customer"),
                 ("gstin", "GSTIN"), ("place_of_supply", "Place of supply"), ("taxable_value", "Taxable value"),
                 ("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST"), ("round_off", "Round off"),
                 ("total", "Total")],
    # Saudi Arabia: one VAT column, the buyer's VAT number.
    "register_vat": [("date", "Date"), ("type", "Type"), ("number", "Number"), ("customer", "Customer"),
                     ("vat_number", "VAT number"), ("taxable_value", "Taxable value"), ("vat", "VAT"),
                     ("total", "Total")],
    "b2b": [("gstin", "GSTIN/UIN of Recipient"), ("receiver_name", "Receiver Name"),
            ("invoice_number", "Invoice Number"), ("invoice_date", "Invoice date"),
            ("invoice_value", "Invoice Value"), ("place_of_supply", "Place Of Supply"),
            ("reverse_charge", "Reverse Charge"), ("invoice_type", "Invoice Type"), ("rate", "Rate"),
            ("taxable_value", "Taxable Value"), ("igst", "Integrated Tax"), ("cgst", "Central Tax"),
            ("sgst", "State/UT Tax"), ("cess", "Cess Amount")],
    "b2cl": [("invoice_number", "Invoice Number"), ("invoice_date", "Invoice date"),
             ("invoice_value", "Invoice Value"), ("place_of_supply", "Place Of Supply"), ("rate", "Rate"),
             ("taxable_value", "Taxable Value"), ("igst", "Integrated Tax"), ("cess", "Cess Amount")],
    "b2cs": [("type", "Type"), ("place_of_supply", "Place Of Supply"), ("rate", "Rate"),
             ("taxable_value", "Taxable Value"), ("igst", "Integrated Tax"), ("cgst", "Central Tax"),
             ("sgst", "State/UT Tax"), ("cess", "Cess Amount")],
    "cdnr": [("gstin", "GSTIN/UIN of Recipient"), ("receiver_name", "Receiver Name"),
             ("note_number", "Note Number"), ("note_date", "Note Date"), ("note_type", "Note Type"),
             ("place_of_supply", "Place Of Supply"), ("reverse_charge", "Reverse Charge"),
             ("note_value", "Note Value"), ("rate", "Rate"), ("taxable_value", "Taxable Value"),
             ("igst", "Integrated Tax"), ("cgst", "Central Tax"), ("sgst", "State/UT Tax"), ("cess", "Cess Amount"),
             ("invoice_number", "Original Invoice Number"), ("invoice_date", "Original Invoice Date")],
    "cdnur": [("ur_type", "UR Type"), ("note_number", "Note Number"), ("note_date", "Note Date"),
              ("note_type", "Note Type"), ("place_of_supply", "Place Of Supply"), ("note_value", "Note Value"),
              ("rate", "Rate"), ("taxable_value", "Taxable Value"), ("igst", "Integrated Tax"),
              ("cess", "Cess Amount"), ("invoice_number", "Original Invoice Number"),
              ("invoice_date", "Original Invoice Date")],
    "hsn": [("type", "B2B/B2C"), ("hsn_code", "HSN"), ("description", "Description"), ("uqc", "UQC"),
            ("qty", "Total Quantity"), ("gst_rate", "Rate"), ("taxable_value", "Taxable Value"),
            ("igst", "Integrated Tax Amount"), ("cgst", "Central Tax Amount"), ("sgst", "State/UT Tax Amount")],
    "tds": [("date", "Payment date"), ("receipt_number", "Receipt"), ("customer", "Customer"),
            ("customer_pan", "Customer PAN"), ("section", "Section"), ("invoice_number", "Invoice"),
            ("invoice_value", "Invoice value"), ("amount_received", "Received"), ("tds_amount", "TDS deducted"),
            ("certificate_received", "Form 16A received")],
    "docs": [("nature", "Nature of Document"), ("from", "Sr. No. From"), ("to", "Sr. No. To"),
             ("total", "Total Number"), ("cancelled", "Cancelled"), ("net_issued", "Net Issued")],
}


def _cell(value, key: str = "") -> str:
    if isinstance(value, date):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, float):
        return f"{value:g}" if key in ("rate", "gst_rate", "qty") else f"{value:.2f}"
    text = "" if value is None else str(value)
    # Spreadsheets run cells starting with these as formulas.
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not _number(text) else text


def _number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def to_csv(kind: str, rows: list[dict]) -> str:
    columns = COLUMNS[kind]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([_cell(row.get(key), key) for key, _ in columns])
    return "﻿" + out.getvalue()
