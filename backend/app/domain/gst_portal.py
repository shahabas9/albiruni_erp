"""e-Invoice and e-way bill JSON, in the government portals' upload formats.

Nothing here talks to the portals: the JSON is downloaded and uploaded
(the NIC e-invoice offline tool or a GST Suvidha Provider, the e-way bill
portal's bulk upload), and the IRN / e-way bill number that comes back is
recorded on the invoice so it prints. A GSP integration can later send the
same payloads directly.

- e-Invoice: NIC schema 1.1 (INV-01) for B2B invoices and credit notes.
  Unregistered buyers (B2C) don't get e-invoices.
- e-Way bill: the portal's bulk JSON, one bill per invoice, needed when goods
  worth more than ₹50,000 move.

Both builders return (payload, problems): problems are what the portal would
reject (a missing PIN code, a buyer without a GSTIN…), to fix before uploading.
"""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import history, tax
from app.domain.errors import ConflictError
from app.models.documents import CreditNote, DeliveryNote, Invoice

EWAY_LIMIT = Decimal("50000")
# Unit quantity codes (UQC) the portals accept, from the units people type.
UQC = {
    "box": "BOX", "boxes": "BOX", "nos": "NOS", "no": "NOS", "unit": "UNT", "units": "UNT", "pcs": "PCS",
    "pc": "PCS", "piece": "PCS", "pieces": "PCS", "kg": "KGS", "kgs": "KGS", "g": "GMS", "gm": "GMS", "gms": "GMS",
    "ltr": "LTR", "l": "LTR", "litre": "LTR", "liter": "LTR", "ml": "MLT", "m": "MTR", "mtr": "MTR", "metre": "MTR",
    "sqm": "SQM", "sqft": "SQF", "set": "SET", "sets": "SET", "pair": "PRS", "pairs": "PRS", "dozen": "DOZ",
    "doz": "DOZ", "bag": "BAG", "bags": "BAG", "roll": "ROL", "rolls": "ROL", "ton": "TON", "tonne": "TON",
    "carton": "CTN", "ctn": "CTN", "packet": "PAC", "pack": "PAC", "bottle": "BTL", "can": "CAN", "drum": "DRM",
    "hour": "OTH", "hr": "OTH", "job": "OTH", "service": "OTH",
}
PIN = re.compile(r"\b([1-9]\d{5})\b")


def uqc(uom: str) -> str:
    return UQC.get((uom or "").strip().lower().rstrip("."), "OTH")


def split_address(address: str, state_code: str) -> dict:
    """Address lines, place and PIN code from free-text address."""

    lines = [l.strip(" ,") for l in (address or "").replace(",", "\n").splitlines() if l.strip(" ,")]
    pin = None
    place = ""
    for line in reversed(lines):
        found = PIN.search(line)
        if found:
            pin = int(found.group(1))
            place = PIN.sub("", line).strip(" -,")
            break
    lines = [l for l in lines if not PIN.fullmatch(l)]
    place = place or (lines[-1] if len(lines) > 1 else "") or tax.state_name(state_code)
    addr1 = lines[0] if lines else ""
    addr2 = ", ".join(lines[1:])[:100] if len(lines) > 1 else ""
    return {"addr1": addr1[:100], "addr2": addr2, "place": place[:50], "pin": pin}


def _money(v) -> float:
    return float(tax.money(v))


def _dmy(day: date) -> str:
    return f"{day:%d/%m/%Y}"


def _party(name, gstin, address, state, problems: list[str], who: str, pos: str | None = None) -> dict:
    parts = split_address(address, state)
    if not gstin:
        problems.append(f"The {who} has no GSTIN — e-invoices are only for registered buyers (B2B).")
    if not parts["pin"]:
        problems.append(f"Add a 6-digit PIN code to the {who}'s address.")
    if len(parts["addr1"]) < 3:
        problems.append(f"The {who}'s address is missing.")
    out = {"Gstin": gstin or "URP", "LglNm": name[:100], "Addr1": parts["addr1"] or "-", "Loc": parts["place"] or "-",
           "Pin": parts["pin"] or 0, "Stcd": state or ""}
    if parts["addr2"]:
        out["Addr2"] = parts["addr2"]
    if pos is not None:
        out["Pos"] = pos
    return out


