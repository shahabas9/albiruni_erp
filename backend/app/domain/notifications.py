"""Notifications: tell people when something needs them.

notify() adds a row in the caller's transaction, so it's kept or dropped
with the change it's about. A background worker (run_worker_cycle, started in
main.py) raises "follow-up overdue" and "invoice overdue" alerts and emails pending notifications
to people who gave an address — both claim rows with SKIP LOCKED, so several
API processes can run it at once without doubling up.
"""

import logging
import smtplib
from collections import Counter
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.domain import crm_service
from app.models.crm import Activity, Lead, Notification, Opportunity
from app.models.documents import Invoice, SalesOrder
from app.models.identity import Role, User

log = logging.getLogger(__name__)
MAX_EMAIL_ATTEMPTS = 3


def notify(
    db: Session, context: RequestContext, user_id: UUID | None, kind: str, title: str, body: str = "",
    link: str = "",
) -> None:
    """Queues a notification for `user_id` — unless there's nobody, or it's
    the person who made the change (you don't need telling what you did)."""

    if user_id is None or (context.user is not None and user_id == context.user.id):
        return
    db.add(Notification(
        tenant_id=context.tenant_id, company_id=context.company_id, user_id=user_id, kind=kind,
        title=title[:200], body=body[:500], link=link[:300],
    ))


def managers(db: Session, context: RequestContext) -> list[UUID]:
    """Active users who can hand out leads — told about unassigned enquiries."""

    rows = db.execute(
        select(User.id, Role.permissions).join(Role, Role.id == User.role_id).where(
            User.tenant_id == context.tenant_id, User.company_id == context.company_id, User.active.is_(True),
        )
    ).all()
    return [uid for uid, perms in rows if "*" in (perms or []) or "crm.lead.assign" in (perms or [])]


def lead_link(lead_id: UUID) -> str:
    return f"/leads?lead={lead_id}"


def deal_link(opportunity_id: UUID) -> str:
    return f"/crm?opp={opportunity_id}"


# --- Reading -------------------------------------------------------------------


def list_for(db: Session, context: RequestContext, *, unread_only: bool = False, limit: int = 30) -> dict:
    base = select(Notification).where(Notification.user_id == context.user.id)
    unread = db.execute(
        select(Notification.id).where(Notification.user_id == context.user.id, Notification.read_at.is_(None))
    ).all()
    stmt = base.where(Notification.read_at.is_(None)) if unread_only else base
    rows = db.execute(stmt.order_by(Notification.created_at.desc()).limit(min(limit, 100))).scalars().all()
    return {"unread": len(unread), "items": rows}


def mark_read(db: Session, context: RequestContext, ids: list[UUID] | None) -> int:
    stmt = update(Notification).where(Notification.user_id == context.user.id, Notification.read_at.is_(None))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = db.execute(stmt.values(read_at=crm_service.now_utc()))
    db.commit()
    return result.rowcount or 0


# --- Background worker ------------------------------------------------------------


def raise_overdue_alerts(db: Session) -> int:
    """One alert per follow-up the first time it's overdue (again after its due time changes)."""

    now = crm_service.now_utc()
    due = db.execute(
        select(Activity)
        .where(Activity.done.is_(False), Activity.due_at < now, Activity.overdue_notified_at.is_(None))
        .order_by(Activity.due_at)
        .limit(500)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for a in due:
        a.overdue_notified_at = now
        owner = a.owner_id
        if owner is None and a.opportunity_id:
            owner = db.get(Opportunity, a.opportunity_id).owner_user_id
        if owner is None and a.lead_id:
            owner = db.get(Lead, a.lead_id).owner_user_id
        if owner is None:
            continue
        context = RequestContext(user=None, tenant_id=a.tenant_id, company_id=a.company_id, permissions=[],
                                 locale="en-IN")
        link = deal_link(a.opportunity_id) if a.opportunity_id else "/activities?show=overdue"
        notify(db, context, owner, "followup_overdue", f"Overdue: {a.subject or a.type}",
               f"{a.type} was due {a.due_at:%d %b, %H:%M} UTC.", link)
    db.commit()
    return len(due)


def raise_overdue_invoice_alerts(db: Session) -> int:
    """One alert per invoice the day after its due date passes with money still owed: to whoever
    issued it and to the owner of the deal it came from."""

    today = crm_service.now_utc().date()
    left = Invoice.left_expr()
    due = db.execute(
        select(Invoice)
        .where(Invoice.status == "Issued", Invoice.due_date < today, left > 0, Invoice.overdue_notified_at.is_(None))
        .order_by(Invoice.due_date)
        .limit(500)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    now = crm_service.now_utc()
    for inv in due:
        inv.overdue_notified_at = now
        people = {inv.issued_by}
        order = db.get(SalesOrder, inv.order_id)
        if order is not None and order.opportunity_id:
            people.add(db.get(Opportunity, order.opportunity_id).owner_user_id)
        context = RequestContext(user=None, tenant_id=inv.tenant_id, company_id=inv.company_id, permissions=[],
                                 locale="en-IN")
        owed = float(inv.grand_total) - float(inv.amount_paid) - float(inv.amount_credited) - float(inv.amount_tds)
        for user_id in people - {None}:
            notify(db, context, user_id, "invoice_overdue", f"Overdue: {inv.number} ({inv.buyer_name})",
                   f"₹{owed:,.2f} was due on {inv.due_date:%d %b %Y}.", f"/sales/invoices/{inv.id}")
    db.commit()
    return len(due)


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send(to: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_pending_emails(db: Session, send=_send) -> Counter:
    """Emails pending notifications; marks each sent, skipped or failed."""

    outcome: Counter = Counter()
    rows = db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(Notification.email_status == "pending")
        .order_by(Notification.created_at)
        .limit(100)
        .with_for_update(of=Notification, skip_locked=True)
    ).all()
    for n, user in rows:
        if not (user.email and user.notify_email and user.active and smtp_configured()):
            n.email_status = "skipped"
            outcome["skipped"] += 1
            continue
        link = f"{settings.app_url.rstrip('/')}{n.link}" if n.link else settings.app_url
        try:
            send(user.email, n.title, f"{n.title}\n\n{n.body}\n\nOpen: {link}\n")
            n.email_status = "sent"
            outcome["sent"] += 1
        except Exception as exc:  # noqa: BLE001 — a bad address or server must not stop the others
            n.email_attempts += 1
            n.email_status = "failed" if n.email_attempts >= MAX_EMAIL_ATTEMPTS else "pending"
            outcome["failed"] += 1
            log.warning("Notification email to %s failed: %s", user.email, exc)
    db.commit()
    return outcome


def run_worker_cycle() -> None:
    with SessionLocal() as db:
        try:
            raise_overdue_alerts(db)
            raise_overdue_invoice_alerts(db)
            send_pending_emails(db)
            from app.domain import reminder_service

            reminder_service.send_due_reminders(db)
        except Exception:  # noqa: BLE001 — log and try again next cycle
            db.rollback()
            log.exception("Notification worker cycle failed")


