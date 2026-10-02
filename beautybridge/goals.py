"""Beauty goal definitions and goal-fit scoring."""
from __future__ import annotations

from dataclasses import dataclass

from . import codebook as cb
from .features import CATEGORICAL_FEATURES, LEVEL_FEATURES, label, level
from .product import Product, ValidationError


@dataclass(frozen=True)
class Criterion:
    type: str                      # "level" | "one_of"
    feature: str
    weight: float
    target: float | None = None
    values: frozenset[str] | None = None

    def describe(self) -> str:
        if self.type == "one_of":
            return f"{self.feature} in {sorted(self.values)}"
        return f"{self.feature} ≈ {describe_level(self.feature, self.target)}"


@dataclass(frozen=True)
class BeautyGoal:
    goal_id: str
    name: str
    name_ko: str
    description: str
    eligible_categories: frozenset[str]
    criteria: tuple[Criterion, ...]
    aliases: tuple[str, ...] = ()
    area: str = ""

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id, "area": self.area, "name": self.name, "name_ko": self.name_ko,
            "description": self.description,
            "eligible_categories": sorted(self.eligible_categories),
            "criteria": [
                {"feature": c.feature, "weight": c.weight, "rule": c.describe()}
                for c in self.criteria
            ],
        }


@dataclass(frozen=True)
class GoalComponent:
    feature: str
    rule: str
    weight: float           # renormalized weight actually used
    fit: float              # 0..1
    product_value: str

    @property
    def points(self) -> float:
        return self.weight * self.fit * 100

    @property
    def max_points(self) -> float:
        return self.weight * 100


@dataclass(frozen=True)
class GoalResult:
    product_id: str
    goal_id: str
    score: float                        # 0..1
    evidence: float                     # share of criterion weight that could be evaluated
    components: tuple[GoalComponent, ...]


_INTENSITY_WORDS = ["none", "slight", "clear", "primary"]


def describe_level(feature: str, value: float | None) -> str:
    if value is None:
        return "unlabeled"
    if feature == "finish":
        nearest = min(cb.FINISH_SCALE, key=lambda k: abs(cb.FINISH_SCALE[k] - value))
        return nearest
    if feature == "coverage":
        nearest = min(cb.COVERAGE_SCALE, key=lambda k: abs(cb.COVERAGE_SCALE[k] - value))
        return nearest
    return _INTENSITY_WORDS[round(value * cb.INTENSITY_MAX)]


def parse_goals(data: dict) -> dict[str, BeautyGoal]:
    goals: dict[str, BeautyGoal] = {}
    for g in data["goals"]:
        gid = g["goal_id"]
        bad = [c for c in g["eligible_categories"] if c not in cb.CATEGORIES]
        if bad:
            raise ValidationError(f"goal {gid}: unknown categories {bad}")
        criteria = []
        for c in g["criteria"]:
            if c["type"] == "level":
                if c["feature"] not in LEVEL_FEATURES:
                    raise ValidationError(f"goal {gid}: '{c['feature']}' is not a level feature")
                if not 0 <= c["target"] <= 1:
                    raise ValidationError(f"goal {gid}: target must be 0..1")
                target = float(c["target"])
                # snap 0.33 / 0.67 written in JSON to the exact label positions
                for exact in (1 / 3, 2 / 3):
                    if abs(target - exact) < 0.01:
                        target = exact
                criteria.append(Criterion("level", c["feature"], float(c["weight"]),
                                          target=target))
            elif c["type"] == "one_of":
                if c["feature"] not in CATEGORICAL_FEATURES:
                    raise ValidationError(f"goal {gid}: '{c['feature']}' is not categorical")
                criteria.append(Criterion("one_of", c["feature"], float(c["weight"]),
                                          values=frozenset(c["values"])))
            else:
                raise ValidationError(f"goal {gid}: unknown criterion type {c['type']}")
        if not criteria:
            raise ValidationError(f"goal {gid}: no criteria")
        goals[gid] = BeautyGoal(
            goal_id=gid, name=g["name"], name_ko=g.get("name_ko", ""),
            description=g.get("description", ""),
            eligible_categories=frozenset(g["eligible_categories"]),
            criteria=tuple(criteria),
            aliases=tuple(g.get("aliases", [])),
            area=g.get("area", ""),
        )
    return goals


def score_goal(p: Product, goal: BeautyGoal) -> GoalResult | None:
    """
    Goal fit = weighted closeness of the product to the goal's target profile.
    Returns None if the product's category is not eligible for the goal.
    Criteria the product has no label for are skipped and the remaining
    weights renormalized; `evidence` records how much weight was usable.
    """
    if p.category not in goal.eligible_categories:
        return None
    total_weight = sum(c.weight for c in goal.criteria)
    usable: list[tuple[Criterion, float, str]] = []
    for c in goal.criteria:
        if c.type == "level":
            v = level(p, c.feature)
            if v is None:
                continue
            usable.append((c, 1.0 - abs(v - c.target), describe_level(c.feature, v)))
        else:
            v = label(p, c.feature)
            if v is None:
                continue
            usable.append((c, 1.0 if v in c.values else 0.0, v))
    used_weight = sum(c.weight for c, _, _ in usable)
    if used_weight == 0:
        return GoalResult(p.product_id, goal.goal_id, 0.0, 0.0, ())
    components = tuple(
        GoalComponent(
            feature=c.feature, rule=c.describe(), weight=c.weight / used_weight,
            fit=fit, product_value=value,
        )
        for c, fit, value in usable
    )
    score = sum(comp.weight * comp.fit for comp in components)
    return GoalResult(p.product_id, goal.goal_id, score, used_weight / total_weight, components)
