"""Money Majra: lending, borrowing, shared expenses and settlements.

All amounts are integer minor units (paise). Everything here is
deterministic: the same entries always give the same balances and the same
settlement plan.

Sign convention for balances: **positive means the person is owed money**,
negative means they owe. Within a group, balances always sum to exactly zero.

Effects of each entry on balances:

* shared expense: the payer is credited the full amount; every participant
  (the payer included, if they took part) is debited their share.
* loan: the lender is credited, the borrower debited.
* payment (a repayment or settlement): the payer is credited, the receiver
  debited. Paying back moves both people towards zero.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

# Exact minimum settlement is exponential in the number of people with a
# non-zero balance; above this, a greedy plan is used and labelled as such.
EXACT_SETTLEMENT_LIMIT = 16

Person = Hashable


class MajraError(ValueError):
    """An entry or request that would make the books inconsistent."""


class SplitMethod(StrEnum):
    EQUAL = "equal"  # everyone pays the same (leftover paise go first-come)
    EXACT = "exact"  # amounts given per person; must add up to the total
    PERCENT = "percent"  # percentages; must add up to 100
    SHARES = "shares"  # weights, e.g. 2 shares vs 1 share


class EntryKind(StrEnum):
    EXPENSE = "expense"
    LOAN = "loan"
    PAYMENT = "payment"


def _largest_remainder(total: int, weights: Sequence[tuple[Person, Decimal]]) -> dict[Person, int]:
    """Split ``total`` proportionally to ``weights`` into integers that add up exactly.

    Each person gets the floor of their exact share; the leftover units go
    one each to the largest fractional remainders, ties broken by the order
    the participants were given in. Deterministic and never off by more than
    one unit from the exact share.
    """
    weight_sum = sum(w for _, w in weights)
    if weight_sum <= 0:
        raise MajraError("split weights must add up to more than zero")
    exact = [(person, Decimal(total) * w / weight_sum) for person, w in weights]
    shares = {person: int(value) for person, value in exact}  # floor (values are >= 0)
    leftover = total - sum(shares.values())
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i][1] - int(exact[i][1])), i))
    for i in order[:leftover]:
        shares[exact[i][0]] += 1
    return shares


def allocate(
    total: int, method: SplitMethod, participants: Sequence[tuple[Person, Decimal | int | None]]
) -> dict[Person, int]:
    """Each participant's share of ``total`` minor units; shares add up to ``total`` exactly."""
    if total <= 0:
        raise MajraError("amount must be positive")
    if not participants:
        raise MajraError("an expense needs at least one participant")
    people = [p for p, _ in participants]
    if len(set(people)) != len(people):
        raise MajraError("a participant is listed twice")

    if method == SplitMethod.EQUAL:
        return _largest_remainder(total, [(p, Decimal(1)) for p in people])
    values = [(p, v) for p, v in participants]
    if any(v is None for _, v in values):
        raise MajraError(f"every participant needs a value for a '{method.value}' split")
    if any(Decimal(v) < 0 for _, v in values):
        raise MajraError("split values cannot be negative")
    if method == SplitMethod.EXACT:
        shares = {p: int(v) for p, v in values}
        if sum(shares.values()) != total:
            raise MajraError(
                f"exact shares add up to {sum(shares.values())}, not the total of {total} (minor units)"
            )
        return shares
    if method == SplitMethod.PERCENT:
        if sum(Decimal(v) for _, v in values) != 100:
            raise MajraError("percentages must add up to 100")
        return _largest_remainder(total, [(p, Decimal(v)) for p, v in values])
    if method == SplitMethod.SHARES:
        return _largest_remainder(total, [(p, Decimal(v)) for p, v in values])
    raise MajraError(f"unknown split method {method}")


@dataclass(frozen=True, slots=True)
class Entry:
    kind: EntryKind
    amount: int  # minor units, positive
    paid_by: Person  # payer / lender / person paying back
    paid_to: Person | None = None  # borrower / person being paid (loan, payment)
    shares: Mapping[Person, int] | None = None  # expense shares

    def effects(self) -> dict[Person, int]:
        if self.amount <= 0:
            raise MajraError("amount must be positive")
        if self.kind == EntryKind.EXPENSE:
            if self.shares is None or sum(self.shares.values()) != self.amount:
                raise MajraError("expense shares must add up to the amount")
            effects = {p: -s for p, s in self.shares.items()}
            effects[self.paid_by] = effects.get(self.paid_by, 0) + self.amount
            return effects
        if self.paid_to is None or self.paid_to == self.paid_by:
            raise MajraError(f"a {self.kind.value} needs two different people")
        return {self.paid_by: self.amount, self.paid_to: -self.amount}


def balances(entries: Iterable[Entry]) -> dict[Person, int]:
    """Net balance per person. Raises if they do not sum to zero (they always should)."""
    totals: dict[Person, int] = {}
    for entry in entries:
        for person, delta in entry.effects().items():
            totals[person] = totals.get(person, 0) + delta
    if sum(totals.values()) != 0:  # pragma: no cover - guarded by construction
        raise MajraError(f"balances do not reconcile: they sum to {sum(totals.values())}")
    return totals


