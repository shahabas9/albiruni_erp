"""Sales targets: what each person should win per month, against what they did.

"Won" is the value of deals whose stage became Won during the month (by
stage_changed_at, UTC), credited to the deal's owner at the time of asking.
"Forecast" is the probability-weighted value of their open deals expected to
close that month. "Invoiced" is the taxable value of invoices issued in the
month for which they're the salesperson, less credit notes dated in the
month against their invoices. The company picks which of won or invoiced
the target is measured against (CrmSettings.target_basis).
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import crm_service
from app.domain.errors import ConflictError
from app.models.crm import OPEN_STAGES, CrmSettings, Opportunity, SalesTarget
from app.models.documents import CreditNote, Invoice
from app.models.identity import User

MAX_TARGET = Decimal("1000000000000")
BASES = ("won", "invoiced")


def basis(db: Session, context: RequestContext) -> str:
    row = db.get(CrmSettings, context.company_id)
    return row.target_basis if row is not None and row.target_basis in BASES else "won"


def set_basis(db: Session, context: RequestContext, value: str) -> None:
    if value not in BASES:
        raise ConflictError("Measure targets on won deals or invoiced sales.")
    row = db.get(CrmSettings, context.company_id)
    if row is None:
        row = CrmSettings(company_id=context.company_id, tenant_id=context.tenant_id, stale_after_days={})
        db.add(row)
    row.target_basis = value
    db.commit()


def _invoiced(db: Session, context: RequestContext, month: date) -> dict:
    """{salesperson: (invoice count, taxable value less the month's credit notes on their invoices)}."""

    scope = (Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
             Invoice.status == "Issued")
    sales = {
        person: (count, Decimal(str(value)))
        for person, count, value in db.execute(
            select(Invoice.salesperson_id, func.count(), func.coalesce(func.sum(Invoice.total), 0))
            .where(*scope, Invoice.invoice_date >= month, Invoice.invoice_date < _next_month(month))
            .group_by(Invoice.salesperson_id)
        )
    }
    for person, value in db.execute(
        select(Invoice.salesperson_id, func.coalesce(func.sum(CreditNote.total), 0))
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .where(*scope, CreditNote.note_date >= month, CreditNote.note_date < _next_month(month))
        .group_by(Invoice.salesperson_id)
    ):
        count, sold = sales.get(person, (0, Decimal(0)))
        sales[person] = (count, sold - Decimal(str(value)))
    return {person: (count, float(value)) for person, (count, value) in sales.items()}


def parse_month(value: str) -> date:
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1)
    except ValueError as exc:
        raise ConflictError("Month must look like 2026-10.") from exc


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def report(db: Session, context: RequestContext, month: date) -> dict:
    start = datetime.combine(month, time.min, timezone.utc)
    end = datetime.combine(_next_month(month), time.min, timezone.utc)
    scope = (Opportunity.tenant_id == context.tenant_id, Opportunity.company_id == context.company_id)

    targets = {
        t.user_id: float(t.amount)
        for t in db.execute(
            select(SalesTarget).where(
                SalesTarget.tenant_id == context.tenant_id,
                SalesTarget.company_id == context.company_id,
                SalesTarget.month == month,
            )
        ).scalars()
    }
    won = {
        owner: (count, float(value))
        for owner, count, value in db.execute(
            select(Opportunity.owner_user_id, func.count(), func.coalesce(func.sum(Opportunity.value), 0))
            .where(*scope, Opportunity.stage == "Won",
                   Opportunity.stage_changed_at >= start, Opportunity.stage_changed_at < end)
            .group_by(Opportunity.owner_user_id)
        )
    }
    forecast = {
        owner: float(value)
        for owner, value in db.execute(
            select(Opportunity.owner_user_id,
                   func.coalesce(func.sum(Opportunity.value * Opportunity.probability_pct / 100), 0))
            .where(*scope, Opportunity.stage.in_(OPEN_STAGES),
                   and_(Opportunity.expected_close_date >= month,
                        Opportunity.expected_close_date < _next_month(month)))
            .group_by(Opportunity.owner_user_id)
        )
    }

    invoiced = _invoiced(db, context, month)
    measure = basis(db, context)

    people = {u.id: u for u in crm_service.list_assignees(db, context)}
    # Also list anyone with a target, a win or a sale this month who has since been deactivated.
    ids = [i for i in (set(targets) | set(won) | set(invoiced)) if i is not None and i not in people]
    if ids:
        people.update({u.id: u for u in db.execute(select(User).where(User.id.in_(ids))).scalars()})

    if not crm_service.sees_all(context):
        # Own records only: your row, and "team" means you.
        people = {context.user.id: people.get(context.user.id, context.user)}
        targets = {k: v for k, v in targets.items() if k == context.user.id}
        won = {k: v for k, v in won.items() if k == context.user.id}
        invoiced = {k: v for k, v in invoiced.items() if k == context.user.id}

    rows = []
    for user in sorted(people.values(), key=lambda u: u.display_name.lower()):
        if not user.active and user.id not in targets and user.id not in won and user.id not in invoiced:
            continue
        target = targets.get(user.id, 0.0)
        count, value = won.get(user.id, (0, 0.0))
        sold_count, sold = invoiced.get(user.id, (0, 0.0))
        achieved = sold if measure == "invoiced" else value
        rows.append({
            "user_id": user.id,
            "name": user.display_name,
            "active": user.active,
            "target": target,
            "won_value": value,
            "won_count": count,
            "invoiced_value": sold,
            "invoiced_count": sold_count,
            "forecast": forecast.get(user.id, 0.0),
            "pct": round(achieved / target * 100) if target else None,
        })
    unowned_count, unowned_value = won.get(None, (0, 0.0))
    team_target = sum(targets.values())
    team_won = sum(value for _, value in won.values())
    team_invoiced = sum(value for _, value in invoiced.values())
    team_achieved = team_invoiced if measure == "invoiced" else team_won
    return {
        "month": f"{month:%Y-%m}",
        "basis": measure,
        "rows": rows,
        "team_target": team_target,
        "team_won": team_won,
        "team_invoiced": team_invoiced,
        "team_pct": round(team_achieved / team_target * 100) if team_target else None,
        "unowned_won_value": unowned_value,
        "unowned_won_count": unowned_count,
    }


def set_targets(db: Session, context: RequestContext, month: date, targets: list[tuple[UUID, Decimal]]) -> None:
    """Sets each listed person's target for the month; 0 removes it."""

    people = {u.id for u in crm_service.list_assignees(db, context)}
    for user_id, amount in targets:
        if user_id not in people:
            raise ConflictError("Targets can only be set for users of this company.")
        if not Decimal(0) <= amount < MAX_TARGET:
            raise ConflictError("A target must be zero or more.")
    for user_id, amount in targets:
        existing = db.execute(
            select(SalesTarget).where(
                SalesTarget.company_id == context.company_id, SalesTarget.user_id == user_id,
                SalesTarget.month == month,
            )
        ).scalar_one_or_none()
        if amount == 0:
            if existing is not None:
                db.delete(existing)
        elif existing is None:
            db.add(SalesTarget(tenant_id=context.tenant_id, company_id=context.company_id,
                               user_id=user_id, month=month, amount=amount))
        else:
            existing.amount = amount
    db.commit()
