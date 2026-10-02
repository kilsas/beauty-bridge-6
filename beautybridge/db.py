"""
Build a database from a data folder, and read it back into memory.

A data folder contains CSV files named like the ones in data/templates/.
Only products.csv is required. Beauty goals come from data/beauty_goals.json.

SQLite is used through the standard library. For PostgreSQL, run
db/schema.sql there and import the same CSVs (see README).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import codebook as cb
from .config import AVAILABILITY_SCALE
from .goals import BeautyGoal, parse_goals
from .product import Product, ValidationError, parse_product

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
GOALS_PATH = ROOT / "data" / "beauty_goals.json"
DEFAULT_DATA_DIR = ROOT / "data" / "demo"
DEFAULT_DB_PATH = ROOT / "db" / "beautybridge.sqlite"
# Real, sourced case-study data (Sephora Korea / Olive Young). Used whenever a
# data folder has no company files of its own.
MARKET_DIR = ROOT / "data" / "market"


@dataclass(frozen=True)
class MarketListing:
    product_id: str
    market: str
    availability: str
    local_price: float | None
    currency: str | None
    rating: float | None
    review_count: int | None
    shipping_days: int | None
    observed_at: str
    source: str

    @property
    def availability_score(self) -> float:
        return AVAILABILITY_SCALE[self.availability]


@dataclass(frozen=True)
class RankingEntry:
    market: str
    chart: str
    date: str
    rank: int
    product_id: str
    source: str = ""


@dataclass
class Dataset:
    products: dict[str, Product]
    goals: dict[str, BeautyGoal]
    listings: dict[tuple[str, str], MarketListing] = field(default_factory=dict)
    rankings: list[RankingEntry] = field(default_factory=list)
    financials: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    judgments: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)   # sourced awards / bestseller reports

    @property
    def markets(self) -> list[str]:
        return sorted({m for (_, m) in self.listings})


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items() if k}
            for row in csv.DictReader(f)
            if any((v or "").strip() for v in row.values())
        ]


def _num(v: str, kind=float):
    return None if v in ("", None) else kind(float(v.replace(",", "")))


def load_products_csv(path: Path) -> dict[str, Product]:
    """Parse and validate every row; report all errors at once."""
    rows = _read_csv(path)
    if not rows:
        raise ValidationError(f"{path} is missing or empty")
    missing = [c for c in cb.PRODUCT_COLUMNS if c not in rows[0]]
    if missing:
        raise ValidationError(f"{path.name} is missing columns: {missing}")
    products: dict[str, Product] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        pid = (row.get("product_id") or "").strip()
        if pid in seen:
            errors.append(f"line {line}: duplicate product_id {pid}")
            continue
        seen.add(pid)
        try:
            p = parse_product(row)
        except ValidationError as e:
            errors.append(f"line {line}: {e}")
            continue
        products[p.product_id] = p
    if errors:
        raise ValidationError(
            f"{len(errors)} problem(s) in {path.name}:\n  " + "\n  ".join(errors)
        )
    return products


def load_folder(data_dir: Path = DEFAULT_DATA_DIR, goals_path: Path = GOALS_PATH) -> Dataset:
    """Read a data folder straight into memory (no database needed)."""
    data_dir = Path(data_dir)
    products = load_products_csv(data_dir / "products.csv")
    goals = parse_goals(json.loads(Path(goals_path).read_text(encoding="utf-8")))

    listings: dict[tuple[str, str], MarketListing] = {}
    for row in _read_csv(data_dir / "market_products.csv"):
        if row["product_id"] not in products:
            raise ValidationError(f"market_products: unknown product {row['product_id']}")
        if row["availability"] not in AVAILABILITY_SCALE:
            raise ValidationError(f"market_products: bad availability {row['availability']}")
        listings[(row["product_id"], row["market"].upper())] = MarketListing(
            product_id=row["product_id"],
            market=row["market"].upper(),
            availability=row["availability"],
            local_price=_num(row.get("local_price", "")),
            currency=row.get("currency") or None,
            rating=_num(row.get("rating", "")),
            review_count=_num(row.get("review_count", ""), int),
            shipping_days=_num(row.get("shipping_days", ""), int),
            observed_at=row.get("observed_at", ""),
            source=row.get("source", ""),
        )

    rankings = []
    for row in _read_csv(data_dir / "rankings.csv"):
        if row["product_id"] not in products:
            raise ValidationError(f"rankings: unknown product {row['product_id']}")
        rankings.append(RankingEntry(
            market=row["market"].upper(), chart=row["chart"], date=row["date"],
            rank=int(row["rank"]), product_id=row["product_id"],
            source=row.get("source") or "unspecified",
        ))

    signals = _read_csv(data_dir / "market_signals.csv")
    for row in signals:
        if row["product_id"] not in products:
            raise ValidationError(f"market_signals: unknown product {row['product_id']}")
        if not row.get("source_url"):
            raise ValidationError(f"market_signals: {row['product_id']} has no source_url")
        if row.get("level") not in ("product", "brand"):
            raise ValidationError(f"market_signals: level must be product or brand ({row['product_id']})")
        row["market"] = row["market"].upper()

    financials = (_read_csv(data_dir / "company_financials.csv")
                  or _read_csv(MARKET_DIR / "company_financials.csv"))
    events = (_read_csv(data_dir / "company_events.csv")
              or _read_csv(MARKET_DIR / "company_events.csv"))
    for row in events:
        if not row.get("source_url"):
            raise ValidationError(f"company_events: '{row.get('event')}' has no source_url")
    for row in financials:
        if not row.get("source_url"):
            raise ValidationError(
                f"company_financials: {row.get('company')} {row.get('fiscal_year')} "
                "has no source_url; every figure must be traceable"
            )

    return Dataset(
        products=products,
        goals=goals,
        listings=listings,
        rankings=rankings,
        financials=financials,
        events=events,
        judgments=_read_csv(data_dir / "judgments.csv"),
        signals=signals,
    )


# ---------------------------------------------------------------------------
# SQLite build
# ---------------------------------------------------------------------------
def _product_row(p: Product) -> dict:
    row = {
        "product_id": p.product_id, "brand": p.brand, "name": p.name,
        "name_ko": p.name_ko, "aliases": cb.MULTI_VALUE_SEPARATOR.join(p.aliases),
        "category": p.category, "category_group": p.category_group,
        "shade_family": p.shade_family, "finish": p.finish,
        "coverage": p.coverage, "texture": p.texture, "undertone": p.undertone,
        "skin_types": cb.MULTI_VALUE_SEPARATOR.join(sorted(p.skin_types)),
        "price": p.price, "currency": p.currency,
        "country_origin": p.country_origin, "url": p.url, "source": p.source,
        "labeled_by": p.labeled_by, "notes": p.notes,
    }
    for feat, v in p.intensities.items():
        row[feat] = None if v is None else round(v * cb.INTENSITY_MAX)
    return row


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    table_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    cols = [c for c in rows[0] if c in table_cols]  # ignore helper columns
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    conn.executemany(sql, [[(r.get(c) if r.get(c) != "" else None) for c in cols] for r in rows])


def build_sqlite(
    data_dir: Path = DEFAULT_DATA_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    goals_path: Path = GOALS_PATH,
) -> Dataset:
    """Validate a data folder and write it to a fresh SQLite file."""
    ds = load_folder(data_dir, goals_path)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _insert(conn, "products", [_product_row(p) for p in ds.products.values()])
        _insert(conn, "beauty_goals", [{
            "goal_id": g.goal_id, "area": g.area, "name": g.name, "name_ko": g.name_ko,
            "description": g.description,
            "eligible_categories": cb.MULTI_VALUE_SEPARATOR.join(sorted(g.eligible_categories)),
        } for g in ds.goals.values()])
        _insert(conn, "goal_criteria", [{
            "goal_id": g.goal_id, "position": i, "type": c.type, "feature": c.feature,
            "target": c.target,
            "vals": cb.MULTI_VALUE_SEPARATOR.join(sorted(c.values)) if c.values else None,
            "weight": c.weight,
        } for g in ds.goals.values() for i, c in enumerate(g.criteria)])
        _insert(conn, "market_products", [l.__dict__ for l in ds.listings.values()])
        _insert(conn, "rankings", [r.__dict__ for r in ds.rankings])
        _insert(conn, "company_financials", ds.financials)
        _insert(conn, "company_events", ds.events)
        _insert(conn, "judgments", ds.judgments)
        _insert(conn, "price_observations", _read_csv(Path(data_dir) / "price_observations.csv"))
        conn.commit()
    finally:
        conn.close()
    return ds


def load_sqlite(db_path: Path = DEFAULT_DB_PATH, goals_path: Path = GOALS_PATH) -> Dataset:
    """Read a database built by build_sqlite back into memory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        def rows(sql: str) -> list[dict]:
            return [
                {k: ("" if r[k] is None else str(r[k]) if not isinstance(r[k], str) else r[k])
                 for k in r.keys()}
                for r in conn.execute(sql)
            ]

        products = {}
        for r in rows("SELECT * FROM products ORDER BY product_id"):
            p = parse_product(r)
            products[p.product_id] = p
        goals = parse_goals(json.loads(Path(goals_path).read_text(encoding="utf-8")))
        listings = {}
        for r in rows("SELECT * FROM market_products"):
            listings[(r["product_id"], r["market"])] = MarketListing(
                product_id=r["product_id"], market=r["market"],
                availability=r["availability"],
                local_price=_num(r["local_price"]), currency=r["currency"] or None,
                rating=_num(r["rating"]), review_count=_num(r["review_count"], int),
                shipping_days=_num(r["shipping_days"], int),
                observed_at=r["observed_at"], source=r["source"],
            )
        rankings = [
            RankingEntry(r["market"], r["chart"], r["date"], int(r["rank"]),
                         r["product_id"], r["source"])
            for r in rows("SELECT * FROM rankings")
        ]
        return Dataset(
            products=products, goals=goals, listings=listings, rankings=rankings,
            financials=rows("SELECT * FROM company_financials"),
            events=rows("SELECT * FROM company_events"),
            judgments=rows("SELECT * FROM judgments"),
        )
    finally:
        conn.close()
