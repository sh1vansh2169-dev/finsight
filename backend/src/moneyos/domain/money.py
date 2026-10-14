"""Conversion between Decimal amounts and integer minor units (paise, cents).

The database stores integer minor units so no engine can round money through
a float. Amounts are parsed to two decimal places, so currencies with three
minor digits (KWD, BHD, ...) are not supported yet.
"""

from __future__ import annotations

from decimal import Decimal

# ISO 4217 currencies without minor units. Everything else is assumed to
# have two.
_ZERO_DECIMAL = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "UGX"})


def exponent(currency: str) -> int:
    return 0 if currency.upper() in _ZERO_DECIMAL else 2


def to_minor(amount: Decimal, currency: str) -> int:
    """Exact conversion; raises ValueError rather than rounding."""
    scaled = amount.scaleb(exponent(currency))
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount} has more decimal places than {currency.upper()} allows")
    return int(scaled)


def from_minor(minor: int, currency: str) -> Decimal:
    places = exponent(currency)
    return Decimal(minor).scaleb(-places).quantize(Decimal(1).scaleb(-places))
