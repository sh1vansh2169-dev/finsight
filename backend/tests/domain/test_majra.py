import random
from decimal import Decimal

import pytest

from moneyos.domain.majra import (
    EXACT_SETTLEMENT_LIMIT,
    Entry,
    EntryKind,
    MajraError,
    SplitMethod,
    allocate,
    apply,
    balances,
    check_payment,
    settle,
)

# ------------------------------------------------------------ allocation


def test_equal_split_is_exact_and_deterministic():
    shares = allocate(10000, SplitMethod.EQUAL, [("A", None), ("B", None), ("C", None)])
    assert shares == {"A": 3334, "B": 3333, "C": 3333}  # 100.00 / 3: the first gets the paisa
    assert sum(shares.values()) == 10000
    again = allocate(10000, SplitMethod.EQUAL, [("C", None), ("A", None), ("B", None)])
    assert again == {"C": 3334, "A": 3333, "B": 3333}  # order given decides who gets it


@pytest.mark.parametrize("seed", range(200))
def test_any_split_adds_up_and_is_fair(seed):
    rng = random.Random(seed)
    total = rng.randint(1, 10_000_000)
    people = [f"P{i}" for i in range(rng.randint(1, 9))]
    weights = [(p, Decimal(rng.randint(0, 5))) for p in people]
    if sum(w for _, w in weights) == 0:
        weights[0] = (people[0], Decimal(1))
    shares = allocate(total, SplitMethod.SHARES, weights)
    assert sum(shares.values()) == total
    weight_sum = sum(w for _, w in weights)
    for person, w in weights:
        exact = Decimal(total) * w / weight_sum
        assert abs(shares[person] - exact) < 1  # never off by a whole paisa or more
    equal = allocate(total, SplitMethod.EQUAL, [(p, None) for p in people])
    assert sum(equal.values()) == total and max(equal.values()) - min(equal.values()) <= 1


def test_percent_and_exact_splits():
    assert allocate(10001, SplitMethod.PERCENT, [("A", Decimal("50")), ("B", Decimal("50"))]) == {"A": 5001, "B": 5000}
    assert allocate(1000, SplitMethod.PERCENT, [("A", Decimal("33.5")), ("B", Decimal("66.5"))]) == {"A": 335, "B": 665}
    assert allocate(1000, SplitMethod.EXACT, [("A", 250), ("B", 750)]) == {"A": 250, "B": 750}


@pytest.mark.parametrize(
    ("method", "participants", "message"),
    [
        (SplitMethod.EXACT, [("A", 250), ("B", 700)], "add up to 950"),
        (SplitMethod.PERCENT, [("A", Decimal(60)), ("B", Decimal(30))], "add up to 100"),
        (SplitMethod.SHARES, [("A", Decimal(0)), ("B", Decimal(0))], "more than zero"),
        (SplitMethod.SHARES, [("A", Decimal(-1)), ("B", Decimal(2))], "negative"),
        (SplitMethod.EXACT, [("A", None), ("B", 1000)], "needs a value"),
        (SplitMethod.EQUAL, [("A", None), ("A", None)], "listed twice"),
        (SplitMethod.EQUAL, [], "at least one"),
    ],
)
def test_bad_splits(method, participants, message):
    with pytest.raises(MajraError, match=message):
        allocate(1000, method, participants)


# -------------------------------------------------------------- balances


def test_dinner_trip_example():
    """You pay 1,200 for dinner for three; Sam lends you 500; Ria pays you back 300."""
    entries = [
        Entry(EntryKind.EXPENSE, 120000, "You",
              shares=allocate(120000, SplitMethod.EQUAL, [("You", None), ("Sam", None), ("Ria", None)])),
        Entry(EntryKind.LOAN, 50000, "Sam", "You"),
        Entry(EntryKind.PAYMENT, 30000, "Ria", "You"),
    ]
    b = balances(entries)
    # You: +1,200 paid - 400 own share - 500 borrowed from Sam - 300 received from Ria = 0.
    # Sam: -400 dinner share + 500 lent = +100 (owed). Ria: -400 + 300 repaid = -100 (owes).
    assert b == {"You": 0, "Sam": 10000, "Ria": -10000}
    assert sum(b.values()) == 0
    (transfer,) = settle(b).transfers
    assert (transfer.payer, transfer.receiver, transfer.amount) == ("Ria", "Sam", 10000)


@pytest.mark.parametrize("seed", range(100))
def test_balances_always_reconcile(seed):
    rng = random.Random(seed)
    people = [f"P{i}" for i in range(rng.randint(2, 8))]
    entries = []
    for _ in range(rng.randint(1, 40)):
        amount = rng.randint(1, 500_000)
        kind = rng.choice(list(EntryKind))
        if kind == EntryKind.EXPENSE:
            group = rng.sample(people, rng.randint(1, len(people)))
            entries.append(Entry(kind, amount, rng.choice(people),
                                 shares=allocate(amount, SplitMethod.EQUAL, [(p, None) for p in group])))
        else:
            a, b = rng.sample(people, 2)
            entries.append(Entry(kind, amount, a, b))
    b = balances(entries)
    assert sum(b.values()) == 0


