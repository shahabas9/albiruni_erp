"""Payment reminders to customers.

A company that turns reminders on gets one email per stage for each unpaid
invoice: `reminder_before_days` before the due date, then on each of
`reminder_after_days` after it (default 1, 7, 15 and 30). Each stage goes at
most once — the stages sent are kept on the invoice — and a run that finds
several stages due (say the worker was down for a week) sends only the
latest. The email carries a share link to the invoice.

Reminders need SMTP and an email on the customer (Customers → billing
email). Staff can also send one by hand, by email or WhatsApp, from the
invoice or the statement.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service, history, notifications, share_service
from app.domain.invoice_service import balance
from app.models.documents import Invoice
from app.models.sales import Customer
from app.models.tenant import Company

log = logging.getLogger(__name__)


def parse_days(text: str) -> list[int]:
    """"1, 7,15" → [1, 7, 15]. Raises ValueError for anything else."""

    days = sorted({int(part) for part in text.replace(" ", "").split(",") if part})
    if not days or any(d < 1 or d > 365 for d in days) or len(days) > 8:
        raise ValueError("Reminder days must be up to 8 numbers between 1 and 365, like 1, 7, 15, 30.")
    return days


def stages(company: Company) -> list[int]:
    """Reminder points as days from the due date: [-3, 1, 7, 15, 30]."""

    before = [-company.reminder_before_days] if company.reminder_before_days else []
    try:
        after = parse_days(company.reminder_after_days or "")
    except ValueError:
        after = []
    return before + after


def stage_due(invoice: Invoice, company: Company, today: date) -> int | None:
    """The reminder stage to send now, if any: the latest stage reached and not yet sent."""

    days = (today - invoice.due_date).days
    reached = [s for s in stages(company) if s <= days]
    if not reached:
        return None
    latest = max(reached)
    return None if latest in (invoice.reminder_offsets_sent or []) else latest


def reminder_text(invoice: Invoice, today: date | None = None) -> str:
    today = today or date.today()
    owed = f"₹{float(balance(invoice)):,.2f}"
    days = (invoice.due_date - today).days
    if days > 0:
        when = f"is due on {invoice.due_date:%d %b %Y}, in {days} day{'' if days == 1 else 's'}"
    elif days == 0:
        when = "is due today"
    else:
        when = f"was due on {invoice.due_date:%d %b %Y} ({-days} day{'' if days == -1 else 's'} ago)"
    return (f"A gentle reminder that {owed} on invoice {invoice.number} {when}. "
            "If you've already paid, please ignore this — and thank you.")


def send_due_reminders(db: Session, today: date | None = None, send=None) -> int:
    """Worker step: emails every reminder that's due. Returns how many went."""

    send = send or notifications._send
    if not notifications.smtp_configured() and send is notifications._send:
        return 0
    today = today or crm_service.now_utc().date()
    sent = 0
    for company in db.execute(select(Company).where(Company.reminders_enabled.is_(True))).scalars():
        rows = db.execute(
            select(Invoice, Customer)
            .join(Customer, Customer.id == Invoice.customer_id)
            .where(Invoice.company_id == company.id, Invoice.status == "Issued", Invoice.left_expr() > 0,
                   Customer.email != "")
            .order_by(Invoice.due_date)
            .limit(500)
            .with_for_update(of=Invoice, skip_locked=True)
        ).all()
        context = RequestContext(user=None, tenant_id=company.tenant_id, company_id=company.id, permissions=[],
                                 locale="en-IN", channel="reminder")
        for invoice, customer in rows:
            stage = stage_due(invoice, company, today)
            if stage is None:
                continue
            url = share_service.link(share_service.make_token(context, "invoice", invoice.id))
            seller = company.legal_name or company.name
            body = (f"Dear {customer.name},\n\n{reminder_text(invoice, today)}\n\nView the invoice: {url}\n\n"
                    + (f"Our bank details:\n{company.bank_details}\n\n" if company.bank_details else "") + f"— {seller}")
            try:
                send(customer.email, f"Payment reminder: invoice {invoice.number} from {seller}", body)
            except Exception as exc:  # noqa: BLE001 — one bad address mustn't stop the rest
                log.warning("Reminder for %s to %s failed: %s", invoice.number, customer.email, exc)
                continue
            invoice.reminder_offsets_sent = sorted({*(invoice.reminder_offsets_sent or []),
                                                    *(s for s in stages(company) if s <= stage)})
            invoice.last_reminder_at = crm_service.now_utc()
            history.record(db, context, "invoice", invoice.id, "reminder",
                           f"Payment reminder emailed to {customer.email}")
            sent += 1
        db.commit()
    return sent
