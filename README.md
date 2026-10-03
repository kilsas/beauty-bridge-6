# Beauty Bridge

**Explainable cross-market beauty product recommendation.**
Find a similar product from another country, a cheaper one, or the best
product for a beauty goal (애교살, glass skin, pore blurring…), and see
exactly *why* each product was recommended.

> Working title. The originally planned name, GlowPick, belongs to an
> existing Korean beauty review app (글로우픽), so it was not used.
> Rename freely: only this README and the API title mention the name.

```
query ─► product identification ─► candidate pool (category gate)
      ─► similarity  /  goal fit          content, market-independent
      ─► price · local fit · popularity   market-dependent, optional
      ─► rank fusion (mode weights) ─► "why this product?" explanation
```

Similarity and popularity are computed and reported **separately**; they
are combined only in rank fusion, with the weights shown in every result.

---

## Quick start (no installation needed)

Python 3.10+ only; the core uses the standard library.

```bash
python -m beautybridge similar P001 --origin KR     # Korean alternatives to a US powder
python -m beautybridge cheaper P001 --market US     # similar AND cheaper, as sold in the US
python -m beautybridge goal aegyo_sal --market KR   # best products for 애교살
python -m beautybridge goals                        # list all beauty goals
python -m beautybridge trending KR                  # chart with rising / falling / new
python -m beautybridge ask "cheap korean powder like bake set"
python -m beautybridge ask "애굣살 추천 일본에서"
python -m unittest discover tests                   # 38 tests
```

Example output:

```
 1. Dalbit Baking Tone-up Loose Powder  [P008, loose_powder, KR]
    final 0.953  |  similarity 0.95  price 1.00  |  $15.11  save $22.89
    95% match
      category     ████████████ 20.0/20.0 same category (loose_powder)
      function     ███████████· 22.9/25.0 shares oil_control, blurring, brightening, longevity
      finish       ████████████ 20.0/20.0 both matte
      texture      ████████████ 15.0/15.0 both loose_powder
      ...
```

Add `--json` to any command for machine-readable output, `--data <folder or .sqlite>` to use your own data.

## Website

`web/index.html` is the full site, a mobile-first shopping-app layout in Korean,
English, Chinese and Japanese, covering Korea, the USA, Japan and China: home with natural-language search,
product pages (similar, cheaper twins, price comparison across markets,
goal fit), beauty goals with skin-type filter, weekly trends, local picks
per country, **Market Intelligence** (Sephora Korea vs Olive Young, every
figure linked to its source) and a method page. Rankings come in five views
(rising, category with a bottom-sheet picker, skin type, goal, brand), with
medal cards for the top three and week-on-week rank changes. Product images
are drawn package illustrations, since the demo products are fictional.

- **Open it**: double-click `web/index.html`. No server or install needed.
- **Rebuild** after changing data or weights: `python scripts/build_site.py`
- **Serve with the API**: `uvicorn beautybridge.api:app` → http://127.0.0.1:8000/
- **Publish**: upload `web/index.html` to GitHub Pages, Netlify or Vercel.

It has no framework on purpose: the build step runs the real Python engine
and embeds its output, so the site always matches the algorithms and needs
no backend to host. A Next.js frontend can call the same API later.

### Beauty goals

26 goals in four areas, each ranked within the product types that make sense:

| area | goals |
|---|---|
| Skin | glass skin, matte, natural base, full coverage, pore blurring, dark circles, long-lasting base, dewy, oily-skin care |
| Eyes | lashes, eyeliner, everyday eyeshadow, brows, aegyo-sal |
| Lips | lipstick, tint, lip maximizer, lip pencil, gloss, lip balm, MLBB, long-lasting |
| Contour | blush, shading, highlighter, bronzer |

Definitions live in `data/beauty_goals.json`; translations in `web/i18n.js`.

## Real data: prices, ratings and reviews

Nothing in the demo build is live. To make it real:

1. **Products**: label real products in `data/real/products.csv` (see the labeling guide).
2. **Feeds**: put CSV snapshots from sources that allow reuse (affiliate or
   partner feeds, official APIs you hold keys for, your own observations) in
   `data/feeds/`, then run `python scripts/refresh_data.py --data data/real`.
   It validates every row, keeps the full price history, updates the latest
   price/rating/review count per market, and rebuilds the database and site.
3. **Schedule**: `.github/workflows/refresh.yml` runs the refresh every day
   at 03:00 KST and republishes the site on GitHub Pages.

Scraping Olive Young, Sephora, Amazon and similar retailers is deliberately
not included: their terms forbid it.

