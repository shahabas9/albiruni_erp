"""ZATCA (FATOORA) e-invoicing for companies registered in Saudi Arabia.

- **QR code** — every Saudi tax invoice and credit note carries one: the
  seller's name, VAT number, the time it was issued, the total with VAT and
  the VAT, as TLV (tag, length, value) bytes in base64. Printed on the
  invoice and the shared copy.
- **UBL 2.1 XML** in ZATCA's profile, for standard (B2B, cleared by ZATCA
  before it reaches the buyer) and simplified (B2C, reported within 24 hours)
  invoices, and credit notes (type 381, referring to the invoice).

What isn't here yet, and needs the company onboarded with ZATCA (a CSID
certificate): the cryptographic stamp, the invoice counter (ICV) and hash
chain (PIH), and sending the XML to ZATCA's clearance/reporting API. The XML
is built so those can be added without changing anything else.
"""

import base64
from datetime import datetime, timezone
from decimal import Decimal
from xml.sax.saxutils import escape

import segno

from app.domain import regimes
from app.domain.gst_portal import uqc
from app.models.documents import CreditNote, Invoice
from app.models.tenant import Company

NS = ('xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
      'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
      'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
      'xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"')
TYPE_NAMES = {"standard": "0100000", "simplified": "0200000"}
NOT_YET = ("The cryptographic stamp, invoice counter (ICV) and previous-invoice hash (PIH) are added when the "
           "invoice is cleared or reported through ZATCA — that needs the company onboarded with ZATCA (a CSID).")


def _tlv(tag: int, value: str) -> bytes:
    data = value.encode("utf-8")
    return bytes([tag, len(data)]) + data


def _stamp(moment: datetime | None) -> str:
    moment = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def qr_text(seller_name: str, vat_number: str, moment: datetime | None, total, vat) -> str:
    """The base64 TLV string ZATCA's QR code holds (tags 1–5)."""

    payload = b"".join((_tlv(1, seller_name), _tlv(2, vat_number), _tlv(3, _stamp(moment)),
                        _tlv(4, f"{Decimal(str(total)):.2f}"), _tlv(5, f"{Decimal(str(vat)):.2f}")))
    return base64.b64encode(payload).decode("ascii")


def qr_svg(text: str) -> str:
    """The QR code as an SVG data URI, for printing."""

    return segno.make(text, error="m").svg_data_uri(scale=3, border=2)


def decode_qr(text: str) -> dict[int, str]:
    raw, out, i = base64.b64decode(text), {}, 0
    while i < len(raw):
        tag, length = raw[i], raw[i + 1]
        out[tag] = raw[i + 2:i + 2 + length].decode("utf-8")
        i += 2 + length
    return out


def invoice_qr(invoice: Invoice) -> str:
    return qr_text(invoice.seller_name, invoice.seller_vat_number, invoice.issued_at, invoice.grand_total,
                   invoice.vat)


def credit_note_qr(note: CreditNote) -> str:
    invoice = note.invoice
    return qr_text(invoice.seller_name, invoice.seller_vat_number, note.created_at, note.grand_total, note.vat)


# --- UBL XML -----------------------------------------------------------------------------


def _x(value) -> str:
    return escape(str(value if value is not None else ""))


def _amt(value) -> str:
    return f"{Decimal(str(value or 0)):.2f}"


def _address(party) -> str:
    return (
        "<cac:PostalAddress>"
        f"<cbc:StreetName>{_x(party.street)}</cbc:StreetName>"
        f"<cbc:BuildingNumber>{_x(party.building_no)}</cbc:BuildingNumber>"
        f"<cbc:CitySubdivisionName>{_x(party.district)}</cbc:CitySubdivisionName>"
        f"<cbc:CityName>{_x(party.city)}</cbc:CityName>"
        f"<cbc:PostalZone>{_x(party.postal_code)}</cbc:PostalZone>"
        f"<cac:Country><cbc:IdentificationCode>{_x(getattr(party, 'country', '') or 'SA')}</cbc:IdentificationCode>"
        "</cac:Country></cac:PostalAddress>"
    )


def _party(tag: str, name: str, vat_number: str, party, scheme: tuple[str, str] | None) -> str:
    ident = (f"<cac:PartyIdentification><cbc:ID schemeID=\"{scheme[0]}\">{_x(scheme[1])}</cbc:ID>"
             "</cac:PartyIdentification>") if scheme and scheme[1] else ""
    tax = (f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(vat_number)}</cbc:CompanyID>"
           "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>") if vat_number else ""
    return (f"<cac:{tag}><cac:Party>{ident}{_address(party)}{tax}"
            f"<cac:PartyLegalEntity><cbc:RegistrationName>{_x(name)}</cbc:RegistrationName></cac:PartyLegalEntity>"
            f"</cac:Party></cac:{tag}>")