def test_entry_validation():
    with pytest.raises(MajraError):
        Entry(EntryKind.LOAN, 100, "A", "A").effects()
    with pytest.raises(MajraError):
        Entry(EntryKind.PAYMENT, 100, "A").effects()
    with pytest.raises(MajraError):
        Entry(EntryKind.EXPENSE, 100, "A", shares={"A": 50}).effects()
    with pytest.raises(MajraError):
        Entry(EntryKind.LOAN, 0, "A", "B").effects()


# ------------------------------------------------------------ settlement


def _min_transfers_brute_force(amounts: list[int]) -> int:
    """n - (largest number of zero-sum blocks over every set partition)."""
    people = [a for a in amounts if a]
    best = 0

    def search(remaining: list[int], blocks: int):
        nonlocal best
        if not remaining:
            best = max(best, blocks)
            return
        first, rest = remaining[0], remaining[1:]
        # Choose the block containing `first`: every subset of the rest.
        for mask in range(1 << len(rest)):
            block = [first] + [rest[i] for i in range(len(rest)) if mask >> i & 1]
            if sum(block) == 0:
                search([rest[i] for i in range(len(rest)) if not mask >> i & 1], blocks + 1)

    search(people, 0)
    return len(people) - best


def _random_balances(rng: random.Random, n: int, pairs: bool) -> dict[str, int]:
    values = []
    if pairs:  # build in zero-sum chunks so that splitting actually matters
        while len(values) < n - 1:
            x = rng.choice([100, 250, 500, 1000, 1500])
            values += [x, -x]
    values += [rng.choice([-700, -300, 200, 400, 900]) for _ in range(max(0, n - len(values) - 1))]
    values.append(-sum(values))
    rng.shuffle(values)
    return {f"P{i}": v for i, v in enumerate(values)}


@pytest.mark.parametrize("seed", range(150))
def test_settlement_is_minimal_and_settles_everyone(seed):
    rng = random.Random(seed)
    balance = _random_balances(rng, rng.randint(1, 7), pairs=seed % 2 == 0)
    plan = settle(balance)
    assert plan.minimal
    assert all(v == 0 for v in apply(balance, plan.transfers).values())
    assert all(t.amount > 0 and t.payer != t.receiver for t in plan.transfers)
    assert len(plan.transfers) == _min_transfers_brute_force(list(balance.values()))


def test_settlement_finds_hidden_zero_sum_groups():
    # Greedy alone pairs 500 with -400 first and needs 4 transfers;
    # splitting into {A, B} and {C, D, E} needs only 3.
    balance = {"A": 500, "B": -500, "C": 400, "D": -300, "E": -100}
    plan = settle(balance)
    assert len(plan.transfers) == 3
    assert all(v == 0 for v in apply(balance, plan.transfers).values())


def test_settlement_edge_cases():
    assert settle({}).transfers == ()
    assert settle({"A": 0, "B": 0}).transfers == ()
    (only,) = settle({"A": -250, "B": 250}).transfers
    assert (only.payer, only.receiver, only.amount) == ("A", "B", 250)
    with pytest.raises(MajraError, match="sum to zero"):
        settle({"A": 1, "B": 0})


def test_large_groups_fall_back_to_a_labelled_greedy_plan():
    rng = random.Random(4)
    balance = _random_balances(rng, EXACT_SETTLEMENT_LIMIT + 4, pairs=False)
    plan = settle(balance)
    assert plan.minimal is False
    nonzero = sum(1 for v in balance.values() if v)
    assert len(plan.transfers) <= nonzero - 1
    assert all(v == 0 for v in apply(balance, plan.transfers).values())


def test_exact_settlement_at_the_size_limit_is_fast_enough():
    import time

    rng = random.Random(9)
    balance = _random_balances(rng, EXACT_SETTLEMENT_LIMIT, pairs=True)
    started = time.perf_counter()
    plan = settle(balance)
    assert plan.minimal and time.perf_counter() - started < 10


# --------------------------------------------------------------- payments


def test_payment_checks():
    balance = {"You": 30000, "Sam": 10000, "Ria": -40000}
    check_payment(balance, "Ria", "You", 30000)  # fine
    with pytest.raises(MajraError, match="more than is outstanding"):
        check_payment(balance, "Ria", "Sam", 10001)
    with pytest.raises(MajraError, match="payer does not owe"):
        check_payment(balance, "Sam", "You", 100)
    with pytest.raises(MajraError, match="receiver is not owed"):
        check_payment(balance, "Ria", "Nobody", 100)
    with pytest.raises(MajraError, match="different people"):
        check_payment(balance, "Ria", "Ria", 100)
