"""Skin depth (how light or deep someone's skin is) and colour payoff.

A shade "shows up" on a skin when it differs enough from that skin. The rule depends on
what the product is for:

* contour / bronzer   - must be darker than the skin, but not so much it looks muddy
* highlighter         - a little lighter than the skin; far lighter reads as chalky
* lip / blush / eyes  - enough colour difference (CIE76 delta-E) from the skin; a shade
                        much lighter than the skin with little colour can look ashy

Skin colours are rough CIELAB averages for five depth levels and the shade colours are the
estimated swatches in shades.csv, so every result here is an estimate. Base products have
no shade data yet, so depth matching for foundation is not attempted.
"""
from __future__ import annotations

import math

DEPTHS: list[str] = ["fair", "light", "medium", "tan", "deep"]

# approximate skin colour (L*, a*, b*) per depth level
SKIN_LAB: dict[str, tuple[float, float, float]] = {
    "fair": (76.0, 10.0, 15.0),
    "light": (69.0, 11.0, 17.0),
    "medium": (61.0, 12.0, 19.0),
    "tan": (51.0, 12.0, 19.0),
    "deep": (39.0, 11.0, 16.0),
}

CONTOUR = {"contour", "bronzer"}
HIGHLIGHT = {"highlighter"}
SHEER = {"lip_balm"}            # sheer by design: payoff isn't the point


def hex_to_lab(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def payoff(category: str, hex_colour: str, depth: str) -> tuple[int, str, str] | None:
    """(score 0-100, verdict good/ok/weak, reason) or None when it doesn't apply."""
    if depth not in SKIN_LAB:
        raise ValueError(f"unknown depth '{depth}'")
    if category in SHEER or not hex_colour:
        return None
    sl, sa, sb = SKIN_LAB[depth]
    L, a, b = hex_to_lab(hex_colour)
    if category in CONTOUR:
        d = sl - L                                   # how much darker than the skin
        if d < 6:
            return round(_clamp(d / 18) * 100), "weak", "vanish"
        if d > 30:
            return max(50, round(100 - (d - 30) * 3)), "ok", "muddy"
        return round(_clamp(d / 18) * 100), ("good" if d >= 12 else "ok"), "show"
    if category in HIGHLIGHT:
        d = L - sl                                   # how much lighter than the skin
        score = round(_clamp(1 - abs(d - 15) / 25) * 100)
        if d < 3:
            return score, "weak", "vanish"
        if d > 35:
            return score, "weak", "ashy"
        return score, ("good" if 6 <= d <= 25 else "ok"), "show"
    # colour: lip, blush, eyeshadow
    de = math.sqrt((L - sl) ** 2 + (a - sa) ** 2 + (b - sb) ** 2)
    chroma = math.hypot(a, b)
    score = round(_clamp(de / 40) * 100)
    if L - sl > 18 and chroma < 28:
        return min(score, 35), "weak", "ashy"
    if de < 16:
        return score, "weak", "vanish"
    return score, ("good" if de >= 28 else "ok"), "show"


def for_site(category: str, hex_colour: str) -> dict:
    out = {}
    for d in DEPTHS:
        r = payoff(category, hex_colour, d)
        if r is not None:
            out[d] = [r[0], r[1], r[2]]
    return out


def similar(a: str, b: str) -> bool:
    """Depths count as similar when they are the same or next to each other."""
    return abs(DEPTHS.index(a) - DEPTHS.index(b)) <= 1