## Product photos

Add licensed photos as `web/images/<product_id>.jpg|png|webp` and register
them in `data/images.csv` (credit, license, source URL). The build embeds them;
products without a photo show a drawn package illustration, labeled as such.
Brand and retailer product photos are copyrighted: use press-kit images under
their terms, images delivered with an affiliate feed, or your own photos.

## Country market rankings

"Market" rankings show, for Korea, the USA, Japan and China, the products
that published sources name as winners or best sellers in that country:
Olive Young Awards 2025 (KR), @cosme Best Cosmetics Awards 2025 (JP), Allure
Readers' Choice 2025 and Circana's 2024 sales data (US), and Tmall's 2025
makeup rankings (CN). Every row in `data/real/market_signals.csv` has a
source URL and date; `beautybridge.market.signal_strength` turns rank and
kind (product award, sales launch, brand-level) into a 0-1 strength, which
also feeds the popularity term when you shop in that country.
API: `GET /market/leaders/{market}?category=`.

## Prices and currency

The site shows every price in the currency of the chosen language: 한국어 →
KRW, English → USD, 日本語 → JPY, 中文 → CNY. Converted prices carry "≈";
the price table also keeps each original local price. Rates are in
`beautybridge/config.py` (`FX_TO_USD`, read from Investing.com on
2026-09-30); update them and their note before analysis.

## Publishing publicly

`docs/deploy.md` (Korean) walks through GitHub Pages plus a review store.
`.github/workflows/pages.yml` rebuilds and deploys the site on every push.
The site picks its review storage automatically:

