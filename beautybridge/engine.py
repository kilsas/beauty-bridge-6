"""
Engine: the one object the API, CLI, demo page and research scripts all use.

Pipeline:  query -> product identification -> candidate pool
           -> similarity / goal fit  (content, market-independent)
           -> price, local fit, popularity  (market-dependent, optional)
           -> rank fusion (mode weights)  -> explanation
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import CHEAPER_MIN_SIMILARITY, FUSION_MODES, FX_TO_USD, SIMILARITY_WEIGHTS
from .db import Dataset
from .goals import score_goal
from .market import local_fit, market_signal, popularity, trending
from .product import Product
from .search import ProductIndex, parse_query
from .similarity import rank_similar


class NotFound(KeyError):
    pass


def price_advantage(reference_usd: float | None, candidate_usd: float | None) -> float | None:
    """0.5 = same price, 1.0 = half the price or less, 0.0 = double or more."""
    if reference_usd is None or candidate_usd is None:
        return None
    return max(0.0, min(1.0, 0.5 + 0.5 * math.log(reference_usd / candidate_usd) / math.log(2)))


def fuse(components: dict[str, float | None], mode: str) -> tuple[float, dict[str, float]]:
    """Weighted sum over available components; weights renormalized and returned."""
    if mode not in FUSION_MODES:
        raise ValueError(f"unknown mode '{mode}', choose from {sorted(FUSION_MODES)}")
    weights = FUSION_MODES[mode]
    usable = {k: w for k, w in weights.items() if components.get(k) is not None and w > 0}
    total = sum(usable.values())
    if total == 0:
        return 0.0, {}
    used = {k: w / total for k, w in usable.items()}
    return sum(used[k] * components[k] for k in used), used


@dataclass
class Recommendation:
    product: Product
    final_score: float
    weights_used: dict[str, float]
    components: dict[str, float | None]
    similarity: dict | None = None      # explanation from similarity.py
    goal: dict | None = None            # explanation from goals.py
    local: dict | None = None
    popularity: dict | None = None
    price_usd: float | None = None
    savings_usd: float | None = None

    def to_dict(self) -> dict:
        return {
            "product": self.product.to_dict(),
            "final_score": round(self.final_score, 4),
            "weights_used": {k: round(v, 3) for k, v in self.weights_used.items()},
            "components": {k: (None if v is None else round(v, 4)) for k, v in self.components.items()},
            "similarity": self.similarity,
            "goal": self.goal,
            "local": self.local,
            "popularity": self.popularity,
            "price_usd": None if self.price_usd is None else round(self.price_usd, 2),
            "savings_usd": None if self.savings_usd is None else round(self.savings_usd, 2),
        }


class Engine:
    def __init__(self, dataset: Dataset):
        self.ds = dataset
        self.index = ProductIndex(dataset.products)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, product_id: str) -> Product:
        try:
            return self.ds.products[product_id]
        except KeyError:
            raise NotFound(f"no product '{product_id}'") from None

    def search(self, query: str, k: int = 10) -> dict:
        pq = parse_query(query, self.ds.goals)
        text = pq.product_text or ("" if pq.goal_id else query)
        hits = self.index.search(text, k=k, category=pq.category, origin=pq.origin) if text else []
        if not hits and text and (pq.category or pq.origin):
            # filters may have been meant for the *recommendations*, not the reference product
            hits = self.index.search(text, k=k)
        return {"parsed": pq.to_dict(), "hits": [h.to_dict() for h in hits]}

    # ------------------------------------------------------------------
    # Market helpers
    # ------------------------------------------------------------------
    def _market_price_usd(self, p: Product, market: str | None) -> float | None:
        if market:
            listing = self.ds.listings.get((p.product_id, market))
            if listing and listing.local_price and listing.currency in FX_TO_USD:
                return listing.local_price * FX_TO_USD[listing.currency]
        return p.price_usd

    def _available(self, p: Product, market: str) -> bool:
        listing = self.ds.listings.get((p.product_id, market))
        return listing is not None and listing.availability != "none"

    def _market_context(self, pool: list[Product], market: str | None):
        if not market:
            return {}, [], {}
        try:
            trend_index = {e.product_id: e for e in trending(self.ds.rankings, market)}
        except ValueError:  # several charts in one market: skip chart signals
            trend_index = {}
        peer_prices = [
            v for v in (self._market_price_usd(p, market) for p in pool if self._available(p, market))
            if v is not None
        ]
        return trend_index, peer_prices, FX_TO_USD

    def _market_signals(self, p: Product, market: str | None, ctx) -> tuple:
        if not market:
            return None, None, None, None
        trend_index, peer_prices, fx = ctx
        pop, pop_detail = popularity(self.ds, p.product_id, market, trend_index)
        sig, evidence = market_signal(self.ds, p.product_id, market)
        if sig is not None and (pop is None or sig > pop):
            pop = sig
            pop_detail = {"market_signal": {"value": round(sig, 3), "weight": 1.0,
                                            "evidence": [{k: e[k] for k in ("source", "category", "rank", "source_url")}
                                                         for e in evidence]}}
        # popularity is passed as None so it is not double counted in fusion
        loc, loc_detail = local_fit(self.ds, p.product_id, market,
                                    peer_prices_usd=peer_prices, fx=fx, popularity_value=None)
        return pop, pop_detail, loc, loc_detail

    # ------------------------------------------------------------------
    # Similar products
    # ------------------------------------------------------------------
    def similar(self, product_id: str, k: int = 10, *, mode: str = "similar",
                market: str | None = None, method: str = "weighted",
                weights: dict[str, float] | None = None,
                origin: str | None = None, only_available: bool = True) -> list[Recommendation]:
        target = self.get(product_id)
        market = market.upper() if market else None
        pool = [p for p in self.ds.products.values()
                if (origin is None or p.country_origin == origin)
                and (not market or not only_available or self._available(p, market))]
        sims = rank_similar(target, pool, k=None, method=method, weights=weights or SIMILARITY_WEIGHTS)
        ctx = self._market_context([self.get(s.candidate_id) for s in sims], market)
        ref_price = self._market_price_usd(target, market)
        recs = []
        for s in sims:
            p = self.get(s.candidate_id)
            cand_price = self._market_price_usd(p, market)
            pop, pop_d, loc, loc_d = self._market_signals(p, market, ctx)
            comps = {
                "similarity": s.score,
                "price": price_advantage(ref_price, cand_price),
                "local": loc,
                "popularity": pop,
            }
            final, used = fuse(comps, mode)
            recs.append(Recommendation(
                product=p, final_score=final, weights_used=used, components=comps,
                similarity=s.to_dict(), local=loc_d or None, popularity=pop_d or None,
                price_usd=cand_price,
                savings_usd=(ref_price - cand_price) if ref_price and cand_price else None,
            ))
        recs.sort(key=lambda r: (-r.final_score, r.product.product_id))
        return recs[:k]

    def cheaper(self, product_id: str, k: int = 10, *, market: str | None = None,
                min_similarity: float = CHEAPER_MIN_SIMILARITY,
                origin: str | None = None) -> list[Recommendation]:
        """Similar (>= min_similarity) AND cheaper than the reference product."""
        recs = self.similar(product_id, k=len(self.ds.products), mode="cheaper",
                            market=market, origin=origin)
        return [
            r for r in recs
            if r.components["similarity"] >= min_similarity
            and r.savings_usd is not None and r.savings_usd > 0
        ][:k]

    # ------------------------------------------------------------------
    # Beauty goals
    # ------------------------------------------------------------------
    def goal(self, goal_id: str, k: int = 10, *, market: str | None = None,
             skin_type: str | None = None, category: str | None = None,
             origin: str | None = None, mode: str = "goal") -> list[Recommendation]:
        if goal_id not in self.ds.goals:
            raise NotFound(f"no goal '{goal_id}'")
        g = self.ds.goals[goal_id]
        market = market.upper() if market else None
        pool = [p for p in self.ds.products.values()
                if p.category in g.eligible_categories
                and (category is None or p.category == category)
                and (origin is None or p.country_origin == origin)
                and (skin_type is None or not p.skin_types or skin_type in p.skin_types)
                and (not market or self._available(p, market))]
        ctx = self._market_context(pool, market)
        prices = sorted(v for v in (self._market_price_usd(p, market) for p in pool) if v is not None)
        recs = []
        for p in pool:
            gr = score_goal(p, g)
            if gr is None:
                continue
            price = self._market_price_usd(p, market)
            price_score = None
            if price is not None and len(prices) > 1:
                cheaper_than = sum(1 for x in prices if x > price)
                price_score = cheaper_than / (len(prices) - 1)
            pop, pop_d, loc, loc_d = self._market_signals(p, market, ctx)
            comps = {"goal": gr.score, "price": price_score, "local": loc, "popularity": pop}
            final, used = fuse(comps, mode)
            recs.append(Recommendation(
                product=p, final_score=final, weights_used=used, components=comps,
                goal={
                    "score": round(gr.score, 4), "percent": round(gr.score * 100),
                    "evidence": round(gr.evidence, 3),
                    "components": [
                        {"feature": c.feature, "rule": c.rule, "product_value": c.product_value,
                         "points": round(c.points, 1), "max_points": round(c.max_points, 1)}
                        for c in gr.components
                    ],
                },
                local=loc_d or None, popularity=pop_d or None, price_usd=price,
            ))
        recs.sort(key=lambda r: (-r.final_score, r.product.product_id))
        return recs[:k]

    # ------------------------------------------------------------------
    # Trends
    # ------------------------------------------------------------------
    def market_leaders(self, market: str, category: str | None = None) -> list[dict]:
        """Products with sourced awards / bestseller evidence in one market, strongest first."""
        market = market.upper()
        out = []
        for pid, p in self.ds.products.items():
            if category and p.category != category and p.category_group != category:
                continue
            s, ev = market_signal(self.ds, pid, market)
            if s is not None:
                out.append({"product_id": pid, "strength": round(s, 3), "evidence": ev,
                            "product": p.to_dict()})
        out.sort(key=lambda r: (-r["strength"], r["product_id"]))
        return out

    def trending(self, market: str, chart: str | None = None) -> list[dict]:
        out = []
        for e in trending(self.ds.rankings, market.upper(), chart):
            d = e.to_dict()
            d["product"] = self.get(e.product_id).to_dict()
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Natural-language entry point
    # ------------------------------------------------------------------
    def ask(self, query: str, k: int = 5, market: str | None = None) -> dict:
        found = self.search(query, k=3)
        pq = found["parsed"]
        market = market or pq["market"]
        if pq["intent"] == "goal" or (pq["goal_id"] and not found["hits"]):
            recs = self.goal(pq["goal_id"], k=k, market=market,
                             category=pq["category"], origin=pq["origin"])
            return {"parsed": pq, "action": "goal", "reference": None,
                    "results": [r.to_dict() for r in recs]}
        if not found["hits"]:
            return {"parsed": pq, "action": "none", "reference": None, "results": []}
        ref = found["hits"][0]["product_id"]
        if pq["intent"] == "cheaper":
            recs = self.cheaper(ref, k=k, market=market, origin=pq["origin"])
            action = "cheaper"
        elif pq["intent"] == "similar" or pq["origin"]:
            recs = self.similar(ref, k=k, market=market, origin=pq["origin"])
            action = "similar"
        else:
            return {"parsed": pq, "action": "search", "reference": None,
                    "results": [{"product": self.get(h["product_id"]).to_dict(), "match": h}
                                for h in found["hits"]]}
        return {"parsed": pq, "action": action, "reference": self.get(ref).to_dict(),
                "results": [r.to_dict() for r in recs]}
