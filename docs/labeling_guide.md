# Labeling Guide (Codebook v0.1)

Every product in `products.csv` is described with the attributes below.
The algorithms can only be as good as these labels, so labeling is part of
the research method, not a chore before it.

**Rules that apply to everything**

1. Label from **evidence**, in this order: (a) the brand's own product page
   and packaging claims, (b) ingredient list, (c) swatches or reviews that
   several independent sources agree on. Record where you looked in `source`.
2. If you cannot find evidence, **leave the cell blank**. Blank is honest; a
   guess is noise. The engine skips blank attributes and lowers its
   confidence score instead of treating them as zero.
3. Write your initials in `labeled_by`. For the agreement study, two people
   label the same 30+ products **independently** (no discussion), then run
   `python research/agreement.py a.csv b.csv`. Any attribute with κ < 0.6
   needs a sharper definition here before the full dataset is labeled.
4. Never change a label because it makes a recommendation "look right".
   Change the definition in this guide, then relabel consistently.

---

## Identity

| column | meaning |
|---|---|
| `product_id` | Your own stable ID (`P001`…). Never reuse one. |
| `brand`, `name` | Official English name as sold. One shade = one product only if shades differ in finish/function; otherwise label the product line. |
| `name_ko` | Korean name as sold in Korea (for search). |
| `aliases` | Other names people search for, `|` separated (e.g. abbreviations). |
| `country_origin` | ISO code of the brand's home country: `KR`, `US`, `JP`, … |
| `url`, `source` | Where the evidence came from. |

## Category (`category`, required)

One value from: face base — `foundation`, `cushion`, `concealer`, `primer`,
`loose_powder`, `pressed_powder`, `setting_spray`; cheek — `blush`,
`highlighter`, `contour`; eye — `eyeshadow`, `eyeliner`, `brow`, `mascara`;
lip — `lip_tint`, `lipstick`, `lip_gloss`, `lip_balm`; skincare —
`cleanser`, `toner`, `serum`, `moisturizer`, `sunscreen`.

Decision rules: tinted moisturizers and skin tints are `foundation`. Liquid
lipsticks are `lipstick` with texture `liquid`. Tone-up creams sold as
sunscreen are `sunscreen`. Multi-use sticks: the category the brand leads with.

## Finish (`finish`) — ordinal

| value | definition | test |
|---|---|---|
| `matte` | no visible shine at all | flat under direct light |
| `soft_matte` | velvety, slight diffuse sheen | "blurred" but not chalky |
| `satin` | natural skin-like sheen (a.k.a. natural) | looks like bare healthy skin |
| `dewy` | visibly moist, luminous | shine on the high points |
| `glossy` | wet-look, reflective | mirror-like reflection |

Skincare: label the after-feel on skin (e.g. a sticky-glow serum is `dewy`).

## Coverage (`coverage`) — ordinal, colored products only

`sheer` (skin fully visible) · `light` (evens tone, freckles show) ·
`medium` (hides redness, most spots) · `full` (hides nearly everything).
Leave blank for skincare without tint and for clear products.

## Texture (`texture`)

`loose_powder`, `pressed_powder`, `liquid`, `cream`, `gel`, `balm`, `stick`,
`cushion`, `water`, `oil`, `mousse`. Label the product as it comes out of the
package.

## Undertone (`undertone`) and shade family (`shade_family`)

`undertone`: `cool`, `neutral`, `warm` — only if the brand states it or it is
visually unambiguous; otherwise blank.
`shade_family` (colored cheek/eye/lip products): `nude`, `rose`, `pink`,
`coral`, `red`, `berry`, `brown`, `champagne`, `gold`, `clear`.

## Functional intensities — integer 0–3

For each of `oil_control`, `hydration`, `blurring`, `shimmer`,
`brightening`, `glow`, `longevity`:

| level | meaning | typical evidence |
|---|---|---|
| 0 | none / not claimed | no mention, and nothing in reviews |
| 1 | slight / secondary | mentioned once, or minor ingredient support |
| 2 | clear | a stated benefit, confirmed by reviews |
| 3 | primary purpose | the product's headline claim |

Definitions:
- `oil_control`: absorbs or prevents sebum shine.
- `hydration`: adds moisture; skin feels less tight.
- `blurring`: visually softens pores and fine texture (soft-focus).
- `shimmer`: visible reflective particles. 2 = fine pearl, 3 = obvious glitter.
- `brightening`: makes the area look lighter/brighter (tone-up, highlight).
- `glow`: overall luminous sheen without distinct particles.
- `longevity`: wear time claims (3 = "24h", "transfer-proof", confirmed).

## Skin types (`skin_types`)

`|` separated from `oily`, `dry`, `combination`, `normal`, `sensitive`, or
`all`. Only what the brand recommends or reviews consistently support.

## Price (`price`, `currency`)

Regular (non-sale) price in the home market, in local currency, on the date
you record in `notes`. Currency codes must exist in `config.FX_TO_USD`.
Note package size in `notes`; if sizes differ a lot within a category,
consider adding a price-per-gram column (planned for v0.2).
