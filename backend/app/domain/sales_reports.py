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
from app.domain import tax
from app.domain.errors import ConflictError
from app.models.documents import CreditNote, Invoice

B2CL_LIMIT = Decimal("100000")
UQC = {
    "box": "BOX", "boxes": "BOX", "nos": "NOS", "no": "NOS", "pcs": "PCS", "pc": "PCS", "piece": "PCS",
    "pieces": "PCS", "kg": "KGS", "kgs": "KGS", "g": "GMS", "gm": "GMS", "ltr": "LTR", "l": "LTR", "litre": "LTR",
    "m": "MTR", "mtr": "MTR", "metre": "MTR", "sqm": "SQM", "sqft": "SQF", "set": "SET", "sets": "SET",
    "pair": "PRS", "roll": "ROL", "bag": "BAG", "dozen": "DOZ", "ton": "TON", "tonne": "TON", "can": "CAN",
    "bottle": "BTL", "pack": "PAC", "carton": "CTN", "unit": "UNT", "units": "UNT",
}
SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn", "docs")


def uqc(uom: str) -> str:
    return UQC.get((uom or "").strip().lower(), "OTH")


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


def sales_register(db: Session, context: RequestContext, date_from: date, date_to: date) -> dict:
    _period(date_from, date_to)
    invoices, notes = _documents(db, context, date_from, date_to)
    rows = [{
        "date": i.invoice_date, "type": "Invoice", "number": i.number, "customer": i.buyer_name,
        "gstin": i.buyer_gstin, "place_of_supply": _pos(i.place_of_supply), "taxable_value": _f(i.total),
        "cgst": _f(i.cgst), "sgst": _f(i.sgst), "igst": _f(i.igst), "round_off": _f(i.round_off),
        "total": _f(i.grand_total), "id": i.id,
    } for i in invoices] + [{
        "date": n.note_date, "type": "Credit note", "number": n.number, "customer": n.invoice.buyer_name,
        "gstin": n.invoice.buyer_gstin, "place_of_supply": _pos(n.invoice.place_of_supply),
        "taxable_value": -_f(n.total), "cgst": -_f(n.cgst), "sgst": -_f(n.sgst), "igst": -_f(n.igst),
        "round_off": -_f(n.round_off), "total": -_f(n.grand_total), "id": n.id,
    } for n in notes]
    rows.sort(key=lambda r: (r["date"], r["type"], r["number"]))
    keys = ("taxable_value", "cgst", "sgst", "igst", "round_off", "total")
    totals = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    return {"date_from": date_from, "date_to": date_to, "rows": rows, "totals": totals,
            "invoices": len(invoices), "credit_notes": len(notes)}


def gstr1(db: Session, context: RequestContext, date_from: date, date_to: date) -> dict:
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


COLUMNS = {
    "register": [("date", "Date"), ("type", "Type"), ("number", "Number"), ("customer", "Customer"),
                 ("gstin", "GSTIN"), ("place_of_supply", "Place of supply"), ("taxable_value", "Taxable value"),
                 ("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST"), ("round_off", "Round off"),
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
