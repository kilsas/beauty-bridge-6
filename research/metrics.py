"""
Ranking metrics for the user study. Pure Python, no dependencies.

Relevance is graded 0-3 (averaged across participants). For binary metrics
an item counts as relevant when its relevance >= threshold (default 2).
"""
from __future__ import annotations

import math
import random
from statistics import mean


def precision_at_k(ranked: list[str], relevance: dict[str, float], k: int, threshold: float = 2) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for i in top if relevance.get(i, 0) >= threshold) / k


def recall_at_k(ranked: list[str], relevance: dict[str, float], k: int, threshold: float = 2) -> float | None:
    relevant = {i for i, r in relevance.items() if r >= threshold}
    if not relevant:
        return None  # undefined: nothing relevant for this query
    return len(relevant & set(ranked[:k])) / len(relevant)


def dcg(gains: list[float]) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: list[str], relevance: dict[str, float], k: int) -> float | None:
    ideal = dcg(sorted(relevance.values(), reverse=True)[:k])
    if ideal == 0:
        return None
    return dcg([relevance.get(i, 0) for i in ranked[:k]]) / ideal


def average_precision(ranked: list[str], relevance: dict[str, float], threshold: float = 2) -> float | None:
    relevant = {i for i, r in relevance.items() if r >= threshold}
    if not relevant:
        return None
    hits, total = 0, 0.0
    for pos, item in enumerate(ranked, start=1):
        if item in relevant:
            hits += 1
            total += hits / pos
    return total / len(relevant)


def mean_defined(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def paired_randomization_test(a: list[float], b: list[float], iterations: int = 10_000,
                              seed: int = 0) -> float:
    """
    Two-sided p-value for H0: models A and B perform the same, using per-query
    scores (sign-flip permutation). Appropriate for small user studies where
    a t-test's normality assumption is doubtful.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b)]
    if not diffs:
        return 1.0
    observed = abs(mean(diffs))
    rng = random.Random(seed)
    extreme = 0
    for _ in range(iterations):
        s = mean(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(s) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (iterations + 1)


def bootstrap_ci(values: list[float], iterations: int = 5_000, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean(rng.choices(values, k=n)) for _ in range(iterations))
    lo = means[int(alpha / 2 * iterations)]
    hi = means[int((1 - alpha / 2) * iterations) - 1]
    return lo, hi
