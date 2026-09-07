# Cost analysis

The **only** cost of running this tool is the Apify actor call. There is no LLM/inference
cost (the tool does no classification), no server, and no storage cost beyond local files.

> **Verification status.** Figures marked ✅ were verified against Apify's live actor
> pages and pricing docs in **September 2026**. Figures marked ⚠️ are **estimates** derived
> from the cost *formula* and stated assumptions — actual spend depends on how many results
> your queries return. Prices change; re-check the actor page before relying on a number.

## 1. Pricing model in play

The actors this tool uses are **pay-per-result** (per tweet returned), **not**
compute-unit priced. Proxy costs are **included** in the per-result price — there is no
separate residential-proxy charge. ✅

| Actor (id) | Price per tweet | Per 1,000 tweets | Verified |
|---|---|---|---|
| `kaitoeasyapi~…-cheapest` (**default**) | $0.00025 | **$0.25** (advertises ~$0.18 at volume) | ✅ |
| `apidojo~tweet-scraper` (alternative) | $0.0004 | **$0.40** | ✅ |

**Apify Free plan:** **$5 of platform usage per month**, no credit card. When the credit is
exhausted you are **blocked until the next monthly cycle**; unused credit does **not** roll
over. Paid plans (as of Sept 2026): **$29 / $199 / $999 per month** of prepaid usage. ✅

## 2. The cost formula (exact)

```
cost_per_run  =  tweets_returned  ×  actor_price_per_tweet_usd
tweets_returned  ≤  max_items          (the actor stops at the cap)
```

Two things keep `tweets_returned` — and therefore cost — down:

- **`minimum_favorites`** is applied **server-side**, so posts below your like floor are
  never returned and never billed.
- **`max_items`** is a hard ceiling: `cost_per_run ≤ max_items × price`.

So the **worst-case (ceiling) cost per run is `max_items × price`**; actual cost is usually
lower because not every query fills the cap.

## 3. Cost per run at three configurations ⚠️ (ceiling = `max_items × price`)

| Config | `max_items` | kaito ($0.00025) | apidojo ($0.0004) |
|---|---|---|---|
| Small | 100 | ≤ **$0.025** | ≤ **$0.040** |
| Medium (**default**) | 300 | ≤ **$0.075** | ≤ **$0.120** |
| Large | 1,000 | ≤ **$0.250** | ≤ **$0.400** |

*Assumption:* each run returns up to the cap. A run that returns fewer tweets costs
proportionally less. The `[acquire]` log line prints both the ceiling estimate and the
actual charge after the pull.

## 4. Monthly cost by cadence ⚠️ (default 300-item cap)

Runs/month: weekly ≈ 4.3, daily = 30, hourly = 720.

| Cadence | Runs/mo | kaito ceiling | apidojo ceiling | Fits $5 free credit? |
|---|---|---|---|---|
| Weekly | ~4.3 | ~$0.32 | ~$0.52 | ✅ easily |
| Daily | 30 | ~$2.25 | ~$3.60 | ✅ yes (both) |
| Hourly | 720 | ~$54 | ~$86 | ❌ needs a paid plan or a much smaller cap |

*Assumption:* every run hits the 300-item ceiling. Real usage is typically lower, so these
are upper bounds.

## 5. What drives cost most (in order)

1. **`max_items`** — linear. Halving it halves the ceiling. The single biggest lever.
2. **Cadence** — linear in runs/month (see §4).
3. **Actor choice** — apidojo costs **1.6×** kaito for identical output.
4. **`minimum_favorites`** — higher floor → fewer results returned → lower actual cost.
5. **`freshness_days`** and **number of queries** — wider window / more queries return more
   results (up to the `max_items` cap), so they raise *actual* cost toward the ceiling but
   never above it.

### How to reduce cost
- Lower `max_items` (start at 100–150).
- Use the **kaito** actor (the default).
- Raise `minimum_favorites` so dead posts are filtered server-side.
- Run **daily or weekly**, not hourly.
- Use `--dry-run` to re-score the last pull for **free** while you tune weights.

## 6. Free-tier coverage & where you exceed it

- **$5/month** covers, at the default 300-item cap: **~66 kaito runs/mo** or **~41 apidojo
  runs/mo** at the ceiling (more in practice). ⚠️
- **Daily** runs fit comfortably within the free credit. **Hourly** runs do not — you would
  exhaust $5 in roughly 2–3 days (kaito, 300-cap) and be blocked until the monthly reset.
- To stay free while running more often: cut `max_items` (e.g. hourly at `max_items=25`
  ≈ 720 × $0.006 ≈ **$4.3/mo** ⚠️, just under the credit).

> Compared to the official X API (2026 pay-per-use ≈ $0.005 per post read), a pay-per-result
> Apify actor at $0.00025–$0.0004 per tweet is roughly **12–20× cheaper** at realistic
> volumes. ✅ (X API pricing verified Sept 2026; treat as context, not a tool dependency.)
