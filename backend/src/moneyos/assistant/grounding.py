"""Check that every money figure in an answer came from MoneyOS.

Language models can misread, round oddly, add numbers up wrongly or invent
them. So after the model answers, every money-like figure in the answer is
looked up among the figures the tools returned (and the user's own question).
Figures not found are reported as *unverified*, and the app shows them that
way instead of letting them pass as fact.

What counts as a money-like figure: a number with a currency mark (₹, Rs,
INR), a number with decimals, a number of 1,000 or more, or a percentage.
Small whole numbers (counts, days, dates) and bare years (1900-2100) are
not checked.

A figure matches if it equals a tool figure exactly or after rounding that
figure to whole rupees (the model may say "₹1,876" for 1875.56). Signs are
ignored ("spent ₹120" for -120.00). Anything the model calculated itself, such
as a sum of two figures, does not match and is flagged, which is the point.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_NUMBER_IN_DATA = re.compile(r"^-?\d+(\.\d+)?$")
# A figure in prose: optional currency mark, digits with optional Indian or Western commas, optional decimals, optional %.
_FIGURE = re.compile(
    r"(?P<cur>₹|rs\.?|inr)?\s*(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<pct>%)?",
    re.IGNORECASE,
)
_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}(-\d{2})?\b")


def _numbers_in(value: Any) -> Iterable[Decimal]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _numbers_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers_in(v)
    elif isinstance(value, bool):
        return
    elif isinstance(value, (int, float)):
        yield Decimal(str(value))
    elif isinstance(value, str):
        if _NUMBER_IN_DATA.match(value.strip()):
            yield Decimal(value.strip())
        else:  # numbers inside sentences, such as warnings and reasons
            for m in _FIGURE.finditer(_DATE_LIKE.sub(" ", value)):
                yield from _parse(m.group("num"))


def _parse(text: str) -> Iterable[Decimal]:
    try:
        yield Decimal(text.replace(",", ""))
    except InvalidOperation:
        return


def known_figures(sources: Iterable[Any]) -> set[Decimal]:
    """Every figure the answer may quote: exact, and rounded to whole units."""
    known: set[Decimal] = set()
    for source in sources:
        for n in _numbers_in(source):
            n = abs(n)
            known.add(n.normalize())
            known.add(n.quantize(Decimal(1), rounding=ROUND_HALF_UP).normalize())
    return known


def figures_in_answer(answer: str) -> list[tuple[str, Decimal]]:
    """Money-like figures in an answer, as (text as written, value)."""
    found = []
    for m in _FIGURE.finditer(_DATE_LIKE.sub(" ", answer)):
        num = m.group("num")
        value = next(iter(_parse(num)), None)
        if value is None:
            continue
        bare = not (m.group("cur") or m.group("pct") or "." in num or "," in num)
        if bare and 1900 <= value <= 2100:
            continue  # a year, as in "March 2026"
        money_like = bool(m.group("cur")) or bool(m.group("pct")) or "." in num or value >= 1000
        if money_like:
            found.append((m.group(0).strip(), value))
    return found


def unverified(answer: str, sources: Iterable[Any]) -> list[str]:
    """Figures in ``answer`` that none of ``sources`` contains."""
    known = known_figures(sources)
    return [text for text, value in figures_in_answer(answer) if abs(value).normalize() not in known]
