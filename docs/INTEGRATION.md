# Integration guide — from zero to a scheduled tracker

This guide assumes **no prior context**. Follow it top to bottom. Every step is a
command you run or a click you make.

---

## 1. Create an Apify account

1. Go to <https://console.apify.com/sign-up>.
2. Sign up (email or Google/GitHub). No credit card is required for the **Free** plan.
3. You are now on the Free plan, which includes **$5 of platform usage per month** (see
   [docs/COST.md](COST.md)). That is enough for dozens of runs at the default settings.

## 2. Get your API token

1. Open <https://console.apify.com/settings/integrations>.
2. Under **Personal API tokens**, copy your token. It looks like `apify_api_XXXXXXXX…`.
3. Keep it secret — treat it like a password. Never commit it to git.

## 3. Choose / confirm the actor

This tool calls one of two interchangeable Apify actors (both return the same fields):

| Actor id | Price | Notes |
|---|---|---|
| `kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest` | **$0.25 / 1,000 tweets** | **Default.** No free-tier per-run cap; cheapest. |
| `apidojo~tweet-scraper` | **$0.40 / 1,000 tweets** | Best-documented; **caps output at ~10 items/run on the Free plan**. |

The default (kaito) works on the Free plan out of the box. You do **not** need to
manually "add" the actor to your account — it is called by id via the API. If you want to
see it, open its store page (search the actor name on <https://apify.com/store>).

> To switch actors later, edit `apify.actor` **and** `apify.actor_price_per_tweet_usd`
> in `config.json`.

## 4. Install the tool

```bash
# Confirm Python 3.8+
python3 --version

# Get the code
git clone https://github.com/theopopov/x-viral-tracker.git
cd x-viral-tracker
```

There are **no dependencies to install**.

## 5. Set your token as an environment variable

Pick one:

```bash
# Option A — export directly (simplest for a one-off run)
export APIFY_TOKEN=apify_api_XXXXXXXX...

# Option B — use a .env file
cp .env.example .env
#   edit .env, put your token in, then load it:
set -a; source .env; set +a
```

The tool reads `APIFY_TOKEN` from the environment. (It does not auto-load `.env`; Option B
loads it into your shell manually.)

## 6. Configure your niche

```bash
cp config.example.json config.json
```

Open `config.json` and edit two things:

1. **`acquire.queries`** — the X/Twitter searches that define your topic. Use normal X
   search syntax (quotes for exact phrases, `OR`, parentheses). Examples:
   ```json
   "queries": [
     "\"open source alternative to\" (Notion OR Airtable)",
     "\"just open-sourced\" (agent OR MCP OR pipeline)",
     "\"Show HN\" (analytics OR CRM)"
   ]
   ```
2. **`relevance_gate.require_any_of.niche_terms`** — keywords that must appear in a post
   for it to pass the cheap pre-gate. Put your topic vocabulary here.

Optional at this stage: `minimum_favorites` (engagement floor), `freshness_days`
(look-back), `max_items` (cost cap). Every key is documented inline in the file.

> **Not tracking open-source repos?** Set
> `relevance_gate.require_any_of.has_github_link` to `false` so the GitHub-link shortcut
> is disabled and only your `niche_terms` decide relevance.

## 7. First test run (cheap)

Start small so your first call costs a fraction of a cent:

```bash
python3 tracker.py --max-items 25
```

You should see output like:
```
[acquire] 5 queries, since 2026-08-31, min_faves>=5, cap 25 items (<= $0.006) ...
[acquire] pulled 25 tweets (actual cost ~$0.006)
[gate] 18/25 passed relevance gate
[dedup] 16 unique drops, 0 already surfaced in prior runs -> 16 new
[done] 16 candidates -> out/candidates_<ts>.json
```

If you see **"No Apify token"**, revisit step 5. If you see an **Apify HTTP** error, the
message includes the reason (bad token, exhausted credit, or a bad actor id).

## 8. Interpret the output

Two files are written to `out/` per run:

- **`candidates_<ts>.md`** — a ranked table you can skim: score, top drivers, author tier,
  age, views, reposts, bookmarks, reach×, handle, text snippet.
- **`candidates_<ts>.json`** — the full record per post: the composite `score`, the raw
  `metrics`, the derived `signals`, `author_tier`, `repo_url`/`dedup_key`, any
  `brand_flags` (hype), and `other_source_urls` (collapsed duplicates).

Highest `score` = strongest viral signal *relative to this pull*. Read the top items and
decide which are genuinely on-topic — that final relevance judgement is yours (or hand the
JSON to an LLM and ask it to classify against your topic).

`out/last_raw.json` holds the raw pull, so you can re-score for free:

```bash
python3 tracker.py --dry-run   # no Apify charge
```

## 9. Schedule recurring runs

The tool is a plain script; schedule it with anything. Example with `cron` (daily at 9am):

```cron
0 9 * * *  cd /path/to/x-viral-tracker && APIFY_TOKEN=apify_api_XXXX python3 tracker.py >> out/cron.log 2>&1
```

Cost scales with cadence and `max_items` — see [docs/COST.md](COST.md). At the default
300-item cap and the kaito actor, a **daily** run costs well under the $5/month free
credit; an **hourly** run does not (you would need a paid plan or a much smaller cap).

> `seen.json` guarantees you never get the same post twice across scheduled runs.
> Optionally run `--calibrate` monthly to keep your virality baselines current.

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No Apify token.` | `APIFY_TOKEN` not set in the current shell. Re-do step 5. |
| `Apify HTTP 401` | Bad/rotated token. Copy a fresh one from the console. |
| `Apify HTTP 402` / credit errors | Free monthly credit exhausted. Wait for reset or upgrade. See COST.md. |
| `Apify HTTP 404` | Wrong `apify.actor` id. Check spelling (use `~`, not `/`). |
| Only ~10 items ever returned | You're on `apidojo` + Free plan (its cap). Switch to the kaito actor. |
| `[gate] 0/... passed relevance gate` | Your `niche_terms` don't match your queries' results. Widen terms or set `has_github_link:true`. |
| Same posts never re-appear even after config changes | Working as intended (`seen.json`). Delete it to reset. |
| Costs higher than expected | Lower `max_items`; raise `minimum_favorites`; use the kaito actor. |
