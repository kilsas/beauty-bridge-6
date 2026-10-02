"""Product record and CSV-row parsing/validation."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import codebook as cb
from .config import FX_TO_USD


class ValidationError(ValueError):
    """Raised when a product row breaks the codebook."""


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str
    name: str
    category: str
    name_ko: str = ""
    aliases: tuple[str, ...] = ()
    shade_family: str | None = None
    finish: str | None = None
    coverage: str | None = None
    texture: str | None = None
    undertone: str | None = None
    # normalized 0..1, None = not labeled
    intensities: dict[str, float | None] = field(default_factory=dict)
    skin_types: frozenset[str] = frozenset()
    price: float | None = None
    currency: str | None = None
    country_origin: str = ""
    url: str = ""
    source: str = ""
    labeled_by: str = ""
    notes: str = ""

    @property
    def category_group(self) -> str:
        return cb.CATEGORY_TO_GROUP[self.category]

    @property
    def price_usd(self) -> float | None:
        if self.price is None or self.currency is None:
            return None
        return self.price * FX_TO_USD[self.currency]

    @property
    def display_name(self) -> str:
        return f"{self.brand} {self.name}"

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "brand": self.brand,
            "name": self.name,
            "name_ko": self.name_ko,
            "category": self.category,
            "category_group": self.category_group,
            "shade_family": self.shade_family,
            "finish": self.finish,
            "coverage": self.coverage,
            "texture": self.texture,
            "undertone": self.undertone,
            "intensities": {
                k: (None if v is None else round(v * cb.INTENSITY_MAX))
                for k, v in self.intensities.items()
            },
            "skin_types": sorted(self.skin_types),
            "price": self.price,
            "currency": self.currency,
            "price_usd": None if self.price_usd is None else round(self.price_usd, 2),
            "country_origin": self.country_origin,
            "url": self.url,
            "source": self.source,
        }


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _enum(row: dict, col: str, allowed, pid: str) -> str | None:
    v = _clean(row.get(col)).lower()
    if not v:
        return None
    if v not in allowed:
        raise ValidationError(
            f"{pid}: {col}='{v}' is not one of {sorted(allowed)}"
        )
    return v


def parse_product(row: dict) -> Product:
    """Turn one CSV row (dict of strings) into a validated Product."""
    pid = _clean(row.get("product_id"))
    if not pid:
        raise ValidationError("row without product_id")
    for required in ("brand", "name", "category"):
        if not _clean(row.get(required)):
            raise ValidationError(f"{pid}: '{required}' is required")

    category = _enum(row, "category", cb.CATEGORIES, pid)

    intensities: dict[str, float | None] = {}
    for feat in cb.INTENSITY_FEATURES:
        raw = _clean(row.get(feat))
        if raw == "":
            intensities[feat] = None
            continue
        try:
            level = int(float(raw))
        except ValueError:
            raise ValidationError(f"{pid}: {feat}='{raw}' must be 0-3") from None
        if not 0 <= level <= cb.INTENSITY_MAX or float(raw) != level:
            raise ValidationError(f"{pid}: {feat}='{raw}' must be an integer 0-3")
        intensities[feat] = level / cb.INTENSITY_MAX

    skin_raw = _clean(row.get("skin_types")).lower()
    if skin_raw == "all":
        skin = frozenset(cb.SKIN_TYPES)
    elif skin_raw:
        parts = [s.strip() for s in skin_raw.split(cb.MULTI_VALUE_SEPARATOR) if s.strip()]
        bad = [s for s in parts if s not in cb.SKIN_TYPES]
        if bad:
            raise ValidationError(f"{pid}: unknown skin_types {bad}")
        skin = frozenset(parts)
    else:
        skin = frozenset()

    price_raw = _clean(row.get("price"))
    currency = _clean(row.get("currency")).upper() or None
    price = None
    if price_raw:
        try:
            price = float(price_raw.replace(",", ""))
        except ValueError:
            raise ValidationError(f"{pid}: price='{price_raw}' is not a number") from None
        if price <= 0:
            raise ValidationError(f"{pid}: price must be positive")
        if currency not in FX_TO_USD:
            raise ValidationError(
                f"{pid}: currency '{currency}' has no FX rate in config.FX_TO_USD"
            )

    aliases = tuple(
        a.strip() for a in _clean(row.get("aliases")).split(cb.MULTI_VALUE_SEPARATOR)
        if a.strip()
    )

    return Product(
        product_id=pid,
        brand=_clean(row["brand"]),
        name=_clean(row["name"]),
        name_ko=_clean(row.get("name_ko")),
        aliases=aliases,
        category=category,
        shade_family=_enum(row, "shade_family", cb.SHADE_FAMILIES, pid),
        finish=_enum(row, "finish", cb.FINISH_SCALE, pid),
        coverage=_enum(row, "coverage", cb.COVERAGE_SCALE, pid),
        texture=_enum(row, "texture", cb.TEXTURES, pid),
        undertone=_enum(row, "undertone", cb.UNDERTONES, pid),
        intensities=intensities,
        skin_types=skin,
        price=price,
        currency=currency if price is not None else None,
        country_origin=_clean(row.get("country_origin")).upper(),
        url=_clean(row.get("url")),
        source=_clean(row.get("source")),
        labeled_by=_clean(row.get("labeled_by")),
        notes=_clean(row.get("notes")),
    )
