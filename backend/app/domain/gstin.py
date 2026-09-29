"""GSTIN (Indian GST registration number) validation.

Format: 2-digit state code, 10-character PAN, entity number, 'Z', and a
check character computed with the GSTN mod-36 algorithm — so a mistyped
character is caught here, not when a tax invoice bounces.
"""

import re

_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def check_character(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def normalize_gstin(value: str) -> str:
    """Returns the upper-cased GSTIN, or "" for none. Raises ValueError if invalid."""

    gstin = value.strip().upper()
    if not gstin:
        return ""
    if not _PATTERN.match(gstin):
        raise ValueError("GSTIN must be 15 characters: state code, PAN, entity number, 'Z' and a check character.")
    if not 1 <= int(gstin[:2]) <= 38 and gstin[:2] != "97":
        raise ValueError(f"'{gstin[:2]}' isn't a valid GST state code.")
    if check_character(gstin[:14]) != gstin[14]:
        raise ValueError("That GSTIN's check character doesn't match — check it for a typo.")
    return gstin
