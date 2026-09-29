"""Sales domain logic: the deterministic business rules a tool handler wraps.

Nothing here knows about AI, prompts or the tool gateway — it is exactly the
service layer a conventional "New Quotation" form would call. That is the
point: the AI path and the human-form path must run the same code, so
neither can bypass pricing, stock or discount-policy rules.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.models.sales import Customer, Item, Quotation, QuotationLine

DISCOUNT_AUTO_APPROVE_LIMIT_PCT = 2.0


class DomainValidationError(Exception):
    """A business-rule failure a caller should see verbatim (ambiguous customer,
    unknown item, insufficient stock, ...)."""


@dataclass
class PricedLine:
    item: Item
    qty: float
    unit_price: float
    line_total: float


@dataclass
class QuotationPricing:
    customer: Customer
    lines: list[PricedLine]
    subtotal: float
    discount_pct: float
    discount_amount: float
    total: float
    requires_approval: bool
    warnings: list[str]


def find_customer_by_name(db: Session, context: RequestContext, name: str) -> Customer:
    stmt = select(Customer).where(
        Customer.tenant_id == context.tenant_id,
        Customer.company_id == context.company_id,
        func.lower(Customer.name) == name.strip().lower(),
        Customer.active.is_(True),
    )
    customer = db.execute(stmt).scalar_one_or_none()
    if customer is None:
        raise DomainValidationError(f"No active customer matches '{name}'.")
    return customer


def find_item_by_name(db: Session, context: RequestContext, name: str) -> Item:
    stmt = select(Item).where(
        Item.tenant_id == context.tenant_id,
        Item.company_id == context.company_id,
        func.lower(Item.name) == name.strip().lower(),
    )
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        raise DomainValidationError(f"No item matches '{name}'.")
    return item


def price_quotation(
    db: Session,
    context: RequestContext,
    customer_name: str,
    requested_lines: list[dict],
    discount_pct: float,
) -> QuotationPricing:
    """Resolve + enrich + validate — steps 2, 4 and 5 of the Appendix A flow.
    Pure computation: nothing is written to the database yet.
    """

    customer = find_customer_by_name(db, context, customer_name)

    warnings: list[str] = []
    priced_lines: list[PricedLine] = []
    for raw in requested_lines:
        item = find_item_by_name(db, context, raw["item_name"])
        qty = float(raw["qty"])
        if qty <= 0:
            raise DomainValidationError(f"Quantity for '{item.name}' must be positive.")
        if float(item.stock_qty) < qty:
            warnings.append(f"{item.name}: only {item.stock_qty} {item.uom} in stock, {qty} requested.")
        unit_price = float(item.unit_price)
        priced_lines.append(PricedLine(item=item, qty=qty, unit_price=unit_price, line_total=qty * unit_price))

    if not priced_lines:
        raise DomainValidationError("A quotation needs at least one line item.")

    subtotal = sum(line.line_total for line in priced_lines)
    discount_amount = subtotal * (discount_pct / 100)
    total = subtotal - discount_amount

    requires_approval = discount_pct > DISCOUNT_AUTO_APPROVE_LIMIT_PCT
    if requires_approval:
        warnings.append(
            f"Discount {discount_pct:g}% exceeds the {DISCOUNT_AUTO_APPROVE_LIMIT_PCT:g}% "
            "auto-approve limit — this will route to the Sales Manager for approval."
        )

    if float(customer.credit_limit) and total > float(customer.credit_limit):
        warnings.append(
            f"Total ₹{total:,.2f} exceeds {customer.name}'s credit limit of ₹{float(customer.credit_limit):,.2f}."
        )

    return QuotationPricing(
        customer=customer,
        lines=priced_lines,
        subtotal=subtotal,
        discount_pct=discount_pct,
        discount_amount=discount_amount,
        total=total,
        requires_approval=requires_approval,
        warnings=warnings,
    )


def next_quotation_number(db: Session, context: RequestContext) -> str:
    year = datetime.now(timezone.utc).year
    count = db.execute(
        select(func.count()).select_from(Quotation).where(Quotation.tenant_id == context.tenant_id)
    ).scalar_one()
    return f"QT-{year}-{count + 1:05d}"


def persist_quotation(
    db: Session,
    context: RequestContext,
    pricing: QuotationPricing,
    created_by: UUID,
) -> Quotation:
    quotation = Quotation(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        number=next_quotation_number(db, context),
        customer_id=pricing.customer.id,
        subtotal=pricing.subtotal,
        discount_pct=pricing.discount_pct,
        total=pricing.total,
        status="Pending approval" if pricing.requires_approval else "Draft",
        created_by=created_by,
    )
    for line in pricing.lines:
        quotation.lines.append(
            QuotationLine(
                item_id=line.item.id,
                qty=line.qty,
                unit_price=line.unit_price,
                line_total=line.line_total,
            )
        )
    db.add(quotation)
    db.flush()
    return quotation
