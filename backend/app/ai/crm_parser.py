"""Deterministic understanding for CRM commands in Ask ERP.

Pure text functions — no database. The orchestrator classifies the intent
and pulls out the pieces (activity type, stage, reason, date/time, note);
names are resolved separately against the tenant's real records
(app.ai.crm_resolver), so phrasing doesn't have to follow a template.

Like orchestrator.py, this is the no-API-key stand-in for an LLM: the tools
it feeds (toolgateway/tools_crm.py) are what a model would call too.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# --- Intent ---------------------------------------------------------------

INTENTS = (
    "sales.create_quotation",
    "crm.overdue",
    "crm.stale",
    "crm.pipeline",
    "crm.move_stage",
    "crm.schedule_followup",
    "crm.log_activity",
    "unknown",
)

_QUESTION = re.compile(r"\b(what|which|how|show|list|any|who|tell me)\b|\?")
_OVERDUE = re.compile(
    r"\b(overdue|late|missed|due today|due tomorrow|what'?s due|what is due|follow[- ]?ups?|to[- ]?do|agenda|my day|today'?s (tasks|calls|follow))\b"
)
_STALE = re.compile(r"\b(stale|idle|going cold|gone cold|cold deals?|rotting|untouched|neglected|going quiet|no activity)\b")
_PIPELINE = re.compile(r"\b(pipeline|forecast|win rate|how much .*deals?|deals? worth|open deals)\b")
_STAGE_VERB = re.compile(r"\b(mark|move|set|change|update|put)\b|\bwe (won|lost)\b|\b(won|lost) the\b")
_QUOTE_CREATE = re.compile(r"\b(create|make|prepare|draft|new|raise|generate)\b.*\b(quotation|quote)\b|\b(quotation|quote) for\b")
_REMIND = re.compile(r"\b(remind|reminder|schedule|follow[- ]?up|set up a|book a)\b")
_ACTION_VERB = re.compile(r"\b(call|ring|phone|meet|visit|whatsapp|message|email|mail|send)\b")
_LOG = re.compile(
    r"\b(log|logged|called|rang|phoned|spoke|spoken|talked|met|visited|whatsapp(ed)?|messaged|emailed|mailed|had a (call|meeting)|just (called|met|spoke))\b"
)

STAGES = {
    "new": "New",
    "qualified": "Qualified",
    "proposal": "Proposal",
    "negotiation": "Negotiation",
    "negotiating": "Negotiation",
    "won": "Won",
    "lost": "Lost",
}
_STAGE_WORD = re.compile(r"\b(" + "|".join(STAGES) + r")\b")


def classify_intent(text: str, now: datetime | None = None) -> str:
    t = text.lower()
    if _QUOTE_CREATE.search(t) or (
        re.search(r"\b(quotation|quote)\b", t) and re.search(r"\d+\s*(boxes?|units?|pcs?|pieces?)\b", t)
    ):
        return "sales.create_quotation"
    if _STALE.search(t):
        return "crm.stale"
    if _PIPELINE.search(t) and (_QUESTION.search(t) or len(t.split()) <= 4):
        return "crm.pipeline"
    if _STAGE_WORD.search(t) and _STAGE_VERB.search(t) and not _QUESTION.search(t):
        return "crm.move_stage"
    if _OVERDUE.search(t) and (_QUESTION.search(t) or len(t.split()) <= 5):
        return "crm.overdue"
    has_when = parse_when(text, now or datetime.now())[0] is not None
    if _REMIND.search(t) or (has_when and _ACTION_VERB.search(t) and not _LOG.search(t)):
        return "crm.schedule_followup"
    if _LOG.search(t):
        return "crm.log_activity"
    return "unknown"


def wants_everyone(text: str) -> bool:
    """'what's overdue for the team' vs the default: just mine."""
    return bool(re.search(r"\b(team|everyone|everybody|all of us|whole|company)\b", text.lower()))


# --- Activity type, stage, reason, note ----------------------------------------

_TYPE_WORDS = [
    ("WhatsApp", r"\b(whatsapp(ed)?|wa message|messaged on whatsapp)\b"),
    ("Meeting", r"\b(meet|met|meeting|visit(ed)?|demo)\b"),
    ("Email", r"\b(e-?mail(ed)?|mailed|mail)\b"),
    ("Call", r"\b(call(ed)?|rang|ring|phone(d)?|spoke|spoken|talked)\b"),
    ("Note", r"\bnote\b"),
]


def activity_type(text: str, default: str = "Task") -> str:
    t = text.lower()
    for kind, pattern in _TYPE_WORDS:
        if re.search(pattern, t):
            return kind
    return default


