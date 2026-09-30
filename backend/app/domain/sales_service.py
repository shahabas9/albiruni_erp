"""Sales domain logic: the deterministic business rules a tool handler wraps.

Nothing here knows about AI, prompts or the tool gateway — it is exactly the
service layer a conventional "New Quotation" form would call. That is the
point: the AI path and the human-form path must run the same code, so
neither can bypass pricing, stock or discount-policy rules.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import tax
from app.models.sales import Customer, DocumentCounter, Item, Quotation, QuotationLine
from app.models.tenant import Company

DISCOUNT_AUTO_APPROVE_LIMIT_PCT = 2.0


class DomainValidationError(Exception):
    """A business-rule failure a caller should see verbatim (ambiguous customer,
    unknown item, insufficient stock, ...)."""


@dataclass
class PricedLine:
    item: Item
    qty: float
    unit_price: float
    line_total: float  # qty × price, before discount
    gst_rate: float = 0
    taxable_value: float = 0  # after discount
    tax_amount: float = 0


@dataclass
class QuotationPricing:
    customer: Customer
    lines: list[PricedLine]
    subtotal: float
    discount_pct: float
    discount_amount: float
    total: float  # after discount, before GST
    requires_approval: bool
    warnings: list[str]
    place_of_supply: str = ""
    interstate: bool = False
    cgst: float = 0
    sgst: float = 0
    igst: float = 0
    round_off: float = 0
    grand_total: float = 0  # what the customer pays


def company_of(db: Session, context: RequestContext) -> Company:
    return db.get(Company, context.company_id)


def item_rate(item: Item, warnings: list[str], *, required: bool) -> Decimal:
    """The item's GST rate. Missing: an error on tax documents, a warning (and
    no tax) on quotations."""

    if item.gst_rate is not None:
        return Decimal(str(item.gst_rate))
    if required:
        raise DomainValidationError(f"Set the GST rate for {item.name} (Inventory → Items) first.")
    warnings.append(f"{item.name} has no GST rate yet, so no tax is added for it.")
    return Decimal("0")


def apply_tax(
    company: Company, customer: Customer, lines: list[PricedLine], discount_pct: float, warnings: list[str],
    *, rates_required: bool = False,
) -> tuple[tax.DocumentTax, str, bool]:
    """Works out GST for priced lines in place; returns the totals, place of supply and interstate flag."""

    pos, interstate, notes = tax.place_of_supply(company.state_code or "", customer.state_code or "")
    warnings.extend(notes)
    rates = [item_rate(line.item, warnings, required=rates_required) for line in lines]
    result = tax.compute(
        [tax.LineIn(Decimal(str(l.qty)), Decimal(str(l.unit_price)), r) for l, r in zip(lines, rates)],
        discount_pct, interstate,
    )
    for line, rate, worked in zip(lines, rates, result.lines):
        line.gst_rate = float(rate)
        line.taxable_value = float(worked.taxable)
        line.tax_amount = float(worked.tax)
    return result, pos, interstate


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
        priced_lines.append(PricedLine(item=item, qty=qty, unit_price=unit_price, line_total=float(tax.money(qty * unit_price))))

    if not priced_lines:
        raise DomainValidationError("A quotation needs at least one line item.")

    worked, pos, interstate = apply_tax(company_of(db, context), customer, priced_lines, discount_pct, warnings)
    subtotal = float(worked.subtotal)
    discount_amount = float(worked.discount_amount)
    total = float(worked.taxable)
    grand_total = float(worked.grand_total)

    requires_approval = discount_pct > DISCOUNT_AUTO_APPROVE_LIMIT_PCT
    if requires_approval:
        warnings.append(
            f"Discount {discount_pct:g}% exceeds the {DISCOUNT_AUTO_APPROVE_LIMIT_PCT:g}% "
            "auto-approve limit — this will route to the Sales Manager for approval."
        )

    if float(customer.credit_limit) and grand_total > float(customer.credit_limit):
        warnings.append(
            f"Total ₹{grand_total:,.2f} (with GST) exceeds {customer.name}'s credit limit of ₹{float(customer.credit_limit):,.2f}."
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
        place_of_supply=pos,
        interstate=interstate,
        cgst=float(worked.cgst),
        sgst=float(worked.sgst),
        igst=float(worked.igst),
        round_off=float(worked.round_off),
        grand_total=grand_total,
    )


def next_quotation_number(db: Session, context: RequestContext) -> str:
    """QT-<year>-<n>, n counting from 1 per tenant each year.

    The first number of a year continues after the highest QT-<year>-… the
    tenant already has (quotations made before the counter existed)."""

    year = datetime.now(timezone.utc).year
    prefix = f"QT-{year}-"
    highest = (
        select(func.coalesce(func.max(cast(func.split_part(Quotation.number, "-", 3), Integer)), 0))
        .where(Quotation.tenant_id == context.tenant_id, Quotation.number.like(f"{prefix}%"))
        .scalar_subquery()
    )
    stmt = (
        pg_insert(DocumentCounter)
        .values(tenant_id=context.tenant_id, kind="quotation", year=year, last_value=highest + 1)
        .on_conflict_do_update(
            index_elements=[DocumentCounter.tenant_id, DocumentCounter.kind, DocumentCounter.year],
            set_={"last_value": DocumentCounter.last_value + 1},
        )
        .returning(DocumentCounter.last_value)
    )
    return f"{prefix}{db.execute(stmt).scalar_one():05d}"


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
        place_of_supply=pricing.place_of_supply,
        cgst=pricing.cgst,
        sgst=pricing.sgst,
        igst=pricing.igst,
        round_off=pricing.round_off,
        grand_total=pricing.grand_total,
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
                hsn_code=line.item.hsn_code or "",
                gst_rate=line.gst_rate,
                taxable_value=line.taxable_value,
                tax_amount=line.tax_amount,
            )
        )
    db.add(quotation)
    db.flush()
    return quotation
