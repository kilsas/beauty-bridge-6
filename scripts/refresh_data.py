"""
Data refresh: turn feed snapshots into the live tables, then rebuild.

This is the "sync" step. Run it by hand or on a schedule (see
.github/workflows/refresh.yml). It does NOT scrape retailer sites: most
retailers (Olive Young, Sephora, Amazon) forbid scraping in their terms.
Feeds must come from sources that allow reuse, for example:

  * affiliate / partner product feeds (CSV or JSON exports),
  * official APIs you have keys for (write a small adapter below),
  * your own manual observations (a CSV you fill in).

Feed format (CSV, one row per product x market x seller observation), in
data/feeds/*.csv:

  product_id, market, seller, price, currency, shipping, availability,
  rating, review_count, shipping_days, observed_at, source

What a refresh does:
  1. validates every feed row against products.csv and the codebook,
  2. appends new rows to price_observations.csv (full history, deduplicated),
  3. rewrites market_products.csv with the latest observation per
     product x market (lowest total price among sellers on that date),
  4. rebuilds the SQLite database and the website.

  python scripts/refresh_data.py [--data data/real] [--feeds data/feeds] [--no-build]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beautybridge.config import AVAILABILITY_SCALE, FX_TO_USD  # noqa: E402
from beautybridge.db import load_products_csv  # noqa: E402

FEED_COLUMNS = ["product_id", "market", "seller", "price", "currency", "shipping", "availability",
                "rating", "review_count", "shipping_days", "observed_at", "source"]
PRICE_COLUMNS = ["product_id", "market", "seller", "price", "shipping", "currency", "observed_at", "source"]
MARKET_COLUMNS = ["product_id", "market", "availability", "local_price", "currency", "rating",
                  "review_count", "shipping_days", "seller", "observed_at", "source"]


class FeedError(ValueError):
    pass


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def write_rows(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in cols} for r in rows)


def validate_feed(rows: list[dict], known: set[str], name: str) -> list[dict]:
    errors, good = [], []
    for i, r in enumerate(rows, start=2):
        missing = [c for c in ("product_id", "market", "seller", "price", "currency", "observed_at", "source") if not r.get(c)]
        if missing:
            errors.append(f"{name}:{i} missing {missing}")
            continue
        if r["product_id"] not in known:
            errors.append(f"{name}:{i} unknown product {r['product_id']}")
            continue
        if r["currency"].upper() not in FX_TO_USD:
            errors.append(f"{name}:{i} currency {r['currency']} has no FX rate")
            continue
        try:
            float(r["price"])
            float(r.get("shipping") or 0)
            if r.get("rating"):
                assert 0 <= float(r["rating"]) <= 5
            if r.get("review_count"):
                int(r["review_count"])
        except (ValueError, AssertionError):
            errors.append(f"{name}:{i} bad number in price/shipping/rating/review_count")
            continue
        av = (r.get("availability") or "high").lower()
        if av not in AVAILABILITY_SCALE:
            errors.append(f"{name}:{i} availability '{av}' not in {list(AVAILABILITY_SCALE)}")
            continue
        good.append({**r, "market": r["market"].upper(), "currency": r["currency"].upper(), "availability": av})
    if errors:
        raise FeedError(f"{len(errors)} problem(s):\n  " + "\n  ".join(errors))
    return good


def refresh(data_dir: Path, feeds_dir: Path) -> dict:
    products = load_products_csv(data_dir / "products.csv")
    feed_rows = []
    for path in sorted(feeds_dir.glob("*.csv")):
        feed_rows += validate_feed(read_rows(path), set(products), path.name)
    if not feed_rows:
        return {"feeds": 0, "new_prices": 0, "listings": 0}

    # 1) append to price history, deduplicated on its primary key
    history = read_rows(data_dir / "price_observations.csv")
    key = lambda r: (r["product_id"], r["market"], r["seller"], r["observed_at"])  # noqa: E731
    seen = {key(r) for r in history}
    added = 0
    for r in feed_rows:
        if key(r) not in seen:
            history.append({c: r.get(c, "") for c in PRICE_COLUMNS})
            seen.add(key(r))
            added += 1
    history.sort(key=key)
    write_rows(data_dir / "price_observations.csv", PRICE_COLUMNS, history)

    # 2) latest observation per product x market; cheapest total among sellers that day
    listings = {(r["product_id"], r["market"]): r for r in read_rows(data_dir / "market_products.csv")}
    by_pm = defaultdict(list)
    for r in feed_rows:
        by_pm[(r["product_id"], r["market"])].append(r)
    for pm, rows in by_pm.items():
        latest = max(r["observed_at"] for r in rows)
        today = [r for r in rows if r["observed_at"] == latest]
        best = min(today, key=lambda r: float(r["price"]) + float(r.get("shipping") or 0))
        old = listings.get(pm)
        if old and old.get("observed_at", "") > latest:
            continue  # never overwrite newer data with an older feed
        listings[pm] = {
            "product_id": pm[0], "market": pm[1], "availability": best["availability"],
            "local_price": best["price"], "currency": best["currency"],
            "rating": best.get("rating") or (old or {}).get("rating", ""),
            "review_count": best.get("review_count") or (old or {}).get("review_count", ""),
            "shipping_days": best.get("shipping_days") or (old or {}).get("shipping_days", ""),
            "seller": best["seller"], "observed_at": latest, "source": best["source"],
        }
    write_rows(data_dir / "market_products.csv", MARKET_COLUMNS,
               sorted(listings.values(), key=lambda r: (r["product_id"], r["market"])))
    return {"feeds": len(feed_rows), "new_prices": added, "listings": len(by_pm)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "demo"))
    ap.add_argument("--feeds", default=str(ROOT / "data" / "feeds"))
    ap.add_argument("--no-build", action="store_true", help="only update the CSV tables")
    args = ap.parse_args(argv)
    try:
        stats = refresh(Path(args.data), Path(args.feeds))
    except FeedError as e:
        print(f"refresh aborted, nothing changed:\n{e}", file=sys.stderr)
        return 1
    print(f"feed rows {stats['feeds']}, new price observations {stats['new_prices']}, "
          f"listings updated {stats['listings']}")
    if not args.no_build and stats["feeds"]:
        subprocess.run([sys.executable, "-m", "beautybridge", "build-db", args.data], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/build_site.py", "--data", args.data], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
