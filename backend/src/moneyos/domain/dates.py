"""Calendar helpers."""

from __future__ import annotations

import calendar
from datetime import date


def add_months(day: date, months: int) -> date:
    """Same day of the month, ``months`` later (or earlier), clamped to the month's length."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))
