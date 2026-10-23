"""
HTTP API (FastAPI). Install:  pip install -r requirements-api.txt
Run:                          uvicorn beautybridge.api:app --reload
Website:                      http://127.0.0.1:8000/
Docs:                         http://127.0.0.1:8000/docs

Data source: env var BEAUTYBRIDGE_DATA (a data folder or .sqlite file);
defaults to data/real (real products) when present, else the demo data.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from pydantic import BaseModel

from . import load_engine
from . import personal_color as pcol
from . import reviews as rv
from .config import FUSION_MODES, SIMILARITY_WEIGHTS
from .engine import NotFound

_REAL = Path(__file__).resolve().parents[1] / "data" / "real"
engine = load_engine(os.environ.get("BEAUTYBRIDGE_DATA") or (_REAL if (_REAL / "products.csv").exists() else None))

app = FastAPI(
    title="Beauty Bridge API",
    version="0.1.0",
    description="Explainable cross-market beauty product recommendation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("BEAUTYBRIDGE_CORS", "http://localhost:3000").split(","),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

Market = Query(None, description="ISO country code, e.g. KR, US, JP", min_length=2, max_length=2)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=e.args[0]) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


SITE = Path(__file__).resolve().parents[1] / "web" / "index.html"
_DATA_DIR = Path(os.environ.get("BEAUTYBRIDGE_DATA") or _REAL)
shades = pcol.load_shades(_DATA_DIR / "shades.csv", set(engine.ds.products)) if _DATA_DIR.is_dir() else {}
store = rv.ReviewStore(os.environ.get("BEAUTYBRIDGE_REVIEWS_DB")
                       or Path(__file__).resolve().parents[1] / "db" / "reviews.sqlite")


class ReviewIn(BaseModel):
    reviewer_id: str
    product_id: str
    rating: int
    skin_type: str | None = None
    age_band: str | None = None
    market: str | None = None
    text: str = ""
    climate: str | None = None
    skin_depth: str | None = None


@app.post("/reviews", status_code=201)
def post_review(body: ReviewIn):
    """Add or replace a reviewer's review of a product. Rankings update at once."""
    try:
        r = rv.make_review(body.model_dump(), set(engine.ds.products))
    except rv.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    store.upsert(r)
    return r.to_dict()


@app.get("/reviews")
def all_reviews(skin_depth: str | None = None):
    """Every current review, for the website. Reviewer ids are replaced by a
    one-way key so visitors can't act as someone else. ?skin_depth=tan keeps only
    reviewers with the same or a neighbouring skin depth."""
    from .skin_depth import DEPTHS
    rows = rv.latest_per_reviewer(store.all())
    if skin_depth:
        if skin_depth not in DEPTHS:
            raise HTTPException(status_code=400, detail=f"skin_depth must be one of {', '.join(DEPTHS)}")
        rows = rv.similar_depth(rows, skin_depth)
    out = []
    for r in rows:
        d = r.to_dict()
        d["reviewer_key"] = rv.reviewer_key(d.pop("reviewer_id"))
        out.append(d)
    return out


class ClickIn(BaseModel):
    visitor_id: str
    product_id: str
    store: str
    market: str | None = None


@app.post("/clicks", status_code=201)
def post_click(body: ClickIn):
    """Record a 'Buy' button click (purchase intent)."""
    try:
        c = rv.make_click(body.model_dump(), set(engine.ds.products))
    except rv.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    store.add_click(c)
    return {"ok": True}


@app.get("/clicks/stats")
def click_stats():
    """Per product: distinct people who clicked 'Buy' (all time, last 7 days) and raw clicks."""
    return [{"product_id": pid, **s} for pid, s in rv.click_stats(store.clicks()).items()]


@app.delete("/reviews/{reviewer_id}/{product_id}", status_code=204)
def delete_review(reviewer_id: str, product_id: str):
    store.delete(reviewer_id, product_id)


@app.get("/products/{product_id}/reviews")
def product_reviews(product_id: str):
    _guard(engine.get, product_id)
    items = [r.to_dict() for r in rv.latest_per_reviewer(store.all()) if r.product_id == product_id]
    items.sort(key=lambda r: r["created_at"], reverse=True)
    stats = rv.bayes_scores(store.all()).get(product_id)
    return {"stats": stats, "reviews": [{k: v for k, v in r.items() if k != "reviewer_id"} for r in items]}


@app.get("/rankings/reviews")
def review_ranking(category: str | None = None, skin_type: str | None = None,
                   age_band: str | None = None, market: str | None = Market):
    """Live ranking from first-party reviews, optionally for one segment."""
    ids = [pid for pid, p in engine.ds.products.items()
           if category is None or p.category == category or p.category_group == category]
    rows = rv.ranking(store.all(), ids, skin_type=skin_type, age_band=age_band,
                      market=market.upper() if market else None)
    return [{**r, "product": engine.get(r["product_id"]).to_dict()} for r in rows]