def einvoice_for_invoice(invoice: Invoice) -> tuple[dict, list[str]]:
    if invoice.status != "Issued":
        raise ConflictError("Issue the invoice first.")
    problems: list[str] = []
    interstate = invoice.igst > 0 or (invoice.buyer_state and invoice.buyer_state != invoice.seller_state)
    items = []
    for i, l in enumerate(invoice.lines, 1):
        amount = Decimal(str(l.amount))
        taxable = Decimal(str(l.taxable_value))
        if not l.hsn_code:
            problems.append(f"Line {i} ({l.description}) has no HSN/SAC code.")
        items.append({
            "SlNo": str(i), "PrdDesc": l.description[:300], "IsServc": "Y" if (l.hsn_code or "").startswith("99") else "N",
            "HsnCd": l.hsn_code or "", "Qty": float(l.qty), "Unit": uqc(l.uom), "UnitPrice": _money(l.unit_price),
            "TotAmt": _money(amount), "Discount": _money(amount - taxable), "AssAmt": _money(taxable),
            "GstRt": float(l.gst_rate), "IgstAmt": _money(l.igst), "CgstAmt": _money(l.cgst), "SgstAmt": _money(l.sgst),
            "TotItemVal": _money(taxable + Decimal(str(l.cgst)) + Decimal(str(l.sgst)) + Decimal(str(l.igst))),
        })
    payload = {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N", "IgstOnIntra": "N"},
        "DocDtls": {"Typ": "INV", "No": invoice.number, "Dt": _dmy(invoice.invoice_date)},
        "SellerDtls": _party(invoice.seller_name, invoice.seller_gstin, invoice.seller_address, invoice.seller_state,
                             problems, "seller"),
        "BuyerDtls": _party(invoice.buyer_name, invoice.buyer_gstin, invoice.billing_address, invoice.buyer_state,
                            problems, "buyer", pos=invoice.place_of_supply),
        "ItemList": items,
        "ValDtls": {"AssVal": _money(invoice.total), "CgstVal": _money(invoice.cgst), "SgstVal": _money(invoice.sgst),
                    "IgstVal": _money(invoice.igst), "RndOffAmt": _money(invoice.round_off),
                    "TotInvVal": _money(invoice.grand_total)},
    }
    if not invoice.seller_gstin:
        problems.append("Your company's GSTIN isn't set (Sales → Company & GST).")
    if interstate and invoice.igst == 0 and invoice.total > 0:
        problems.append("Interstate supply without IGST — check the place of supply.")
    return payload, list(dict.fromkeys(problems))


def einvoice_for_credit_note(note: CreditNote) -> tuple[dict, list[str]]:
    invoice = note.invoice
    payload, problems = einvoice_for_invoice(invoice)
    items = []
    for i, l in enumerate(note.lines, 1):
        taxable = Decimal(str(l.taxable_value))
        qty = Decimal(str(l.qty or 0))
        items.append({
            "SlNo": str(i), "PrdDesc": l.description[:300], "IsServc": "Y" if (l.hsn_code or "").startswith("99") else "N",
            "HsnCd": l.hsn_code or "", "Qty": float(qty), "Unit": uqc(l.uom),
            "UnitPrice": _money(taxable / qty) if qty else _money(taxable), "TotAmt": _money(taxable), "Discount": 0,
            "AssAmt": _money(taxable), "GstRt": float(l.gst_rate), "IgstAmt": _money(l.igst), "CgstAmt": _money(l.cgst),
            "SgstAmt": _money(l.sgst),
            "TotItemVal": _money(taxable + Decimal(str(l.cgst)) + Decimal(str(l.sgst)) + Decimal(str(l.igst))),
        })
    payload["DocDtls"] = {"Typ": "CRN", "No": note.number, "Dt": _dmy(note.note_date)}
    payload["ItemList"] = items
    payload["ValDtls"] = {"AssVal": _money(note.total), "CgstVal": _money(note.cgst), "SgstVal": _money(note.sgst),
                          "IgstVal": _money(note.igst), "RndOffAmt": _money(note.round_off),
                          "TotInvVal": _money(note.grand_total)}
    payload["RefDtls"] = {"PrecDocDtls": [{"InvNo": invoice.number, "InvDt": _dmy(invoice.invoice_date)}]}
    return payload, problems


