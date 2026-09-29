"""The public web enquiry form: website visitors become leads.

Each company gets a secret key; the form lives at /api/public/enquiry/<key>
(a hosted page to link to or embed in an iframe, or a JSON endpoint for a
site's own form). Nobody is signed in, so every guard lives here: the key
must match an enabled form, a honeypot field catches bots, submissions are
rate-limited per IP, and input is size-checked. An enquiry from someone who
is already a lead (same phone or email) is added to that lead as a note
instead of creating a duplicate; new leads go to the lead rotation when it's
on, otherwise they're unassigned.
"""

import re
import secrets
import threading
import time
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, duplicates, history
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Activity, CrmSettings, Lead
from app.models.tenant import Company

MAX_NAME = 160
MAX_MESSAGE = 2000
DEFAULT_SOURCE = "Website"
DEFAULT_THANK_YOU = "Thank you — we've received your enquiry and will be in touch shortly."
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Per-process limits (a multi-process deployment should use a shared store).
PER_IP_LIMIT = (5, 10 * 60)  # 5 submissions per 10 minutes from one IP, per form
PER_FORM_LIMIT = (200, 60 * 60)  # 200 per hour per form
_hits: dict[tuple, deque] = defaultdict(deque)
_lock = threading.Lock()


class RateLimited(Exception):
    pass


def _allow(bucket: tuple, limit: tuple[int, int]) -> bool:
    count, window = limit
    now = time.monotonic()
    with _lock:
        hits = _hits[bucket]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= count:
            return False
        hits.append(now)
        return True


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


# --- Settings (signed-in, crm.settings.write) --------------------------------------


