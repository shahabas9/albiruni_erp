"""The company's own details for tax invoices, and sales defaults."""

from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.domain import tax
from app.domain.errors import ConflictError
from app.domain.gstin import normalize_gstin
from app.models.tenant import Company
from app.schemas.sales import CompanyProfile, CompanyProfileUpdate

FIELDS = (
    "legal_name", "gstin", "state_code", "address", "phone", "email", "bank_details", "invoice_terms",
    "payment_terms_days", "quotation_validity_days", "allow_negative_stock",
)


def profile(db: Session, context: RequestContext) -> CompanyProfile:
    company = db.get(Company, context.company_id)
    return CompanyProfile(name=company.name, **{f: getattr(company, f) for f in FIELDS})


def update_profile(db: Session, context: RequestContext, body: CompanyProfileUpdate) -> CompanyProfile:
    company = db.get(Company, context.company_id, with_for_update=True, populate_existing=True)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    try:
        if "gstin" in data:
            data["gstin"] = normalize_gstin(data["gstin"])
        if "state_code" in data:
            data["state_code"] = tax.clean_state(data["state_code"])
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    for key in ("legal_name", "address", "phone", "email", "bank_details", "invoice_terms"):
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