@app.get("/rankings/rising")
def review_rising():
    rows = rv.trending(store.all())
    return [{**r, "product": engine.get(r["product_id"]).to_dict()} for r in rows]


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def website():
    """The website (built by scripts/build_site.py)."""
    if not SITE.exists():
        return HTMLResponse("<p>Website not built yet. Run: python scripts/build_site.py</p>", status_code=404)
    return HTMLResponse(SITE.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    ds = engine.ds
    return {"status": "ok", "products": len(ds.products), "goals": len(ds.goals),
            "markets": ds.markets}


@app.get("/config")
def config():
    return {"similarity_weights": SIMILARITY_WEIGHTS, "fusion_modes": FUSION_MODES}


@app.get("/products/search")
def search(q: str = Query(..., min_length=1), k: int = Query(10, ge=1, le=50)):
    out = engine.search(q, k=k)
    out["hits"] = [{**h, "product": engine.get(h["product_id"]).to_dict()} for h in out["hits"]]
    return out


@app.get("/products/{product_id}")
def product(product_id: str):
    p = _guard(engine.get, product_id)
    listings = [
        {k: v for k, v in l.__dict__.items() if k != "product_id"}
        for (pid, _), l in engine.ds.listings.items() if pid == product_id
    ]
    return {**p.to_dict(), "markets": listings}


@app.get("/recommendations/similar/{product_id}")
def similar(product_id: str, k: int = Query(10, ge=1, le=50),
            mode: str = Query("similar"), market: str | None = Market,
            origin: str | None = Market, method: str = Query("weighted", pattern="^(weighted|cosine)$")):
    recs = _guard(engine.similar, product_id, k=k, mode=mode, market=market,
                  origin=origin.upper() if origin else None, method=method)
    return {"reference": engine.get(product_id).to_dict(), "mode": mode, "market": market,
            "results": [r.to_dict() for r in recs]}


@app.get("/recommendations/cheaper/{product_id}")
def cheaper(product_id: str, k: int = Query(10, ge=1, le=50), market: str | None = Market,
            origin: str | None = Market, min_similarity: float = Query(0.8, ge=0, le=1)):
    recs = _guard(engine.cheaper, product_id, k=k, market=market,
                  origin=origin.upper() if origin else None, min_similarity=min_similarity)
    return {"reference": engine.get(product_id).to_dict(), "market": market,
            "results": [r.to_dict() for r in recs]}


@app.get("/goals")
def goals():
    return [g.to_dict() for g in engine.ds.goals.values()]


@app.get("/recommendations/goal/{goal_id}")
def goal(goal_id: str, k: int = Query(10, ge=1, le=50), market: str | None = Market,
         skin_type: str | None = None, category: str | None = None):
    recs = _guard(engine.goal, goal_id.replace("-", "_"), k=k, market=market,
                  skin_type=skin_type, category=category)
    return {"goal": engine.ds.goals[goal_id.replace("-", "_")].to_dict(), "market": market,
            "results": [r.to_dict() for r in recs]}


@app.get("/personal-color/types")
def personal_color_types():
    return {"types": list(pcol.TYPES), "targets": pcol.TYPES, "weights": pcol.WEIGHTS}


@app.get("/personal-color/{pc_type}")
def personal_color(pc_type: str, k: int = Query(20, ge=1, le=100)):
    """Shades ranked for one personal colour type (e.g. summer_mute)."""
    rows = _guard(pcol.best_shades, shades, pc_type, k)
    return [{"product": engine.get(s.product_id).to_dict(), "shade": s.name, "shade_local": s.name_local,
             "fit": f, "stated": s.stated_text, "stated_url": s.stated_url} for s, f in rows]


@app.get("/products/{product_id}/shades")
def product_shades(product_id: str):
    _guard(engine.get, product_id)
    return [{"name": s.name, "name_local": s.name_local, "temp": s.temp, "value": s.value, "chroma": s.chroma,
             "fit": s.fit, "stated": s.stated_text, "stated_url": s.stated_url} for s in shades.get(product_id, [])]


class VoteIn(BaseModel):
    voter_id: str
    product_id: str
    shade: str
    pc_type: str
    verdict: str
    skin_type: str | None = None


@app.post("/shade-votes", status_code=201)
def post_vote(body: VoteIn):
    """'Did this shade suit you?' from someone who knows their type. Replaces their earlier answer."""
    try:
        v = pcol.make_vote(body.model_dump(), shades)
    except pcol.ShadeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    store.upsert_vote(v)
    return {"ok": True}


@app.delete("/shade-votes/{voter_id}/{product_id}/{shade}", status_code=204)
def delete_vote(voter_id: str, product_id: str, shade: str):
    store.delete_vote(voter_id, product_id, shade)


@app.get("/shade-votes/stats")
def vote_stats():
    """Counts per product, shade and personal colour type (no voter ids)."""
    return pcol.vote_stats(store.votes())


@app.get("/shade-votes/mine/{voter_id}")
def my_votes(voter_id: str):
    return [{k: v[k] for k in ("product_id", "shade", "pc_type", "verdict", "skin_type")} for v in store.votes(voter_id)]


@app.get("/shade-votes/agreement")
def vote_agreement():
    """How often the estimated shade labels matched what people said."""
    return pcol.agreement(store.votes(), shades)


class CategoryReportIn(BaseModel):
    reporter_id: str
    product_id: str
    suggested: str
    note: str = ""


def _product_categories() -> dict[str, str]:
    return {pid: p.category for pid, p in engine.ds.products.items()}


@app.post("/category-reports", status_code=201)
def post_category_report(body: CategoryReportIn):
    """'This product belongs in another category.' Replaces the person's earlier suggestion."""
    from .codebook import CATEGORIES
    try:
        r = rv.make_category_report(body.model_dump(), _product_categories(), CATEGORIES)
    except rv.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    store.upsert_category_report(r)
    return {"ok": True}


@app.delete("/category-reports/{reporter_id}/{product_id}", status_code=204)
def delete_category_report(reporter_id: str, product_id: str):
    store.delete_category_report(reporter_id, product_id)


@app.get("/category-reports/stats")
def category_report_stats():
    return rv.category_report_stats(store.category_reports())


@app.get("/category-reports/mine/{reporter_id}")
def my_category_reports(reporter_id: str):
    return [{k: r[k] for k in ("product_id", "suggested", "note")} for r in store.category_reports(reporter_id)]


@app.get("/climate/{product_id}")
def product_climate(product_id: str):
    """Estimated sweat/oil resistance (0-3) and fit per climate (0-100, with reasons)."""
    from . import climate as cl
    p = engine.ds.products.get(product_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"unknown product '{product_id}'")
    return cl.for_site(p)


class HoldLogIn(BaseModel):
    logger_id: str
    product_id: str
    climate: str
    result: str
    day: str | None = None


@app.post("/hold-logs", status_code=201)
def post_hold_log(body: HoldLogIn):
    """'Did it hold at noon?' One log per person per product per day (a new one replaces it)."""
    from . import hold_log as hl
    try:
        g = hl.make_log(body.model_dump(), set(engine.ds.products))
    except (hl.HoldLogError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    store.upsert_hold_log(g)
    return {"ok": True}


@app.delete("/hold-logs/{logger_id}/{product_id}/{day}", status_code=204)
def delete_hold_log(logger_id: str, product_id: str, day: str):
    store.delete_hold_log(logger_id, product_id, day)


@app.get("/hold-logs/stats")
def hold_log_stats():
    from . import hold_log as hl
    return hl.stats(store.hold_logs())


@app.get("/hold-logs/mine/{logger_id}")
def my_hold_logs(logger_id: str):
    return [{k: g[k] for k in ("product_id", "climate", "result", "day")} for g in store.hold_logs(logger_id)]


@app.get("/hold-logs/check/{climate}")
def hold_label_check(climate: str):
    """Of the products the label rates 3, how many did users see break down in this climate?"""
    from . import climate as cl, hold_log as hl
    if climate not in cl.CLIMATES:
        raise HTTPException(status_code=400, detail="unknown climate")
    hold_of = {pid: cl.hold(p) for pid, p in engine.ds.products.items()}
    return hl.label_vs_users(hl.stats(store.hold_logs()), hold_of, climate)


@app.get("/market/leaders/{market}")
def market_leaders(market: str, category: str | None = None):
    """Sourced market leaders (awards, bestseller reports) for one country."""
    return engine.market_leaders(market, category)


@app.get("/trending/{market}")
def trend(market: str, chart: str | None = None):
    return _guard(engine.trending, market, chart)


@app.get("/ask")
def ask(q: str = Query(..., min_length=1), k: int = Query(5, ge=1, le=20),
        market: str | None = Market):
    return engine.ask(q, k=k, market=market.upper() if market else None)


@app.get("/market/financials")
def financials(company: str | None = None):
    rows = engine.ds.financials
    return [r for r in rows if company is None or r["company"] == company]


@app.get("/market/events")
def events(company: str | None = None):
    rows = engine.ds.events
    return [r for r in rows if company is None or r["company"] == company]