def _row(db: Session, context: RequestContext) -> CrmSettings:
    row = db.execute(
        select(CrmSettings).where(
            CrmSettings.company_id == context.company_id, CrmSettings.tenant_id == context.tenant_id
        ).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = CrmSettings(company_id=context.company_id, tenant_id=context.tenant_id, stale_after_days={})
        db.add(row)
    return row


def settings_for(db: Session, context: RequestContext) -> dict:
    row = db.execute(
        select(CrmSettings).where(
            CrmSettings.company_id == context.company_id, CrmSettings.tenant_id == context.tenant_id
        )
    ).scalar_one_or_none()
    form = (row.web_form if row else None) or {}
    return {
        "enabled": bool(form.get("enabled")) and bool(form.get("key")),
        "key": form.get("key"),
        "source": form.get("source") or DEFAULT_SOURCE,
        "thank_you": form.get("thank_you") or DEFAULT_THANK_YOU,
    }


def update_settings(db: Session, context: RequestContext, *, enabled: bool | None = None,
                    source: str | None = None, thank_you: str | None = None) -> dict:
    row = _row(db, context)
    form = dict(row.web_form or {})
    if enabled is not None:
        form["enabled"] = enabled
        if enabled and not form.get("key"):
            form["key"] = secrets.token_urlsafe(24)
    if source is not None:
        source = source.strip()
        if not source or len(source) > 60:
            raise ConflictError("Lead source must be 1–60 characters.")
        form["source"] = source
    if thank_you is not None:
        thank_you = thank_you.strip()
        if not thank_you or len(thank_you) > 300:
            raise ConflictError("The thank-you message must be 1–300 characters.")
        form["thank_you"] = thank_you
    row.web_form = form
    db.commit()
    return settings_for(db, context)


def regenerate_key(db: Session, context: RequestContext) -> dict:
    """A new secret link; the old one stops working at once."""

    row = _row(db, context)
    row.web_form = {**(row.web_form or {}), "key": secrets.token_urlsafe(24)}
    db.commit()
    return settings_for(db, context)


# --- Public ---------------------------------------------------------------------


def form_for_key(db: Session, key: str) -> tuple[CrmSettings, Company]:
    if not key or len(key) > 64:
        raise NotFoundError("This enquiry form doesn't exist.")
    found = db.execute(
        select(CrmSettings, Company)
        .join(Company, Company.id == CrmSettings.company_id)
        .where(CrmSettings.web_form["key"].astext == key)
    ).first()
    if found is None or not found[0].web_form.get("enabled"):
        raise NotFoundError("This enquiry form isn't available.")
    return found[0], found[1]


def _clean(data: dict, field: str, limit: int) -> str:
    value = data.get(field)
    value = "" if value is None else str(value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()
    if len(value) > limit:
        raise ConflictError(f"{field.replace('_', ' ').capitalize()} is too long (at most {limit} characters).")
    return value


def submit(db: Session, key: str, data: dict, client_ip: str) -> dict:
    """Handles one submission. Returns {"thank_you": str, "lead_id": ..., "created": bool}.
    Raises NotFoundError (unknown/disabled form), RateLimited or ConflictError (bad input)."""

    settings_row, company = form_for_key(db, key)
    if not _allow(("ip", key, client_ip), PER_IP_LIMIT) or not _allow(("form", key), PER_FORM_LIMIT):
        raise RateLimited("Too many enquiries — please try again in a few minutes.")
    form = settings_row.web_form
    thank_you = form.get("thank_you") or DEFAULT_THANK_YOU

    # Honeypot: a field people never see. Bots fill it; pretend all went well.
    if _clean(data, "website", 200):
        return {"thank_you": thank_you, "lead_id": None, "created": False}

    name = _clean(data, "name", MAX_NAME)
    company_name = _clean(data, "company", MAX_NAME)
    phone = _clean(data, "phone", 40)
    email = _clean(data, "email", 160).lower()
    message = _clean(data, "message", MAX_MESSAGE)
    if not name and not company_name:
        raise ConflictError("Please tell us your name.")
    if not phone and not email:
        raise ConflictError("Please give a phone number or an email so we can reply.")
    if email and not _EMAIL.match(email):
        raise ConflictError("That email address doesn't look right.")
    if phone and not 10 <= len(re.sub(r"\D", "", phone)) <= 15:
        raise ConflictError("That phone number doesn't look right.")

    context = RequestContext(
        user=None, tenant_id=company.tenant_id, company_id=company.id, permissions=[], locale="en-IN",
        channel="web_form",
    )
    note = f"Web enquiry: {message}" if message else "Web enquiry (no message)"
    existing = [
        lead for lead in duplicates.lead_matches(db, context, phone=phone, email=email)
        if lead.status != "Converted"
    ]
    if existing:
        lead = existing[0]
        if lead.status == "Lost":
            lead.status = "New"
            history.record(db, context, "lead", lead.id, "status_changed",
                           "Status: Lost → New (new web enquiry)", {"status": ["Lost", "New"]})
        db.add(Activity(
            tenant_id=context.tenant_id, company_id=context.company_id, type="Note", subject=note[:200],
            notes=message, lead_id=lead.id, owner_id=lead.owner_user_id, done=True,
            completed_at=crm_service.now_utc(),
        ))
        history.record(db, context, "lead", lead.id, "activity_logged", "New enquiry from the website form")
        db.commit()
        return {"thank_you": thank_you, "lead_id": lead.id, "created": False}

    rotated = crm_service.next_rotation_owner(db, context)
    lead = Lead(
        tenant_id=context.tenant_id, company_id=context.company_id, name=name or company_name,
        company_name=company_name, phone=phone, email=email, source=form.get("source") or DEFAULT_SOURCE,
        notes=message, status="New", owner_user_id=rotated.id if rotated else None, tags=[], custom={},
    )
    db.add(lead)
    db.flush()
    by = f" — assigned by rotation to {rotated.display_name}" if rotated else ""
    history.record(db, context, "lead", lead.id, "created", f"Lead created from the website enquiry form{by}")
    db.commit()
    return {"thank_you": thank_you, "lead_id": lead.id, "created": True}
