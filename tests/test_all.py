"""Run:  python -m unittest discover tests      (or: pytest)"""
from __future__ import annotations

import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from beautybridge import build_sqlite, load_engine, load_folder, load_sqlite  # noqa: E402
from beautybridge import codebook as cb  # noqa: E402
from beautybridge.engine import fuse, price_advantage  # noqa: E402
from beautybridge.goals import score_goal  # noqa: E402
from beautybridge.product import ValidationError, parse_product  # noqa: E402
from beautybridge.search import parse_query  # noqa: E402
from beautybridge.similarity import (  # noqa: E402
    category_similarity, cosine_similarity, is_comparable, weighted_similarity,
)
import agreement  # noqa: E402
import metrics  # noqa: E402

ENGINE = load_engine()
P = ENGINE.ds.products


def row(**over) -> dict:
    base = {c: "" for c in cb.PRODUCT_COLUMNS}
    base.update(product_id="T1", brand="B", name="N", category="loose_powder")
    base.update(over)
    return base


class TestValidation(unittest.TestCase):
    def test_demo_data_is_valid(self):
        self.assertEqual(len(P), 90)

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValidationError):
            parse_product(row(category="powderz"))

    def test_rejects_out_of_range_intensity(self):
        for bad in ("4", "-1", "1.5", "high"):
            with self.assertRaises(ValidationError, msg=bad):
                parse_product(row(shimmer=bad))

    def test_rejects_unknown_currency(self):
        with self.assertRaises(ValidationError):
            parse_product(row(price="10", currency="XYZ"))

    def test_all_skin_types_expands(self):
        self.assertEqual(parse_product(row(skin_types="all")).skin_types, frozenset(cb.SKIN_TYPES))

    def test_intensity_normalized(self):
        p = parse_product(row(shimmer="3", glow="0"))
        self.assertEqual(p.intensities["shimmer"], 1.0)
        self.assertEqual(p.intensities["glow"], 0.0)
        self.assertIsNone(p.intensities["hydration"])

    def test_loader_reports_all_errors(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "products.csv"
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cb.PRODUCT_COLUMNS)
                w.writeheader()
                w.writerow(row(product_id="A", finish="shiny"))
                w.writerow(row(product_id="B", coverage="huge"))
                w.writerow(row(product_id="A"))
            with self.assertRaises(ValidationError) as ctx:
                load_folder(Path(d))
            msg = str(ctx.exception)
            self.assertIn("3 problem", msg)


class TestSimilarity(unittest.TestCase):
    def test_self_similarity_is_one(self):
        for p in list(P.values())[:10]:
            self.assertAlmostEqual(weighted_similarity(p, p).score, 1.0)

    def test_symmetric(self):
        a, b = P["P001"], P["P003"]
        self.assertAlmostEqual(weighted_similarity(a, b).score, weighted_similarity(b, a).score)

    def test_bounds(self):
        ids = list(P)
        for i in ids[::5]:
            for j in ids[::7]:
                s = weighted_similarity(P[i], P[j]).score
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 1.0)

    def test_points_add_up(self):
        r = weighted_similarity(P["P001"], P["P002"])
        self.assertAlmostEqual(sum(c.points for c in r.components), r.score * 100)
        self.assertAlmostEqual(sum(c.max_points for c in r.components), 100.0)

    def test_designed_dupe_ranks_first(self):
        top = ENGINE.similar("P001", k=1, mode="similarity_only")[0]
        self.assertEqual(top.product.product_id, "P008")

    def test_category_gate(self):
        self.assertFalse(is_comparable(P["P001"], P["P042"]))   # powder vs toner
        self.assertTrue(is_comparable(P["P001"], P["P006"]))    # loose vs pressed
        ids = [r.product.product_id for r in ENGINE.similar("P001", k=50)]
        self.assertTrue(all(P[i].category_group == "face_base" for i in ids))

    def test_related_categories_symmetric(self):
        self.assertEqual(category_similarity(P["P001"], P["P006"]),
                         category_similarity(P["P006"], P["P001"]))

    def test_missing_attributes_renormalize(self):
        r = weighted_similarity(P["P043"], P["P048"])  # serums: no coverage
        self.assertIn("coverage", r.skipped)
        self.assertAlmostEqual(sum(c.weight for c in r.components), 1.0)
        self.assertLess(r.evidence, 1.0)

    def test_cosine_bounds(self):
        self.assertAlmostEqual(cosine_similarity(P["P001"], P["P001"]), 1.0)
        self.assertLess(cosine_similarity(P["P001"], P["P041"]), 0.6)


