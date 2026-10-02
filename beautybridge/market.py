"""
Popularity, trend detection and local market fit.

Kept strictly separate from similarity: "how similar is it?" and "how popular
is it?" are different questions, combined only in rank fusion, and always
reported as separate numbers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import (
    LOCAL_WEIGHTS, POPULARITY_WEIGHTS, REVIEW_COUNT_SATURATION,
    RISING_THRESHOLD, SHIPPING_DAYS_AT_ZERO,
)
from .db import Dataset, MarketListing, RankingEntry


def _renormalized(parts: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, dict]:
    usable = {k: v for k, v in parts.items() if v is not None and weights.get(k, 0) > 0}
    total = sum(weights[k] for k in usable)
    if total == 0:
        return None, {}
    detail = {k: {"value": round(v, 3), "weight": round(weights[k] / total, 3)} for k, v in usable.items()}
    return sum(weights[k] / total * v for k, v in usable.items()), detail


def review_score(review_count: int | None) -> float | None:
    if review_count is None:
        return None
    return min(1.0, math.log1p(review_count) / math.log1p(REVIEW_COUNT_SATURATION))


def rating_score(rating: float | None) -> float | None:
    # 3.0 stars or below = 0, 5.0 = 1 (almost nothing is rated below 3)
    return None if rating is None else max(0.0, min(1.0, (rating - 3.0) / 2.0))


# ---------------------------------------------------------------------------
# Rankings and trends
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TrendEntry:
    product_id: str
    rank: int
    previous_rank: int | None
    chart_size: int

    @property
    def change(self) -> int | None:
        """Positive = moved up the chart."""
        return None if self.previous_rank is None else self.previous_rank - self.rank

    @property
    def status(self) -> str:
        if self.previous_rank is None:
            return "new"
        if self.change >= RISING_THRESHOLD:
            return "rising"
        if self.change <= -RISING_THRESHOLD:
            return "falling"
        return "steady"

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id, "rank": self.rank,
            "previous_rank": self.previous_rank, "change": self.change,
            "status": self.status,
        }


def chart_snapshots(rankings: list[RankingEntry], market: str, chart: str | None = None):
    rows = [r for r in rankings if r.market == market and (chart is None or r.chart == chart)]
    charts = sorted({r.chart for r in rows})
    if chart is None and len(charts) > 1:
        raise ValueError(f"market {market} has several charts {charts}; pass chart=")
    dates = sorted({r.date for r in rows})
    return {d: {r.product_id: r.rank for r in rows if r.date == d} for d in dates}


def trending(rankings: list[RankingEntry], market: str, chart: str | None = None) -> list[TrendEntry]:
    """Latest chart for a market, each entry compared with the previous snapshot."""
    snaps = chart_snapshots(rankings, market, chart)
    if not snaps:
        return []
    dates = sorted(snaps)
    latest = snaps[dates[-1]]
    previous = snaps[dates[-2]] if len(dates) > 1 else {}
    entries = [
        TrendEntry(pid, rank, previous.get(pid), len(latest))
        for pid, rank in latest.items()
    ]
    return sorted(entries, key=lambda e: e.rank)


def rank_score(entry: TrendEntry | None) -> float | None:
    if entry is None:
        return None
    if entry.chart_size <= 1:
        return 1.0
    return 1.0 - (entry.rank - 1) / (entry.chart_size - 1)


def growth_score(entry: TrendEntry | None) -> float | None:
    if entry is None or entry.change is None:
        return None
    # map change in [-size, +size] to [0, 1]; no change = 0.5
    return max(0.0, min(1.0, 0.5 + entry.change / (2 * entry.chart_size)))


# ---------------------------------------------------------------------------
# Popularity in one market
# ---------------------------------------------------------------------------
def popularity(ds: Dataset, product_id: str, market: str,
               trend_index: dict[str, TrendEntry] | None = None) -> tuple[float | None, dict]:
    listing = ds.listings.get((product_id, market))
    entry = (trend_index or {}).get(product_id)
    parts = {
        "rank": rank_score(entry),
        "reviews": review_score(listing.review_count) if listing else None,
        "rating": rating_score(listing.rating) if listing else None,
        "growth": growth_score(entry),
    }
    return _renormalized(parts, POPULARITY_WEIGHTS)


# ---------------------------------------------------------------------------
# Local fit: can a shopper in this market actually get it, at a fair price?
# ---------------------------------------------------------------------------
def shipping_score(days: int | None) -> float | None:
    return None if days is None else max(0.0, 1.0 - days / SHIPPING_DAYS_AT_ZERO)


def local_price_score(listing: MarketListing, peer_prices_usd: list[float], fx: dict[str, float]) -> float | None:
    """1 = cheapest among comparable products sold in this market, 0 = priciest."""
    if listing.local_price is None or not listing.currency or not peer_prices_usd:
        return None
    mine = listing.local_price * fx[listing.currency]
    lo, hi = min(peer_prices_usd), max(peer_prices_usd)
    if hi == lo:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (mine - lo) / (hi - lo)))


def local_fit(ds: Dataset, product_id: str, market: str, *,
              peer_prices_usd: list[float], fx: dict[str, float],
              popularity_value: float | None) -> tuple[float | None, dict]:
    listing = ds.listings.get((product_id, market))
    if listing is None or listing.availability == "none":
        return 0.0, {"availability": {"value": 0.0, "weight": 1.0,
                                      "note": f"not sold in {market}"}}
    parts = {
        "availability": listing.availability_score,
        "popularity": popularity_value,
        "price": local_price_score(listing, peer_prices_usd, fx),
        "reviews": review_score(listing.review_count),
        "shipping": shipping_score(listing.shipping_days),
    }
    return _renormalized(parts, LOCAL_WEIGHTS)


# ---------------------------------------------------------------------------
# Market signals: sourced awards and bestseller reports per country
# ---------------------------------------------------------------------------
UNRANKED_PRODUCT_SIGNAL = 0.65


def signal_strength(row: dict) -> float:
    """0..1 strength of one sourced signal (see docs/research_design.md)."""
    rank = int(row["rank"]) if str(row.get("rank") or "").strip() else None
    if row.get("level") == "brand":
        return {1: 0.5, 2: 0.45, 3: 0.4}.get(rank, 0.38)
    cat = row.get("category", "")
    if "launch" in cat:
        return 0.9
    if cat == "overall" and rank:
        return max(0.7, 1.02 - 0.04 * rank)          # #1 overall ~ 0.98, #7 ~ 0.74
    if rank:
        return {1: 1.0, 2: 0.85, 3: 0.75}.get(rank, 0.7)
    return UNRANKED_PRODUCT_SIGNAL


def market_signal(ds: Dataset, product_id: str, market: str) -> tuple[float | None, list[dict]]:
    """Strongest sourced signal for a product in one market, with the evidence."""
    rows = [r for r in ds.signals if r["product_id"] == product_id and r["market"] == market]
    if not rows:
        return None, []
    return max(signal_strength(r) for r in rows), rows
