"""
Product-to-product similarity.

Two methods:
  * weighted_similarity  (default): interpretable per-attribute comparison
    with missing-value handling and a point-by-point explanation.
  * cosine_similarity: cosine over dense_vector(); a baseline for the paper.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import codebook as cb
from .config import MIN_CATEGORY_SIMILARITY, MIN_EVIDENCE, PRICE_RATIO_AT_ZERO, SIMILARITY_WEIGHTS
from .features import dense_vector, function_vector
from .product import Product


# ---------------------------------------------------------------------------
# Per-attribute similarity functions. Each returns (similarity 0..1, reason)
# or None when either product lacks the attribute.
# ---------------------------------------------------------------------------
def category_similarity(a: Product, b: Product) -> float:
    if a.category == b.category:
        return 1.0
    related = cb.RELATED_CATEGORIES.get(frozenset({a.category, b.category}))
    if related is not None:
        return related
    if a.category_group == b.category_group:
        return cb.SAME_GROUP_SIMILARITY
    return 0.0


def _category(a: Product, b: Product):
    s = category_similarity(a, b)
    if s == 1.0:
        return s, f"same category ({a.category})"
    return s, f"{a.category} vs {b.category}"


def _function(a: Product, b: Product):
    pairs = [(x, y, f) for x, y, f in zip(function_vector(a), function_vector(b), cb.INTENSITY_FEATURES)
             if x is not None and y is not None]
    if not pairs:
        return None
    # Only compare features that matter to at least one of the two products;
    # two products that both lack shimmer are not "similar" because of it.
    active = [(x, y, f) for x, y, f in pairs if x > 0 or y > 0]
    if not active:
        return 1.0, "neither product has functional claims"
    s = 1.0 - sum(abs(x - y) for x, y, _ in active) / len(active)
    big = [f for x, y, f in sorted(active, key=lambda t: -abs(t[0] - t[1])) if abs(x - y) >= 2 / 3]
    shared = [f for x, y, f in active if x > 0 and y > 0 and f not in big]
    reason = "shares " + ", ".join(shared) if shared else "no shared functions"
    if big:
        reason += "; differs strongly on " + ", ".join(big)
    return s, reason


def _ordinal(scale: dict[str, float], feature: str):
    def fn(a: Product, b: Product):
        va, vb = getattr(a, feature), getattr(b, feature)
        if va is None or vb is None:
            return None
        s = 1.0 - abs(scale[va] - scale[vb])
        return s, (f"both {va}" if va == vb else f"{va} vs {vb}")
    return fn


def _texture(a: Product, b: Product):
    if a.texture is None or b.texture is None:
        return None
    if a.texture == b.texture:
        return 1.0, f"both {a.texture}"
    s = cb.RELATED_TEXTURES.get(frozenset({a.texture, b.texture}), 0.0)
    return s, f"{a.texture} vs {b.texture}"


def _skin_type(a: Product, b: Product):
    if not a.skin_types or not b.skin_types:
        return None
    inter = a.skin_types & b.skin_types
    s = len(inter) / len(a.skin_types | b.skin_types)
    return s, ("suits " + ", ".join(sorted(inter))) if inter else "different skin types"


def _price(a: Product, b: Product):
    pa, pb = a.price_usd, b.price_usd
    if pa is None or pb is None:
        return None
    ratio = abs(math.log(pa / pb))
    s = max(0.0, 1.0 - ratio / math.log(PRICE_RATIO_AT_ZERO))
    return s, f"${pb:.0f} vs ${pa:.0f} (reference)"


COMPARATORS = {
    "category": _category,
    "function": _function,
    "finish": _ordinal(cb.FINISH_SCALE, "finish"),
    "texture": _texture,
    "skin_type": _skin_type,
    "coverage": _ordinal(cb.COVERAGE_SCALE, "coverage"),
    "price": _price,
}


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Component:
    attribute: str
    weight: float        # renormalized weight actually applied
    similarity: float    # 0..1
    reason: str

    @property
    def points(self) -> float:
        return self.weight * self.similarity * 100

    @property
    def max_points(self) -> float:
        return self.weight * 100

    def to_dict(self) -> dict:
        return {
            "attribute": self.attribute,
            "points": round(self.points, 1),
            "max_points": round(self.max_points, 1),
            "similarity": round(self.similarity, 3),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SimilarityResult:
    target_id: str
    candidate_id: str
    score: float                  # 0..1
    evidence: float               # share of configured weight that was evaluable
    components: tuple[Component, ...]
    skipped: tuple[str, ...]      # attributes missing on one side

    @property
    def low_confidence(self) -> bool:
        return self.evidence < MIN_EVIDENCE

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "percent": round(self.score * 100),
            "evidence": round(self.evidence, 3),
            "low_confidence": self.low_confidence,
            "components": [c.to_dict() for c in self.components],
            "skipped_attributes": list(self.skipped),
        }


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------
def weighted_similarity(
    target: Product,
    candidate: Product,
    weights: dict[str, float] | None = None,
) -> SimilarityResult:
    weights = weights or SIMILARITY_WEIGHTS
    unknown = set(weights) - set(COMPARATORS)
    if unknown:
        raise KeyError(f"no comparator for {sorted(unknown)}")
    total = sum(w for w in weights.values() if w > 0)
    evaluated: list[tuple[str, float, float, str]] = []
    skipped: list[str] = []
    for attr, w in weights.items():
        if w <= 0:
            continue
        out = COMPARATORS[attr](target, candidate)
        if out is None:
            skipped.append(attr)
            continue
        evaluated.append((attr, w, *out))
    used = sum(w for _, w, _, _ in evaluated)
    if used == 0:
        return SimilarityResult(target.product_id, candidate.product_id, 0.0, 0.0, (), tuple(skipped))
    components = tuple(
        Component(attr, w / used, s, reason) for attr, w, s, reason in evaluated
    )
    score = sum(c.weight * c.similarity for c in components)
    return SimilarityResult(
        target.product_id, candidate.product_id, score, used / total, components, tuple(skipped),
    )


def cosine_similarity(a: Product, b: Product) -> float:
    va, vb = dense_vector(a), dense_vector(b)
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def is_comparable(target: Product, candidate: Product) -> bool:
    """Category gate: only substitutable categories can be 'similar'."""
    return (
        candidate.product_id != target.product_id
        and category_similarity(target, candidate) >= MIN_CATEGORY_SIMILARITY
    )


def rank_similar(
    target: Product,
    candidates: list[Product],
    k: int | None = 10,
    method: str = "weighted",
    weights: dict[str, float] | None = None,
) -> list[SimilarityResult]:
    pool = [c for c in candidates if is_comparable(target, c)]
    if method == "weighted":
        results = [weighted_similarity(target, c, weights) for c in pool]
    elif method == "cosine":
        results = [
            SimilarityResult(target.product_id, c.product_id, cosine_similarity(target, c), 1.0, (), ())
            for c in pool
        ]
    else:
        raise ValueError(f"unknown method '{method}'")
    # deterministic order: score, then evidence, then id
    results.sort(key=lambda r: (-r.score, -r.evidence, r.candidate_id))
    return results if k is None else results[:k]


__all__ = [
    "Component", "SimilarityResult", "weighted_similarity", "cosine_similarity",
    "category_similarity", "is_comparable", "rank_similar",
]
