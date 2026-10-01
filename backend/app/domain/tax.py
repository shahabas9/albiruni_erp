"""Indian GST arithmetic shared by every sales document.

Pure functions, no database: quotations, orders, invoices and credit notes
all price their lines through compute(), so a figure can never differ
between the quote a customer saw and the invoice they receive.

Rules applied:
- Prices exclude GST; tax is added on top.
- A line's own discount, then the document's discount, come off each line
  before tax.
- Supply within the seller's state: CGST + SGST, half the rate each.
  Supply to another state: IGST at the full rate.
- Each tax amount is rounded to the paisa per line; the grand total is
  rounded to the nearest rupee and the difference shown as "round off".
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# GST state codes (the first two digits of a GSTIN).
STATES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}
# Codes that appear in older GSTINs but are no longer offered for new records.
LEGACY_STATES = {"25": "Daman and Diu", "28": "Andhra Pradesh (old)"}

# Rates in use. 12% and 28% remain for goods not moved by the 2025 rate changes.
GST_RATES = (Decimal("0"), Decimal("0.25"), Decimal("3"), Decimal("5"), Decimal("12"), Decimal("18"),
             Decimal("28"), Decimal("40"))

PAISA = Decimal("0.01")
RUPEE = Decimal("1")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def state_name(code: str) -> str:
    return STATES.get(code) or LEGACY_STATES.get(code) or ""


def clean_state(code: str | None) -> str:
    """"" or a known two-digit code; raises ValueError otherwise."""

    code = (code or "").strip()
    if not code:
        return ""
    if code.isdigit() and len(code) == 1:
        code = "0" + code
    if code not in STATES and code not in LEGACY_STATES:
        raise ValueError(f"'{code}' isn't a GST state code.")
    return code


def clean_rate(rate) -> Decimal:
    value = Decimal(str(rate))
    if value not in GST_RATES:
        raise ValueError(f"GST rate must be one of {', '.join(f'{r:g}' for r in GST_RATES)}%.")
    return value


def clean_hsn(code: str | None) -> str:
    code = (code or "").strip().replace(" ", "")
    if code and (not code.isdigit() or len(code) not in (4, 6, 8)):
        raise ValueError("HSN/SAC code must be 4, 6 or 8 digits.")
    return code


@dataclass
class LineIn:
    qty: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    # This line's own discount, before the document's.
    discount_pct: Decimal = Decimal(0)


@dataclass
class LineTax:
    amount: Decimal  # qty × price, before discount
    taxable: Decimal  # after the document discount
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


@dataclass
class DocumentTax:
    lines: list[LineTax]
    subtotal: Decimal  # sum of line amounts
    discount_amount: Decimal
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    round_off: Decimal
    grand_total: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


def compute(lines: list[LineIn], discount_pct, interstate: bool) -> DocumentTax:
    discount = Decimal(str(discount_pct or 0))
    out: list[LineTax] = []
    for line in lines:
        amount = money(line.qty * line.unit_price)
        line_discount = Decimal(str(line.discount_pct or 0))
        taxable = money(amount * (100 - line_discount) / 100 * (100 - discount) / 100)
        if interstate:
            cgst = sgst = Decimal("0.00")
            igst = money(taxable * line.gst_rate / 100)
        else:
            cgst = sgst = money(taxable * line.gst_rate / 200)
            igst = Decimal("0.00")
        out.append(LineTax(amount, taxable, cgst, sgst, igst))
    subtotal = sum((l.amount for l in out), Decimal("0.00"))
    taxable = sum((l.taxable for l in out), Decimal("0.00"))
    cgst = sum((l.cgst for l in out), Decimal("0.00"))
    sgst = sum((l.sgst for l in out), Decimal("0.00"))
    igst = sum((l.igst for l in out), Decimal("0.00"))
    exact = taxable + cgst + sgst + igst
    grand = exact.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return DocumentTax(out, subtotal, subtotal - taxable, taxable, cgst, sgst, igst, grand - exact, money(grand))


def place_of_supply(company_state: str, customer_state: str) -> tuple[str, bool, list[str]]:
    """(place of supply, interstate?, warnings). An unknown customer state is
    treated as within the seller's state (an over-the-counter sale)."""

    warnings = []
    if not company_state:
        warnings.append("Your company's GST state isn't set (Sales → Company & GST), so tax is shown as CGST + SGST.")
    if not customer_state:
        if company_state:
            warnings.append("This customer's state isn't set, so the sale is treated as within your state.")
        return company_state, False, warnings
    return customer_state, bool(company_state) and customer_state != company_state, warnings


# --- Financial years and words --------------------------------------------------------


def fy_start_year(day: date) -> int:
    """Indian financial year: April to March. 30 Sep 2026 → 2026 (FY 2026-27)."""

    return day.year if day.month >= 4 else day.year - 1


def fy_label(day: date) -> str:
    start = fy_start_year(day)
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    hundred, rest = divmod(n, 100)
    parts = [f"{_ONES[hundred]} Hundred"] if hundred else []
    if rest:
        parts.append(_two(rest))
    return " ".join(parts)


def _indian(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{_indian(crore)} Crore")
    if lakh:
        parts.append(f"{_two(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two(thousand)} Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts)


def amount_in_words(amount) -> str:
    """"Rupees One Lakh Twenty Thousand and Fifty Paise Only"."""

    value = money(amount)
    sign = "Minus " if value < 0 else ""
    rupees, paise = divmod(int(abs(value) * 100), 100)
    words = f"{sign}Rupees {_indian(rupees)}"
    if paise:
        words += f" and {_two(paise)} Paise"
    return words + " Only"
