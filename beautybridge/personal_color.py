"""
Personal colour (퍼스널 컬러) fit for individual shades.

Personal colour is a property of a *shade*, not a product: one tint line has
spring-warm and summer-cool shades. Each shade in data/real/shades.csv is
described on three axes used in personal-colour theory (hue temperature,
value, chroma). Each of the eight Korean types has a target on the same axes,
and a shade's fit is 1 - weighted distance:

    fit = 1 - (0.5 * |temp - T| + 0.25 * |value - V| + 0.25 * |chroma - C|)

Temperature weighs most because warm/cool is the first split in the system;
value and chroma separate the sub-types (light/bright/mute/deep). Clear
(transparent) shades fit every type.

When a source (brand, magazine, review) states a season for a shade, that
statement is kept separately and shown with its link; it adds a small bonus
(STATED_BONUS) to the types it names, but never replaces the computed score.
Online self-diagnosis is unreliable, so the site asks people to choose the
type they were diagnosed with rather than diagnosing them.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

TEMP = {"warm": 1.0, "neutral": 0.5, "cool": 0.0}
VALUE = {"light": 1.0, "medium": 0.5, "deep": 0.0}
CHROMA = {"vivid": 1.0, "soft": 0.5, "muted": 0.0}

# type: (temperature, value, chroma) targets on 0..1
TYPES: dict[str, tuple[float, float, float]] = {
    "spring_light": (1.0, 1.0, 0.75),
    "spring_bright": (1.0, 0.6, 1.0),
    "summer_light": (0.0, 1.0, 0.5),
    "summer_mute": (0.0, 0.5, 0.0),
    "autumn_mute": (1.0, 0.5, 0.0),
    "autumn_deep": (1.0, 0.0, 0.5),
    "winter_bright": (0.0, 0.5, 1.0),
    "winter_deep": (0.0, 0.0, 0.75),
}
WEIGHTS = (0.5, 0.25, 0.25)
GOOD, OK = 0.85, 0.75          # "suits you" / "works" thresholds shown on the site
STATED_BONUS = 0.05

# words a source may use, mapped to the types they cover
STATED_TAGS: dict[str, set[str]] = {
    **{t: {t} for t in TYPES},
    "spring": {"spring_light", "spring_bright"}, "summer": {"summer_light", "summer_mute"},
    "autumn": {"autumn_mute", "autumn_deep"}, "winter": {"winter_bright", "winter_deep"},
    "warm": {"spring_light", "spring_bright", "autumn_mute", "autumn_deep"},
    "cool": {"summer_light", "summer_mute", "winter_bright", "winter_deep"},
}


class ShadeError(ValueError):
    pass


@dataclass(frozen=True)
class Shade:
    product_id: str
    name: str
    name_local: str
    temp: str            # warm | neutral | cool | clear
    value: str           # light | medium | deep
    chroma: str          # vivid | soft | muted
    hex: str             # approximate swatch for display only
    stated: tuple[str, ...] = ()
    stated_text: str = ""
    stated_url: str = ""
    shade_url: str = ""
    fit: dict[str, float] = field(default_factory=dict, compare=False)

    @property
    def stated_types(self) -> set[str]:
        out: set[str] = set()
        for tag in self.stated:
            out |= STATED_TAGS[tag]
        return out


def fit_scores(temp: str, value: str, chroma: str, stated: set[str] | None = None) -> dict[str, float]:
    """0..1 fit of one shade to each of the eight types."""
    if temp == "clear":
        return {t: 1.0 for t in TYPES}
    x = (TEMP[temp], VALUE[value], CHROMA[chroma])
    out = {}
    for t, target in TYPES.items():
        d = sum(w * abs(a - b) for w, a, b in zip(WEIGHTS, x, target))
        s = 1.0 - d + (STATED_BONUS if stated and t in stated else 0.0)
        out[t] = round(min(1.0, s), 3)
    return out


def load_shades(path: Path, products: set[str]) -> dict[str, list[Shade]]:
    """Read and validate shades.csv; returns product_id -> shades with fit scores."""
    if not Path(path).exists():
        return {}
    out: dict[str, list[Shade]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            pid = (row.get("product_id") or "").strip()
            if pid not in products:
                raise ShadeError(f"shades.csv line {i}: unknown product '{pid}'")
            temp, value, chroma = (row.get(k, "").strip() for k in ("temp", "value", "chroma"))
            if temp not in TEMP and temp != "clear":
                raise ShadeError(f"shades.csv line {i}: temp must be warm, neutral, cool or clear")
            if value not in VALUE or chroma not in CHROMA:
                raise ShadeError(f"shades.csv line {i}: value/chroma out of vocabulary")
            hx = row.get("hex", "").strip()
            if not (len(hx) == 7 and hx.startswith("#")):
                raise ShadeError(f"shades.csv line {i}: hex must look like #a1b2c3")
            tags = tuple(t for t in (row.get("stated") or "").split() if t)
            for t in tags:
                if t not in STATED_TAGS:
                    raise ShadeError(f"shades.csv line {i}: unknown stated tag '{t}'")
            if (tags or row.get("stated_text", "").strip()) and not row.get("stated_url", "").startswith("https://"):
                raise ShadeError(f"shades.csv line {i}: a stated personal colour needs a source URL")
            sh = Shade(pid, row["name"].strip(), (row.get("name_local") or "").strip(), temp, value, chroma, hx,
                       tags, (row.get("stated_text") or "").strip(), (row.get("stated_url") or "").strip(),
                       (row.get("shade_url") or "").strip())
            object.__setattr__(sh, "fit", fit_scores(temp, value, chroma, sh.stated_types))
            out.setdefault(pid, []).append(sh)
    return out


def best_shades(shades: dict[str, list[Shade]], pc_type: str, k: int = 20) -> list[tuple[Shade, float]]:
    """Shades ranked for one personal-colour type (clear shades last, they fit everyone)."""
    if pc_type not in TYPES:
        raise ShadeError(f"unknown personal colour type '{pc_type}'")
    rows = [(s, s.fit[pc_type]) for ss in shades.values() for s in ss if s.fit[pc_type] >= OK]
    rows.sort(key=lambda x: (x[0].temp == "clear", -x[1], -len(x[0].stated_types & {pc_type}), x[0].product_id, x[0].name))
    return rows[:k]