class TestRecommendations(unittest.TestCase):
    def test_cheaper_really_cheaper_and_similar(self):
        ref = P["P001"]
        recs = ENGINE.cheaper("P001", k=10)
        self.assertTrue(recs)
        for r in recs:
            self.assertGreaterEqual(r.components["similarity"], 0.8)
            self.assertLess(r.product.price_usd, ref.price_usd)

    def test_origin_filter(self):
        recs = ENGINE.similar("P001", k=10, origin="KR")
        self.assertTrue(all(r.product.country_origin == "KR" for r in recs))

    def test_market_filter_only_available(self):
        recs = ENGINE.similar("P001", k=20, market="JP")
        for r in recs:
            listing = ENGINE.ds.listings.get((r.product.product_id, "JP"))
            self.assertIsNotNone(listing)
            self.assertNotEqual(listing.availability, "none")

    def test_similarity_and_popularity_reported_separately(self):
        r = ENGINE.similar("P001", k=1, market="KR")[0]
        self.assertIn("similarity", r.components)
        self.assertIn("popularity", r.components)
        self.assertIsNotNone(r.similarity)

    def test_without_market_weights_renormalize(self):
        r = ENGINE.similar("P001", k=1, mode="similar")[0]
        self.assertAlmostEqual(sum(r.weights_used.values()), 1.0)
        self.assertNotIn("local", r.weights_used)

    def test_goal_eligibility(self):
        g = ENGINE.ds.goals["aegyo_sal"]
        for r in ENGINE.goal("aegyo_sal", k=20):
            self.assertIn(r.product.category, g.eligible_categories)
        self.assertIsNone(score_goal(P["P001"], g))   # a powder is not eligible

    def test_goal_prefers_subtle_shimmer(self):
        g = ENGINE.ds.goals["aegyo_sal"]
        subtle = score_goal(P["P032"], g).score     # fine pearl shadow
        glitter = score_goal(P["P031"], g).score    # glitter, glossy
        self.assertGreater(subtle, glitter)

    def test_skin_type_filter(self):
        for r in ENGINE.goal("pore_blurring", k=20, skin_type="dry"):
            self.assertIn("dry", r.product.skin_types)

    def test_fuse_and_price_advantage(self):
        self.assertAlmostEqual(price_advantage(20, 20), 0.5)
        self.assertAlmostEqual(price_advantage(20, 10), 1.0)
        self.assertAlmostEqual(price_advantage(20, 40), 0.0)
        score, used = fuse({"similarity": 0.8, "price": None}, "similarity_price")
        self.assertAlmostEqual(score, 0.8)
        self.assertEqual(used, {"similarity": 1.0})
        with self.assertRaises(ValueError):
            fuse({}, "nope")

    def test_trending_statuses(self):
        rows = ENGINE.trending("KR")
        self.assertEqual([r["rank"] for r in rows], list(range(1, len(rows) + 1)))
        self.assertTrue(any(r["status"] == "rising" for r in rows))
        self.assertTrue(any(r["status"] == "new" for r in rows))


class TestGoalAreas(unittest.TestCase):
    def test_every_goal_has_area(self):
        areas = {g.area for g in ENGINE.ds.goals.values()}
        self.assertEqual(areas, {"skin", "eye", "lip", "contour", "moist", "clear", "tone", "sun"})

    def test_every_goal_has_candidates(self):
        for gid in ENGINE.ds.goals:
            self.assertTrue(ENGINE.goal(gid, k=3), gid)

    def test_new_category_goals(self):
        top = lambda g: ENGINE.goal(g, k=1, mode="goal")[0].product.category
        self.assertEqual(top("lashes"), "mascara")
        self.assertEqual(top("lip_liner"), "lip_liner")
        self.assertEqual(top("shading"), "contour")
        self.assertEqual(top("bronzer"), "bronzer")

    def test_china_market(self):
        self.assertIn("CN", ENGINE.ds.markets)
        self.assertTrue(ENGINE.trending("CN"))
        for r in ENGINE.similar("P001", k=5, market="CN"):
            self.assertNotEqual(ENGINE.ds.listings[(r.product.product_id, "CN")].availability, "none")


