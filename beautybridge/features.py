"""Uniform access to product attributes as numbers (0..1) or category labels."""
from __future__ import annotations

from . import codebook as cb
from .product import Product

LEVEL_FEATURES = {*cb.INTENSITY_FEATURES, "finish", "coverage"}
CATEGORICAL_FEATURES = {"shade_family", "undertone", "texture", "category"}


def level(p: Product, feature: str) -> float | None:
    """A product attribute on the shared 0..1 scale, or None if unlabeled."""
    if feature in cb.INTENSITY_FEATURES:
        return p.intensities.get(feature)
    if feature == "finish":
        return None if p.finish is None else cb.FINISH_SCALE[p.finish]
    if feature == "coverage":
        return None if p.coverage is None else cb.COVERAGE_SCALE[p.coverage]
    raise KeyError(f"'{feature}' is not a level feature")


def label(p: Product, feature: str) -> str | None:
    if feature not in CATEGORICAL_FEATURES:
        raise KeyError(f"'{feature}' is not a categorical feature")
    return getattr(p, feature)


def function_vector(p: Product) -> list[float | None]:
    return [p.intensities.get(f) for f in cb.INTENSITY_FEATURES]


def dense_vector(p: Product) -> list[float]:
    """
    Fixed-length numeric encoding for vector methods (cosine similarity,
    pgvector later). One-hot for nominal attributes, 0..1 for ordinal ones;
    missing values encode as 0 (vector methods cannot skip them, which is one
    reason the weighted method is the default).
    """
    vec: list[float] = []
    vec += [1.0 if p.category == c else 0.0 for c in cb.CATEGORIES]
    vec += [1.0 if p.category_group == g else 0.0 for g in cb.CATEGORY_GROUPS]
    vec += [1.0 if p.texture == t else 0.0 for t in cb.TEXTURES]
    vec += [1.0 if p.undertone == u else 0.0 for u in cb.UNDERTONES]
    vec += [1.0 if s in p.skin_types else 0.0 for s in cb.SKIN_TYPES]
    vec.append(level(p, "finish") or 0.0)
    vec.append(level(p, "coverage") or 0.0)
    vec += [v or 0.0 for v in function_vector(p)]
    return vec
