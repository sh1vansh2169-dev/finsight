"""Parsing and normalisation of raw statement values.

Every parser either returns a clean value or raises CleaningError. Nothing
here guesses: a value that could be read two ways is rejected so the row
shows up in the import report instead of silently corrupting totals.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal


class CleaningError(ValueError):
    """A raw value could not be parsed safely."""


_CENT = Decimal("0.01")
_CURRENCY_TOKENS = re.compile(r"₹|\$|€|£|\brs\.?|\b(?:inr|usd|eur|gbp)", re.IGNORECASE)
_DR_CR_SUFFIX = re.compile(r"\s*(cr|dr)\.?$", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"\d+(\.\d+)?|\.\d+")
# Western (1,234,567.89) and Indian (12,34,567.89) grouping. The last group
# must be three digits, which rejects decimal commas such as "12,50".
_GROUPED_NUMBER = re.compile(r"\d{1,3}(,\d{2,3})*,\d{3}(\.\d+)?")

_ISO_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_TIME_SUFFIX = re.compile(
    r"[T\s]+\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\s*(am|pm)?$", re.IGNORECASE
)
_DAY_FIRST_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y")
_MONTH_FIRST_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y")
_NAMED_MONTH_FORMATS = (
    "%d %b %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


def parse_amount(text: str | None) -> Decimal:
    """Parse a money string into a Decimal rounded to two places.

    Handles currency symbols/codes, thousands separators, and the usual ways
    statements mark a negative: leading or trailing minus, parentheses, or a
    DR suffix. A CR suffix forces the value positive.
    """
    if text is None or not text.strip():
        raise CleaningError("missing amount")
    s = unicodedata.normalize("NFKC", text).replace("−", "-").strip()

    forced_sign = None
    suffix = _DR_CR_SUFFIX.search(s)
    if suffix:
        forced_sign = -1 if suffix.group(1).lower() == "dr" else 1
        s = s[: suffix.start()]

    s = _CURRENCY_TOKENS.sub("", s).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if s.endswith("-"):
        negative = True
        s = s[:-1]
    s = s.replace(" ", "")

    if not (_PLAIN_NUMBER.fullmatch(s) or _GROUPED_NUMBER.fullmatch(s)):
        raise CleaningError(f"unparseable amount: {text.strip()!r}")
    value = Decimal(s.replace(",", "")).quantize(_CENT, rounding=ROUND_HALF_UP)

    if forced_sign is not None:
        return value * forced_sign
    return -value if negative else value


def parse_date(text: str | None, *, day_first: bool = True) -> date:
    """Parse a statement date. Any time-of-day component is discarded.

    ISO (year-first) and named-month dates are unambiguous. For numeric dates
    like 03/04/2026, ``day_first`` decides the reading and there is no
    fallback to the other order, so one file is never parsed two ways.
    """
    if text is None or not text.strip():
        raise CleaningError("missing date")
    s = _TIME_SUFFIX.sub("", text.strip())

    iso = _ISO_DATE.fullmatch(s)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            raise CleaningError(f"invalid date: {text.strip()!r}") from None

    numeric = _DAY_FIRST_FORMATS if day_first else _MONTH_FIRST_FORMATS
    for fmt in (*numeric, *_NAMED_MONTH_FORMATS):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise CleaningError(f"invalid date: {text.strip()!r}")


def clean_description(text: str | None) -> str:
    """Unicode-normalise and collapse whitespace; keeps the original case."""
    if text is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalize_key(text: str) -> str:
    """Case- and punctuation-insensitive form used for matching, not display."""
    return re.sub(r"[^a-z0-9]+", " ", clean_description(text).casefold()).strip()
