"""
Search: typo-tolerant product lookup, plus a small rule-based query
processor that turns "cheap Korean powder like Bake Set" into a structured
request (intent + filters + product reference).

Uses rapidfuzz when installed, otherwise the standard library's difflib.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import codebook as cb
from .goals import BeautyGoal
from .product import Product

try:  # optional speed-up, same results within a few points
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover
    _rf_fuzz = None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ratio(a: str, b: str) -> float:
    if _rf_fuzz is not None:
        return _rf_fuzz.ratio(a, b) / 100
    return SequenceMatcher(None, a, b).ratio()


def _token_match(q: str, t: str) -> float:
    """Best fuzzy match of one query token against the tokens of a text."""
    return max((_ratio(q, tok) for tok in t.split()), default=0.0)


@dataclass(frozen=True)
class SearchHit:
    product_id: str
    score: float
    matched: str

    def to_dict(self) -> dict:
        return {"product_id": self.product_id, "score": round(self.score, 3), "matched": self.matched}


class ProductIndex:
    def __init__(self, products: dict[str, Product]):
        self.products = products
        self._texts: dict[str, list[str]] = {}
        for p in products.values():
            texts = [p.display_name, p.name, p.name_ko, *p.aliases, f"{p.brand} {p.name_ko}"]
            self._texts[p.product_id] = [normalize(t) for t in texts if t]

    def search(self, query: str, k: int = 10, min_score: float = 0.55,
               category: str | None = None, origin: str | None = None) -> list[SearchHit]:
        q = normalize(query)
        if not q:
            return []
        q_tokens = q.split()
        hits: list[SearchHit] = []
        for pid, texts in self._texts.items():
            p = self.products[pid]
            if category and p.category != category:
                continue
            if origin and p.country_origin != origin:
                continue
            best, best_text = 0.0, ""
            for t in texts:
                if q == t:
                    s = 1.0
                elif q in t:
                    s = 0.9 + 0.1 * len(q) / len(t)
                else:
                    # each query token looks for its closest partner; the mean
                    # rewards matching everything, the max tolerates one noisy word
                    per_token = [_token_match(tok, t) for tok in q_tokens]
                    token_score = 0.6 * sum(per_token) / len(per_token) + 0.4 * max(per_token)
                    s = 0.85 * max(token_score, _ratio(q, t))
                if s > best:
                    best, best_text = s, t
            if best >= min_score:
                hits.append(SearchHit(pid, best, best_text))
        hits.sort(key=lambda h: (-h.score, h.product_id))
        return hits[:k]


# ---------------------------------------------------------------------------
# Query processor
# ---------------------------------------------------------------------------
INTENT_WORDS = {
    "cheaper": ["cheap", "cheaper", "affordable", "budget", "dupe", "저렴", "싼", "싸게", "가성비", "대체", "平替", "便宜", "安い", "プチプラ"],
    "similar": ["similar", "like", "alternative", "비슷", "유사", "같은", "相似", "类似", "似ている", "似た"],
}
ORIGIN_WORDS = {
    "KR": ["korean", "korea", "k beauty", "kbeauty", "한국", "국산", "k뷰티", "韩国", "韓国"],
    "US": ["american", "us brand", "미국", "美国", "アメリカ"],
    "JP": ["japanese", "japan", "일본", "日本製"],
    "CN": ["chinese", "china", "c beauty", "중국", "中国", "国货"],
}
MARKET_WORDS = {
    "KR": ["in korea", "한국에서"],
    "US": ["in the us", "in us", "in america", "미국에서"],
    "JP": ["in japan", "일본에서", "日本で"],
    "CN": ["in china", "중국에서", "在中国"],
}
CATEGORY_WORDS = {
    "loose_powder": ["loose powder", "루스 파우더", "루스파우더", "파우더", "powder", "散粉", "パウダー"],
    "pressed_powder": ["pressed powder", "팩트", "프레스드", "粉饼"],
    "foundation": ["foundation", "파운데이션", "파데", "粉底", "ファンデーション"],
    "cushion": ["cushion", "쿠션", "气垫", "クッション"],
    "concealer": ["concealer", "컨실러", "遮瑕", "コンシーラー"],
    "primer": ["primer", "프라이머", "妆前", "下地"],
    "setting_spray": ["setting spray", "픽서", "세팅 스프레이"],
    "blush": ["blush", "블러셔", "치크", "腮红", "チーク"],
    "highlighter": ["highlighter", "하이라이터", "高光", "ハイライト"],
    "eyeshadow": ["eyeshadow", "shadow", "섀도우", "아이섀도", "眼影", "アイシャドウ"],
    "lip_tint": ["tint", "틴트", "唇釉", "ティント"],
    "lipstick": ["lipstick", "립스틱", "口红", "リップスティック"],
    "lip_gloss": ["gloss", "글로스", "글로즈", "唇彩", "グロス"],
    "lip_balm": ["lip balm", "립밤", "润唇膏", "リップバーム"],
    "lip_liner": ["lip liner", "lip pencil", "립펜슬", "립 라이너", "唇线笔", "リップライナー"],
    "lip_plumper": ["lip plumper", "maximizer", "맥시마이저", "립 플럼퍼", "丰唇", "リッププランパー"],
    "mascara": ["mascara", "마스카라", "睫毛膏", "マスカラ"],
    "eyeliner": ["eyeliner", "아이라이너", "眼线", "アイライナー"],
    "brow": ["brow", "eyebrow", "아이브로우", "눈썹", "眉笔", "アイブロウ"],
    "contour": ["contour", "shading", "쉐딩", "셰딩", "修容", "シェーディング"],
    "bronzer": ["bronzer", "브론저", "古铜", "ブロンザー"],
    "toner": ["toner", "토너", "스킨", "化妆水", "化粧水"],
    "serum": ["serum", "세럼", "에센스", "精华", "美容液"],
    "moisturizer": ["moisturizer", "cream", "크림", "수분크림"],
    "sunscreen": ["sunscreen", "spf", "선크림", "선블록", "防晒", "日焼け止め"],
}
STOP_WORDS = {"a", "an", "the", "to", "for", "something", "product", "제품", "추천", "for my", "me", "i", "want"}


@dataclass
class ParsedQuery:
    raw: str
    intent: str = "search"            # search | similar | cheaper | goal
    goal_id: str | None = None
    category: str | None = None
    origin: str | None = None
    market: str | None = None
    product_text: str = ""
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]")


def _consume(text: str, phrase: str) -> tuple[bool, str]:
    """Remove a phrase from the text. Korean/Japanese phrases may carry a
    suffix (저렴한, 파우더를); Latin phrases must match whole words."""
    p = normalize(phrase)
    if not p:
        return False, text
    if _CJK.search(p):
        pattern = rf"{re.escape(p)}\w*"
    else:
        pattern = rf"(?<!\w){re.escape(p)}(?!\w)"
    new, n = re.subn(pattern, " ", text)
    return n > 0, new


def parse_query(query: str, goals: dict[str, BeautyGoal]) -> ParsedQuery:
    pq = ParsedQuery(raw=query)
    text = f" {normalize(query)} "

    for gid, g in goals.items():
        for phrase in {g.name, g.name_ko, gid.replace("_", " "), *g.aliases}:
            if not phrase:
                continue
            hit, text = _consume(text, phrase)
            if hit:
                pq.goal_id = gid
                pq.matched_terms.append(phrase)

    for market, phrases in MARKET_WORDS.items():
        for ph in phrases:
            hit, text = _consume(text, ph)
            if hit:
                pq.market = market
                pq.matched_terms.append(ph)

    for origin, phrases in ORIGIN_WORDS.items():
        for ph in phrases:
            hit, text = _consume(text, ph)
            if hit:
                pq.origin = origin
                pq.matched_terms.append(ph)

    for intent in ("cheaper", "similar"):
        for ph in INTENT_WORDS[intent]:
            hit, text = _consume(text, ph)
            if hit:
                if pq.intent == "search" or intent == "cheaper":
                    pq.intent = intent
                pq.matched_terms.append(ph)

    # longest phrases first so "loose powder" beats "powder"
    phrase_to_cat = sorted(
        ((ph, cat) for cat, phs in CATEGORY_WORDS.items() for ph in phs),
        key=lambda t: -len(t[0]),
    )
    for ph, cat in phrase_to_cat:
        hit, text = _consume(text, ph)
        if hit and pq.category is None:
            pq.category = cat
            pq.matched_terms.append(ph)

    leftover = [t for t in text.split() if t not in STOP_WORDS]
    pq.product_text = " ".join(leftover)
    if pq.goal_id and pq.intent == "search":
        pq.intent = "goal"
    return pq


assert set(CATEGORY_WORDS) <= set(cb.CATEGORIES)
