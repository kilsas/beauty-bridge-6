"""
Generate the DEMO market and ranking tables for the fictional demo products.

These are synthetic numbers that exist only so every feature of the engine
can be exercised end to end. Never cite them. Real data replaces them in
data/real/ (see README, "Replacing demo data").

Run:  python scripts/make_demo_side_data.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"

MARKETS = {"KR": "KRW", "US": "USD", "JP": "JPY", "CN": "CNY"}
FX = {"USD": 1.0, "KRW": 1 / 1390, "JPY": 1 / 147, "CNY": 1 / 7.2}


def main() -> None:
    rng = random.Random(20260930)
    with open(DEMO / "products.csv", newline="", encoding="utf-8") as f:
        products = list(csv.DictReader(f))

    market_rows = []
    for p in products:
        home = p["country_origin"]
        price_usd = float(p["price"]) * FX[p["currency"]]
        for market, cur in MARKETS.items():
            if market == home:
                availability, markup, ship = "high", 1.0, rng.randint(1, 3)
            else:
                availability = rng.choices(
                    ["none", "low", "medium", "high"], weights=[2, 3, 4, 2]
                )[0]
                if availability == "none":
                    continue
                markup = rng.uniform(1.15, 1.6)
                ship = rng.randint(5, 16)
            local_price = price_usd * markup / FX[cur]
            local_price = int(round(local_price, -2)) if cur in ("KRW", "JPY") else round(local_price, 2 if cur == "USD" else 0)
            reviews = int(rng.lognormvariate(6.5 if market == home else 4.5, 1.1))
            market_rows.append({
                "product_id": p["product_id"],
                "market": market,
                "availability": availability,
                "local_price": local_price,
                "currency": cur,
                "rating": round(rng.uniform(3.6, 4.9), 1),
                "review_count": reviews,
                "shipping_days": ship,
                "seller": "demo_store",
                "observed_at": "2026-09-28",
                "source": "DEMO synthetic",
            })

    with open(DEMO / "market_products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(market_rows[0]))
        w.writeheader()
        w.writerows(market_rows)

    # Two weekly snapshots of a top-30 chart per market so trend detection has
    # input: mostly small moves, two drop-outs, two newcomers, three clear risers.
    rank_rows = []
    for market in MARKETS:
        ids = [r["product_id"] for r in market_rows if r["market"] == market]
        size = min(30, len(ids) - 2)
        week1 = rng.sample(ids, size)
        week2 = week1[:]
        for _ in range(12):
            i = rng.randrange(len(week2) - 1)
            week2[i], week2[i + 1] = week2[i + 1], week2[i]
        newcomers = [pid for pid in ids if pid not in week1][:2]
        week2 = week2[:-2]
        for pid in newcomers:
            week2.insert(rng.randint(8, min(20, len(week2))), pid)
        for pid in week2[size - 8:size - 5]:
            week2.remove(pid)
            week2.insert(rng.randint(0, 6), pid)
        for date, order in (("2026-09-21", week1), ("2026-09-28", week2)):
            for rank, pid in enumerate(order, start=1):
                rank_rows.append({
                    "market": market, "chart": "demo_overall", "date": date,
                    "rank": rank, "product_id": pid, "source": "DEMO synthetic",
                })
    with open(DEMO / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rank_rows[0]))
        w.writeheader()
        w.writerows(rank_rows)

    print(f"wrote {len(market_rows)} market rows, {len(rank_rows)} ranking rows")


if __name__ == "__main__":
    main()
