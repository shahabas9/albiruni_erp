"""A minimal stand-in for the "AI Orchestrator + Model Gateway" layer.

This is intentionally NOT a real LLM integration — it is a small
regex-based intent classifier and entity extractor, just enough to drive
the same Understand -> Resolve -> Validate -> Preview -> Confirm -> Execute
pipeline from Appendix A end-to-end without an external API key. Swapping
this module for a real LLM call (with the tool registry exposed as
function-calling tools) is the natural next step; nothing downstream of it
— the tool gateway, audit trail, permission checks — needs to change when
that happens, which is the whole point of the layering.
"""

import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

QUOTATION_KEYWORDS = ("quotation", "quote")

_QTY_LINE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s+(?:boxes?|units?|pcs?|pieces?)\s+((?:[A-Z][\w]*\s*)+)",
)
_DISCOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*discount", re.IGNORECASE)
_CUSTOMER_RE = re.compile(r"for\s+([A-Z][A-Za-z&.\- ]*?)(?=[:,]|\s+\d|$)")


@dataclass
class ParsedQuotationRequest:
    customer_name: str | None
    lines: list[dict[str, Any]]
    discount_pct: float


def classify_intent(text: str) -> str:
    lowered = text.lower()
    if any(kw in lowered for kw in QUOTATION_KEYWORDS):
        return "sales.create_quotation"
    return "unknown"


def parse_quotation_request(text: str) -> ParsedQuotationRequest:
    customer_match = _CUSTOMER_RE.search(text)
    customer_name = customer_match.group(1).strip() if customer_match else None

    lines = [
        {"item_name": " ".join(name.split()), "qty": float(qty)}
        for qty, name in _QTY_LINE_RE.findall(text)
    ]

    discount_match = _DISCOUNT_RE.search(text)
    discount_pct = float(discount_match.group(1)) if discount_match else 0.0

    return ParsedQuotationRequest(customer_name=customer_name, lines=lines, discount_pct=discount_pct)


# --- Preview cache -----------------------------------------------------
#
# "Bind confirmation to an immutable action preview, user, context and
# expiration time" (Section 5). A real deployment puts this in Redis so it
# survives restarts and works across multiple API workers; an in-process
# dict is enough for a single-process dev skeleton.

PREVIEW_TTL = timedelta(minutes=10)


@dataclass
class PendingPreview:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tool_name: str
    intent: str
    request_text: str
    correlation_id: str
    args: dict[str, Any]
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + PREVIEW_TTL)


_PREVIEWS: dict[str, PendingPreview] = {}


def store_preview(preview: PendingPreview) -> str:
    token = secrets.token_urlsafe(18)
    _PREVIEWS[token] = preview
    return token


def pop_preview(token: str) -> PendingPreview | None:
    preview = _PREVIEWS.pop(token, None)
    if preview is None:
        return None
    if datetime.now(timezone.utc) > preview.expires_at:
        return None
    return preview


def new_correlation_id() -> str:
    return f"corr_{secrets.token_hex(6)}"
