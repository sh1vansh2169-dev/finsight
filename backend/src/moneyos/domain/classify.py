"""Rule-based inference of transaction type and category.

Only fields whose basis is NONE are filled in: a value stated by the source
file or set by the user is never overwritten by a rule. When nothing matches,
the field stays unknown rather than being guessed from the direction alone
(money in is not automatically income).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

from moneyos.domain.cleaning import normalize_key
from moneyos.domain.models import UNCATEGORIZED, Basis, Direction, Transaction, TxnType


class RulesError(ValueError):
    """The rules file is malformed."""


@dataclass(frozen=True, slots=True)
class Rule:
    label: str  # a TxnType value or a category name
    direction: Direction | None  # None means either direction
    keywords: tuple[str, ...]

    def matches(self, padded_key: str, direction: Direction) -> bool:
        if self.direction is not None and self.direction != direction:
            return False
        return any(f" {keyword} " in padded_key for keyword in self.keywords)


@dataclass(frozen=True, slots=True)
class Rules:
    type_rules: tuple[Rule, ...]
    category_rules: tuple[Rule, ...]

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(rule.label for rule in self.category_rules))


def _parse_rules(entries: list[dict], *, label_key: str, is_type: bool) -> tuple[Rule, ...]:
    rules = []
    for index, entry in enumerate(entries, start=1):
        try:
            label = entry[label_key]
            direction_text = entry.get("direction", "any")
            keywords = entry["keywords"]
        except (KeyError, TypeError):
            raise RulesError(f"rule {index} needs {label_key!r} and 'keywords'") from None
        if is_type:
            try:
                label = TxnType(label).value
            except ValueError:
                raise RulesError(f"rule {index}: unknown transaction type {label!r}") from None
        if direction_text == "any":
            direction = None
        else:
            try:
                direction = Direction(direction_text)
            except ValueError:
                raise RulesError(f"rule {index}: bad direction {direction_text!r}") from None
        normalized = tuple(normalize_key(k) for k in keywords if normalize_key(k))
        if not normalized:
            raise RulesError(f"rule {index}: no usable keywords")
        rules.append(Rule(label, direction, normalized))
    return tuple(rules)


def parse_rules(text: str) -> Rules:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RulesError(f"invalid TOML: {error}") from None
    return Rules(
        type_rules=_parse_rules(data.get("type_rules", []), label_key="type", is_type=True),
        category_rules=_parse_rules(data.get("categories", []), label_key="name", is_type=False),
    )


def load_rules(path: str | Path | None = None) -> Rules:
    """Load rules from ``path``, or the packaged defaults when None."""
    if path is None:
        text = resources.files("moneyos.domain").joinpath("default_rules.toml").read_text("utf-8")
    else:
        text = Path(path).read_text("utf-8")
    return parse_rules(text)


def classify(transaction: Transaction, rules: Rules) -> Transaction:
    """Fill in type and category where they are not already known."""
    padded = f" {normalize_key(transaction.description)} "
    direction = transaction.direction
    changes = {}

    if transaction.category_basis == Basis.NONE:
        for rule in rules.category_rules:
            if rule.matches(padded, direction):
                changes.update(category=rule.label, category_basis=Basis.RULE)
                break

    if transaction.type_basis == Basis.NONE:
        for rule in rules.type_rules:
            if rule.matches(padded, direction):
                changes.update(txn_type=TxnType(rule.label), type_basis=Basis.RULE)
                break
        else:
            category = changes.get("category", transaction.category)
            if direction == Direction.DEBIT and category != UNCATEGORIZED:
                changes.update(txn_type=TxnType.EXPENSE, type_basis=Basis.RULE)

    return replace(transaction, **changes) if changes else transaction
