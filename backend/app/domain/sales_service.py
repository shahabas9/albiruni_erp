"""Sales domain logic: the deterministic business rules a tool handler wraps.

Nothing here knows about AI, prompts or the tool gateway — it is exactly the
service layer a conventional "New Quotation" form would call. That is the
point: the AI path and the human-form path must run the same code, so
neither can bypass pricing, stock or discount-policy rules.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.regimes import cur
from app.core.deps import RequestContext
from app.domain import price_lists, regimes, tax
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
    discount_pct: float = 0  # this line's own discount
    taxable_value: float = 0  # after discount
    tax_amount: float = 0
    tax_category: str = ""  # ZATCA category in Saudi Arabia


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
    vat: float = 0
    round_off: float = 0
    grand_total: float = 0  # what the customer pays


def company_of(db: Session, context: RequestContext) -> Company:
    return db.get(Company, context.company_id)


def item_rate(item: Item, warnings: list[str], *, required: bool, tax_name: str = "GST") -> Decimal:
    """The item's tax rate. Missing: an error on tax documents, a warning (and
    no tax) on quotations."""

    if item.gst_rate is not None:
        return Decimal(str(item.gst_rate))
    if required:
        raise DomainValidationError(f"Set the {tax_name} rate for {item.name} (Inventory → Items) first.")
    warnings.append(f"{item.name} has no {tax_name} rate yet, so no tax is added for it.")
    return Decimal("0")


def is_export(company: Company, customer: Customer) -> bool:
    """A customer registered in another country (a Saudi company's sale abroad is zero-rated)."""

    return bool(customer.country) and customer.country != (company.country or "IN")


def line_category(company: Company, customer: Customer, item: Item, rate: Decimal) -> tuple[str, Decimal]:
    """(ZATCA category, rate) for a line: exports are zero-rated; "" outside Saudi Arabia."""

    if regimes.of(company).country != "SA":
        return "", rate
    if is_export(company, customer):
        return "Z", Decimal("0")
    return item.tax_category or ("S" if rate > 0 else "Z"), rate


def apply_tax(
    company: Company, customer: Customer, lines: list[PricedLine], discount_pct: float, warnings: list[str],
    *, rates_required: bool = False,
) -> tuple[tax.DocumentTax, str, bool]:
    """Works out tax for priced lines in place — GST in India, VAT in Saudi Arabia; returns the totals,
    place of supply and interstate flag (Indian concepts: "" and False elsewhere)."""

    regime = regimes.of(company)
    if regime.split_by_state:
        pos, interstate, notes = tax.place_of_supply(company.state_code or "", customer.state_code or "")
        warnings.extend(notes)
    else:
        pos, interstate = "", False
    rates = []
    for line in lines:
        category, rate = line_category(company, customer, line.item,
                                       item_rate(line.item, warnings, required=rates_required, tax_name=regime.tax_name))
        line.tax_category = category
        rates.append(rate)
    result = tax.compute(
        [tax.LineIn(Decimal(str(l.qty)), Decimal(str(l.unit_price)), r, Decimal(str(l.discount_pct or 0)))
         for l, r in zip(lines, rates)],
        discount_pct, interstate, vat=not regime.split_by_state, round_to_unit=regime.round_to_unit,
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


def effective_discount(line_pct: float, doc_pct: float) -> float:
    """A line discount and the document's together: 10% then 5% is 14.5%."""

    return 100 - (100 - float(line_pct or 0)) * (100 - float(doc_pct or 0)) / 100


def find_customer_by_id(db: Session, context: RequestContext, customer_id) -> Customer:
    customer = db.get(Customer, UUID(str(customer_id)))
    if customer is None or customer.tenant_id != context.tenant_id or customer.company_id != context.company_id:
        raise DomainValidationError("That customer doesn't exist.")
    if not customer.active:
        raise DomainValidationError(f"{customer.name} is inactive.")
    return customer


def find_item_by_id(db: Session, context: RequestContext, item_id) -> Item:
    item = db.get(Item, UUID(str(item_id)))
    if item is None or item.tenant_id != context.tenant_id or item.company_id != context.company_id:
        raise DomainValidationError("That item doesn't exist.")
    return item


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
    customer_name: str | None,
    requested_lines: list[dict],
    discount_pct: float,
    *,
    customer_id: UUID | None = None,
) -> QuotationPricing:
    """Resolve + enrich + validate — steps 2, 4 and 5 of the Appendix A flow.
    Pure computation: nothing is written to the database yet. Lines name an
    item (item_name, as Ask ERP does) or pick one (item_id), and may set
    their own unit_price; below the list price needs approval.
    """

    customer = find_customer_by_id(db, context, customer_id) if customer_id else find_customer_by_name(
        db, context, customer_name or "")

    warnings: list[str] = []
    priced_lines: list[PricedLine] = []
    below_list = False
    for raw in requested_lines:
        item = (find_item_by_id(db, context, raw["item_id"]) if raw.get("item_id")
                else find_item_by_name(db, context, raw["item_name"]))
        qty = float(raw["qty"])
        if qty <= 0:
            raise DomainValidationError(f"Quantity for '{item.name}' must be positive.")
        if item.kind != "service" and float(item.stock_qty) < qty:
            warnings.append(f"{item.name}: only {item.stock_qty} {item.uom} in stock, {qty} requested.")
        agreed = price_lists.price_for(db, context, customer, item, qty)
        unit_price = agreed if raw.get("unit_price") is None else float(raw["unit_price"])
        line_discount = float(raw.get("discount_pct") or 0)
        if unit_price < 0 or not 0 <= line_discount <= 100:
            raise DomainValidationError("A price can't be negative, and a line discount must be 0–100%.")
        if unit_price < agreed or effective_discount(line_discount, discount_pct) > DISCOUNT_AUTO_APPROVE_LIMIT_PCT:
            below_list = True
        priced_lines.append(PricedLine(item=item, qty=qty, unit_price=unit_price, discount_pct=line_discount,
                                       line_total=float(tax.money(qty * unit_price))))

    if not priced_lines:
        raise DomainValidationError("A quotation needs at least one line item.")

    worked, pos, interstate = apply_tax(company_of(db, context), customer, priced_lines, discount_pct, warnings)
    subtotal = float(worked.subtotal)
    discount_amount = float(worked.discount_amount)
    total = float(worked.taxable)
    grand_total = float(worked.grand_total)

    requires_approval = discount_pct > DISCOUNT_AUTO_APPROVE_LIMIT_PCT or below_list
    if discount_pct > DISCOUNT_AUTO_APPROVE_LIMIT_PCT:
        warnings.append(
            f"Discount {discount_pct:g}% exceeds the {DISCOUNT_AUTO_APPROVE_LIMIT_PCT:g}% "
            "auto-approve limit — this will route to the Sales Manager for approval."
        )
    if below_list:
        warnings.append("A price is below the agreed price, or a line's discount takes it over the limit — this "
                        "will route to the Sales Manager for approval.")

    if float(customer.credit_limit) and grand_total > float(customer.credit_limit):
        warnings.append(
            f"Total {cur(context)}{grand_total:,.2f} (with tax) exceeds {customer.name}'s credit limit of {cur(context)}{float(customer.credit_limit):,.2f}."
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
        vat=float(worked.vat),
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


def next_document_number(db: Session, context: RequestContext, kind: str, prefix: str, day) -> str:
    """<prefix>/<year>/<n>: counting from 1 per tenant each financial year of
    the company (26-27 for April–March in India, 2026 for a calendar year), as
    GST and ZATCA expect of invoice numbers. The counter row stays locked until
    commit, so numbers are never shared or skipped."""

    start_month = company_of(db, context).fy_start_month or 4
    stmt = (
        pg_insert(DocumentCounter)
        .values(tenant_id=context.tenant_id, kind=kind, year=tax.fy_start_year(day, start_month), last_value=1)
        .on_conflict_do_update(
            index_elements=[DocumentCounter.tenant_id, DocumentCounter.kind, DocumentCounter.year],
            set_={"last_value": DocumentCounter.last_value + 1},
        )
        .returning(DocumentCounter.last_value)
    )
    return f"{prefix}/{tax.fy_label(day, start_month)}/{db.execute(stmt).scalar_one():05d}"


def persist_quotation(
    db: Session,
    context: RequestContext,
    pricing: QuotationPricing,
    created_by: UUID,
    *,
    valid_until=None,
    notes: str = "",
) -> Quotation:
    days = company_of(db, context).quotation_validity_days or 0
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
        vat=pricing.vat,
        round_off=pricing.round_off,
        grand_total=pricing.grand_total,
        status="Pending approval" if pricing.requires_approval else "Draft",
        created_by=created_by,
        valid_until=valid_until or (date.today() + timedelta(days=days) if days else None),
        notes=notes.strip(),
    )
    replace_lines(quotation, pricing)
    db.add(quotation)
    db.flush()
    return quotation


def replace_lines(quotation: Quotation, pricing: QuotationPricing) -> None:
    """Puts pricing's lines and totals on a quotation (new or being edited)."""

    quotation.lines.clear()
    for field in ("subtotal", "discount_pct", "total", "place_of_supply", "cgst", "sgst", "igst", "vat", "round_off",
                  "grand_total"):
        setattr(quotation, field, getattr(pricing, field))
    for line in pricing.lines:
        quotation.lines.append(
            QuotationLine(
                item_id=line.item.id,
                qty=line.qty,
                unit_price=line.unit_price,
                line_total=line.line_total,
                hsn_code=line.item.hsn_code or "",
                gst_rate=line.gst_rate,
                tax_category=line.tax_category,
                discount_pct=line.discount_pct,
                taxable_value=line.taxable_value,
                tax_amount=line.tax_amount,
            )
        )
