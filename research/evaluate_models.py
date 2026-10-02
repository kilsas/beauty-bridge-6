"""
Compare recommendation models against human judgments (the user study).

Input: a judgments CSV (data/templates/judgments.csv format):
    participant_id, task, query_id, candidate_product_id, relevance (0-3)

For every query, each model ranks the SAME judged candidate pool, so models
are compared on identical items. Relevance is averaged over participants.

Tasks and what they can test:
  similar   : "How similar is this to the reference?"  -> tests similarity only.
              Adding popularity/local signals is NOT expected to help here.
  would_buy : "Would you buy this instead of the reference, where you live?"
              -> the task that can test H3 (local popularity helps).
Use --task to pick; never pool the two.

  python research/evaluate_models.py data/demo/judgments.csv --task would_buy --market US
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from beautybridge import load_engine  # noqa: E402
from metrics import (  # noqa: E402
    average_precision, bootstrap_ci, mean_defined, ndcg_at_k,
    paired_randomization_test, precision_at_k, recall_at_k,
)

# model name -> how to score a candidate pool
MODELS = {
    "A_similarity_only": {"mode": "similarity_only", "method": "weighted"},
    "A0_cosine_baseline": {"mode": "similarity_only", "method": "cosine"},
    "B_similarity_price": {"mode": "similarity_price", "method": "weighted"},
    "C_similarity_price_local": {"mode": "similarity_price_local", "method": "weighted"},
}
BASELINE = "A_similarity_only"


def load_judgments(path: str, task: str) -> dict[str, dict[str, float]]:
    per: dict[tuple[str, str], list[float]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["task"].strip() != task:
                continue
            per[(r["query_id"].strip(), r["candidate_product_id"].strip())].append(float(r["relevance"]))
    queries: dict[str, dict[str, float]] = defaultdict(dict)
    for (q, c), vals in per.items():
        queries[q][c] = mean(vals)
    return dict(queries)


def rank_pool(engine, query_id: str, pool: list[str], model: dict, market: str | None) -> list[str]:
    recs = engine.similar(query_id, k=len(engine.ds.products), mode=model["mode"],
                          method=model["method"], market=market, only_available=False)
    score = {r.product.product_id: r.final_score for r in recs}
    # candidates the model refuses to compare (category gate) go last, in id order
    return sorted(pool, key=lambda pid: (-score.get(pid, -1.0), pid))


def evaluate(engine, judgments: dict[str, dict[str, float]], k: int, market: str | None,
             threshold: float) -> dict:
    per_query: dict[str, dict[str, dict]] = {m: {} for m in MODELS}
    for q, rel in sorted(judgments.items()):
        if q not in engine.ds.products:
            print(f"warning: query {q} is not a product, skipped", file=sys.stderr)
            continue
        pool = [c for c in rel if c in engine.ds.products and c != q]
        for name, model in MODELS.items():
            ranked = rank_pool(engine, q, pool, model, market)
            per_query[name][q] = {
                "precision": precision_at_k(ranked, rel, k, threshold),
                "recall": recall_at_k(ranked, rel, k, threshold),
                "ndcg": ndcg_at_k(ranked, rel, k),
                "ap": average_precision(ranked, rel, threshold),
            }
    summary = {}
    for name, rows in per_query.items():
        ndcgs = [v["ndcg"] for v in rows.values() if v["ndcg"] is not None]
        summary[name] = {
            f"P@{k}": mean_defined([v["precision"] for v in rows.values()]),
            f"R@{k}": mean_defined([v["recall"] for v in rows.values()]),
            f"NDCG@{k}": mean_defined(ndcgs),
            "MAP": mean_defined([v["ap"] for v in rows.values()]),
            "NDCG_95CI": bootstrap_ci(ndcgs) if ndcgs else None,
            "queries": len(rows),
        }
    # paired tests vs baseline on per-query NDCG (queries defined for both)
    tests = {}
    for name in MODELS:
        if name == BASELINE:
            continue
        qs = [q for q in per_query[name]
              if per_query[name][q]["ndcg"] is not None and per_query[BASELINE][q]["ndcg"] is not None]
        a = [per_query[name][q]["ndcg"] for q in qs]
        b = [per_query[BASELINE][q]["ndcg"] for q in qs]
        tests[f"{name} vs {BASELINE}"] = {
            "mean_diff_ndcg": (mean(a) - mean(b)) if qs else None,
            "p_value": paired_randomization_test(a, b) if qs else None,
            "n_queries": len(qs),
        }
    return {"summary": summary, "tests": tests, "per_query": per_query}


def fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, tuple):
        return f"[{v[0]:.2f}, {v[1]:.2f}]"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("judgments")
    ap.add_argument("--task", required=True, choices=["similar", "would_buy"])
    ap.add_argument("--market", help="participants' market (needed for model C's local signals)")
    ap.add_argument("--data", help="data folder or .sqlite (default: demo data)")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--threshold", type=float, default=2.0, help="mean relevance counted as relevant")
    ap.add_argument("--out", help="write full results as JSON here")
    args = ap.parse_args(argv)

    engine = load_engine(args.data)
    judgments = load_judgments(args.judgments, args.task)
    if not judgments:
        print(f"no judgments for task '{args.task}'", file=sys.stderr)
        return 1
    if args.market is None and args.task == "would_buy":
        print("note: no --market given, model C cannot use local signals and equals model B",
              file=sys.stderr)
    res = evaluate(engine, judgments, args.k, args.market.upper() if args.market else None,
                   args.threshold)

    k = args.k
    cols = [f"P@{k}", f"R@{k}", f"NDCG@{k}", "MAP", "NDCG_95CI", "queries"]
    print(f"\nTask: {args.task}   market: {args.market or '-'}   queries: {len(judgments)}\n")
    print(f"| model | {' | '.join(cols)} |")
    print("|---|" + "---:|" * len(cols))
    for name, s in res["summary"].items():
        print(f"| {name} | " + " | ".join(fmt(s[c]) for c in cols) + " |")
    print("\nPaired randomization test on per-query NDCG:")
    for name, t in res["tests"].items():
        print(f"  {name}: Δ={fmt(t['mean_diff_ndcg'])}  p={fmt(t['p_value'])}  (n={t['n_queries']})")
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
