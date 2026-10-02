"""The company's own details for tax invoices, and sales defaults."""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import regimes, tax
from app.domain.errors import ConflictError
from app.domain.gstin import normalize_gstin
from app.models.documents import Invoice, SalesOrder
from app.models.sales import Quotation
from app.models.tenant import Company
from app.schemas.sales import CompanyProfile, CompanyProfileUpdate

FIELDS = (
    "country", "currency", "fy_start_month", "legal_name", "name_ar", "gstin", "state_code", "vat_number", "cr_number",
    "address", "building_no", "street", "district", "city", "postal_code", "phone", "email", "bank_details", "invoice_terms",
    "payment_terms_days", "quotation_validity_days", "allow_negative_stock", "reminders_enabled",
    "reminder_before_days", "reminder_after_days",
)


def has_documents(db: Session, company_id) -> bool:
    """Whether the company has any sales documents — after which its country is fixed."""

    return any(db.execute(select(exists().where(model.company_id == company_id))).scalar()
               for model in (Quotation, SalesOrder, Invoice))


def regime_info(regime: regimes.Regime) -> dict:
    return {
        "country": regime.country, "country_name": regime.country_name, "currency": regime.currency,
        "tax_name": regime.tax_name, "tax_id_label": regime.tax_id_label,
        "rates": [float(r) for r in regime.rates], "categories": list(regime.categories),
        "round_to_unit": regime.round_to_unit, "split_by_state": regime.split_by_state,
        "postal_code_digits": regime.postal_code_digits,
        "exemption_reasons": regimes.EXEMPTION_REASONS if regime.categories else {},
    }


def profile(db: Session, context: RequestContext) -> CompanyProfile:
    company = db.get(Company, context.company_id)
    return CompanyProfile(name=company.name, country_locked=has_documents(db, company.id),
                          regime=regime_info(regimes.of(company)), **{f: getattr(company, f) for f in FIELDS})


def update_profile(db: Session, context: RequestContext, body: CompanyProfileUpdate) -> CompanyProfile:
    company = db.get(Company, context.company_id, with_for_update=True, populate_existing=True)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    try:
        if "country" in data:
            data["country"] = regimes.clean_country(data["country"])
            if data["country"] != company.country:
                if has_documents(db, company.id):
                    raise ConflictError("The country can't change once the company has quotations, orders or invoices "
                                        "— a company registered elsewhere is a new company.")
                new = regimes.REGIMES[data["country"]]
                data["currency"] = new.currency
                data.setdefault("fy_start_month", new.fy_start_month)
        regime = regimes.REGIMES[data.get("country", company.country or "IN")]
        if "fy_start_month" in data and data["fy_start_month"] != company.fy_start_month and has_documents(db, company.id):
            raise ConflictError("The financial year can't change once the company has documents — numbering follows it.")
        if "vat_number" in data:
            data["vat_number"] = regimes.clean_vat_number(data["vat_number"])
        if "cr_number" in data:
            data["cr_number"] = regimes.clean_cr_number(data["cr_number"])
        if "postal_code" in data:
            data["postal_code"] = regimes.clean_postal_code(regime, data["postal_code"])
        if "building_no" in data and regime.country == "SA":
            data["building_no"] = regimes.clean_building_no(data["building_no"])
        if "gstin" in data:
            data["gstin"] = normalize_gstin(data["gstin"])
        if "state_code" in data:
            data["state_code"] = tax.clean_state(data["state_code"])
        if "reminder_after_days" in data:
            from app.domain.reminder_service import parse_days

            data["reminder_after_days"] = ",".join(str(d) for d in parse_days(data["reminder_after_days"]))
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    for key in ("legal_name", "name_ar", "address", "street", "district", "city", "phone", "email", "bank_details",
                "invoice_terms"):
        if key in data:
            data[key] = data[key].strip()
    gstin = data.get("gstin", company.gstin)
    state = data.get("state_code", company.state_code)
    if gstin:
        if "state_code" in data and state and state != gstin[:2]:
            raise ConflictError(f"The GSTIN is registered in state {gstin[:2]}, not {state}.")
        data["state_code"] = gstin[:2]
    for key, value in data.items():
        setattr(company, key, value)
    db.commit()
    return profile(db, context)
