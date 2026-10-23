"""Did it hold at noon? People log, day by day, whether a product survived until midday
in their climate. This checks the *estimated* sweat/oil resistance tag (climate.hold)
against what actually happened.

One log per person per product per day. A product's user score in a climate is
(held + 0.5 * partly) / n. Once a product has MIN_LOGS logs in a climate, the site ranks
it by the user score instead of the label estimate.
"""
from __future__ import annotations

import re
from datetime import date

from .codebook import CLIMATES

RESULTS = ("held", "partly", "broke")
MIN_LOGS = 5           # logs needed before the user score replaces the label estimate
BROKE_BELOW = 0.5      # user score under this = "broke down before lunch"


class HoldLogError(ValueError):
    pass


def make_log(data: dict, products: set[str]) -> dict:
    lid = str(data.get("logger_id", "")).strip()
    if not lid or len(lid) > 128:
        raise HoldLogError("logger_id is required")
    pid = str(data.get("product_id", "")).strip()
    if pid not in products:
        raise HoldLogError(f"unknown product '{pid}'")
    climate = str(data.get("climate", "")).strip()
    if climate not in CLIMATES:
        raise HoldLogError(f"climate must be one of {', '.join(CLIMATES)}")
    result = str(data.get("result", "")).strip()
    if result not in RESULTS:
        raise HoldLogError("result must be held, partly or broke")
    day = str(data.get("day") or date.today().isoformat())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise HoldLogError("day must be YYYY-MM-DD")
    date.fromisoformat(day)
    return {"logger_id": lid, "product_id": pid, "climate": climate, "result": result, "day": day}


def stats(logs: list[dict]) -> list[dict]:
    """Counts per (product, climate) with first/last day. No logger ids."""
    agg: dict[tuple, dict] = {}
    for g in logs:
        key = (g["product_id"], g["climate"])
        row = agg.setdefault(key, {"product_id": key[0], "climate": key[1], "n": 0,
                                   "held": 0, "partly": 0, "broke": 0, "first": g["day"], "last": g["day"]})
        row["n"] += 1
        row[g["result"]] += 1
        row["first"] = min(row["first"], g["day"])
        row["last"] = max(row["last"], g["day"])
    return sorted(agg.values(), key=lambda r: (r["product_id"], r["climate"]))


def user_score(row: dict) -> float | None:
    return (row["held"] + 0.5 * row["partly"]) / row["n"] if row.get("n") else None


def label_vs_users(rows: list[dict], hold_of: dict[str, int | None], climate: str) -> dict:
    """Of the products the label rates 3 (strongest), how many did users see break down?
    Only products with at least MIN_LOGS logs in this climate count."""
    checked, broke = [], []
    for r in rows:
        if r["climate"] != climate or hold_of.get(r["product_id"]) != 3 or r["n"] < MIN_LOGS:
            continue
        checked.append(r["product_id"])
        if user_score(r) < BROKE_BELOW:
            broke.append(r["product_id"])
    return {"climate": climate, "checked": len(checked), "broke": len(broke), "broke_ids": sorted(broke)}


# ---------------------------------------------------------------------------
# The survey that came before the site's logging feature: 10 people (8 in Korea,
# 2 in Singapore) answered twice a week for 6 weeks between August and October (Singapore
# hot and humid throughout; Korea warmer than usual but very dry in September) about 3 base products, in their
# own words. Each answer was sorted into held / partly / broke by the project author;
# answers that could go either way carry a worse and a better reading, so every
# score comes with a range. Because the results are the author's reading and Korea's
# weather doesn't fit one climate type, it is shown next to the site's logs, never mixed in.
# ---------------------------------------------------------------------------
SURVEY_REGIONS = ("KR", "SG")


def _score(rows: list[dict], key: str) -> float:
    held = sum(r[key] == "held" for r in rows)
    partly = sum(r[key] == "partly" for r in rows)
    return (held + 0.5 * partly) / len(rows)


def survey_summary(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{product_id: {"ALL"|region: {n, held, partly, broke, score, low, high, ambiguous}}}"""
    for r in rows:
        for k in ("result", "result_if_worse", "result_if_better"):
            if r[k] not in RESULTS:
                raise HoldLogError(f"bad survey result '{r[k]}'")
    out: dict[str, dict[str, dict]] = {}
    for pid in sorted({r["product_id"] for r in rows}):
        mine = [r for r in rows if r["product_id"] == pid]
        groups = {"ALL": mine, **{g: [r for r in mine if r["region"] == g] for g in SURVEY_REGIONS}}
        out[pid] = {}
        for g, rs in groups.items():
            if not rs:
                continue
            out[pid][g] = {
                "n": len(rs),
                "held": sum(r["result"] == "held" for r in rs),
                "partly": sum(r["result"] == "partly" for r in rs),
                "broke": sum(r["result"] == "broke" for r in rs),
                "score": round(_score(rs, "result"), 3),
                "low": round(_score(rs, "result_if_worse"), 3),
                "high": round(_score(rs, "result_if_better"), 3),
                "ambiguous": sum(bool(r.get("ambiguous")) for r in rs),
            }
    return out
