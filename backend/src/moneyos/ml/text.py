"""Text preparation shared by training and prediction (no train/serve skew)."""

from __future__ import annotations

import re

from moneyos.domain.cleaning import normalize_key

# Payment-rail words and codes that say nothing about the category.
_NOISE = frozenset(
    "upi dr cr pos neft imps rtgs ach nach ecs payment paid to from in xxxxxx txn ref ind ltd pvt".split()
)
_CODES = re.compile(r"^(?:[a-z]{4}0\d*|ok[a-z]+|ybl|ibl|axl|paytm|hdfc|icic|sbin|utib|kkbk|yesb|punb|barb)$")


def prepare(description: str) -> str:
    """Lower-case words with digits, bank codes and rail words removed.

    "UPI/DR/412345678901/ROYAL KITCHEN/HDFC/royalkitchen@okaxis/Payment"
    becomes "royal kitchen royalkitchen".
    """
    words = []
    for word in normalize_key(description).split():
        if word in _NOISE or any(ch.isdigit() for ch in word) or _CODES.match(word):
            continue
        words.append(word)
    return " ".join(words)
