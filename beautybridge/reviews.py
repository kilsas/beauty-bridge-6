"""
First-party reviews: the live signal behind rankings.

Rankings like a review app's come from the site's own users, not from
scraping other shops. Every review carries who wrote it (an opaque id), a
1-5 rating, and optional context (skin type, age band, the country the
reviewer shops in), so rankings can be cut the same ways.

Scoring uses a Bayesian average so one 5-star review does not beat fifty
4.7s:  score = (C * m + sum_of_ratings) / (C + n)
where m is the mean over all reviews in scope and C (PRIOR_WEIGHT) is how
many "average" reviews every product starts with. The website computes the
identical formula in JavaScript (web/template.html, bayes()).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import codebook as cb

PRIOR_WEIGHT = 5
DEFAULT_PRIOR_MEAN = 3.8        # used only when there are no reviews at all
AGE_BANDS = ["10s", "20s", "30s", "40s+"]
MAX_TEXT = 300
TREND_WINDOW_DAYS = 7


def reviewer_key(reviewer_id: str) -> str:
    """Public, one-way key for a reviewer (first 16 hex chars of SHA-256).
    The website computes the same value to recognise its own reviews."""
    import hashlib
    return hashlib.sha256(reviewer_id.encode("utf-8")).hexdigest()[:16]


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class Review:
    reviewer_id: str
    product_id: str
    rating: int
    created_at: str                   # ISO 8601, UTC
    skin_type: str | None = None
    age_band: str | None = None
    market: str | None = None
    text: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def make_review(data: dict, known_products: set[str]) -> Review:
    """Validate raw input (from a form or the API) into a Review."""
    pid = str(data.get("product_id", "")).strip()
    if pid not in known_products:
        raise ReviewError(f"unknown product '{pid}'")
    rid = str(data.get("reviewer_id", "")).strip()
    if not rid or len(rid) > 128:
        raise ReviewError("reviewer_id is required")
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        raise ReviewError("rating must be an integer 1-5") from None
    if not 1 <= rating <= 5:
        raise ReviewError("rating must be an integer 1-5")
    skin = data.get("skin_type") or None
    if skin is not None and skin not in cb.SKIN_TYPES:
        raise ReviewError(f"skin_type must be one of {cb.SKIN_TYPES}")
    age = data.get("age_band") or None
    if age is not None and age not in AGE_BANDS:
        raise ReviewError(f"age_band must be one of {AGE_BANDS}")
    market = (data.get("market") or "").upper() or None
    text = str(data.get("text") or "").strip()
    if len(text) > MAX_TEXT:
        raise ReviewError(f"text is limited to {MAX_TEXT} characters")
    created = data.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except ValueError:
        raise ReviewError("created_at must be ISO 8601") from None
    return Review(rid, pid, rating, str(created), skin, age, market, text)


def latest_per_reviewer(reviews: list[Review]) -> list[Review]:
    """One review per (reviewer, product): the most recent one counts."""
    best: dict[tuple[str, str], Review] = {}
    for r in reviews:
        key = (r.reviewer_id, r.product_id)
        if key not in best or r.created_at > best[key].created_at:
            best[key] = r
    return list(best.values())


def filter_reviews(reviews: list[Review], *, skin_type: str | None = None,
                   age_band: str | None = None, market: str | None = None) -> list[Review]:
    return [r for r in reviews
            if (skin_type is None or r.skin_type == skin_type)
            and (age_band is None or r.age_band == age_band)
            and (market is None or r.market == market)]


def bayes_scores(reviews: list[Review], prior_weight: float = PRIOR_WEIGHT) -> dict[str, dict]:
    """Per product: n, mean rating and Bayesian score (1-5)."""
    reviews = latest_per_reviewer(reviews)
    if not reviews:
        return {}
    m = sum(r.rating for r in reviews) / len(reviews)
    by: dict[str, list[int]] = defaultdict(list)
    for r in reviews:
        by[r.product_id].append(r.rating)
    return {
        pid: {"n": len(v), "mean": sum(v) / len(v),
              "score": (prior_weight * m + sum(v)) / (prior_weight + len(v))}
        for pid, v in by.items()
    }


def popularity_from_reviews(stats: dict) -> float:
    """Map a Bayesian score (1-5) to 0..1 for rank fusion."""
    return max(0.0, min(1.0, (stats["score"] - 1) / 4))


def ranking(reviews: list[Review], product_ids: list[str] | None = None, **filters) -> list[dict]:
    """Products ranked by Bayesian score within a segment (skin, age, market)."""
    scores = bayes_scores(filter_reviews(reviews, **filters))
    rows = [{"product_id": pid, **s} for pid, s in scores.items()
            if product_ids is None or pid in product_ids]
    rows.sort(key=lambda r: (-r["score"], -r["n"], r["product_id"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def trending(reviews: list[Review], now: datetime | None = None,
             window_days: int = TREND_WINDOW_DAYS) -> list[dict]:
    """Review momentum: reviews in the last window vs the window before."""
    now = now or datetime.now(timezone.utc)
    recent_start = now - timedelta(days=window_days)
    prev_start = now - timedelta(days=2 * window_days)
    recent, prev = defaultdict(int), defaultdict(int)
    for r in latest_per_reviewer(reviews):
        t = datetime.fromisoformat(r.created_at.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= recent_start:
            recent[r.product_id] += 1
        elif t >= prev_start:
            prev[r.product_id] += 1
    rows = [{"product_id": pid, "recent": recent[pid], "previous": prev[pid],
             "growth": recent[pid] - prev[pid]} for pid in set(recent) | set(prev)]
    rows.sort(key=lambda r: (-r["growth"], -r["recent"], r["product_id"]))
    return rows


def click_stats(clicks: list[dict], now: datetime | None = None,
                window_days: int = TREND_WINDOW_DAYS) -> dict[str, dict]:
    """'Buy' button clicks per product: distinct people (all time and recent) and raw clicks.
    Ranking uses people, so one visitor clicking many times counts once."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    people, recent, n = defaultdict(set), defaultdict(set), defaultdict(int)
    for c in clicks:
        pid, who = c["product_id"], c["visitor_id"]
        people[pid].add(who)
        n[pid] += 1
        t = datetime.fromisoformat(str(c["created_at"]).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= start:
            recent[pid].add(who)
    return {pid: {"people": len(people[pid]), "people_7d": len(recent[pid]), "clicks": n[pid]} for pid in people}


def make_click(data: dict, known_products: set[str]) -> dict:
    pid = str(data.get("product_id", "")).strip()
    if pid not in known_products:
        raise ReviewError(f"unknown product '{pid}'")
    vid = str(data.get("visitor_id", "")).strip()
    if not vid or len(vid) > 128:
        raise ReviewError("visitor_id is required")
    store = str(data.get("store", "")).strip()
    if not store or len(store) > 40:
        raise ReviewError("store is required")
    market = (data.get("market") or "").upper() or None
    if market is not None and market not in ("KR", "US", "JP", "CN"):
        raise ReviewError("market must be KR, US, JP or CN")
    return {"visitor_id": vid, "product_id": pid, "store": store, "market": market,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class ReviewStore:
    """SQLite-backed review storage for the API (one row per reviewer x product)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS reviews (
        reviewer_id TEXT NOT NULL,
        product_id  TEXT NOT NULL,
        rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
        skin_type   TEXT,
        age_band    TEXT,
        market      TEXT,
        text        TEXT,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (reviewer_id, product_id)
    )"""

    CLICKS = """
    CREATE TABLE IF NOT EXISTS buy_clicks (
        visitor_id  TEXT NOT NULL,
        product_id  TEXT NOT NULL,
        store       TEXT NOT NULL,
        market      TEXT,
        created_at  TEXT NOT NULL
    )"""

    VOTES = """
    CREATE TABLE IF NOT EXISTS shade_votes (
        voter_id    TEXT NOT NULL,
        product_id  TEXT NOT NULL,
        shade       TEXT NOT NULL,
        pc_type     TEXT NOT NULL,
        verdict     TEXT NOT NULL CHECK (verdict IN ('suits','okay','not')),
        created_at  TEXT NOT NULL,
        PRIMARY KEY (voter_id, product_id, shade)
    )"""

    def __init__(self, path):
        import sqlite3
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(self.SCHEMA)
        self.conn.execute(self.CLICKS)
        self.conn.execute(self.VOTES)
        self.conn.commit()

    def upsert(self, r: Review) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?,?,?)",
            (r.reviewer_id, r.product_id, r.rating, r.skin_type, r.age_band, r.market, r.text, r.created_at),
        )
        self.conn.commit()

    def delete(self, reviewer_id: str, product_id: str) -> None:
        self.conn.execute("DELETE FROM reviews WHERE reviewer_id=? AND product_id=?", (reviewer_id, product_id))
        self.conn.commit()

    def all(self) -> list[Review]:
        cur = self.conn.execute(
            "SELECT reviewer_id, product_id, rating, created_at, skin_type, age_band, market, text FROM reviews")
        return [Review(*row[:4], row[4], row[5], row[6], row[7] or "") for row in cur]

    def add_click(self, c: dict) -> None:
        self.conn.execute("INSERT INTO buy_clicks VALUES (?,?,?,?,?)",
                          (c["visitor_id"], c["product_id"], c["store"], c["market"], c["created_at"]))
        self.conn.commit()

    def clicks(self) -> list[dict]:
        cur = self.conn.execute("SELECT visitor_id, product_id, store, market, created_at FROM buy_clicks")
        return [dict(zip(("visitor_id", "product_id", "store", "market", "created_at"), row)) for row in cur]

    # shade checks: one answer per person per shade (a new answer replaces the old one)
    def upsert_vote(self, v: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO shade_votes VALUES (?,?,?,?,?,?)",
                          (v["voter_id"], v["product_id"], v["shade"], v["pc_type"], v["verdict"],
                           datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    def delete_vote(self, voter_id: str, product_id: str, shade: str) -> None:
        self.conn.execute("DELETE FROM shade_votes WHERE voter_id=? AND product_id=? AND shade=?",
                          (voter_id, product_id, shade))
        self.conn.commit()

    def votes(self, voter_id: str | None = None) -> list[dict]:
        q = "SELECT voter_id, product_id, shade, pc_type, verdict, created_at FROM shade_votes"
        cur = self.conn.execute(q + " WHERE voter_id=?", (voter_id,)) if voter_id else self.conn.execute(q)
        return [dict(zip(("voter_id", "product_id", "shade", "pc_type", "verdict", "created_at"), row)) for row in cur]
