"""The grounding check: every money figure in an answer must come from MoneyOS."""

import pytest

from moneyos.assistant.grounding import figures_in_answer, unverified

TOOLS = [{"spending": "36007.64", "rent": "-22000.00", "percent_used": 5, "income": "85000.00",
          "warnings": ["1 failed transaction of 1,875.56 was excluded"]}]


@pytest.mark.parametrize("answer", [
    "You spent ₹36,007.64 in March 2026.",        # exact, with Indian commas; the year is not a figure
    "Rent was ₹22,000.",                           # sign dropped, rounded to whole rupees
    "Around Rs 36,008 overall.",                   # rounded
    "You have used 5% of the budget.",
    "One failed payment of INR 1,875.56 was left out.",  # a figure inside a warning sentence
    "On 2026-03-27 you made 3 payments.",          # dates and small counts are not checked
    "Income: 85000",
])
def test_figures_from_the_tools_pass(answer):
    assert unverified(answer, TOOLS) == []


@pytest.mark.parametrize("answer, flagged", [
    ("Together that is ₹58,007.64.", ["₹58,007.64"]),       # the model's own sum
    ("You saved about ₹49,000.", ["₹49,000"]),              # close to the net, but not a tool figure
    ("Spending rose 12%.", ["12%"]),
    ("That leaves 1,23,456.78.", ["1,23,456.78"]),
    ("A bill of 999.50 is due.", ["999.50"]),
])
def test_figures_not_from_the_tools_are_flagged(answer, flagged):
    assert unverified(answer, TOOLS) == flagged


def test_numbers_in_the_question_count_as_known():
    assert unverified("A ₹30,000 laptop", [TOOLS, "What if I buy a 30000 laptop?"]) == []


def test_what_counts_as_a_figure():
    assert [text for text, _ in figures_in_answer("₹120, 3 coffees, 2,500 in 2026, 7.5% and 1999")] == [
        "₹120", "2,500", "7.5%"]
