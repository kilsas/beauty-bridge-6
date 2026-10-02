"""
Build the Beauty Bridge website: one self-contained file, web/index.html.

No framework and no install: open the file in a browser, host it on any
static host (GitHub Pages, Netlify), or let the API serve it at "/".
Every recommendation is computed here by the real engine and embedded, so
the site shows exactly what the Python code returns. The Market Intelligence
section reads the sourced case-study files in data/market/.

  python scripts/build_site.py [--data folder] [--out web/index.html]
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beautybridge import codebook as cb, load_engine  # noqa: E402
from beautybridge.config import FUSION_MODES, FX_RATES_NOTE, FX_TO_USD, SIMILARITY_WEIGHTS  # noqa: E402
from beautybridge.db import MARKET_DIR  # noqa: E402
from beautybridge.goals import score_goal  # noqa: E402
from beautybridge.market import local_fit, popularity, signal_strength, trending  # noqa: E402
from beautybridge import search as search_mod  # noqa: E402
from beautybridge import reviews as rv  # noqa: E402

MARKETS = ["", "KR", "US", "JP", "CN"]


def compact(rec, kind: str) -> dict:
    d = rec.to_dict()
    out = {
        "id": d["product"]["product_id"],
        "f": d["final_score"],
        "c": {k: v for k, v in d["components"].items() if v is not None},
        "w": d["weights_used"],
        "usd": d["price_usd"],
        "save": d["savings_usd"],
    }
    block = d["similarity"] if kind == "sim" else d["goal"]
    out["pct"], out["ev"] = block["percent"], block["evidence"]
    if kind == "sim":
        out["x"] = [[c["attribute"], c["points"], c["max_points"], c["reason"]] for c in block["components"]]
    else:
        out["x"] = [[c["feature"], c["points"], c["max_points"], c["product_value"], c["rule"]]
                    for c in block["components"]]
    return out


MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def product_image(pid: str, meta: dict | None) -> dict | None:
    """A registered, licensed photo from web/images, embedded as a data URI."""
    if not meta:
        return None
    path = ROOT / "web" / "images" / meta["file"]
    if not path.exists() or path.suffix.lower() not in MIME:
        print(f"warning: image for {pid} not found or unsupported: {path}", file=sys.stderr)
        return None
    if path.stat().st_size > 400_000:
        print(f"warning: {path.name} is over 400 KB; resize it", file=sys.stderr)
    data = base64.b64encode(path.read_bytes()).decode()
    return {"src": f"data:{MIME[path.suffix.lower()]};base64,{data}",
            "credit": meta.get("credit", ""), "license": meta.get("license", ""),
            "url": meta.get("source_url", "")}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build(engine, ds_dir) -> dict:
    ds = engine.ds
    P = ds.products

    data_dir = Path(ds_dir)
    brands = {r["brand"]: r for r in (read_csv(data_dir / "brands.csv") or read_csv(ROOT / "data" / "demo" / "brands.csv"))}
    images = {r["product_id"]: r for r in read_csv(ROOT / "data" / "images.csv")}
    products = {}
    for p in P.values():
        d = p.to_dict()
        listings = []
        for m in ds.markets:
            l = ds.listings.get((p.product_id, m))
            if not l:
                continue
            usd = l.local_price * FX_TO_USD[l.currency] if l.local_price and l.currency else None
            listings.append({"m": m, "av": l.availability, "price": l.local_price, "cur": l.currency,
                             "est": "estimate" in l.source,
                             "usd": None if usd is None else round(usd, 2), "rating": l.rating,
                             "reviews": l.review_count, "ship": l.shipping_days, "at": l.observed_at})
        fits = []
        for g in ds.goals.values():
            r = score_goal(p, g)
            if r is not None:
                fits.append([g.goal_id, round(r.score * 100)])
        fits.sort(key=lambda x: -x[1])
        products[p.product_id] = {
            "brand": d["brand"], "name": d["name"], "ko": d["name_ko"], "al": list(p.aliases),
            "cat": d["category"], "grp": d["category_group"], "shade": d["shade_family"],
            "finish": d["finish"], "cov": d["coverage"], "tex": d["texture"], "tone": d["undertone"],
            "int": d["intensities"], "skin": d["skin_types"], "price": d["price"],
            "cur": d["currency"], "usd": d["price_usd"], "origin": d["country_origin"],
            "list": listings, "fits": fits[:4],
            "bko": brands.get(p.brand, {}).get("brand_ko", p.brand),
            "bcol": brands.get(p.brand, {}).get("color", "#6c6676"),
        }
        sig = {}
        for row in ds.signals:
            if row["product_id"] == p.product_id:
                sig.setdefault(row["market"], []).append({
                    "src": row["source"], "cat": row["category"], "rank": int(row["rank"]) if row.get("rank") else None,
                    "level": row["level"], "date": row["date"], "url": row["source_url"],
                    "s": round(signal_strength(row), 3)})
        for rows in sig.values():
            rows.sort(key=lambda r: -r["s"])
        products[p.product_id]["sig"] = sig
        img = product_image(p.product_id, images.get(p.product_id))
        if img:
            products[p.product_id]["img"] = img

    similar, cheaper = {}, {}
    for pid in P:
        similar[pid] = {m: [compact(r, "sim") for r in engine.similar(pid, k=10, market=m or None)] for m in MARKETS}
        cheaper[pid] = {m: [compact(r, "sim") for r in engine.cheaper(pid, k=12, market=m or None)] for m in MARKETS}

    goals = {}
    for gid, g in ds.goals.items():
        goals[gid] = {
            "meta": {"name": g.name, "ko": g.name_ko, "desc": g.description, "area": g.area,
                     "cats": sorted(g.eligible_categories), "al": list(g.aliases),
                     "rules": [c.describe() for c in g.criteria]},
            # full ranking so the page can filter by skin type without losing results
            "r": {m: [compact(r, "goal") for r in engine.goal(gid, k=30, market=m or None)] for m in MARKETS},
        }

    trends = {}
    for m in ds.markets:
        try:
            rows = trending(ds.rankings, m)
        except ValueError:
            rows = []
        if rows:
            trends[m] = [{"id": t.product_id, "rank": t.rank, "prev": t.previous_rank,
                          "chg": t.change, "st": t.status} for t in rows]

    local = {}
    for m in ds.markets:
        tindex = {t.product_id: t for t in trending(ds.rankings, m)} if m in trends else {}
        available = [p for p in P.values()
                     if (l := ds.listings.get((p.product_id, m))) and l.availability != "none"]
        peer = [l.local_price * FX_TO_USD[l.currency] for p in available
                if (l := ds.listings[(p.product_id, m)]).local_price]
        rows = []
        for p in available:
            pop, _ = popularity(ds, p.product_id, m, tindex)
            fit, _ = local_fit(ds, p.product_id, m, peer_prices_usd=peer, fx=FX_TO_USD, popularity_value=pop)
            rows.append({"id": p.product_id, "pop": round(pop or 0, 3), "fit": round(fit or 0, 3)})
        rows.sort(key=lambda r: -r["fit"])
        local[m] = rows

    for m, rows in local.items():
        for r in rows:
            products[r["id"]].setdefault("pop", {})[m] = r["pop"]
    for pid, pr in products.items():
        pr.setdefault("pop", {})
        pr["pop"][""] = pr["pop"].get(pr["origin"], 0)

    chart_dates = sorted({r.date for r in ds.rankings}) or [None, None]
    real = all("Real product" in p.source for p in P.values())

    # Featured references: products with a close, cheaper match from another country
    featured = []
    for pid, p in P.items():
        for r in engine.similar(pid, k=10):
            q = r.product
            if q.country_origin != p.country_origin and r.savings_usd and r.savings_usd > 0:
                featured.append((r.components["similarity"], pid, p.category))
                break
    seen_cats, feat = set(), []
    for sim, pid, cat in sorted(featured, reverse=True):
        if cat not in seen_cats:
            feat.append(pid)
            seen_cats.add(cat)
        if len(feat) == 3:
            break
    usd_prices = [p.price_usd for p in P.values() if p.price_usd]

    return {
        "products": products, "similar": similar, "cheaper": cheaper, "goals": goals,
        "trends": trends, "local": local,
        "areas": json.loads((ROOT / "data" / "beauty_goals.json").read_text(encoding="utf-8")).get("areas", []),
        "chartDates": chart_dates[-2:],
        "mode": "real" if real else "demo",
        "featured": ([x for x in (data_dir / "featured.txt").read_text().split() if x in P]
                     if (data_dir / "featured.txt").exists() else feat) or list(P)[:3],
        "reviewPrior": {"weight": rv.PRIOR_WEIGHT, "mean": rv.DEFAULT_PRIOR_MEAN, "window": rv.TREND_WINDOW_DAYS,
                        "ages": rv.AGE_BANDS, "maxText": rv.MAX_TEXT},
        "market": {
            "financials": read_csv(MARKET_DIR / "company_financials.csv"),
            "events": read_csv(MARKET_DIR / "company_events.csv"),
            "facts": read_csv(MARKET_DIR / "company_facts.csv"),
        },
        "config": {"weights": SIMILARITY_WEIGHTS, "modes": FUSION_MODES,
                   "fx": FX_TO_USD, "fxNote": FX_RATES_NOTE},
        "codebook": {"finish": list(cb.FINISH_SCALE), "coverage": list(cb.COVERAGE_SCALE),
                     "intensity": cb.INTENSITY_FEATURES, "groups": cb.CATEGORY_GROUPS,
                     "skin": cb.SKIN_TYPES},
        "query": {"intent": search_mod.INTENT_WORDS, "origin": search_mod.ORIGIN_WORDS,
                  "market": search_mod.MARKET_WORDS, "category": search_mod.CATEGORY_WORDS},
        "stats": {"products": len(P), "brands": len({p.brand for p in P.values()}),
                  "goals": len(ds.goals), "markets": ds.markets,
                  "medianUsd": round(statistics.median(usd_prices), 2) if usd_prices else None},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--out", default=str(ROOT / "web" / "index.html"))
    args = ap.parse_args(argv)
    data_dir = Path(args.data) if args.data else (ROOT / "data" / "real" if (ROOT / "data" / "real" / "products.csv").exists() else ROOT / "data" / "demo")
    data = build(load_engine(data_dir), data_dir)
    template = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if "/*__DATA__*/null" not in template:
        raise SystemExit("template is missing the /*__DATA__*/null placeholder")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    i18n = (ROOT / "web" / "i18n.js").read_text(encoding="utf-8")
    html = template.replace("/*__I18N__*/", i18n).replace("/*__DATA__*/null", payload)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
