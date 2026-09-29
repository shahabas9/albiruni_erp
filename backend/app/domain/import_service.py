"""CSV import for leads and customers.

Two passes over the same code: a dry run that validates every row and flags
duplicates (nothing written), then a commit that writes the valid rows in one
transaction. Headers are matched loosely ("Mobile", "Phone number" and
"phone" are all the phone column) so an export from Excel, Tally or another
CRM usually works without editing.
"""

import csv
import io
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, history
from app.domain.duplicates import phone_key
from app.domain.gstin import normalize_gstin
from app.models.crm import Lead
from app.models.sales import Customer

MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024

# canonical column -> accepted header spellings (lower-cased, punctuation-insensitive)
COLUMNS = {
    "leads": {
        "name": ["name", "contact", "contact name", "contact person", "person", "full name", "lead name"],
        "company_name": ["company", "company name", "business", "business name", "organisation", "organization", "firm", "account"],
        "phone": ["phone", "mobile", "mobile number", "mobile no", "phone number", "phone no", "contact number", "whatsapp", "cell"],
        "email": ["email", "e mail", "email address", "mail"],
        "source": ["source", "lead source", "channel"],
        "notes": ["notes", "note", "remarks", "comments", "comment", "description"],
        "owner": ["owner", "assigned to", "salesperson", "sales person", "sales rep", "rep"],
    },
    "customers": {
        "name": ["name", "customer", "customer name", "company", "company name", "business", "business name", "party", "party name"],
        "gstin": ["gstin", "gst", "gst no", "gst number", "gstin uin", "gstin/uin", "gst in"],
        "credit_limit": ["credit limit", "credit", "limit", "credit amount"],
    },
}
REQUIRED = {"leads": "name or company", "customers": "name"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CsvImportError(Exception):
    """The file as a whole can't be imported (wrong columns, too big, not CSV)."""


@dataclass
class Row:
    line: int
    values: dict[str, str]
    status: str = "ok"  # ok | duplicate | error
    messages: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.status = "error"
        self.messages.append(message)


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", h.lower()).strip()


def parse(kind: str, text: str) -> tuple[list[Row], dict[str, str]]:
    if kind not in COLUMNS:
        raise CsvImportError(f"Can't import '{kind}'. Use leads or customers.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CsvImportError("That file is over 2 MB — split it into smaller files.")
    text = text.lstrip("﻿")  # Excel's UTF-8 byte-order mark
    if not text.strip():
        raise CsvImportError("The file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])

    mapping: dict[int, str] = {}
    for idx, raw in enumerate(header):
        h = _norm_header(raw)
        for canonical, aliases in COLUMNS[kind].items():
            if h in aliases and canonical not in mapping.values():
                mapping[idx] = canonical
    found = set(mapping.values())
    if not ({"name", "company_name"} & found if kind == "leads" else {"name"} & found):
        expected = ", ".join(COLUMNS[kind])
        raise CsvImportError(f"No {REQUIRED[kind]} column found. Expected headers like: {expected}.")

    rows = []
    for line_no, record in enumerate(reader, start=2):
        if not any(cell.strip() for cell in record):
            continue
        values = {col: (record[i].strip() if i < len(record) else "") for i, col in mapping.items()}
        rows.append(Row(line_no, values))
        if len(rows) > MAX_ROWS:
            raise CsvImportError(f"That's more than {MAX_ROWS} rows — split the file.")
    if not rows:
        raise CsvImportError("The file has a header row but no data rows.")
    columns = {canonical: header[i] for i, canonical in mapping.items()}
    return rows, columns


def _validate_leads(db: Session, context: RequestContext, rows: list[Row]) -> None:
    existing = db.execute(
        select(Lead.phone, Lead.email).where(Lead.tenant_id == context.tenant_id, Lead.company_id == context.company_id)
    ).all()
    seen_phones = {phone_key(p) for p, _ in existing if phone_key(p)}
    seen_emails = {e.lower() for _, e in existing if e}
    users = {
        key.lower(): u
        for u in crm_service.list_assignees(db, context)
        for key in (u.display_name, u.username)
    }
    can_assign = context.has_permission("crm.lead.assign")

    for row in rows:
        v = row.values
        if not v.get("name") and not v.get("company_name"):
            row.error("Needs a name or a company.")
            continue
        v.setdefault("name", "")
        v["name"] = v["name"] or v.get("company_name", "")
        if len(v["name"]) > 160 or len(v.get("company_name", "")) > 160:
            row.error("Name or company is longer than 160 characters.")
        email = v.get("email", "")
        if email and not _EMAIL.match(email):
            row.error(f"“{email}” isn't a valid email.")
        phone = v.get("phone", "")
        if phone and not 10 <= len(re.sub(r"\D", "", phone)) <= 15:
            row.error(f"“{phone}” doesn't look like a phone number.")
        owner = v.get("owner", "")
        if owner:
            user = users.get(owner.lower())
            if user is None:
                row.error(f"No user called “{owner}” in this company.")
            elif user.id != context.user.id and not can_assign:
                row.error("You can't assign leads to other people (needs crm.lead.assign).")
            else:
                v["owner_user_id"] = str(user.id)
        if row.status == "error":
            continue
        key = phone_key(phone)
        if (key and key in seen_phones) or (email and email.lower() in seen_emails):
            row.status = "duplicate"
            row.messages.append("Already exists (same phone or email) — will be skipped.")
            continue
        if key:
            seen_phones.add(key)
        if email:
            seen_emails.add(email.lower())


def _validate_customers(db: Session, context: RequestContext, rows: list[Row]) -> None:
    existing = db.execute(
        select(Customer.name, Customer.gstin).where(
            Customer.tenant_id == context.tenant_id, Customer.company_id == context.company_id
        )
    ).all()
    seen_names = {n.lower() for n, _ in existing}
    seen_gstins = {g for _, g in existing if g}

    for row in rows:
        v = row.values
        name = v.get("name", "")
        if not name:
            row.error("Needs a name.")
            continue
        if len(name) > 160:
            row.error("Name is longer than 160 characters.")
        try:
            v["gstin"] = normalize_gstin(v.get("gstin", ""))
        except ValueError as exc:
            row.error(str(exc))
        raw_limit = re.sub(r"[₹,\s]|rs\.?|inr", "", v.get("credit_limit", ""), flags=re.IGNORECASE)
        try:
            limit = Decimal(raw_limit) if raw_limit else Decimal(0)
            if limit < 0:
                raise InvalidOperation
            v["credit_limit"] = str(limit)
        except InvalidOperation:
            row.error(f"Credit limit “{v.get('credit_limit')}” isn't a number.")
        if row.status == "error":
            continue
        if name.lower() in seen_names or (v["gstin"] and v["gstin"] in seen_gstins):
            row.status = "duplicate"
            row.messages.append("Already exists (same name or GSTIN) — will be skipped.")
            continue
        seen_names.add(name.lower())
        if v["gstin"]:
            seen_gstins.add(v["gstin"])


def validate(db: Session, context: RequestContext, kind: str, rows: list[Row]) -> None:
    (_validate_leads if kind == "leads" else _validate_customers)(db, context, rows)


def commit(db: Session, context: RequestContext, kind: str, rows: list[Row]) -> int:
    """Writes every "ok" row in one transaction; returns how many were created."""

    context = replace(context, channel="import")
    created = 0
    for row in rows:
        if row.status != "ok":
            continue
        v = row.values
        if kind == "leads":
            lead = Lead(
                tenant_id=context.tenant_id, company_id=context.company_id,
                name=v["name"], company_name=v.get("company_name", ""), phone=v.get("phone", ""),
                email=v.get("email", ""), source=v.get("source", "") or "Import", notes=v.get("notes", ""),
                status="New", owner_user_id=UUID(v["owner_user_id"]) if v.get("owner_user_id") else context.user.id,
            )
            db.add(lead)
            db.flush()
            history.record(db, context, "lead", lead.id, "created", f"Lead imported from CSV (line {row.line})")
        else:
            db.add(Customer(
                tenant_id=context.tenant_id, company_id=context.company_id,
                name=v["name"], gstin=v["gstin"], credit_limit=Decimal(v["credit_limit"]), active=True,
            ))
        created += 1
    db.commit()
    return created