@dataclass(frozen=True, slots=True)
class Transfer:
    payer: Person
    receiver: Person
    amount: int


@dataclass(frozen=True, slots=True)
class SettlementPlan:
    transfers: tuple[Transfer, ...]
    minimal: bool  # proven minimum number of transfers, or a greedy plan


def _greedy(people: list[tuple[Person, int]]) -> list[Transfer]:
    """Largest debtor pays largest creditor until everyone is square.

    Every transfer brings at least one person to zero, so a group of k people
    needs at most k - 1 transfers. Ties are broken by the input order.
    """
    order = {p: i for i, (p, _) in enumerate(people)}
    debtors = [[p, -b] for p, b in people if b < 0]
    creditors = [[p, b] for p, b in people if b > 0]
    transfers = []
    while debtors and creditors:
        debtors.sort(key=lambda x: (-x[1], order[x[0]]))
        creditors.sort(key=lambda x: (-x[1], order[x[0]]))
        debtor, creditor = debtors[0], creditors[0]
        amount = min(debtor[1], creditor[1])
        transfers.append(Transfer(debtor[0], creditor[0], amount))
        debtor[1] -= amount
        creditor[1] -= amount
        debtors = [d for d in debtors if d[1]]
        creditors = [c for c in creditors if c[1]]
    return transfers


def settle(balance: Mapping[Person, int]) -> SettlementPlan:
    """Transfers that bring every balance to zero, using as few as possible.

    The minimum number of transfers is (people with a non-zero balance) minus
    (the largest number of groups those people can be split into, each of
    which sums to zero on its own). That maximum is found exactly with a
    dynamic programme over subsets: dp[S] = max over members i of
    dp[S - i], plus 1 if S itself sums to zero. Each zero-sum group is then
    settled internally with size - 1 transfers.
    """
    if sum(balance.values()) != 0:
        raise MajraError("balances must sum to zero to be settled")
    people = [(p, b) for p, b in balance.items() if b != 0]
    n = len(people)
    if n == 0:
        return SettlementPlan((), True)
    if n > EXACT_SETTLEMENT_LIMIT:
        return SettlementPlan(tuple(_greedy(people)), False)

    amounts = [b for _, b in people]
    size = 1 << n
    sums = [0] * size
    dp = [0] * size
    best_drop = [0] * size  # which member to drop to reach the best sub-solution
    for mask in range(1, size):
        low = mask & -mask
        i = low.bit_length() - 1
        sums[mask] = sums[mask ^ low] + amounts[i]
        best, drop = -1, 0
        m = mask
        while m:
            bit = m & -m
            if dp[mask ^ bit] > best:
                best, drop = dp[mask ^ bit], bit
            m ^= bit
        dp[mask] = best + (1 if sums[mask] == 0 else 0)
        best_drop[mask] = drop

    # Walk back from everyone; each time the remaining set sums to zero, the
    # members dropped since the previous zero-sum set form one group.
    groups, current, mask = [], [], size - 1
    while mask:
        if sums[mask] == 0 and current:
            groups.append(current)
            current = []
        bit = best_drop[mask]
        current.append(bit.bit_length() - 1)
        mask ^= bit
    groups.append(current)

    transfers = []
    for group in groups:
        transfers.extend(_greedy([people[i] for i in sorted(group)]))
    plan = SettlementPlan(tuple(transfers), True)
    if len(plan.transfers) != n - dp[size - 1]:  # pragma: no cover - internal consistency check
        raise MajraError("settlement plan is not minimal; please report this")
    return plan


def apply(balance: Mapping[Person, int], transfers: Iterable[Transfer]) -> dict[Person, int]:
    """Balances after the given transfers are paid."""
    result = dict(balance)
    for t in transfers:
        result[t.payer] = result.get(t.payer, 0) + t.amount
        result[t.receiver] = result.get(t.receiver, 0) - t.amount
    return result


def check_payment(balance: Mapping[Person, int], payer: Person, receiver: Person, amount: int) -> None:
    """Refuse a payment that would make the books inconsistent.

    A repayment must go from someone who owes to someone who is owed, and may
    not exceed either side's balance. Overpaying would silently turn a
    repayment into a new loan; record a loan for that instead.
    """
    if amount <= 0:
        raise MajraError("amount must be positive")
    if payer == receiver:
        raise MajraError("payer and receiver must be different people")
    owes, owed = -balance.get(payer, 0), balance.get(receiver, 0)
    if owes <= 0:
        raise MajraError("the payer does not owe anything in this group")
    if owed <= 0:
        raise MajraError("the receiver is not owed anything in this group")
    if amount > min(owes, owed):
        raise MajraError(
            f"this payment ({amount}) is more than is outstanding ({min(owes, owed)}, minor units); "
            "record the extra as a loan if it is one"
        )
