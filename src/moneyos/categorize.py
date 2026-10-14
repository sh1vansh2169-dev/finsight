"""Keyword-based categorisation. First matching rule wins."""

from __future__ import annotations

from dataclasses import replace

from moneyos.cleaning import normalize_key
from moneyos.models import UNCATEGORIZED, Transaction

INCOME = "Income"
TRANSFER = "Transfer"

# Keywords are matched as whole words/phrases against the normalised
# description. Transfer comes first so "transfer to credit card" is not
# picked up by a later rule.
DEFAULT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (TRANSFER, ("transfer", "payment received", "card payment")),
    (INCOME, ("salary", "payroll", "bonus", "interest credit")),
    ("Housing", ("rent",)),
    ("Utilities", ("electricity", "broadband", "water bill", "gas bill", "mobile recharge")),
    ("Groceries", ("groceries", "supermarket", "freshmart")),
    ("Dining", ("restaurant", "cafe", "pizza")),
    ("Transport", ("metro", "cab", "quickcab", "fuel", "petrol")),
    ("Shopping", ("shopkart", "store")),
    ("Entertainment", ("streamflix", "cinema")),
    ("Health", ("pharmacy", "clinic")),
)


def categorize(transaction: Transaction, rules=DEFAULT_RULES) -> Transaction:
    """Return the transaction with a category assigned.

    A category that came from the source file is kept as is. Income rules
    only apply to money coming in.
    """
    if transaction.category != UNCATEGORIZED:
        return transaction
    padded = f" {normalize_key(transaction.description)} "
    for category, keywords in rules:
        if category == INCOME and transaction.amount < 0:
            continue
        if any(f" {keyword} " in padded for keyword in keywords):
            return replace(transaction, category=category)
    return transaction