def target_stage(text: str) -> str | None:
    # "move X from proposal to negotiation": the stage after "to" wins.
    t = text.lower()
    after_to = re.search(r"\bto\s+(" + "|".join(STAGES) + r")\b", t)
    if after_to:
        return STAGES[after_to.group(1)]
    found = _STAGE_WORD.findall(t)
    return STAGES[found[-1]] if found else None


_SEPARATOR = re.compile(r"\s(?:—|–|-|:)\s|[:,]\s|\b(?:because|as|since|reason|saying|said|about|regarding|re:|to discuss)\b\s*", re.IGNORECASE)


def trailing_note(text: str) -> str:
    """The free text after a separator: "log a call with X — no answer" -> "no answer"."""
    parts = _SEPARATOR.split(text, maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[-1].strip(" .,-—–:") if parts[-1] else ""


def lost_reason(text: str) -> str:
    """The reason after the *last* separator — deal names can contain dashes
    ("Mark Malabar — branch expansion lost — price too high")."""
    parts = [p for p in _SEPARATOR.split(text) if p and p.strip()]
    if len(parts) < 2:
        return ""
    reason = parts[-1].strip(" .,-—–:")
    return "" if crm_stage_only(reason) else reason


def crm_stage_only(fragment: str) -> bool:
    return fragment.lower().strip() in {"lost", "mark lost", "as lost"}


# --- When ---------------------------------------------------------------------

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


@dataclass
class When:
    at: datetime  # naive, in the user's local time
    has_time: bool


def _parse_time(t: str) -> time | None:
    m = re.search(r"\b(?:at|by|@)?\s*(\d{1,2})(?::|\.)(\d{2})\s*(am|pm)?\b", t)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"\b(?:at|by|@)\s*(\d{1,2})\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b", t)
        if not m:
            for word, hour in (("morning", 10), ("noon", 12), ("afternoon", 15), ("evening", 18), ("tonight", 19)):
                if re.search(rf"\b{word}\b", t):
                    return time(hour)
            return None
        h = int(m.group(1) or m.group(3))
        mi = 0
        ap = m.group(2) or m.group(4)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if ap is None and 1 <= h <= 7:
        h += 12  # "at 3" in a business context means 3 pm
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return time(h, mi)


def _parse_date(t: str, today: date) -> date | None:
    if re.search(r"\bday after tomorrow\b", t):
        return today + timedelta(days=2)
    if re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        return today
    if re.search(r"\btomorrow\b|\btmrw\b|\bnaale\b", t):  # naale: Malayalam "tomorrow"
        return today + timedelta(days=1)
    m = re.search(r"\bin (\d+|a|an|one|two|three) (day|days|week|weeks)\b", t)
    if m:
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1)) or int(m.group(1))
        return today + timedelta(days=n * (7 if m.group(2).startswith("week") else 1))
    if re.search(r"\bnext week\b", t):
        return today + timedelta(days=7 - today.weekday())  # next Monday
    m = re.search(r"\b(next\s+|this\s+|on\s+)?(" + "|".join(_WEEKDAYS) + r"|mon|tue|tues|wed|thu|thurs|fri|sat|sun)\b", t)
    if m:
        name = m.group(2)
        target = next(i for i, d in enumerate(_WEEKDAYS) if d.startswith(name[:3]))
        # "friday" / "next friday" both mean the coming one; the preview shows the exact date.
        ahead = (target - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE + r"\b", t) or re.search(
        r"\b" + _MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", t
    )
    if m:
        groups = m.groups()
        day_s = groups[0] if groups[0] and groups[0].isdigit() else groups[1]
        mon_s = groups[1] if groups[0] and groups[0].isdigit() else groups[0]
        d = date(today.year, _MONTHS[mon_s[:3]], int(day_s))
        return d if d >= today else date(today.year + 1, d.month, d.day)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)  # dd/mm — Indian order
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        year += 2000 if year < 100 else 0
        return date(year, int(m.group(2)), int(m.group(1)))
    return None


def parse_when(text: str, now: datetime) -> tuple[When | None, str]:
    """Finds a date/time in `text`, relative to `now` (the user's local time).
    A time with no date means today (or tomorrow if that time has passed);
    a date with no time defaults to 10:00."""

    t = text.lower()
    try:
        day = _parse_date(t, now.date())
    except ValueError:  # e.g. 31/02
        return None, "That date doesn't exist."
    at = _parse_time(t)
    if day is None and at is None:
        return None, ""
    if day is None:
        day = now.date() if datetime.combine(now.date(), at) > now else now.date() + timedelta(days=1)
    return When(datetime.combine(day, at or time(10, 0)), has_time=at is not None), ""
