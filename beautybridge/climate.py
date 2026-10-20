"""Climate fit: how well a product is likely to hold up where the user lives.

Two things live here:

1. ``hold``: an estimated 0-3 "sweat / oil / humidity resistance" tag for makeup and
   sunscreen. It is NOT a new hand label. It is derived by a fixed rule from labels
   the product already has (longevity, oil control, finish, texture) plus explicit
   claims in the product name ("waterproof", "longwear", "24H"...). The site shows it
   as an estimate.

2. ``fit(product, climate)``: a 0..1 score for one of four climates, built from a few
   named components so the site can say *why* (e.g. "light texture", "rich texture").

These scores are kept separate from the 13 function features used for similarity, so
adding climate does not change any similarity number.
"""
from __future__ import annotations

import re

from . import codebook as cb
from .product import Product

CLIMATES: list[str] = cb.CLIMATES

# makeup groups + sunscreen get a hold tag; other skincare doesn't (it isn't worn on top)
HOLD_GROUPS = {"face_base", "cheek", "eye", "lip"}
HOLD_EXTRA = {"sunscreen"}
NO_HOLD = {"lip_balm"}

CLAIM = re.compile(
    r"water\s*-?\s*proof|water\s*-?\s*resist|sweat|smudge|long\s*-?\s*wear|24\s*h|all\s*day|"
    r"워터프루프|롱웨어|땀|번짐",
    re.I,
)

LIGHT_TEX = {"gel", "water", "liquid", "loose_powder", "pressed_powder", "mousse", "pad", "sheet"}
RICH_TEX = {"cream", "balm", "oil", "cushion"}
MATTE = {"matte", "soft_matte"}
DEWY = {"dewy", "glossy"}

# weights of each component per climate (renormalised over the components a product has)
WEIGHTS: dict[str, dict[str, float]] = {
    "hot_humid": {"hold": 0.35, "oil": 0.20, "matte": 0.20, "light": 0.25},
    "hot_dry":   {"hold": 0.35, "hydr": 0.30, "light": 0.15, "dewy": 0.20},
    "cold_dry":  {"hydr": 0.40, "rich": 0.30, "dewy": 0.30},
    # temperate: no strong constraint, so no score
}
GOOD, OK = 0.62, 0.40


def has_hold(p: Product) -> bool:
    return (p.category_group in HOLD_GROUPS or p.category in HOLD_EXTRA) and p.category not in NO_HOLD


def claims(p: Product) -> bool:
    return bool(CLAIM.search(f"{p.name} {p.name_ko}"))


def hold(p: Product) -> int | None:
    """Estimated sweat/oil/humidity resistance, 0-3 (None when it doesn't apply)."""
    if not has_hold(p):
        return None
    lon = p.intensities.get("longevity")
    if lon is None:
        return None
    score = round(lon * cb.INTENSITY_MAX)
    if (p.intensities.get("oil_control") or 0) * cb.INTENSITY_MAX >= 2:
        score += 1
    if claims(p):
        score += 1
    if p.category_group in {"face_base", "cheek"}:
        if p.finish in DEWY:
            score -= 1
        if p.texture in {"cream", "balm", "oil"}:
            score -= 1
    return max(0, min(3, score))


def _components(p: Product) -> dict[str, float]:
    c: dict[str, float] = {}
    h = hold(p)
    if h is not None:
        c["hold"] = h / 3
    skin_contact = p.category_group in {"face_base", "skincare"}      # oil control matters on skin
    oil = p.intensities.get("oil_control")
    if oil is not None and skin_contact:
        c["oil"] = oil
    hyd = p.intensities.get("hydration")
    if hyd is not None and (skin_contact or p.category_group == "lip"):
        c["hydr"] = hyd
    if p.finish:
        c["matte"] = 1.0 if p.finish in MATTE else 0.5 if p.finish == "satin" else 0.0
        c["dewy"] = 1.0 if p.finish in DEWY else 0.6 if p.finish == "satin" else 0.0
    if p.texture:
        c["light"] = 1.0 if p.texture in LIGHT_TEX else 0.0 if p.texture in RICH_TEX else 0.5
        c["rich"] = 1.0 if p.texture in RICH_TEX else 0.0 if p.texture in {"loose_powder", "pressed_powder"} else 0.4
    return c


def fit(p: Product, climate: str) -> tuple[float, list[str]] | None:
    """(score 0..1, reasons) for a climate, or None when the climate doesn't constrain it.

    reasons are component names that pushed the score up (value >= 0.6) or down
    (value <= 0.2), prefixed '+' or '-', strongest first."""
    if climate not in CLIMATES:
        raise ValueError(f"unknown climate '{climate}'")
    w = WEIGHTS.get(climate)
    if not w or (climate == "cold_dry" and p.category_group == "eye"):   # eye makeup isn't dried out by cold air
        return None
    comp = _components(p)
    used = {k: v for k, v in w.items() if k in comp}
    total = sum(used.values())
    if total < 0.5:          # too little information to say anything
        return None
    score = sum(comp[k] * v for k, v in used.items()) / total
    reasons = sorted(((("+" if comp[k] >= 0.6 else "-") + k, v) for k, v in used.items()
                      if comp[k] >= 0.6 or comp[k] <= 0.2), key=lambda x: -x[1])
    return round(score, 3), [r for r, _ in reasons]


def verdict(score: float) -> str:
    return "good" if score >= GOOD else "ok" if score >= OK else "weak"


def for_site(p: Product) -> dict:
    """Compact per-product climate data for the static site."""
    out: dict = {"hold": hold(p), "claim": claims(p)}
    fits = {}
    for c in CLIMATES:
        r = fit(p, c)
        if r is not None:
            fits[c] = [round(r[0] * 100), r[1]]
    out["cf"] = fits
    return out
