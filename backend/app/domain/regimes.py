"""Tax regimes: what changes with the country a company is registered in.

Every company has a country (India or Saudi Arabia for now), chosen when it's
set up and fixed once it has issued a sales document — a move abroad is a new
company, and documents keep the rules they were issued under. Everything
country-specific reads the regime from here instead of assuming India:

- India: GST split into CGST + SGST (within the state) or IGST (between
  states), GSTIN and HSN codes, totals rounded to the rupee, April–March year.
- Saudi Arabia: one VAT line (15% standard, or zero-rated / exempt / out of
  scope), VAT and CR numbers, structured national addresses for ZATCA, totals
  to the halala, January–December year by default.

When a module needs something new per country, add it to Regime rather than
writing `if India`.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.domain.tax import GST_RATES


@dataclass(frozen=True)
class Regime:
    country: str
    country_name: str
    currency: str
    tax_name: str  # what the tax is called on documents
    tax_id_label: str  # the seller's registration number
    rates: tuple[Decimal, ...]
    # ZATCA tax categories: S standard, Z zero-rated, E exempt, O out of scope. Empty: not used.
    categories: tuple[str, ...]
    fy_start_month: int  # default; a company can set its own
    round_to_unit: bool  # grand total rounded to the rupee (India) or kept to the halala
    split_by_state: bool  # CGST + SGST vs IGST
    postal_code_digits: int


INDIA = Regime("IN", "India", "INR", "GST", "GSTIN", GST_RATES, (), 4, True, True, 6)
SAUDI_ARABIA = Regime("SA", "Saudi Arabia", "SAR", "VAT", "VAT number", (Decimal("0"), Decimal("15")),
                      ("S", "Z", "E", "O"), 1, False, False, 5)
REGIMES = {r.country: r for r in (INDIA, SAUDI_ARABIA)}
COUNTRIES = {"IN": "India", "SA": "Saudi Arabia", "AE": "United Arab Emirates", "QA": "Qatar", "OM": "Oman",
             "KW": "Kuwait", "BH": "Bahrain", "US": "United States", "GB": "United Kingdom"}

# Why a line carries no VAT in Saudi Arabia (ZATCA exemption reason codes).
EXEMPTION_REASONS = {
    "VATEX-SA-29": "Financial services (Article 29)",
    "VATEX-SA-29-7": "Life insurance services (Article 29)",
    "VATEX-SA-30": "Real estate transactions (Article 30)",
    "VATEX-SA-32": "Export of goods",
    "VATEX-SA-33": "Export of services",
    "VATEX-SA-34-1": "International transport of goods",
    "VATEX-SA-34-2": "International transport of passengers",
    "VATEX-SA-34-3": "Services directly connected to international transport",
    "VATEX-SA-34-4": "Supply of qualifying means of transport",
    "VATEX-SA-34-5": "Services relating to goods or passenger transport",
    "VATEX-SA-35": "Medicines and medical equipment",
    "VATEX-SA-36": "Qualifying metals",
    "VATEX-SA-EDU": "Private education to citizens",
    "VATEX-SA-HEA": "Private healthcare to citizens",
    "VATEX-SA-OOS": "Out of scope",
}


SYMBOLS = {"INR": "₹", "SAR": "SAR "}


def symbol(currency: str | None) -> str:
    return SYMBOLS.get(currency or "INR", f"{currency} ")


def cur(context) -> str:
    """The currency prefix for amounts in messages: ₹ or SAR."""

    return symbol(getattr(context, "currency", None))


def of(company) -> Regime:
    return REGIMES.get(getattr(company, "country", None) or "IN", INDIA)


def clean_country(code: str | None) -> str:
    code = (code or "").strip().upper()
    if code not in REGIMES:
        raise ValueError(f"Companies can be registered in: {', '.join(r.country_name for r in REGIMES.values())}.")
    return code


def clean_party_country(code: str | None) -> str:
    """A customer's country: "" for the company's own, else a two-letter code."""

    code = (code or "").strip().upper()
    if code and not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError("Country must be a two-letter code (SA, IN, AE…).")
    return code


def clean_rate(regime: Regime, rate) -> Decimal:
    value = Decimal(str(rate))
    if value not in regime.rates:
        raise ValueError(f"{regime.tax_name} rate must be one of {', '.join(f'{r:g}' for r in regime.rates)}%.")
    return value


def clean_category(regime: Regime, category: str | None, rate) -> str:
    """The ZATCA category for an item, consistent with its rate. "" outside Saudi Arabia."""

    if not regime.categories:
        return ""
    category = (category or "").strip().upper() or ("S" if rate and Decimal(str(rate)) > 0 else "Z")
    if category not in regime.categories:
        raise ValueError("VAT category must be S (standard), Z (zero-rated), E (exempt) or O (out of scope).")
    if rate is not None and (category == "S") != (Decimal(str(rate)) > 0):
        raise ValueError("Standard-rated (S) items carry 15% VAT; zero-rated, exempt and out-of-scope items carry 0%.")
    return category


def clean_vat_number(value: str | None) -> str:
    """Saudi VAT registration number: 15 digits, starting and ending with 3."""

    value = re.sub(r"\s", "", value or "")
    if value and not re.fullmatch(r"3\d{13}3", value):
        raise ValueError("A Saudi VAT number is 15 digits, starting and ending with 3.")
    return value


def clean_cr_number(value: str | None) -> str:
    """Commercial Registration number: 10 digits."""

    value = re.sub(r"\s", "", value or "")
    if value and not re.fullmatch(r"\d{10}", value):
        raise ValueError("A Commercial Registration (CR) number is 10 digits.")
    return value


def clean_postal_code(regime: Regime, value: str | None) -> str:
    value = re.sub(r"\s", "", value or "")
    if value and not re.fullmatch(rf"\d{{{regime.postal_code_digits}}}", value):
        label = "PIN code" if regime.country == "IN" else "postal code"
        raise ValueError(f"A {label} is {regime.postal_code_digits} digits.")
    return value


def clean_building_no(value: str | None) -> str:
    value = re.sub(r"\s", "", value or "")
    if value and not re.fullmatch(r"\d{4}", value):
        raise ValueError("A Saudi building number is 4 digits.")
    return value
