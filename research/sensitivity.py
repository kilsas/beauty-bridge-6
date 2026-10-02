"""
Weight sensitivity analysis: how much do the top-k similar products change
when one similarity weight is raised or lowered?

For each attribute weight, multiply it by (1 - delta) and (1 + delta), keep
the others, and measure against the default ranking:
  * top-k overlap (share of the default top-k still in the new top-k)
  * Kendall's tau between the two full rankings

High overlap/tau = rankings are robust to that weight; low = your results
depend on a choice you made, so justify it in the paper.

  python research/sensitivity.py [--delta 0.5] [-k 5] [--data folder]
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beautybridge import load_engine  # noqa: E402
from beautybridge.config import SIMILARITY_WEIGHTS  # noqa: E402
from beautybridge.similarity import rank_similar  # noqa: E402


def kendall_tau(a: list[str], b: list[str]) -> float:
    items = [x for x in a if x in set(b)]
    if len(items) < 2:
        return 1.0
    pos_b = {x: i for i, x in enumerate(b)}
    concordant = discordant = 0
    for x, y in combinations(items, 2):
        if pos_b[x] < pos_b[y]:
            concordant += 1
        else:
            discordant += 1
    return (concordant - discordant) / (concordant + discordant)


def ranking(engine, target, weights):
    pool = list(engine.ds.products.values())
    return [r.candidate_id for r in rank_similar(target, pool, k=None, weights=weights)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data")
    ap.add_argument("--delta", type=float, default=0.5)
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv)

    engine = load_engine(args.data)
    targets = list(engine.ds.products.values())
    base = {t.product_id: ranking(engine, t, SIMILARITY_WEIGHTS) for t in targets}

    print(f"Sensitivity of similarity rankings ({len(targets)} reference products, "
          f"weight × {1 - args.delta:.1f} / × {1 + args.delta:.1f})\n")
    print(f"| attribute | default weight | top-{args.k} overlap (−) | τ (−) | top-{args.k} overlap (+) | τ (+) |")
    print("|---|---:|---:|---:|---:|---:|")
    for attr, w in SIMILARITY_WEIGHTS.items():
        cells = []
        for factor in (1 - args.delta, 1 + args.delta):
            weights = {**SIMILARITY_WEIGHTS, attr: w * factor}
            overlaps, taus = [], []
            for t in targets:
                new = ranking(engine, t, weights)
                old = base[t.product_id]
                if not old:
                    continue
                k = min(args.k, len(old))
                overlaps.append(len(set(old[:k]) & set(new[:k])) / k)
                taus.append(kendall_tau(old, new))
            cells += [f"{mean(overlaps):.2f}", f"{mean(taus):.2f}"]
        print(f"| {attr} | {w:.2f} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
