"""
Build the materials for the user study, and (optionally) synthetic answers.

1) Study kit (use this for the real study):
     python research/make_study_kit.py kit --queries P001 P009 P023 --out study/
   For each reference product it pools the top-5 of EVERY model plus a few
   random same-group products, shuffles them (so participants cannot tell
   which model proposed what), and writes:
     study/pool.csv            the candidate list per query (keep private)
     study/answer_sheet.csv    one row per (query, candidate), relevance blank
   Participants copy answer_sheet.csv, fill participant_id and relevance 0-3.
   Concatenate all sheets into one judgments.csv and run evaluate_models.py.

2) Synthetic judgments (pipeline testing ONLY; the numbers mean nothing,
   and they are generated from the model's own features, so they are
   biased toward the model):
     python research/make_study_kit.py synthetic --out data/demo/judgments.csv
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beautybridge import load_engine  # noqa: E402
from beautybridge.similarity import category_similarity, weighted_similarity  # noqa: E402

sys.path.insert(0, str(ROOT / "research"))
from evaluate_models import MODELS  # noqa: E402

RELEVANCE_SCALE = "0 = not a substitute, 1 = weak, 2 = decent, 3 = excellent substitute"


def build_pool(engine, query_id: str, per_model: int, n_random: int, rng: random.Random,
               market: str | None) -> list[str]:
    target = engine.get(query_id)
    pool: set[str] = set()
    for model in MODELS.values():
        recs = engine.similar(query_id, k=per_model, mode=model["mode"], method=model["method"],
                              market=market, only_available=False)
        pool.update(r.product.product_id for r in recs)
    same_group = [p.product_id for p in engine.ds.products.values()
                  if p.product_id != query_id and p.product_id not in pool
                  and p.category_group == target.category_group]
    pool.update(rng.sample(same_group, min(n_random, len(same_group))))
    out = sorted(pool)
    rng.shuffle(out)
    return out


def cmd_kit(args) -> int:
    engine = load_engine(args.data)
    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pool_rows, sheet_rows = [], []
    for q in args.queries:
        ref = engine.get(q)
        for pos, c in enumerate(build_pool(engine, q, args.per_model, args.random, rng, args.market), 1):
            cand = engine.get(c)
            pool_rows.append({"query_id": q, "position": pos, "candidate_product_id": c})
            sheet_rows.append({
                "participant_id": "", "task": args.task, "query_id": q,
                "reference": ref.display_name, "candidate_product_id": c,
                "candidate": cand.display_name, "relevance": "", "judged_at": "",
            })
    with open(out / "pool.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pool_rows[0])); w.writeheader(); w.writerows(pool_rows)
    with open(out / "answer_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sheet_rows[0])); w.writeheader(); w.writerows(sheet_rows)
    (out / "INSTRUCTIONS.txt").write_text(
        f"Task: {args.task}\nRate each candidate against its reference product.\n"
        f"Scale: {RELEVANCE_SCALE}\nFill participant_id on every row. Do not discuss answers.\n",
        encoding="utf-8")
    print(f"wrote {len(sheet_rows)} rows for {len(args.queries)} queries to {out}/")
    return 0


def cmd_synthetic(args) -> int:
    engine = load_engine(args.data)
    rng = random.Random(args.seed)
    queries = args.queries or ["P001", "P009", "P011", "P015", "P023", "P029", "P035", "P043"]
    rows = []
    for q in queries:
        target = engine.get(q)
        pool = build_pool(engine, q, 5, 3, rng, args.market)
        for participant in range(1, args.participants + 1):
            for c in pool:
                cand = engine.get(c)
                sim = weighted_similarity(target, cand).score if category_similarity(target, cand) >= 0.3 else 0.1
                # "similar" task: similarity plus rater noise
                s_true = sim + rng.gauss(0, 0.12)
                # "would_buy" task: similarity, price and local availability matter
                cheap = 0.5
                if target.price_usd and cand.price_usd:
                    cheap = max(0.0, min(1.0, 0.5 + (target.price_usd - cand.price_usd) / (2 * target.price_usd)))
                listing = engine.ds.listings.get((c, args.market)) if args.market else None
                avail = listing.availability_score if listing else 0.0
                b_true = 0.55 * sim + 0.2 * cheap + 0.25 * avail + rng.gauss(0, 0.12)
                for task, v in (("similar", s_true), ("would_buy", b_true)):
                    rel = max(0, min(3, round((v - 0.35) / 0.6 * 3)))
                    rows.append({"participant_id": f"SYN{participant:02d}", "task": task,
                                 "query_id": q, "candidate_product_id": c, "relevance": rel,
                                 "judged_at": "2026-09-30"})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} SYNTHETIC judgments to {out} (pipeline testing only)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data folder or .sqlite (default: demo data)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--market", default="US")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kit")
    k.add_argument("--queries", nargs="+", required=True)
    k.add_argument("--task", default="would_buy", choices=["similar", "would_buy"])
    k.add_argument("--per-model", type=int, default=5)
    k.add_argument("--random", type=int, default=3)
    k.add_argument("--out", default="study")
    s = sub.add_parser("synthetic")
    s.add_argument("--queries", nargs="*")
    s.add_argument("--participants", type=int, default=6)
    s.add_argument("--out", default=str(ROOT / "data" / "demo" / "judgments.csv"))
    args = ap.parse_args(argv)
    return cmd_kit(args) if args.cmd == "kit" else cmd_synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