def eway_bill(db: Session, context: RequestContext, invoice: Invoice, *, distance_km: int = 0, vehicle_no: str = "",
              transporter_id: str = "", transporter_name: str = "") -> tuple[dict, list[str]]:
    if invoice.status != "Issued":
        raise ConflictError("Issue the invoice first.")
    problems: list[str] = []
    delivery = db.execute(select(DeliveryNote).where(
        DeliveryNote.order_id == invoice.order_id, DeliveryNote.status != "Cancelled",
    ).order_by(DeliveryNote.delivery_date.desc(), DeliveryNote.created_at.desc()).limit(1)).scalar_one_or_none()
    vehicle = (vehicle_no or (delivery.vehicle_no if delivery else "")).replace(" ", "").replace("-", "").upper()
    transporter_name = transporter_name or (delivery.transporter if delivery else "")
    goods = [l for l in invoice.lines if not (l.hsn_code or "").startswith("99")]
    if not goods:
        problems.append("Only services on this invoice — no e-way bill is needed.")
    if Decimal(str(invoice.grand_total)) <= EWAY_LIMIT:
        problems.append("Below ₹50,000 — an e-way bill isn't required (some states set other limits).")
    if not vehicle and not transporter_id:
        problems.append("Enter the vehicle number, or the transporter's GSTIN/ID for them to add it.")
    if not 1 <= distance_km <= 4000:
        problems.append("Enter the approximate distance in km (1–4000).")
    seller = split_address(invoice.seller_address, invoice.seller_state)
    buyer = split_address(invoice.shipping_address or invoice.billing_address, invoice.buyer_state)
    for who, parts in (("your company", seller), ("delivery", buyer)):
        if not parts["pin"]:
            problems.append(f"Add a 6-digit PIN code to the {who} address.")
    interstate = invoice.igst > 0
    bill = {
        "userGstin": invoice.seller_gstin, "supplyType": "O", "subSupplyType": 1, "subSupplyDesc": "",
        "docType": "INV", "docNo": invoice.number, "docDate": _dmy(invoice.invoice_date),
        "fromGstin": invoice.seller_gstin, "fromTrdName": invoice.seller_name, "fromAddr1": seller["addr1"],
        "fromAddr2": seller["addr2"], "fromPlace": seller["place"], "fromPincode": seller["pin"] or 0,
        "fromStateCode": int(invoice.seller_state or 0), "actFromStateCode": int(invoice.seller_state or 0),
        "toGstin": invoice.buyer_gstin or "URP", "toTrdName": invoice.buyer_name, "toAddr1": buyer["addr1"],
        "toAddr2": buyer["addr2"], "toPlace": buyer["place"], "toPincode": buyer["pin"] or 0,
        "toStateCode": int(invoice.place_of_supply or invoice.buyer_state or 0),
        "actToStateCode": int(invoice.buyer_state or invoice.place_of_supply or 0),
        "transactionType": 1, "otherValue": _money(invoice.round_off),
        "totalValue": _money(sum((Decimal(str(l.taxable_value)) for l in goods), Decimal(0))),
        "cgstValue": _money(sum((Decimal(str(l.cgst)) for l in goods), Decimal(0))),
        "sgstValue": _money(sum((Decimal(str(l.sgst)) for l in goods), Decimal(0))),
        "igstValue": _money(sum((Decimal(str(l.igst)) for l in goods), Decimal(0))),
        "cessValue": 0, "cessNonAdvolValue": 0, "totInvValue": _money(invoice.grand_total),
        "transMode": "1" if vehicle else "", "transDistance": str(distance_km or 0),
        "transporterId": transporter_id.strip().upper(), "transporterName": transporter_name[:100],
        "transDocNo": "", "transDocDate": "", "vehicleNo": vehicle, "vehicleType": "R" if vehicle else "",
        "itemList": [{
            "itemNo": i, "productName": l.description[:100], "productDesc": l.description[:100],
            "hsnCode": int(l.hsn_code) if (l.hsn_code or "").isdigit() else 0, "quantity": float(l.qty),
            "qtyUnit": uqc(l.uom), "taxableAmount": _money(l.taxable_value),
            "sgstRate": 0 if interstate else float(l.gst_rate) / 2, "cgstRate": 0 if interstate else float(l.gst_rate) / 2,
            "igstRate": float(l.gst_rate) if interstate else 0, "cessRate": 0,
        } for i, l in enumerate(goods, 1)],
    }
    return {"version": "1.0.0621", "billLists": [bill]}, problems


def record_references(db: Session, context: RequestContext, invoice: Invoice, *, irn: str | None = None,
                      irn_ack_no: str | None = None, irn_ack_date: date | None = None, eway_bill_no: str | None = None,
                      eway_bill_date: date | None = None) -> Invoice:
    """The IRN and acknowledgement from the e-invoice portal, and the e-way bill number, as sent back."""

    if invoice.status != "Issued":
        raise ConflictError("Issue the invoice first.")
    changes = []
    if irn is not None:
        irn = irn.strip().lower()
        if irn and not re.fullmatch(r"[0-9a-f]{64}", irn):
            raise ConflictError("An IRN is 64 letters and digits (0-9, a-f).")
        invoice.irn = irn
        changes.append(f"IRN {irn[:12]}…" if irn else "IRN cleared")
    if irn_ack_no is not None:
        invoice.irn_ack_no = irn_ack_no.strip()[:20]
    if irn_ack_date is not None:
        invoice.irn_ack_date = irn_ack_date
    if eway_bill_no is not None:
        number = eway_bill_no.replace(" ", "")
        if number and not re.fullmatch(r"\d{12}", number):
            raise ConflictError("An e-way bill number is 12 digits.")
        invoice.eway_bill_no = number
        changes.append(f"e-way bill {number}" if number else "e-way bill cleared")
    if eway_bill_date is not None:
        invoice.eway_bill_date = eway_bill_date
    if changes:
        history.record(db, context, "invoice", invoice.id, "gst_portal", "Recorded " + ", ".join(changes))
    db.commit()
    return invoice
