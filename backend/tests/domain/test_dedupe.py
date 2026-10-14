from moneyos.domain.dedupe import deduplicate, fingerprint


def test_no_duplicates(make_txn):
    a, b = make_txn(amount="-1.00"), make_txn(amount="-2.00")
    result = deduplicate([[a], [b]])
    assert result.unique == [a, b]
    assert result.duplicates == []
    assert result.suspected == []


def test_overlapping_files_drop_the_later_copy(make_txn):
    first = make_txn(source_file="jan.csv")
    again = make_txn(source_file="feb.csv")
    result = deduplicate([[first], [again]])
    assert result.unique == [first]
    assert result.duplicates == [again]


def test_match_ignores_description_formatting(make_txn):
    first = make_txn(description="FRESHMART GROCERIES")
    again = make_txn(description="freshmart   groceries")
    assert fingerprint(first) == fingerprint(again)


def test_different_date_amount_account_or_currency_is_not_a_duplicate(make_txn):
    base = make_txn()
    others = [
        make_txn(day="2026-01-16"),
        make_txn(amount="-100.01"),
        make_txn(amount="100.00"),
        make_txn(account="Card"),
        make_txn(currency="USD"),
        make_txn(description="FRESHMART GROCERY"),
    ]
    result = deduplicate([[base], others])
    assert result.duplicates == []
    assert len(result.unique) == 7


def test_identical_rows_in_one_file_are_kept_but_flagged(make_txn):
    coffee_1 = make_txn(description="CHAI POINT CAFE", amount="-120.00", source_row=2)
    coffee_2 = make_txn(description="CHAI POINT CAFE", amount="-120.00", source_row=3)
    result = deduplicate([[coffee_1, coffee_2]])
    assert result.unique == [coffee_1, coffee_2]
    assert result.duplicates == []
    assert result.suspected == [coffee_2]


def test_repeated_rows_are_matched_by_occurrence_across_files(make_txn):
    def coffees(count, source):
        return [
            make_txn(description="CHAI POINT CAFE", source_file=source, source_row=i)
            for i in range(count)
        ]

    # Two in the first export, three in the second: exactly one is new.
    first, second = coffees(2, "a.csv"), coffees(3, "b.csv")
    result = deduplicate([first, second])
    assert result.unique == [*first, second[2]]
    assert result.duplicates == second[:2]

    # Re-importing a file that has fewer copies adds nothing.
    result = deduplicate([coffees(2, "a.csv"), coffees(1, "b.csv"), coffees(2, "c.csv")])
    assert len(result.unique) == 2
    assert len(result.duplicates) == 3


def test_growing_exports_add_only_the_new_copies(make_txn):
    def coffees(count, source):
        return [make_txn(description="CHAI POINT CAFE", source_file=source) for _ in range(count)]

    # Each export repeats everything before it and adds one more coffee.
    result = deduplicate([coffees(1, "a.csv"), coffees(2, "b.csv"), coffees(3, "c.csv")])
    assert len(result.unique) == 3
    assert len(result.duplicates) == 3


def test_reference_identifies_a_transaction_even_if_other_fields_differ(make_txn):
    pending = make_txn(day="2026-01-15", description="SHOPKART PENDING", reference="CC000001")
    posted = make_txn(day="2026-01-16", description="SHOPKART ONLINE STORE", reference="cc000001")
    result = deduplicate([[pending], [posted]])
    assert result.unique == [pending]
    assert result.duplicates == [posted]


def test_repeated_reference_in_one_file_is_a_duplicate(make_txn):
    a = make_txn(reference="CC000001")
    b = make_txn(reference="CC000001")
    result = deduplicate([[a, b]])
    assert result.unique == [a]
    assert result.duplicates == [b]
    assert result.suspected == []


def test_same_reference_on_different_accounts_is_not_a_duplicate(make_txn):
    a = make_txn(reference="1", account="Card A")
    b = make_txn(reference="1", account="Card B")
    assert deduplicate([[a, b]]).duplicates == []


def test_existing_transactions_count_as_already_imported(make_txn):
    stored = [make_txn(), make_txn(amount="-5.00")]
    new = make_txn(amount="-9.99")
    result = deduplicate([[make_txn(), new]], existing=stored)
    assert result.unique == [new]
    assert len(result.duplicates) == 1


def test_empty_input():
    result = deduplicate([])
    assert (result.unique, result.duplicates, result.suspected) == ([], [], [])