1. inside claude.ai: the artifact's own shared database;
2. otherwise Supabase, when `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set
   (anonymous sign-in, row-level security in `supabase/setup.sql`, realtime);
3. otherwise your own API server, when `REVIEWS_API_URL` is set
   (`GET /reviews` returns one-way reviewer keys, never raw ids).

With none configured, everything except posting reviews still works.

## Live reviews (how rankings work now)

Rankings are built from reviews posted on the site itself, the same model a
review app uses. Each review has a 1-5 rating plus the reviewer's skin type,
age band and the country they bought in, so rankings can be cut by skin type
and age. Scores use a Bayesian average (`beautybridge/reviews.py`; the site
computes the identical formula in JavaScript). "Rising" means the most new
reviews in the last 7 days compared with the 7 days before.

- On claude.ai the published page stores reviews in the artifact's shared
  database: everyone reads all reviews, each person can only write their own.
  People need Contributor access to the page to post.
- Self-hosted, the API does the same: `POST /reviews`,
  `GET /products/{id}/reviews`, `GET /rankings/reviews?category=&skin_type=&age_band=`,
  `GET /rankings/rising` (SQLite at `db/reviews.sqlite`).
- Until a segment has reviews, its ranking falls back to goal fit and says so.

## Buy buttons and purchase-intent ranking
Each product page links to official shops in the chosen country (`data/stores.json`:
Olive Young and Coupang in Korea, Amazon, Sephora and Ulta in the US, Rakuten and
Amazon Japan, Tmall and JD in China). Clicks are stored (Supabase `buy_clicks`, run
`supabase/buy_clicks.sql`; or the API's `POST /clicks`) and the **Most bought** ranking
counts distinct people per product. Swap in affiliate links per store (`append`,
`affiliate`) or per product (`data/real/buy_links.csv`); the page then shows a disclosure.

## ⚠️ Which data is real

- `data/real/`: **real products** (92, from Korea, the USA, Japan, China and
  France). Names and brands are real; attribute labels, reference prices and
  country availability were added by Claude from general knowledge and are
  marked unverified. No ratings or review counts are invented for them. The
  website and API use this folder by default.
- `data/demo/`: **fictional.** 90 invented products (7 brands, one of them Chinese) (brands like "Halo
  Studio", "Mulberry Seoul") and synthetic market, ranking and judgment data,
  so every feature can run. Never cite a number produced from it.
- `data/market/`: **real, sourced.** Sephora Korea and Olive Young
  financials, events and facts, each row linked to a dated press report.
  Confirm against DART filings before citing; Sephora Korea revenue is left
  blank because press reports conflict.

## HTTP API

```bash
pip install -r requirements-api.txt
uvicorn beautybridge.api:app --reload          # docs at http://127.0.0.1:8000/docs
BEAUTYBRIDGE_DATA=data/real uvicorn beautybridge.api:app   # your data
```

| endpoint | purpose |
|---|---|
| `GET /products/search?q=` | typo-tolerant search (English/Korean) + parsed intent |
| `GET /products/{id}` | product with market listings |
| `GET /recommendations/similar/{id}?market=&origin=&mode=&method=` | similar products |
| `GET /recommendations/cheaper/{id}?market=&min_similarity=` | similar but cheaper |
| `GET /goals`, `GET /recommendations/goal/{goal_id}?market=&skin_type=` | beauty goals |
| `GET /trending/{market}` | ranking chart with trend status |
| `GET /ask?q=` | natural-language entry point |
| `GET /market/financials`, `GET /market/events` | case-study data (sourced) |
| `GET /` | the website |
| `GET /config` | all weights, for transparency |

## Using real data

1. `cp -r data/templates data/real`
2. Label products in `data/real/products.csv` following
   **[docs/labeling_guide.md](docs/labeling_guide.md)**. Blank = unknown.
3. `python -m beautybridge validate data/real` — lists every problem at once.
4. `python -m beautybridge build-db data/real --db db/real.sqlite`
5. `python -m beautybridge --data db/real.sqlite similar P001`

Optional files in the same folder: `market_products.csv`, `rankings.csv`,
`price_observations.csv`, `company_financials.csv` (requires `source_url`
on every row: use DART filings), `company_events.csv`, `judgments.csv`.

**PostgreSQL:** `db/schema.sql` is portable. After step 4:
`python scripts/sqlite_to_postgres.py db/real.sqlite > db/pg_load.sql` then
`psql "$DATABASE_URL" -f db/pg_load.sql`.

## Research toolkit

See **[docs/research_design.md](docs/research_design.md)** for hypotheses,
procedure and threats to validity.

| script | does |
|---|---|
| `research/agreement.py a.csv b.csv` | inter-labeler agreement per attribute (Cohen's κ, weighted κ) |
| `research/make_study_kit.py kit --queries P001 P009 …` | blind, shuffled candidate pools + answer sheet for participants |
| `research/evaluate_models.py judgments.csv --task would_buy --market US` | P@k, R@k, NDCG@k, MAP, bootstrap CI, paired randomization test for models A0/A/B/C |
| `research/sensitivity.py` | how much rankings change when each weight moves ±50% |
| `research/make_study_kit.py synthetic` | fake judgments for **pipeline testing only** |

## How the scores work

**Similarity** (`beautybridge/similarity.py`): weighted sum of per-attribute
similarities — category 20%, function 25%, finish 20%, texture 15%, skin
type 10%, coverage 5%, price 5% (`config.py`).
- Ordinal attributes (finish, coverage): `1 − |a − b|` on a 0–1 scale.
- Function: mean agreement over the 7 intensity features that at least one
  product has (shared absences don't count as similarity).
- Skin types: Jaccard. Price: log-ratio, 0 at 4× difference.
- Missing labels are **skipped and weights renormalized**; `evidence` reports
  how much weight could be evaluated, and results under 60% are flagged.
- Category gate: products in non-substitutable categories are never "similar".

**Goal fit** (`goals.py`, `data/beauty_goals.json`): closeness to a target
profile per goal, only for eligible categories. The profiles are the
author's hypotheses and are meant to be validated in the user study.

**Rank fusion** (`engine.py`): mode-specific weights over similarity/goal,
price advantage, local fit and popularity; components that are unavailable
(e.g. no market chosen) are dropped and the rest renormalized.

## Project layout

```
beautybridge/   engine: codebook, product parsing, db, similarity, goals,
                market (popularity, trends, local fit), search, engine, api, cli
data/           beauty_goals.json, templates/ (empty CSVs), demo/ (fictional),
                market/ (real, sourced case-study data)
db/             schema.sql (SQLite + PostgreSQL)
docs/           labeling_guide.md, research_design.md
research/       metrics, agreement, study kit, evaluation, sensitivity
scripts/        demo data generation, website build, PostgreSQL export
web/            template.html (source) and index.html (built website)
tests/          unit tests
```

## Roadmap

- [x] Phase 1 — schema, codebook, validation, demo data
- [x] Phase 2 — search (typo-tolerant, Korean), product detail
- [x] Phase 3 — explainable similarity, cheaper alternatives
- [x] Phase 4 — beauty goals
- [x] Phase 5 — rankings + trend detection (engine; needs real chart data)
- [ ] Label 100–300 real products, run agreement study
- [x] Website: all sections, served standalone or by the API
- [x] Market intelligence with press-sourced figures
- [ ] Replace press figures with DART audit-report figures
- [ ] Next.js frontend on top of the API (optional)
- [ ] User study → evaluation → paper
