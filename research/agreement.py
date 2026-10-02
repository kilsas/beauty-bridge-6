"""
Inter-rater agreement for product labels.

Two people label the same products independently (same CSV format as
data/templates/products.csv). This script reports, per attribute, how much
they agree beyond chance. Report these numbers in the paper's Methods
section; attributes with kappa < 0.6 need a clearer definition in the
labeling guide before you label the full dataset.

  python research/agreement.py labels_alice.csv labels_bob.csv [--out report.md]

Interpretation (Landis & Koch, 1977): <0.20 slight, 0.21-0.40 fair,
0.41-0.60 moderate, 0.61-0.80 substantial, 0.81-1.00 almost perfect.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beautybridge import codebook as cb  # noqa: E402

NOMINAL = ["category", "texture", "undertone", "shade_family"]
ORDINAL = {
    "finish": list(cb.FINISH_SCALE),
    "coverage": list(cb.COVERAGE_SCALE),
    **{f: ["0", "1", "2", "3"] for f in cb.INTENSITY_FEATURES},
}
MULTI = ["skin_types"]


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb_ = Counter(a), Counter(b)
    pe = sum(ca[c] * cb_[c] for c in set(a) | set(b)) / (n * n)
    if pe == 1:
        return 1.0 if po == 1 else None
    return (po - pe) / (1 - pe)


def weighted_kappa(a: list[str], b: list[str], levels: list[str]) -> float | None:
    """Quadratic-weighted kappa: near-misses (matte vs soft_matte) count partially."""
    n = len(a)
    if n == 0:
        return None
    idx = {lv: i for i, lv in enumerate(levels)}
    k = len(levels)
    if k < 2:
        return None
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[idx[x]][idx[y]] += 1
    ra = [sum(row) for row in obs]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * ra[i] * rb[j] / n for i in range(k) for j in range(k))
    return None if den == 0 else 1 - num / den


def jaccard(x: str, y: str) -> float:
    sx = set(cb.SKIN_TYPES) if x == "all" else {s for s in x.split("|") if s}
    sy = set(cb.SKIN_TYPES) if y == "all" else {s for s in y.split("|") if s}
    if not sx and not sy:
        return 1.0
    return len(sx & sy) / len(sx | sy)


def band(k: float | None) -> str:
    if k is None:
        return "n/a"
    for limit, name in ((0.2, "slight"), (0.4, "fair"), (0.6, "moderate"), (0.8, "substantial")):
        if k <= limit:
            return name
    return "almost perfect"


def read(path: str) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["product_id"].strip(): {k: (v or "").strip().lower() for k, v in r.items()}
                for r in csv.DictReader(f) if r.get("product_id")}


def compare(path_a: str, path_b: str) -> tuple[list[dict], int]:
    A, B = read(path_a), read(path_b)
    shared = sorted(set(A) & set(B))
    rows = []
    for col in NOMINAL + list(ORDINAL) + MULTI:
        pairs = [(A[p].get(col, ""), B[p].get(col, "")) for p in shared]
        pairs = [(x, y) for x, y in pairs if x and y]  # both labeled
        if not pairs:
            rows.append({"attribute": col, "n": 0, "agreement": None, "kappa": None, "kind": ""})
            continue
        a, b = [x for x, _ in pairs], [y for _, y in pairs]
        exact = sum(x == y for x, y in pairs) / len(pairs)
        if col in MULTI:
            rows.append({"attribute": col, "n": len(pairs), "agreement": exact,
                         "kappa": sum(jaccard(x, y) for x, y in pairs) / len(pairs),
                         "kind": "mean Jaccard"})
        elif col in ORDINAL:
            known = [(x, y) for x, y in pairs if x in ORDINAL[col] and y in ORDINAL[col]]
            a, b = [x for x, _ in known], [y for _, y in known]
            rows.append({"attribute": col, "n": len(pairs), "agreement": exact,
                         "kappa": weighted_kappa(a, b, ORDINAL[col]), "kind": "weighted κ"})
        else:
            rows.append({"attribute": col, "n": len(pairs), "agreement": exact,
                         "kappa": cohen_kappa(a, b), "kind": "Cohen κ"})
    return rows, len(shared)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels_a")
    ap.add_argument("labels_b")
    ap.add_argument("--out", help="write a Markdown report here")
    args = ap.parse_args(argv)
    rows, n = compare(args.labels_a, args.labels_b)
    lines = [f"# Labeling agreement ({n} products labeled by both)", "",
             "| attribute | n | exact agreement | statistic | value | interpretation |",
             "|---|---:|---:|---|---:|---|"]
    for r in rows:
        ag = "" if r["agreement"] is None else f"{r['agreement']:.0%}"
        kv = "" if r["kappa"] is None else f"{r['kappa']:.2f}"
        interp = band(r["kappa"]) if r["kind"] != "mean Jaccard" else ""
        flag = " ⚠ revise definition" if r["kappa"] is not None and r["kappa"] < 0.6 and r["kind"] != "mean Jaccard" else ""
        lines.append(f"| {r['attribute']} | {r['n']} | {ag} | {r['kind']} | {kv} | {interp}{flag} |")
    report = "\n".join(lines)
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
