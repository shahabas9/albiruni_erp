"""CSV exports of the CRM and sales lists, with the same filters and visibility as the
screens. Runs as the audited tool crm.export_records.v1 (see tools_crm), so
every export — who, what, which filters, how many rows — is on record.
"""

import csv
import io
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import activity_service, contact_service, crm_service, customer_service, fields, lead_service
from app.domain import invoice_service, opportunity_service, order_service, payment_service
from app.domain.errors import ConflictError

MAX_ROWS = 50_000
READ = {
    "leads": "crm.lead.read", "opportunities": "crm.opportunity.read", "customers": "sales.customer.read",
    "contacts": "crm.contact.read", "activities": "crm.activity.read",
    "orders": "sales.order.read", "invoices": "sales.invoice.read", "payments": "sales.payment.read",
}
CUSTOM_TYPE = {"leads": "lead", "opportunities": "opportunity", "customers": "customer"}


def _cell(value: Any) -> str:
    """Plain text for a CSV cell. Values that a spreadsheet would run as a
    formula (=, +, -, @ …) get a leading apostrophe."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text):
        return "'" + text
    return text


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


def build(db: Session, context: RequestContext, kind: str, filters: dict[str, Any]) -> tuple[str, str, int]:
    """(filename, csv text, row count). Raises ConflictError for a bad kind or
    PermissionError when the caller can't read that kind of record."""

    if kind not in READ:
        raise ConflictError(f"Export one of: {', '.join(READ)}.")
    if not context.has_permission(READ[kind]):
        raise PermissionError(f"Missing permission: {READ[kind]}")
    f = {k: v for k, v in filters.items() if v not in (None, "")}

    if kind == "leads":
        rows, _ = lead_service.list_leads(db, context, q=f.get("q", ""), status=f.get("status", ""),
                                          owner=f.get("owner", ""), tag=f.get("tag", ""), limit=None)
        owners = crm_service.owner_names(db, {r.owner_user_id for r in rows})
        header = ["Name", "Company", "Phone", "Email", "Source", "Status", "Owner", "Tags", "Notes", "Created"]
        data = [[r.name, r.company_name, r.phone, r.email, r.source, r.status, owners.get(r.owner_user_id, ""),
                 r.tags, r.notes, r.created_at] for r in rows]
    elif kind == "opportunities":
        closed_since = date.fromisoformat(f["closed_since"]) if f.get("closed_since") else None
        rows, _ = opportunity_service.list_opportunities(
            db, context, q=f.get("q", ""), stage=f.get("stage", ""), owner=f.get("owner", ""), tag=f.get("tag", ""),
            stale_only=str(f.get("stale", "")).lower() in ("1", "true"), customer_id=_uuid(f.get("customer_id")),
            closed_since=closed_since, limit=None,
        )
        owners = crm_service.owner_names(db, {r.owner_user_id for r in rows})
        header = ["Deal", "Customer", "Stage", "Value", "Probability %", "Weighted value", "Expected close", "Owner",
                  "Lost reason", "Stage changed", "Tags", "Created"]
        data = [[r.name, r.customer.name, r.stage, float(r.value), r.probability_pct,
                 round(float(r.value) * r.probability_pct / 100, 2), r.expected_close_date,
                 owners.get(r.owner_user_id, ""), r.lost_reason, r.stage_changed_at, r.tags, r.created_at] for r in rows]
    elif kind == "customers":
        active = f.get("active")
        active = None if active is None else str(active).lower() in ("1", "true", "yes")
        rows, _ = customer_service.list_customers(db, context, q=f.get("q", ""), active=active, tag=f.get("tag", ""),
                                                  limit=None)
        header = ["Name", "GSTIN", "Credit limit", "Active", "Tags"]
        data = [[r.name, r.gstin, float(r.credit_limit), r.active, r.tags] for r in rows]
    elif kind == "contacts":
        rows, _ = contact_service.list_contacts(db, context, q=f.get("q", ""), customer_id=_uuid(f.get("customer_id")),
                                                limit=None)
        header = ["Name", "Customer", "Title", "Phone", "Email"]
        data = [[r.name, r.customer.name, r.title, r.phone, r.email] for r in rows]
    elif kind == "orders":
        rows, _ = order_service.list_orders(db, context, status=f.get("status", ""), q=f.get("q", ""),
                                            customer_id=_uuid(f.get("customer_id")), limit=None)
        people = crm_service.owner_names(db, {r.salesperson_id for r in rows})
        header = ["Order", "Date", "Customer", "GSTIN", "Customer PO", "Status", "Invoicing", "Taxable value", "CGST",
                  "SGST", "IGST", "Total", "Salesperson", "Created"]
        data = [[r.number, r.order_date, r.customer.name, r.customer.gstin, r.customer_po, r.status,
                 order_service.invoice_status(r), float(r.total), float(r.cgst), float(r.sgst), float(r.igst),
                 float(r.grand_total), people.get(r.salesperson_id, ""), r.created_at] for r in rows]
    elif kind == "invoices":
        rows, _ = invoice_service.list_invoices(db, context, status=f.get("status", ""), q=f.get("q", ""),
                                                customer_id=_uuid(f.get("customer_id")), limit=None)
        header = ["Invoice", "Date", "Due", "Customer", "GSTIN", "Place of supply", "Taxable value", "CGST", "SGST",
                  "IGST", "Total", "Paid", "Credited", "TDS", "Refunded", "Balance", "Status", "Salesperson"]
        people = crm_service.owner_names(db, {r.salesperson_id for r in rows})
        data = [[r.number or "(draft)", r.invoice_date, r.due_date, r.buyer_name or r.customer.name,
                 r.buyer_gstin or r.customer.gstin, r.place_of_supply, float(r.total), float(r.cgst), float(r.sgst),
                 float(r.igst), float(r.grand_total), float(r.amount_paid), float(r.amount_credited),
                 float(r.amount_tds or 0), float(r.amount_refunded or 0), float(invoice_service.balance(r)),
                 invoice_service.payment_status(r), people.get(r.salesperson_id, "")] for r in rows]
    elif kind == "payments":
        with_advance = str(f.get("with_advance", "")).lower() in ("1", "true")
        rows, _ = payment_service.list_receipts(db, context, q=f.get("q", ""), customer_id=_uuid(f.get("customer_id")),
                                                with_advance=with_advance, limit=None)
        header = ["Receipt", "Date", "Customer", "Mode", "Reference", "Amount", "TDS", "TDS section", "Applied to",
                  "Applied", "Refunded", "Advance left", "Status"]
        data = [[r.number, r.receipt_date, r.customer.name, r.mode, r.reference, float(r.amount),
                 float(r.tds_amount or 0), r.tds_section, [a.invoice.number for a in r.allocations],
                 float(payment_service.allocated(r)), float(r.amount_refunded or 0),
                 float(payment_service.unallocated(r)), r.status] for r in rows]
    else:
        rows, _ = activity_service.list_activities(
            db, context, show=f.get("show", "all"), owner=f.get("owner", ""), lead_id=_uuid(f.get("lead_id")),
            customer_id=_uuid(f.get("customer_id")), opportunity_id=_uuid(f.get("opportunity_id")), limit=None,
        )
        labels = activity_service.related_labels(db, context, rows)
        owners = crm_service.owner_names(db, {r.owner_id for r in rows})
        header = ["Type", "Subject", "Related to", "Due", "Done", "Overdue", "Owner", "Notes", "Created"]
        data = [[r.type, r.subject, labels.get(r.id, ""), r.due_at, r.done, crm_service.is_overdue(r),
                 owners.get(r.owner_id, ""), r.notes, r.created_at] for r in rows]

    if len(rows) > MAX_ROWS:
        raise ConflictError(f"That's {len(rows):,} rows — narrow the filters to at most {MAX_ROWS:,}.")
    if kind in CUSTOM_TYPE:  # one column per custom field, archived ones included
        defs = fields.list_fields(db, context, CUSTOM_TYPE[kind], include_archived=True)
        header += [d.label for d in defs]
        for row, record in zip(data, rows):
            row += [(record.custom or {}).get(d.key) for d in defs]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows([[_cell(v) for v in row] for row in data])
    filename = f"{kind}-{datetime.now():%Y-%m-%d}.csv"
    return filename, out.getvalue(), len(rows)
