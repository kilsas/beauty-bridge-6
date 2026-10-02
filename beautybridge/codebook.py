"""
Codebook: the single source of truth for how a product is described.

Every labeler, every CSV, every algorithm reads its vocabulary from here.
If you change a value here, update docs/labeling_guide.md too.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORY_GROUPS: dict[str, list[str]] = {
    "face_base": [
        "foundation", "cushion", "concealer", "primer",
        "loose_powder", "pressed_powder", "setting_spray",
    ],
    "cheek": ["blush", "highlighter", "contour", "bronzer"],
    "eye": ["eyeshadow", "eyeliner", "brow", "mascara"],
    "lip": ["lip_tint", "lipstick", "lip_gloss", "lip_balm", "lip_liner", "lip_plumper"],
    "skincare": ["cleanser", "toner", "serum", "moisturizer", "sunscreen"],
}
CATEGORIES: list[str] = [c for group in CATEGORY_GROUPS.values() for c in group]
CATEGORY_TO_GROUP: dict[str, str] = {
    c: g for g, cats in CATEGORY_GROUPS.items() for c in cats
}

# Hand-specified substitutability between *different* categories (symmetric).
# Same category = 1.0. Same group, unlisted pair = SAME_GROUP_SIMILARITY.
# Different group, unlisted pair = 0.0.
RELATED_CATEGORIES: dict[frozenset, float] = {
    frozenset({"loose_powder", "pressed_powder"}): 0.8,
    frozenset({"foundation", "cushion"}): 0.8,
    frozenset({"lip_tint", "lipstick"}): 0.6,
    frozenset({"lip_tint", "lip_gloss"}): 0.6,
    frozenset({"lip_gloss", "lip_balm"}): 0.5,
    frozenset({"highlighter", "eyeshadow"}): 0.4,   # shimmer shadows double as highlight
    frozenset({"primer", "moisturizer"}): 0.3,
    frozenset({"contour", "bronzer"}): 0.6,
    frozenset({"lip_plumper", "lip_gloss"}): 0.6,
    frozenset({"lip_liner", "lipstick"}): 0.4,
    frozenset({"eyeliner", "brow"}): 0.3,
}
SAME_GROUP_SIMILARITY = 0.3

# ---------------------------------------------------------------------------
# Ordinal attributes (mapped to 0..1 so distances are comparable)
# ---------------------------------------------------------------------------
FINISH_SCALE: dict[str, float] = {
    "matte": 0.0,
    "soft_matte": 0.25,
    "satin": 0.5,        # a.k.a. natural
    "dewy": 0.75,
    "glossy": 1.0,
}
COVERAGE_SCALE: dict[str, float] = {
    "sheer": 0.0,
    "light": 1 / 3,
    "medium": 2 / 3,
    "full": 1.0,
}

# ---------------------------------------------------------------------------
# Nominal attributes
# ---------------------------------------------------------------------------
TEXTURES: list[str] = [
    "loose_powder", "pressed_powder", "liquid", "cream", "gel",
    "balm", "stick", "cushion", "water", "oil", "mousse", "pencil",
]
RELATED_TEXTURES: dict[frozenset, float] = {
    frozenset({"loose_powder", "pressed_powder"}): 0.7,
    frozenset({"liquid", "cushion"}): 0.7,
    frozenset({"cream", "balm"}): 0.6,
    frozenset({"gel", "water"}): 0.6,
    frozenset({"liquid", "water"}): 0.5,
    frozenset({"cream", "mousse"}): 0.6,
    frozenset({"liquid", "gel"}): 0.5,
    frozenset({"cream", "stick"}): 0.4,
    frozenset({"pencil", "stick"}): 0.7,
}

UNDERTONES: list[str] = ["cool", "neutral", "warm"]

SHADE_FAMILIES: list[str] = [
    "nude", "rose", "pink", "coral", "red", "berry", "brown",
    "champagne", "gold", "clear",
]

SKIN_TYPES: list[str] = ["oily", "dry", "combination", "normal", "sensitive"]

# ---------------------------------------------------------------------------
# Intensity attributes: labeled 0-3, stored normalized to 0..1
#   0 = none / not a claim, 1 = slight, 2 = clear, 3 = primary purpose
# ---------------------------------------------------------------------------
INTENSITY_FEATURES: list[str] = [
    "oil_control", "hydration", "blurring", "shimmer",
    "brightening", "glow", "longevity",
    "volume",      # lash volume, lip plumping
    "precision",   # fine, controllable tip (liners, brow, pencils)
]
INTENSITY_MAX = 3

# Columns every product CSV must have, in order.
PRODUCT_COLUMNS: list[str] = [
    "product_id", "brand", "name", "name_ko", "aliases",
    "category", "shade_family", "finish", "coverage", "texture", "undertone",
    *INTENSITY_FEATURES,
    "skin_types", "price", "currency", "country_origin",
    "url", "source", "labeled_by", "notes",
]

MULTI_VALUE_SEPARATOR = "|"
