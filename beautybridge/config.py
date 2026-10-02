"""
Tunable parameters. Everything a research experiment might vary lives here,
so model variants (A/B/C) are just different configs, not different code.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Product-to-product similarity weights (must sum to 1; renormalized anyway)
# ---------------------------------------------------------------------------
SIMILARITY_WEIGHTS: dict[str, float] = {
    "category": 0.20,
    "function": 0.25,    # the 7 intensity features, compared as a profile
    "finish": 0.20,
    "texture": 0.15,
    "skin_type": 0.10,
    "coverage": 0.05,
    "price": 0.05,
}

# Candidates whose category similarity is below this are never "similar",
# however close their other attributes are (a toner is not a powder dupe).
MIN_CATEGORY_SIMILARITY = 0.3

# If less than this share of the similarity weight could be evaluated
# (because attributes are missing), the result is flagged low-confidence.
MIN_EVIDENCE = 0.6

# Price ratio at which price similarity reaches 0 (4 = four times the price).
PRICE_RATIO_AT_ZERO = 4.0

# ---------------------------------------------------------------------------
# "Similar but cheaper"
# ---------------------------------------------------------------------------
CHEAPER_MIN_SIMILARITY = 0.80

# ---------------------------------------------------------------------------
# Currency conversion to USD.
# Rates as read on the date in FX_RATES_NOTE. Update them (and the note)
# before any real analysis and record the date in your paper.
# ---------------------------------------------------------------------------
FX_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "KRW": 1 / 1352.79,
    "JPY": 1 / 157.29,
    "CNY": 1 / 6.7034,
    "EUR": 1.1467,
    "SGD": 1 / 1.34,   # not refreshed
}
FX_RATES_NOTE = "Investing.com rates read on 2026-09-30 (USD/KRW 1352.79, USD/JPY 157.29, USD/CNY 6.7034, EUR/USD 1.1467). Refresh before analysis."

# ---------------------------------------------------------------------------
# Rank fusion modes. Each component is a 0..1 score; missing components are
# dropped and the remaining weights renormalized (and reported).
# ---------------------------------------------------------------------------
FUSION_MODES: dict[str, dict[str, float]] = {
    # Model A in the evaluation: pure content similarity
    "similarity_only": {"similarity": 1.0},
    # Model B
    "similarity_price": {"similarity": 0.75, "price": 0.25},
    # Model C
    "similarity_price_local": {
        "similarity": 0.60, "price": 0.20, "local": 0.10, "popularity": 0.10,
    },
    # Product-facing modes (from the project plan)
    "similar": {"similarity": 0.70, "local": 0.10, "price": 0.10, "popularity": 0.10},
    "cheaper": {"similarity": 0.40, "price": 0.35, "local": 0.15, "popularity": 0.10},
    "goal": {"goal": 0.50, "popularity": 0.20, "price": 0.15, "local": 0.15},
}

# ---------------------------------------------------------------------------
# Popularity and local fit
# ---------------------------------------------------------------------------
POPULARITY_WEIGHTS: dict[str, float] = {
    "rank": 0.40, "reviews": 0.25, "rating": 0.20, "growth": 0.15,
}
# Review count that maps to a review score of 1.0 (log scale).
REVIEW_COUNT_SATURATION = 10_000
# Rank improvement (positions) that counts as a "rising" product.
RISING_THRESHOLD = 10

LOCAL_WEIGHTS: dict[str, float] = {
    "availability": 0.30, "popularity": 0.25, "price": 0.20,
    "reviews": 0.15, "shipping": 0.10,
}
AVAILABILITY_SCALE: dict[str, float] = {
    "none": 0.0, "low": 1 / 3, "medium": 2 / 3, "high": 1.0,
}
# Shipping days that map to a shipping score of 0.
SHIPPING_DAYS_AT_ZERO = 21