def _reason(line, export: bool) -> tuple[str, str]:
    """(code, text) for a zero-rated / exempt / out-of-scope line."""

    if export:
        code = "VATEX-SA-33" if (line.item.kind == "service") else "VATEX-SA-32"
    else:
        code = line.item.exemption_reason or ""
    return code, regimes.EXEMPTION_REASONS.get(code, "")


def _category(code: str, percent, reason: tuple[str, str] | None) -> str:
    extra = (f"<cbc:TaxExemptionReasonCode>{_x(reason[0])}</cbc:TaxExemptionReasonCode>"
             f"<cbc:TaxExemptionReason>{_x(reason[1])}</cbc:TaxExemptionReason>") if reason and reason[0] else ""
    return (f"<cac:TaxCategory><cbc:ID>{code}</cbc:ID><cbc:Percent>{_amt(percent)}</cbc:Percent>{extra}"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>")


def _document(*, number: str, uuid, kind: str, type_code: str, issued: datetime | None, supply_date, company: Company,
              customer, seller_name: str, seller_vat: str, buyer_name: str, buyer_vat: str, lines: list[dict],
              taxable, vat, total, qr: str, billing_ref: str = "", note: str = "") -> tuple[str, list[str]]:
    problems: list[str] = []
    export = bool(customer.country) and customer.country != "SA"
    for label, value in (("VAT number", seller_vat), ("CR number", company.cr_number), ("street", company.street),
                         ("building number", company.building_no), ("district", company.district),
                         ("city", company.city), ("postal code", company.postal_code)):
        if not value:
            problems.append(f"Your company's {label} is missing (Sales → Company & Tax).")
    if kind == "standard":
        for label, value in (("street", customer.street), ("building number", customer.building_no),
                             ("district", customer.district), ("city", customer.city),
                             ("postal code", customer.postal_code)):
            if not value and not export:
                problems.append(f"The buyer's {label} is missing — standard invoices need their national address.")
    subtotals: dict[tuple[str, Decimal], dict] = {}
    line_xml = []
    for i, l in enumerate(lines, 1):
        code = l["category"] or ("S" if l["rate"] > 0 else "Z")
        reason = _reason(l["line"], export) if code != "S" else None
        if reason is not None and not reason[0]:
            problems.append(f"Line {i} ({l['name']}) is {code}-rated without an exemption reason (Inventory → Items).")
        key = (code, Decimal(str(l["rate"])))
        sub = subtotals.setdefault(key, {"taxable": Decimal(0), "vat": Decimal(0), "reason": reason})
        sub["taxable"] += Decimal(str(l["taxable"]))
        sub["vat"] += Decimal(str(l["vat"]))
        allowance = Decimal(str(l["amount"])) - Decimal(str(l["taxable"]))
        line_xml.append(
            f"<cac:InvoiceLine><cbc:ID>{i}</cbc:ID>"
            f"<cbc:InvoicedQuantity unitCode=\"{uqc(l['uom'])}\">{Decimal(str(l['qty'])):f}</cbc:InvoicedQuantity>"
            f"<cbc:LineExtensionAmount currencyID=\"SAR\">{_amt(l['taxable'])}</cbc:LineExtensionAmount>"
            + (f"<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
               f"<cbc:AllowanceChargeReason>Discount</cbc:AllowanceChargeReason>"
               f"<cbc:Amount currencyID=\"SAR\">{_amt(allowance)}</cbc:Amount></cac:AllowanceCharge>"
               if allowance > 0 else "")
            + f"<cac:TaxTotal><cbc:TaxAmount currencyID=\"SAR\">{_amt(l['vat'])}</cbc:TaxAmount>"
            f"<cbc:RoundingAmount currencyID=\"SAR\">{_amt(Decimal(str(l['taxable'])) + Decimal(str(l['vat'])))}"
            "</cbc:RoundingAmount></cac:TaxTotal>"
            f"<cac:Item><cbc:Name>{_x(l['name'])}</cbc:Name>"
            f"<cac:ClassifiedTaxCategory><cbc:ID>{code}</cbc:ID><cbc:Percent>{_amt(l['rate'])}</cbc:Percent>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>"
            f"<cac:Price><cbc:PriceAmount currencyID=\"SAR\">{_amt(l['price'])}</cbc:PriceAmount></cac:Price>"
            "</cac:InvoiceLine>"
        )
    moment = (issued or datetime.now(timezone.utc)).astimezone(timezone.utc)
    subtotal_xml = "".join(
        f"<cac:TaxSubtotal><cbc:TaxableAmount currencyID=\"SAR\">{_amt(s['taxable'])}</cbc:TaxableAmount>"
        f"<cbc:TaxAmount currencyID=\"SAR\">{_amt(s['vat'])}</cbc:TaxAmount>{_category(code, rate, s['reason'])}"
        "</cac:TaxSubtotal>"
        for (code, rate), s in subtotals.items()
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice {NS}>'
        "<cbc:ProfileID>reporting:1.0</cbc:ProfileID>"
        f"<cbc:ID>{_x(number)}</cbc:ID><cbc:UUID>{_x(uuid)}</cbc:UUID>"
        f"<cbc:IssueDate>{moment:%Y-%m-%d}</cbc:IssueDate><cbc:IssueTime>{moment:%H:%M:%S}</cbc:IssueTime>"
        f"<cbc:InvoiceTypeCode name=\"{TYPE_NAMES[kind]}\">{type_code}</cbc:InvoiceTypeCode>"
        "<cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode><cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode>"
        + (f"<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>{_x(billing_ref)}</cbc:ID>"
           "</cac:InvoiceDocumentReference></cac:BillingReference>" if billing_ref else "")
        + "<cac:AdditionalDocumentReference><cbc:ID>QR</cbc:ID><cac:Attachment>"
        f"<cbc:EmbeddedDocumentBinaryObject mimeCode=\"text/plain\">{qr}</cbc:EmbeddedDocumentBinaryObject>"
        "</cac:Attachment></cac:AdditionalDocumentReference>"
        + _party("AccountingSupplierParty", seller_name, seller_vat, company, ("CRN", company.cr_number))
        + _party("AccountingCustomerParty", buyer_name, buyer_vat, customer, None)
        + f"<cac:Delivery><cbc:ActualDeliveryDate>{supply_date:%Y-%m-%d}</cbc:ActualDeliveryDate></cac:Delivery>"
        + "<cac:PaymentMeans><cbc:PaymentMeansCode>30</cbc:PaymentMeansCode>"
        + (f"<cbc:InstructionNote>{_x(note)}</cbc:InstructionNote>" if note else "")
        + "</cac:PaymentMeans>"
        f"<cac:TaxTotal><cbc:TaxAmount currencyID=\"SAR\">{_amt(vat)}</cbc:TaxAmount></cac:TaxTotal>"
        f"<cac:TaxTotal><cbc:TaxAmount currencyID=\"SAR\">{_amt(vat)}</cbc:TaxAmount>{subtotal_xml}</cac:TaxTotal>"
        "<cac:LegalMonetaryTotal>"
        f"<cbc:LineExtensionAmount currencyID=\"SAR\">{_amt(taxable)}</cbc:LineExtensionAmount>"
        f"<cbc:TaxExclusiveAmount currencyID=\"SAR\">{_amt(taxable)}</cbc:TaxExclusiveAmount>"
        f"<cbc:TaxInclusiveAmount currencyID=\"SAR\">{_amt(total)}</cbc:TaxInclusiveAmount>"
        "<cbc:AllowanceTotalAmount currencyID=\"SAR\">0.00</cbc:AllowanceTotalAmount>"
        f"<cbc:PayableAmount currencyID=\"SAR\">{_amt(total)}</cbc:PayableAmount>"
        "</cac:LegalMonetaryTotal>"
        + "".join(line_xml)
        + "</Invoice>\n"
    )
    return xml, list(dict.fromkeys(problems))


def invoice_xml(invoice: Invoice, company: Company) -> tuple[str, list[str]]:
    lines = [{"line": l, "name": l.description, "qty": l.qty, "uom": l.uom, "price": l.unit_price, "amount": l.amount,
              "taxable": l.taxable_value, "vat": l.vat, "rate": float(l.gst_rate), "category": l.tax_category}
             for l in invoice.lines]
    return _document(
        number=invoice.number, uuid=invoice.id, kind=invoice.invoice_kind or "simplified", type_code="388",
        issued=invoice.issued_at, supply_date=invoice.invoice_date, company=company, customer=invoice.customer,
        seller_name=invoice.seller_name, seller_vat=invoice.seller_vat_number, buyer_name=invoice.buyer_name,
        buyer_vat=invoice.buyer_vat_number, lines=lines, taxable=invoice.total, vat=invoice.vat,
        total=invoice.grand_total, qr=invoice_qr(invoice),
    )


def credit_note_xml(note: CreditNote, company: Company) -> tuple[str, list[str]]:
    invoice = note.invoice
    by_id = {l.id: l for l in invoice.lines}
    lines = []
    for l in note.lines:
        source = by_id[l.invoice_line_id]
        qty = Decimal(str(l.qty or 0)) or Decimal(1)
        lines.append({"line": source, "name": l.description, "qty": qty, "uom": l.uom,
                      "price": Decimal(str(l.taxable_value)) / qty, "amount": l.taxable_value,
                      "taxable": l.taxable_value, "vat": l.vat, "rate": float(l.gst_rate),
                      "category": l.tax_category})
    return _document(
        number=note.number, uuid=note.id, kind=invoice.invoice_kind or "simplified", type_code="381",
        issued=note.created_at, supply_date=note.note_date, company=company, customer=invoice.customer,
        seller_name=invoice.seller_name, seller_vat=invoice.seller_vat_number, buyer_name=invoice.buyer_name,
        buyer_vat=invoice.buyer_vat_number, lines=lines, taxable=note.total, vat=note.vat, total=note.grand_total,
        qr=credit_note_qr(note), billing_ref=invoice.number, note=note.reason,
    )
