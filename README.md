# x-viral-tracker

Find viral, **on-topic** X/Twitter posts for a niche you choose, rank them by a
configurable virality model, and never surface the same post twice — using
[Apify](https://apify.com)'s official Twitter/X scraper actors and your own API token.

The tool does only the cheap, deterministic work: **acquire → score → gate →
suppress → dedup → emit**. It writes a ranked `candidates_<timestamp>.json` (and a
human-readable `.md` table). Deciding which surfaced posts are *genuinely* relevant,
and what to do with them, is left to you (or an LLM you point at the JSON) — so the
tool itself has **no model API key and no inference bill**.

```
  Apify pull ─► virality score ─► relevance gate ─► suppress-flag ─► dedup ledger ─► candidates_<ts>.{json,md}
```

- **No third-party dependencies.** Python 3.8+ standard library only.
- **One external cost: Apify.** Roughly `items_returned × actor_price_per_tweet`. See [docs/COST.md](docs/COST.md).
- **Bring your own niche.** Every keyword, query, threshold, and weight is in `config.json`.
- **Compliant by construction.** Reads only public data through Apify's official actors; see [Compliance](#compliance).

---

## How it works

Per run, the tool:

1. **Acquires** tweets from Apify. Each configured search query gets the operators
   `lang:<language> since:<date> min_faves:<minimum_favorites>` appended, so filtering
   happens **server-side** — you don't pay for posts below your engagement floor.
2. **Scores virality.** For each post it computes, from real returned fields:
   - **reach_ratio** = views ÷ author_followers — outperforming one's own distribution.
   - **engagement_rate** = (likes+reposts+replies+quotes) ÷ views.
   - **velocity** = engagement ÷ hours-since-posting — surfaces posts still climbing.
   - **reply_like_ratio** (discussion) and **quote_repost_ratio** (commentary vs passive amplification).
   - **bookmark_rate** = bookmarks ÷ views — a strong "this is useful" signal.
   - **author_tier** — a follower band, for annotation (small accounts are rewarded via reach_ratio, never penalized).

   The **composite score** = a weighted sum of each signal *normalized to the pull's
   median* (ratio-to-median, capped), × an **age-decay** factor (default half-life 36h).
   Weights, cap, decay, and bands all live in `config.json → virality`.
3. **Relevance gate.** Keeps a post if it contains a `github.com` link (when
   `has_github_link` is on) **or** any of your `niche_terms`.
4. **Suppress-flag.** Posts using hype language (`suppress_terms`) are *flagged and
   score-penalized* (not deleted) so you still see them.
5. **Dedup.** A post's key is its GitHub `owner/repo` if present, else its tweet URL.
   Within a run, duplicate keys collapse (extras listed as `other_source_urls`); across
   runs, any key already in `seen.json` is dropped — **the same post never re-surfaces**.
6. **Emits** the survivors, ranked, to `out/candidates_<ts>.json` + `.md`.

> **The numeric layer is a recall shortlist, not a precision filter.** It ranks by
> virality; it does not *understand* your topic. Expect to make the final relevance
> cut yourself (or with an LLM). This is by design — it keeps the tool free to run.

## Prerequisites

- **Python 3.8+** (check with `python3 --version`). No packages to install.
- **An Apify account** and **API token** (free plan works — see below).
- Basic command-line familiarity.

## Install

```bash
git clone https://github.com/theopopov/x-viral-tracker.git
cd x-viral-tracker
cp config.example.json config.json      # your editable config
export APIFY_TOKEN=your_apify_token      # or: cp .env.example .env && edit && set -a; source .env; set +a
```

There is nothing to `pip install`.

## Quickstart

```bash
# 1. Edit config.json: put YOUR niche in acquire.queries and relevance_gate.niche_terms.
# 2. Do a cheap first run with a small cap:
python3 tracker.py --max-items 25

# 3. Read the newest output:
#    out/candidates_<timestamp>.json   (full records)
#    out/candidates_<timestamp>.md     (human table)
```

New here? Follow the numbered, zero-context walkthrough in **[docs/INTEGRATION.md](docs/INTEGRATION.md)**.

## Commands

```bash
python3 tracker.py                 # normal run  → out/candidates_<ts>.{json,md}
python3 tracker.py --max-items 150 # override the per-run item cap (cost cap) for this run
python3 tracker.py --calibrate     # bigger pull; freezes niche baselines into config.json
python3 tracker.py --dry-run       # re-score the last raw pull for free (no Apify charge)
python3 tracker.py --config PATH   # use an alternate config file
```

## Configuration reference

All configuration lives in `config.json` (copy from `config.example.json`). Every key
is documented inline in that file. Summary:

| Section | Key | What it does |
|---|---|---|
| `apify` | `actor` | Apify actor id. Default `kaitoeasyapi~…-cheapest`; alt `apidojo~tweet-scraper`. Both return the same schema. |
| | `actor_price_per_tweet_usd` | Used only for the printed cost estimate. Set to match your actor. |
| | `token_env` | Env var the token is read from (default `APIFY_TOKEN`). |
| `acquire` | `queries` | **Your niche.** X search strings. `lang/since/min_faves` are appended automatically. |
| | `sort` | `Top` or `Latest`. |
| | `language` | Two-letter lang filter (e.g. `en`). |
| | `freshness_days` | Look-back window. |
| | `minimum_favorites` | Server-side like floor — you don't pay for posts below it. |
| | `max_items` | Per-run item cap = **cost ceiling**. |
| `relevance_gate` | `require_any_of.has_github_link` | Keep any post with a `github.com` link. Toggle off for non-OSS niches. |
| | `require_any_of.niche_terms` | **Your keywords.** Substring OR-list. |
| `suppress_terms` / `suppress_penalty` | | Hype phrases to flag; score multiplier applied to flagged posts. |
| `virality.weights` | | Relative weight of each signal in the composite score. |
| `virality.normalization_cap` | | Caps how far one signal can dominate. |
| `virality.age_decay_half_life_hours` | | How fast old posts fade. |
| `virality.reply_like_pivot` | | Reply/like ratio treated as "discussion-heavy". |
| `virality.author_tier_bands` | | Follower bands for the `author_tier` label. |
| `baseline` | | Calibrated niche medians (see `--calibrate`); `calibrated:false` self-normalizes each pull. |
| `output` | `top_n` | `0` = emit every unique drop; `N` = cap per run. |
| | `dir`, `seen_ledger`, `profile` | Output folder, dedup-ledger filename, output label. |

### Tuning guide

| Symptom | Turn this |
|---|---|
| Too noisy / off-topic | Tighten `acquire.queries` (name specific terms); raise `minimum_favorites`; raise `weights.reach_ratio`/`bookmark_rate`. |
| Too sparse | Add broad catch-all queries; lower `minimum_favorites`; raise `max_items`; widen `freshness_days`. |
| Stale posts dominating | Lower `age_decay_half_life_hours`. |
| Big accounts crowding out smaller makers | Raise `weights.reach_ratio`; lower `weights.spread`/`engagement_rate`. |
| Hype slipping through | Add `suppress_terms`; lower `suppress_penalty` (harsher). |
| Cost creeping up | Lower `max_items` and/or raise `minimum_favorites`. |

## Example output

A worked, anonymized example lives in [`examples/`](examples/):
`sample_raw.json` (input) → `sample_candidates.json` + `sample_candidates.md` (output).
Regenerate it yourself:

```bash
mkdir -p out && cp examples/sample_raw.json out/last_raw.json
python3 tracker.py --config examples/example.config.json --dry-run
```

## No duplicate outputs

`seen.json` is a ledger keyed on **repo (`github.com/owner/repo`) → else tweet URL**.
Each run drops any key already surfaced and collapses multiple tweets about the same repo
into one item. Delete `seen.json` to reset the memory.

## Calibration (optional)

By default the score self-normalizes to each pull's median (good cold-start). Run
`python3 tracker.py --calibrate` to pull a larger sample and freeze niche-wide medians
into `config.json → baseline` for a stable bar across runs. Re-calibrate when your niche
shifts.

## Scheduling recurring runs

The tool is a plain script — schedule it however you like. See
[docs/INTEGRATION.md § Schedule](docs/INTEGRATION.md#9-schedule-recurring-runs) for a
cron example and a note on cost at each cadence.

## Limitations

- **Relevance precision is yours to make.** The numeric score ranks by virality, not
  topical fit; treat the output as a shortlist.
- **Single acquisition dependency.** If your actor is deprecated or blocked, switch
  `apify.actor` (kaito ↔ apidojo — same output schema).
- **Repo extraction misses** when a repo sits behind a `t.co` shortlink that resolves to
  an aggregator; dedup then falls back to the tweet URL (still no re-surface).
- **No cross-source corroboration** (GitHub/HN/Product Hunt). Not implemented.
- The free Apify plan hard-blocks you when the monthly credit is exhausted — see
  [docs/COST.md](docs/COST.md).

## Compliance

- Uses **Apify's official Twitter/X actors and public API** — no logged-in session
  scraping, no credential pooling, no circumvention of access controls.
- Retrieves only **publicly available** post and profile data.
- `minimum_favorites` and `max_items` keep request volume bounded; respect Apify's and
  X's terms of service and rate limits.
- You are responsible for how you use the retrieved data. Review
  [Apify's Terms](https://apify.com/terms-of-use) and
  [X's Terms of Service](https://x.com/en/tos) for your use case and jurisdiction.

## License

[MIT](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
