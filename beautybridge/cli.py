"""
Command line interface.

  python -m beautybridge validate [data_dir]
  python -m beautybridge build-db [data_dir] [--db path]
  python -m beautybridge search "bake set"
  python -m beautybridge similar P001 [--market US] [--origin KR] [--mode similar]
  python -m beautybridge cheaper P001 [--market US]
  python -m beautybridge goal aegyo_sal [--market KR] [--skin oily]
  python -m beautybridge goals
  python -m beautybridge trending KR
  python -m beautybridge ask "cheap korean powder like bake set"
Add --data <folder|.sqlite> to any command to use other data, --json for raw output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import load_engine
from .config import FUSION_MODES
from .db import DEFAULT_DATA_DIR, DEFAULT_DB_PATH, build_sqlite, load_folder
from .engine import NotFound, Recommendation
from .product import ValidationError


def bar(points: float, max_points: float, width: int = 12) -> str:
    filled = 0 if max_points == 0 else round(width * points / max_points)
    return "█" * filled + "·" * (width - filled)


def print_recs(recs: list[Recommendation], explain: bool = True) -> None:
    if not recs:
        print("  (no results)")
        return
    for i, r in enumerate(recs, 1):
        p = r.product
        price = f"${r.price_usd:,.2f}" if r.price_usd is not None else "price n/a"
        save = f"  save ${r.savings_usd:,.2f}" if r.savings_usd and r.savings_usd > 0 else ""
        print(f"\n{i:>2}. {p.display_name}  [{p.product_id}, {p.category}, {p.country_origin}]")
        comps = "  ".join(f"{k} {v:.2f}" for k, v in r.components.items() if v is not None)
        print(f"    final {r.final_score:.3f}  |  {comps}  |  {price}{save}")
        if not explain:
            continue
        block = r.similarity or r.goal
        if block:
            label = "match" if r.similarity else "goal fit"
            flag = "  (low confidence: many attributes unlabeled)" if block.get("low_confidence") else ""
            print(f"    {block['percent']}% {label}{flag}")
            for c in block["components"]:
                name = c.get("attribute") or c.get("feature")
                why = c.get("reason") or f"{c['product_value']} (wants {c['rule']})"
                print(f"      {name:<12} {bar(c['points'], c['max_points'])} "
                      f"{c['points']:>4.1f}/{c['max_points']:<4.1f} {why}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="beautybridge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data folder or .sqlite file (default: demo data)")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check a data folder against the codebook")
    v.add_argument("folder", nargs="?", default=str(DEFAULT_DATA_DIR))
    b = sub.add_parser("build-db", help="validate a data folder and write SQLite")
    b.add_argument("folder", nargs="?", default=str(DEFAULT_DATA_DIR))
    b.add_argument("--db", default=str(DEFAULT_DB_PATH))

    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-k", type=int, default=10)
    for name in ("similar", "cheaper"):
        c = sub.add_parser(name)
        c.add_argument("product_id"); c.add_argument("-k", type=int, default=5)
        c.add_argument("--market"); c.add_argument("--origin")
        if name == "similar":
            c.add_argument("--mode", default="similar", choices=sorted(FUSION_MODES))
            c.add_argument("--method", default="weighted", choices=["weighted", "cosine"])
    g = sub.add_parser("goal"); g.add_argument("goal_id"); g.add_argument("-k", type=int, default=5)
    g.add_argument("--market"); g.add_argument("--skin"); g.add_argument("--category")
    sub.add_parser("goals")
    t = sub.add_parser("trending"); t.add_argument("market"); t.add_argument("--chart")
    a = sub.add_parser("ask"); a.add_argument("query"); a.add_argument("-k", type=int, default=5)
    a.add_argument("--market")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "validate":
            ds = load_folder(Path(args.folder))
            print(f"OK: {len(ds.products)} products, {len(ds.goals)} goals, "
                  f"{len(ds.listings)} market listings, {len(ds.rankings)} ranking rows, "
                  f"{len(ds.financials)} financial rows")
            return 0
        if args.cmd == "build-db":
            ds = build_sqlite(Path(args.folder), Path(args.db))
            print(f"wrote {args.db} ({len(ds.products)} products)")
            return 0

        engine = load_engine(args.data)
        out = None
        if args.cmd == "search":
            res = engine.search(args.query, k=args.k)
            if args.json:
                out = res
            else:
                print(f"parsed: {res['parsed']}")
                for h in res["hits"]:
                    p = engine.get(h["product_id"])
                    print(f"  {h['score']:.2f}  {p.product_id}  {p.display_name}  ({p.category})")
        elif args.cmd in ("similar", "cheaper"):
            ref = engine.get(args.product_id)
            market = args.market.upper() if args.market else None
            origin = args.origin.upper() if args.origin else None
            if args.cmd == "similar":
                recs = engine.similar(args.product_id, k=args.k, mode=args.mode, market=market,
                                      origin=origin, method=args.method)
            else:
                recs = engine.cheaper(args.product_id, k=args.k, market=market, origin=origin)
            if args.json:
                out = [r.to_dict() for r in recs]
            else:
                print(f"Reference: {ref.display_name} ({ref.category}, ${ref.price_usd:,.2f})"
                      + (f"  market={market}" if market else ""))
                print_recs(recs)
        elif args.cmd == "goal":
            recs = engine.goal(args.goal_id, k=args.k,
                               market=args.market.upper() if args.market else None,
                               skin_type=args.skin, category=args.category)
            if args.json:
                out = [r.to_dict() for r in recs]
            else:
                g = engine.ds.goals[args.goal_id]
                print(f"Goal: {g.name} / {g.name_ko} — {g.description}")
                print_recs(recs)
        elif args.cmd == "goals":
            gs = [g.to_dict() for g in engine.ds.goals.values()]
            if args.json:
                out = gs
            else:
                for g in gs:
                    print(f"  {g['goal_id']:<24} {g['name']} / {g['name_ko']}")
        elif args.cmd == "trending":
            rows = engine.trending(args.market, args.chart)
            if args.json:
                out = rows
            else:
                icon = {"rising": "▲", "falling": "▼", "steady": "–", "new": "NEW"}
                for r in rows:
                    ch = "" if r["change"] is None else f"{r['change']:+d}"
                    print(f"  #{r['rank']:<3} {icon[r['status']]:<3} {ch:>4}  "
                          f"{r['product']['brand']} {r['product']['name']}")
        elif args.cmd == "ask":
            res = engine.ask(args.query, k=args.k,
                             market=args.market.upper() if args.market else None)
            if args.json:
                out = res
            else:
                pq = res["parsed"]
                print(f"understood: intent={pq['intent']} goal={pq['goal_id']} "
                      f"category={pq['category']} origin={pq['origin']} market={pq['market']} "
                      f"product='{pq['product_text']}'")
                if res["reference"]:
                    print(f"reference: {res['reference']['brand']} {res['reference']['name']}")
                print(f"action: {res['action']}")
                for i, r in enumerate(res["results"], 1):
                    p = r["product"]
                    score = r.get("final_score", r.get("match", {}).get("score"))
                    print(f"  {i}. {p['brand']} {p['name']} ({p['product_id']})  score {score}")
        if out is not None:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (NotFound, ValidationError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
