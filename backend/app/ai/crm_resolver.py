"""Finds which lead, customer or deal a sentence is about.

Instead of pulling a name out with a regex ("with <Name>"), every record the
user can see is scored by how many of its distinctive words appear in the
sentence. "log a call with rahman" finds "Rahman Traders"; generic words
("traders", "hardware", "co") alone never match; ties become a question.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.models.crm import OPEN_STAGES, Lead, Opportunity
from app.models.sales import Customer

# Words too common in business names to identify anyone on their own.
_GENERIC = {
    "traders", "trading", "trade", "co", "company", "and", "the", "ltd", "limited", "pvt", "private",
    "llp", "inc", "group", "enterprises", "enterprise", "industries", "store", "stores", "shop", "agencies",
    "agency", "new", "deal", "opportunity", "hardware", "steel", "tiles", "build", "mart", "corporation",
    "sons", "brothers", "bros", "india", "kerala", "q1", "q2", "q3", "q4", "restock", "expansion", "branch",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _distinct(name: str) -> set[str]:
    words = {t for t in _tokens(name) if len(t) >= 3}
    # A name made only of generic words ("Steel Traders") still has to be findable.
    return (words - _GENERIC) or words


@dataclass
class Match:
    kind: str  # "lead" | "customer" | "opportunity"
    id: UUID
    label: str
    customer_id: UUID | None
    score: float
    open: bool = True


def _score(text_tokens: set[str], text_lower: str, *names: str) -> float:
    best = 0.0
    for name in names:
        if not name:
            continue
        distinct = _distinct(name)
        if not distinct:
            continue
        hit = sum(1 for t in distinct if t in text_tokens or any(w.startswith(t) for w in text_tokens if len(t) >= 4))
        if hit == 0:
            continue
        score = hit / len(distinct)
        if name.lower() in text_lower:
            score += 0.5  # the full name was typed out
        best = max(best, score)
    return best


def find(db: Session, context: RequestContext, text: str, *, kinds: tuple[str, ...]) -> list[Match]:
    """Records mentioned in `text`, best first. Only the caller's company."""

    text_lower = text.lower()
    text_tokens = set(_tokens(text))
    scope = lambda model: (model.tenant_id == context.tenant_id, model.company_id == context.company_id)  # noqa: E731
    matches: list[Match] = []

    if "lead" in kinds:
        for lead in db.execute(select(Lead).where(*scope(Lead), Lead.status.notin_(("Converted", "Lost")))).scalars():
            s = _score(text_tokens, text_lower, lead.company_name, lead.name)
            if s:
                label = f"{lead.company_name} ({lead.name})" if lead.company_name else lead.name
                matches.append(Match("lead", lead.id, label, None, s))
    if "customer" in kinds:
        for c in db.execute(select(Customer).where(*scope(Customer), Customer.active.is_(True))).scalars():
            s = _score(text_tokens, text_lower, c.name)
            if s:
                matches.append(Match("customer", c.id, c.name, c.id, s))
    if "opportunity" in kinds:
        for o in db.execute(select(Opportunity).where(*scope(Opportunity))).scalars():
            s = _score(text_tokens, text_lower, o.name, o.customer.name)
            if s:
                matches.append(Match("opportunity", o.id, o.name, o.customer_id, s, open=o.stage in OPEN_STAGES))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def top(matches: list[Match]) -> list[Match]:
    """All matches tied for the best score (more than one = ask which)."""
    if not matches:
        return []
    best = matches[0].score
    return [m for m in matches if m.score >= best - 1e-9]


def open_deals_for_customer(db: Session, context: RequestContext, customer_id: UUID) -> list[Opportunity]:
    return list(
        db.execute(
            select(Opportunity).where(
                Opportunity.tenant_id == context.tenant_id,
                Opportunity.company_id == context.company_id,
                Opportunity.customer_id == customer_id,
                Opportunity.stage.in_(OPEN_STAGES),
            )
        ).scalars()
    )
