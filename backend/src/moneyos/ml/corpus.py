"""Synthetic labelled transaction descriptions for categorisation experiments.

**Everything here is invented**, including the merchant names. Each merchant
gets a category and a name built from a distinctive word and, usually, a
descriptor ("Kitchen", "Medicos", "Academy"). Its transactions are rendered
through realistic Indian payment-rail templates (UPI narrations, card POS
lines, NEFT/ACH, payment-app text) with truncation, case changes and typos.

What this data can and cannot show:

* It can show whether a pipeline learns *descriptor words* and generalises
  to merchants it has never seen, compared with keyword rules.
* It cannot show real-world accuracy: the generator's vocabulary and noise
  are assumptions. Some descriptors are deliberately shared between
  categories ("Mart", "Travels", "Point") and some merchants have no
  descriptor at all, so a perfect score is impossible by design.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

CATEGORIES = (
    "Dining", "Groceries", "Transport", "Shopping", "Utilities",
    "Entertainment", "Health", "Education", "Housing", "Travel",
)

# Descriptor words per category. A few are shared on purpose (ambiguity).
_DESCRIPTORS = {
    "Dining": ["Restaurant", "Kitchen", "Cafe", "Dhaba", "Biryani House", "Foods", "Bakers", "Pizzeria",
               "Sweets", "Chai Point", "Eatery", "Tiffins"],
    "Groceries": ["Supermarket", "Mart", "Kirana Store", "Fresh", "Provisions", "Dairy", "Vegetables",
                  "General Stores", "Hypermarket", "Organics"],
    "Transport": ["Cabs", "Fuel Station", "Petroleum", "Metro Card", "Auto Services", "Parking", "Tolls",
                  "Bike Rentals", "Fastag"],
    "Shopping": ["Fashions", "Electronics", "Mart", "Store", "Footwear", "Online Retail", "Collections",
                 "Trends", "Gifts"],
    "Utilities": ["Electricity Board", "Broadband", "Gas Agency", "Water Supply", "Mobile Recharge",
                  "DTH Recharge", "Power Distribution", "Telecom"],
    "Entertainment": ["Cinemas", "Streaming", "Multiplex", "Gaming", "Music", "Events", "Bowling", "Club"],
    "Health": ["Pharmacy", "Medicos", "Clinic", "Hospital", "Diagnostics", "Dental Care", "Labs",
               "Chemist", "Eye Care"],
    "Education": ["Academy", "Tutorials", "School", "College", "Coaching Centre", "Book Depot",
                  "Learning", "Institute", "Online Courses"],
    "Housing": ["Rent", "Society Maintenance", "Properties", "Housing Society", "Estates", "Realty",
                "Apartments"],
    "Travel": ["Travels", "Airlines", "Hotels", "Resorts", "Railways", "Tours", "Holidays", "Bus Booking",
               "Stays"],
}

# Distinctive name parts: deliberately bland, so the descriptor carries the signal.
_NAME_PARTS = (
    "Aarav Amber Anand Apex Aria Arjun Bharat Blue Bright City Coral Crown Daily Deccan Delta Dhruv "
    "Eagle Elite Ever Galaxy Ganga Golden Green Happy Harbor Indus Ishaan Jade Jasmine Kaveri Kiran "
    "Lakshmi Laxmi Lotus Lucky Madhav Maple Metro Mira Moon Neel Noble Nova Ocean Orchid Pearl Prime "
    "Raj Ravi Royal Ruby Sagar Sai Saffron Shree Silver Sky Sonu Star Sun Sunrise Surya Swift Tara "
    "Trinity Unity Urban Vasant Vedant Vista Zen Zenith"
).split()
_CITIES = ["MUMBAI", "PUNE", "BANGALORE", "BENGALURU", "DELHI", "CHENNAI", "HYDERABAD", "KOLKATA", "NOIDA", "GURGAON"]
_BANKS = ["HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "YESB", "PUNB", "BARB"]
_PSPS = ["okaxis", "okhdfcbank", "oksbi", "ybl", "paytm", "ibl", "axl"]


@dataclass(frozen=True, slots=True)
class Merchant:
    name: str
    category: str
    has_descriptor: bool


@dataclass(frozen=True, slots=True)
class LabelledText:
    text: str
    category: str
    merchant: str  # grouping key: the same merchant must not span train and test


def make_merchants(rng: random.Random, per_category: int = 40, no_descriptor_share: float = 0.15) -> list[Merchant]:
    merchants, used = [], set()
    for category in CATEGORIES:
        made = 0
        while made < per_category:
            parts = rng.sample(_NAME_PARTS, rng.choice((1, 1, 2)))
            base = " ".join(parts)
            if rng.random() < no_descriptor_share:
                name, has_descriptor = base, False
            else:
                name, has_descriptor = f"{base} {rng.choice(_DESCRIPTORS[category])}", True
            if name in used:
                continue
            used.add(name)
            merchants.append(Merchant(name, category, has_descriptor))
            made += 1
    return merchants


def _typo(rng: random.Random, word: str) -> str:
    if len(word) < 5:
        return word
    i = rng.randrange(1, len(word) - 1)
    return word[:i] + word[i + 1:]  # drop one letter


def render(rng: random.Random, merchant: Merchant) -> str:
    """One payment-rail description for a merchant."""
    name = merchant.name
    if rng.random() < 0.15:
        name = " ".join(_typo(rng, w) if rng.random() < 0.3 else w for w in name.split())
    compact = name.replace(" ", "").lower()[:12]
    digits = "".join(rng.choice("0123456789") for _ in range(12))
    template = rng.choice((
        "UPI/DR/{digits}/{NAME}/{bank}/{compact}@{psp}/Payment",
        "UPI-{NAME}-{compact}@{psp}-{bank}0001234-{digits}-UPI",
        "POS {card}XXXXXX{last4} {NAME} {city}",
        "{NAME} {city} IN",
        "Paid to {Name}",
        "ACH D- {NAME}-{digits}",
        "NEFT DR-{bank}0000123-{NAME}-{digits}",
        "{NAME}",
    ))
    text = template.format(
        digits=digits, NAME=name.upper(), Name=name, bank=rng.choice(_BANKS), compact=compact,
        psp=rng.choice(_PSPS), card=rng.choice(("4", "5")) + "".join(rng.choice("0123456789") for _ in range(5)),
        last4="".join(rng.choice("0123456789") for _ in range(4)), city=rng.choice(_CITIES),
    )
    if rng.random() < 0.2:  # banks often cut narrations short
        text = text[: rng.randint(22, 34)]
    return text


def make_corpus(seed: int, *, per_category: int = 40, mean_per_merchant: int = 15) -> list[LabelledText]:
    """A labelled corpus. Merchant popularity is skewed: a few merchants are very frequent."""
    rng = random.Random(seed)
    corpus = []
    for merchant in make_merchants(rng, per_category):
        count = max(1, int(rng.paretovariate(1.6) * mean_per_merchant / 2.5))
        for _ in range(min(count, mean_per_merchant * 8)):
            corpus.append(LabelledText(render(rng, merchant), merchant.category, merchant.name))
    rng.shuffle(corpus)
    return corpus
