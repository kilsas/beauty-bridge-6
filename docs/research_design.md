# Research Design

## Framing

**Case study (background, qualitative + financial):**
Why did Sephora's entry into South Korea (2019–2024) end in exit, while
CJ Olive Young built a dominant domestic position and is expanding abroad?

**Computational research question (tested):**
When a shopper looks for a substitute for a product from another market,
does adding market signals (price, local availability, local popularity) to
content-based similarity produce recommendations people are more willing to
buy?

The case study motivates the variables; the user study tests them. The
engine does **not** explain why Sephora failed. Two companies are two data
points; no statistical claim about market performance can be made from them.

## Hypotheses (as tested)

| | hypothesis | task | comparison |
|---|---|---|---|
| H1 | Weighted, attribute-level similarity matches human similarity judgments better than a one-hot cosine baseline. | `similar` | A vs A0 |
| H2 | Adding price to similarity improves purchase-intent ranking. | `would_buy` | B vs A |
| H3 | Adding local availability and popularity improves purchase-intent ranking further. | `would_buy` | C vs B |
| H4 (exploratory) | Explanations ("why this product") increase trust ratings. | post-task survey | with vs without explanation |

H2/H3 must be tested with the **`would_buy`** question. Asking "is this
similar?" cannot reward price or popularity, because those are not
similarity. This is why similarity and popularity are kept as separate
scores in the engine.

## Models

Defined in `beautybridge/config.py` → `FUSION_MODES`:

- **A0** cosine over one-hot/ordinal vectors (baseline)
- **A** weighted attribute similarity only
- **B** A + price advantage
- **C** B + local fit + local popularity

## Procedure

1. **Labeling reliability.** Two labelers independently label ≥30 products.
   Report per-attribute κ (`research/agreement.py`). Revise the guide for any
   κ < 0.6, relabel, report both rounds.
2. **Dataset.** 100–300 products, 3 markets (KR, US, JP). Every price and
   availability row has `observed_at` and `source`.
3. **Pools.** `research/make_study_kit.py kit` pools top-5 of every model plus
   random same-group items and shuffles them, so participants are blind to
   the model.
4. **Participants.** 20–50, recruited per market where possible. Record the
   market they shop in. Ethics: informed consent, no personal data beyond
   age band and market; check your school's requirements.
5. **Judgments.** Relevance 0–3 per (reference, candidate). ~8–12 reference
   products per participant keeps a session under 20 minutes.
6. **Analysis.** `research/evaluate_models.py` → P@5, R@5, NDCG@5, MAP,
   bootstrap 95% CI, paired randomization test on per-query NDCG.
   With ~10 queries and 4 models, report effect sizes and CIs, not only
   p-values, and correct for multiple comparisons (Holm).

## Threats to validity (put these in the paper)

- **Label subjectivity.** Mitigated by the codebook and κ.
- **Author-defined weights.** Similarity and goal weights are hypotheses.
  Report a sensitivity analysis (perturb each weight ±50%, check rank
  stability) and, with enough judgments, fit weights on half the queries and
  test on the other half.
- **Circularity.** Never tune weights on the same judgments you report.
  Synthetic judgments (`make_study_kit.py synthetic`) are generated from the
  model's own features and are for pipeline testing only.
- **Small sample.** A handful of queries gives wide intervals. Say so.
- **Market data freshness.** Prices change daily; results hold for the
  observation dates recorded.
- **Selection.** Products in the dataset are chosen by you; describe how.

## Market case study (Market Intelligence dashboard)

- Financials only from **primary sources**: DART (dart.fss.or.kr) audit
  reports of the Korean entities (e.g. 세포라코리아 유한회사, CJ올리브영),
  company IR pages. News articles can point you to a figure; cite the filing.
- Record `basis` (separate vs consolidated) — mixing them is a common error.
- `company_financials.csv` refuses rows without `source_url`.
- Keep facts (financials, dated events) separate from interpretation
  (your analysis of assortment, pricing, channels), and label any
  "market fit" score as a model output under stated assumptions, never as a
  historical finding.