class TestReviews(unittest.TestCase):
    def setUp(self):
        from beautybridge import reviews as rv
        self.rv = rv
        known = set(P)
        mk = lambda who, pid, r, day, **kw: rv.make_review(  # noqa: E731
            {"reviewer_id": who, "product_id": pid, "rating": r,
             "created_at": f"2026-09-{day:02d}T10:00:00+00:00", **kw}, known)
        self.reviews = [
            mk("a", "P001", 5, 29, skin_type="oily"), mk("b", "P001", 4, 29, skin_type="dry"),
            mk("c", "P001", 5, 28, skin_type="oily"), mk("a", "P002", 5, 20),
            mk("a", "P002", 3, 21),  # same reviewer again: only the latest counts
        ]

    def test_validation(self):
        with self.assertRaises(self.rv.ReviewError):
            self.rv.make_review({"reviewer_id": "x", "product_id": "P001", "rating": 6}, set(P))
        with self.assertRaises(self.rv.ReviewError):
            self.rv.make_review({"reviewer_id": "x", "product_id": "NOPE", "rating": 5}, set(P))
        with self.assertRaises(self.rv.ReviewError):
            self.rv.make_review({"reviewer_id": "x", "product_id": "P001", "rating": 5, "age_band": "5s"}, set(P))

    def test_one_review_per_reviewer(self):
        s = self.rv.bayes_scores(self.reviews)
        self.assertEqual(s["P002"]["n"], 1)
        self.assertEqual(s["P002"]["mean"], 3)

    def test_bayes_shrinks_small_samples(self):
        s = self.rv.bayes_scores(self.reviews)
        # three strong reviews beat one weak review
        self.assertGreater(s["P001"]["score"], s["P002"]["score"])
        # score is pulled toward the global mean
        self.assertLess(s["P001"]["score"], s["P001"]["mean"])

    def test_segment_ranking(self):
        oily = self.rv.ranking(self.reviews, skin_type="oily")
        self.assertEqual([r["product_id"] for r in oily], ["P001"])
        self.assertEqual(oily[0]["n"], 2)

    def test_trending(self):
        from datetime import datetime, timezone
        rows = self.rv.trending(self.reviews, now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(rows[0]["product_id"], "P001")
        self.assertEqual(rows[0]["recent"], 3)

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            st = self.rv.ReviewStore(Path(d) / "r.sqlite")
            for r in self.reviews:
                st.upsert(r)
            self.assertEqual(len(st.all()), 4)   # (a, P002) replaced
            st.delete("a", "P002")
            self.assertEqual(len(st.all()), 3)


class TestRealData(unittest.TestCase):
    def test_real_dataset_valid_and_flagged(self):
        ds = load_folder(ROOT / "data" / "real")
        self.assertGreaterEqual(len(ds.products), 60)
        for p in ds.products.values():
            self.assertIn("unverified", p.source)
        # no invented ratings or review counts on real products
        for l in ds.listings.values():
            self.assertIsNone(l.rating)
            self.assertIsNone(l.review_count)


class TestMarketSignals(unittest.TestCase):
    def setUp(self):
        from beautybridge import Engine
        self.e = Engine(load_folder(ROOT / "data" / "real"))

    def test_every_market_has_leaders(self):
        for m in ("KR", "US", "JP", "CN"):
            self.assertTrue(self.e.market_leaders(m), m)

    def test_signals_are_sourced(self):
        for row in self.e.ds.signals:
            self.assertTrue(row["source_url"].startswith("https://"))

    def test_strength_order(self):
        from beautybridge.market import signal_strength
        first = signal_strength({"level": "product", "category": "cushion", "rank": "1"})
        third = signal_strength({"level": "product", "category": "cushion", "rank": "3"})
        brand = signal_strength({"level": "brand", "category": "brand_rank", "rank": "1"})
        self.assertGreater(first, third)
        self.assertGreater(third, brand)

    def test_market_leader_is_local(self):
        top = self.e.market_leaders("JP")[0]
        self.assertEqual(top["product"]["product_id"], "J013")   # @cosme 2025 best cushion #1


class TestSearch(unittest.TestCase):
    def top(self, q):
        hits = ENGINE.search(q)["hits"]
        return hits[0]["product_id"] if hits else None

    def test_exact_typo_korean(self):
        self.assertEqual(self.top("Bake Set Loose Powder"), "P001")
        self.assertEqual(self.top("bake sett"), "P001")
        self.assertEqual(self.top("베이크 셋"), "P001")
        self.assertEqual(self.top("노세범"), "P002")
        self.assertIsNone(self.top("xyzzy qwerty"))

    def test_query_parsing(self):
        pq = parse_query("cheap Korean powder similar to bake set", ENGINE.ds.goals)
        self.assertEqual((pq.intent, pq.origin, pq.category), ("cheaper", "KR", "loose_powder"))
        self.assertEqual(pq.product_text, "bake set")
        pq = parse_query("애굣살 추천", ENGINE.ds.goals)
        self.assertEqual((pq.intent, pq.goal_id), ("goal", "aegyo_sal"))
        pq = parse_query("中国 气垫", ENGINE.ds.goals)
        self.assertEqual((pq.category, pq.origin), ("cushion", "CN"))
        pq = parse_query("립 맥시마이저 추천", ENGINE.ds.goals)
        self.assertEqual(pq.goal_id, "lip_plumper")
        pq = parse_query("선크림 추천 미국에서", ENGINE.ds.goals)
        self.assertEqual((pq.category, pq.market), ("sunscreen", "US"))

    def test_ask_end_to_end(self):
        res = ENGINE.ask("cheap korean powder like bake set")
        self.assertEqual(res["action"], "cheaper")
        self.assertEqual(res["reference"]["product_id"], "P001")
        self.assertTrue(all(r["product"]["country_origin"] == "KR" for r in res["results"]))


class TestDatabase(unittest.TestCase):
    def test_sqlite_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.sqlite"
            build_sqlite(ROOT / "data" / "demo", db)
            ds = load_sqlite(db)
            self.assertEqual(set(ds.products), set(P))
            self.assertEqual(ds.products["P001"], P["P001"])
            self.assertEqual(len(ds.listings), len(ENGINE.ds.listings))
            self.assertEqual(len(ds.rankings), len(ENGINE.ds.rankings))

    def test_financials_require_source(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "products.csv").write_text((ROOT / "data/demo/products.csv").read_text("utf-8"), "utf-8")
            (d / "company_financials.csv").write_text(
                "company,fiscal_year,basis,revenue_krw,operating_profit_krw,net_income_krw,"
                "store_count,source_url,source_document,retrieved_at\n"
                "x,2022,separate,1,1,1,1,,doc,2026-09-30\n", "utf-8")
            with self.assertRaises(ValidationError):
                load_folder(d)


class TestResearchTools(unittest.TestCase):
    def test_metrics(self):
        rel = {"a": 3, "b": 0, "c": 2}
        self.assertAlmostEqual(metrics.precision_at_k(["a", "b"], rel, 2), 0.5)
        self.assertAlmostEqual(metrics.recall_at_k(["a", "b"], rel, 2), 0.5)
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "c", "b"], rel, 3), 1.0)
        self.assertLess(metrics.ndcg_at_k(["b", "c", "a"], rel, 3), 1.0)
        self.assertIsNone(metrics.ndcg_at_k(["a"], {"a": 0}, 1))
        self.assertAlmostEqual(metrics.average_precision(["a", "b", "c"], rel), (1 + 2 / 3) / 2)

    def test_randomization_test(self):
        self.assertGreater(metrics.paired_randomization_test([0.5] * 8, [0.5] * 8), 0.9)
        self.assertLess(metrics.paired_randomization_test([0.9] * 10, [0.1] * 10), 0.01)

    def test_kappa(self):
        self.assertAlmostEqual(agreement.cohen_kappa(list("aabb"), list("aabb")), 1.0)
        self.assertAlmostEqual(agreement.cohen_kappa(list("abab"), list("baba")), -1.0)
        levels = ["0", "1", "2", "3"]
        near = agreement.weighted_kappa(list("0123"), list("0122"), levels)
        far = agreement.weighted_kappa(list("0123"), list("0120"), levels)
        self.assertGreater(near, far)
        self.assertTrue(math.isclose(agreement.weighted_kappa(list("0123"), list("0123"), levels), 1.0))


class TestBuyButtons(unittest.TestCase):
    def test_click_stats_count_people_not_clicks(self):
        from datetime import datetime, timezone
        from beautybridge import reviews as rv
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        clicks = [{"visitor_id": "a", "product_id": "R004", "created_at": "2026-10-01T00:00:00+00:00"}] * 5 + [
            {"visitor_id": "b", "product_id": "R004", "created_at": "2026-09-01T00:00:00+00:00"},
            {"visitor_id": "a", "product_id": "U001", "created_at": "2026-10-01T00:00:00Z"}]
        st = rv.click_stats(clicks, now=now)
        self.assertEqual(st["R004"], {"people": 2, "people_7d": 1, "clicks": 6})
        self.assertEqual(st["U001"]["people"], 1)

    def test_make_click_validates(self):
        from beautybridge import reviews as rv
        ok = rv.make_click({"visitor_id": "v", "product_id": "R004", "store": "oliveyoung", "market": "kr"}, {"R004"})
        self.assertEqual(ok["market"], "KR")
        for bad in ({"visitor_id": "v", "product_id": "X", "store": "s"},
                    {"visitor_id": "", "product_id": "R004", "store": "s"},
                    {"visitor_id": "v", "product_id": "R004", "store": ""},
                    {"visitor_id": "v", "product_id": "R004", "store": "s", "market": "FR"}):
            with self.assertRaises(rv.ReviewError):
                rv.make_click(bad, {"R004"})

    def test_click_store_roundtrip(self):
        from beautybridge import reviews as rv
        with tempfile.TemporaryDirectory() as d:
            store = rv.ReviewStore(Path(d) / "r.sqlite")
            store.add_click(rv.make_click({"visitor_id": "v", "product_id": "R004", "store": "coupang"}, {"R004"}))
            self.assertEqual(rv.click_stats(store.clicks())["R004"]["people"], 1)

    def test_stores_and_buy_links(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_site
        stores = build_site.stores_config()
        self.assertEqual(set(stores), {"KR", "US", "JP", "CN"})
        for rows in stores.values():
            for s in rows:
                self.assertTrue(s["search"].startswith("https://") and "{q}" in s["search"])
        with tempfile.TemporaryDirectory() as d:
            Path(d, "buy_links.csv").write_text("product_id,store,url,affiliate\nR004,coupang,https://link.coupang.com/a/x,yes\n", encoding="utf-8")
            self.assertEqual(build_site.buy_links(Path(d), {"R004": 1}), {"R004": {"coupang": {"url": "https://link.coupang.com/a/x", "aff": True}}})
            Path(d, "buy_links.csv").write_text("product_id,store,url,affiliate\nR004,coupang,http://x,no\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_site.buy_links(Path(d), {"R004": 1})


    def test_official_sites_cover_every_brand(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_site
        with open(ROOT / "data" / "real" / "products.csv", encoding="utf-8") as f:
            brands = {r["brand"] for r in csv.DictReader(f)}
        off = build_site.official_sites(ROOT / "data" / "real", brands)
        self.assertEqual(set(off), brands)
        with tempfile.TemporaryDirectory() as d:
            Path(d, "brand_sites.csv").write_text("brand,market,url,search,kind\nCLIO,KR,https://x.kr,https://x.kr/s?k=,shop\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_site.official_sites(Path(d), {"CLIO"})


class TestSkincareSection(unittest.TestCase):
    def setUp(self):
        self.e = load_engine(ROOT / "data" / "real")

    def test_enough_skincare_products_in_every_country(self):
        from collections import Counter
        sk = [p for p in self.e.ds.products.values() if p.category_group == "skincare"]
        self.assertGreaterEqual(len(sk), 40)
        by = Counter(p.country_origin if p.country_origin in ("KR", "US", "JP", "CN") else "US" for p in sk)
        for m in ("KR", "US", "JP", "CN"):
            self.assertGreaterEqual(by[m], 7, m)

    def test_skincare_goals_only_rank_skincare(self):
        import json
        areas = {a["area"]: a.get("section", "makeup") for a in json.loads((ROOT / "data" / "beauty_goals.json").read_text("utf-8"))["areas"]}
        for g in self.e.ds.goals.values():
            recs = self.e.goal(g.goal_id, k=10)
            want_skin = areas[g.area] == "skincare"
            self.assertGreaterEqual(len(recs), 3 if want_skin else 2, g.goal_id)
            for r in recs:
                self.assertEqual(r.product.category_group == "skincare", want_skin, (g.goal_id, r.product.product_id))

    def test_new_skincare_products_have_sourced_signals(self):
        sig = {r["product_id"] for r in self.e.ds.signals}
        for pid, p in self.e.ds.products.items():
            if p.category_group == "skincare" and pid >= "C011" and pid[0] == "C" or pid in ("R030", "U027", "J026"):
                self.assertIn(pid, sig)


if __name__ == "__main__":
    unittest.main()
