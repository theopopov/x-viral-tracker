#!/usr/bin/env python3
"""
x-viral-tracker — X/Twitter viral-post tracker (deterministic stage).

Pipeline:  acquire (Apify) -> numeric virality score -> relevance gate ->
           suppress-flag -> dedup (repo/url ledger) -> emit ranked candidates.

This tool does ONLY the cheap, deterministic work. Any downstream classification
(deciding which surfaced posts are genuinely on-topic for you, drafting angles,
etc.) is left to a human or an LLM reading the emitted candidates_*.json — so the
tool itself has no model API key and no inference bill.

Deps: Python 3 stdlib only. No pip install.

Usage:
    python3 tracker.py                 # normal run -> out/candidates_<ts>.{json,md}
    python3 tracker.py --calibrate     # bigger pull, write niche baselines into config
    python3 tracker.py --dry-run       # score a saved raw pull without hitting Apify (uses out/last_raw.json)
    python3 tracker.py --max-items 150 # override the per-run cost cap for this run
    python3 tracker.py --config PATH   # use an alternate config file (default: config.json next to this script)
"""
import json, os, sys, re, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(HERE, "config.json")


# ---------- config / io ----------
def load_config(path):
    with open(path) as f:
        return json.load(f)

def save_config(cfg, path):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)

def apify_token(cfg):
    return os.environ.get(cfg["apify"]["token_env"]) or cfg["apify"].get("token") or ""


# ---------- acquire ----------
def acquire(cfg, max_items_override=None):
    ap = cfg["apify"]; acq = cfg["acquire"]
    token = apify_token(cfg)
    if not token:
        sys.exit("No Apify token. Set the APIFY_TOKEN env var (see .env.example) or apify.token in config.json.")
    start = (datetime.now(timezone.utc) - timedelta(days=acq["freshness_days"])).strftime("%Y-%m-%d")
    max_items = max_items_override or acq["max_items"]
    # Bake filters as X search operators so the call is actor-agnostic
    # (kaito and apidojo both pass searchTerms straight to X search).
    ops = f" lang:{acq['language']} since:{start} min_faves:{acq['minimum_favorites']}"
    terms = [q + ops for q in acq["queries"]]
    payload = {
        "searchTerms": terms,
        "maxItems": max_items,
        "sort": acq["sort"],           # apidojo
        "queryType": acq["sort"],      # kaito
    }
    url = (f"https://api.apify.com/v2/acts/{ap['actor']}/run-sync-get-dataset-items"
           f"?token={token}&maxItems={max_items}")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    est = max_items * ap["actor_price_per_tweet_usd"]
    print(f"[acquire] {len(acq['queries'])} queries, since {start}, min_faves>={acq['minimum_favorites']}, "
          f"cap {max_items} items (<= ${est:.3f}) ...", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            items = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Apify HTTP {e.code}: {e.read().decode()[:400]}")
    if not isinstance(items, list):
        sys.exit(f"Unexpected Apify response: {str(items)[:300]}")
    with open(os.path.join(HERE, cfg["output"]["dir"], "last_raw.json"), "w") as f:
        json.dump(items, f)
    print(f"[acquire] pulled {len(items)} tweets (actual cost ~${len(items)*ap['actor_price_per_tweet_usd']:.3f})", flush=True)
    return items


# ---------- helpers ----------
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)

def parse_created(s):
    # Twitter format: "Fri Nov 24 17:49:36 +0000 2023"
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

SKIP_REPO = ("blog", "about", "topics", "features", "sponsors", "orgs", "settings")

def _norm_repo(m):
    if m and m.group(2).lower().rstrip(".") not in SKIP_REPO:
        return f"github.com/{m.group(1)}/{m.group(2).rstrip('.')}".lower()
    return None

def extract_repo(t):
    # prefer the full expanded_url (display_url is truncated with an ellipsis)
    for u in ((t.get("entities") or {}).get("urls") or []):
        r = _norm_repo(GITHUB_RE.search(u.get("expanded_url") or ""))
        if r:
            return r
    return _norm_repo(GITHUB_RE.search(t.get("text") or t.get("fullText") or ""))

def dedup_key(t):
    return extract_repo(t) or (t.get("url") or t.get("twitterUrl") or "").lower()

def author_tier(followers, bands):
    for name, (lo, hi) in bands.items():
        if lo <= followers < hi:
            return name
    return "mega"


# ---------- scoring ----------
def raw_signals(t, now):
    a = t.get("author") or {}
    views = t.get("viewCount") or 0
    followers = a.get("followers") or 0
    likes = t.get("likeCount") or 0
    reposts = t.get("retweetCount") or 0
    replies = t.get("replyCount") or 0
    quotes = t.get("quoteCount") or 0
    bookmarks = t.get("bookmarkCount") or 0
    eng = likes + reposts + replies + quotes
    created = parse_created(t.get("createdAt") or "")
    age_h = max(0.5, (now - created).total_seconds() / 3600.0) if created else 999.0
    return {
        "views": views, "followers": followers,
        "likes": likes, "reposts": reposts, "replies": replies,
        "quotes": quotes, "bookmarks": bookmarks, "eng": eng,
        "age_hours": round(age_h, 1),
        "reach_ratio": (views / followers) if followers > 0 else 0.0,
        "engagement_rate": (eng / views) if views > 0 else 0.0,
        "velocity": eng / age_h,
        "reply_like_ratio": replies / max(likes, 1),
        "quote_repost_ratio": quotes / max(reposts, 1),
        "bookmark_rate": (bookmarks / views) if views > 0 else 0.0,
        "spread": reposts + quotes,
    }

def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return 0.0
    n = len(xs); mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2

def score_all(posts, cfg):
    now = datetime.now(timezone.utc)
    v = cfg["virality"]; w = v["weights"]; cap = v["normalization_cap"]
    hl = v["age_decay_half_life_hours"]
    reply_pivot = v.get("reply_like_pivot", 0.15)  # ~0.15 reply/like ~= discussion-heavy
    base = cfg["baseline"]
    for p in posts:
        p["signals"] = raw_signals(p["_t"], now)

    # baselines: stored (calibrated) medians, else self-normalize to this pull
    def med(field, key):
        if base.get("calibrated") and base.get(key) is not None:
            return base[key]
        return median([p["signals"][field] for p in posts]) or 1e-9
    m = {
        "velocity":        med("velocity", "velocity_median"),
        "bookmark_rate":   med("bookmark_rate", "bookmark_rate_median"),
        "reach_ratio":     med("reach_ratio", "reach_ratio_median"),
        "spread":          med("spread", "spread_median"),
        "engagement_rate": med("engagement_rate", "engagement_rate_median"),
    }
    for p in posts:
        s = p["signals"]
        def n(field):  # ratio-to-median, capped
            return min(cap, s[field] / (m[field] or 1e-9))
        reply_q = min(cap, s["reply_like_ratio"] / reply_pivot)
        score = (w["velocity"]        * n("velocity") +
                 w["bookmark_rate"]   * n("bookmark_rate") +
                 w["reach_ratio"]     * n("reach_ratio") +
                 w["spread"]          * n("spread") +
                 w["engagement_rate"] * n("engagement_rate") +
                 w["reply_quality"]   * reply_q)
        decay = 0.5 ** (s["age_hours"] / hl)
        p["score_raw"] = round(score, 4)
        p["age_decay"] = round(decay, 3)
        p["score"] = round(score * decay, 4)
        p["author_tier"] = author_tier(s["followers"], v["author_tier_bands"])
        # which normalized signals drove it (for the brief)
        drivers = {"velocity": n("velocity"), "bookmarks": n("bookmark_rate"),
                   "reach_ratio": n("reach_ratio"), "spread": n("spread"),
                   "engagement": n("engagement_rate")}
        p["top_drivers"] = [k for k, _ in sorted(drivers.items(), key=lambda kv: -kv[1])[:2]]
    return posts


# ---------- gates ----------
def relevance_ok(t, cfg):
    g = cfg["relevance_gate"]["require_any_of"]
    text = (t.get("text") or t.get("fullText") or "").lower()
    if g.get("has_github_link") and "github.com" in text:
        return True
    return any(term in text for term in g.get("niche_terms", []))

def suppress_flags(t, cfg):
    text = (t.get("text") or t.get("fullText") or "").lower()
    return [term for term in cfg["suppress_terms"] if term in text]


# ---------- main pipeline ----------
def run(cfg, args, config_path):
    outdir = os.path.join(HERE, cfg["output"]["dir"])
    os.makedirs(outdir, exist_ok=True)

    if args.get("dry_run"):
        with open(os.path.join(outdir, "last_raw.json")) as f:
            items = json.load(f)
        print(f"[dry-run] scoring {len(items)} cached tweets")
    else:
        items = acquire(cfg, args.get("max_items"))

    # keep only real tweets
    items = [t for t in items if (t.get("type") in (None, "tweet")) and (t.get("createdAt"))]

    # relevance gate + wrap
    posts = []
    for t in items:
        if not relevance_ok(t, cfg):
            continue
        posts.append({"_t": t, "suppress": suppress_flags(t, cfg)})
    print(f"[gate] {len(posts)}/{len(items)} passed relevance gate")

    if not posts:
        print("[done] nothing passed the gate this run.")
        return

    score_all(posts, cfg)

    # suppress penalty
    pen = cfg.get("suppress_penalty", 0.5)
    for p in posts:
        if p["suppress"]:
            p["score"] = round(p["score"] * pen, 4)

    # within-run dedup: collapse by key, keep best, attach other sources
    by_key = {}
    for p in sorted(posts, key=lambda x: -x["score"]):
        k = dedup_key(p["_t"])
        if k in by_key:
            by_key[k]["other_sources"].append(p["_t"].get("url"))
        else:
            p["dedup_key"] = k
            p["other_sources"] = []
            by_key[k] = p
    collapsed = list(by_key.values())

    # cross-run dedup: drop keys already surfaced
    ledger_path = os.path.join(HERE, cfg["output"]["seen_ledger"])
    seen = {}
    if os.path.exists(ledger_path):
        with open(ledger_path) as f:
            seen = json.load(f)
    fresh = [p for p in collapsed if p["dedup_key"] not in seen]
    skipped = len(collapsed) - len(fresh)
    print(f"[dedup] {len(collapsed)} unique drops, {skipped} already surfaced in prior runs -> {len(fresh)} new")

    fresh.sort(key=lambda x: -x["score"])
    tn = cfg["output"]["top_n"]
    top = fresh if tn in (0, None) else fresh[:tn]  # top_n<=0 => emit every relevance-gated drop (virality is only a sort key)

    # build output records (raw metrics + signals; downstream classification is out of scope)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    profile = cfg["output"].get("profile", "x_viral_tracker")
    records = []
    for p in top:
        t = p["_t"]; a = t.get("author") or {}; s = p["signals"]
        records.append({
            "score": p["score"], "score_raw": p["score_raw"], "age_decay": p["age_decay"],
            "top_drivers": p["top_drivers"], "author_tier": p["author_tier"],
            "url": t.get("url") or t.get("twitterUrl"),
            "author_handle": a.get("userName"), "author_followers": a.get("followers"),
            "author_verified": a.get("isBlueVerified") or a.get("isVerified"),
            "posted_at": t.get("createdAt"), "age_hours": s["age_hours"],
            "text": (t.get("text") or t.get("fullText") or "").strip(),
            "metrics": {"views": s["views"], "likes": s["likes"], "reposts": s["reposts"],
                        "replies": s["replies"], "quotes": s["quotes"], "bookmarks": s["bookmarks"]},
            "signals": {k: round(s[k], 4) for k in
                        ("reach_ratio", "engagement_rate", "velocity", "reply_like_ratio",
                         "quote_repost_ratio", "bookmark_rate", "spread")},
            "repo_url": ("https://" + p["dedup_key"]) if p["dedup_key"].startswith("github.com") else None,
            "dedup_key": p["dedup_key"],
            "brand_flags": p["suppress"],
            "other_source_urls": [u for u in p["other_sources"] if u],
        })

    json_path = os.path.join(outdir, f"candidates_{ts}.json")
    with open(json_path, "w") as f:
        json.dump({"generated_at": ts, "count": len(records),
                   "profile": profile, "candidates": records}, f, indent=2)

    md_path = os.path.join(outdir, f"candidates_{ts}.md")
    write_md(md_path, records)

    # update ledger
    for p in fresh:  # mark all new unique drops as seen (surfaced or logged)
        seen[p["dedup_key"]] = ts
    with open(ledger_path, "w") as f:
        json.dump(seen, f, indent=2)

    print(f"\n[done] {len(records)} candidates -> {json_path}")
    print(f"       human table         -> {md_path}")
    print(f"       ledger now tracks {len(seen)} drops (no re-surfacing).")
    print("\nNext: read the JSON (yourself or with an LLM) and classify the survivors for your topic.")


def write_md(path, records):
    lines = ["# x-viral-tracker — X candidates (deterministic pre-brief)\n",
             f"{len(records)} candidates, ranked by virality score. "
             "Downstream classification (relevance, angle) is added separately.\n",
             "| # | score | drivers | tier | age(h) | views | reposts | bmarks | reach× | author | text |",
             "|--|--|--|--|--|--|--|--|--|--|--|"]
    for i, r in enumerate(records, 1):
        txt = r["text"].replace("\n", " ").replace("|", "/")[:80]
        lines.append(f"| {i} | {r['score']:.2f} | {'+'.join(r['top_drivers'])} | {r['author_tier']} | "
                     f"{r['age_hours']:.0f} | {r['metrics']['views']} | {r['metrics']['reposts']} | "
                     f"{r['metrics']['bookmarks']} | {r['signals']['reach_ratio']:.2f} | "
                     f"@{r['author_handle']} | {txt} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def calibrate(cfg, args, config_path):
    # bigger pull, compute medians, write into config baseline
    items = acquire(cfg, args.get("max_items") or 500)
    items = [t for t in items if t.get("createdAt")]
    posts = [{"_t": t, "suppress": []} for t in items if relevance_ok(t, cfg)]
    now = datetime.now(timezone.utc)
    for p in posts:
        p["signals"] = raw_signals(p["_t"], now)
    fields = {"reach_ratio_median": "reach_ratio", "engagement_rate_median": "engagement_rate",
              "velocity_median": "velocity", "bookmark_rate_median": "bookmark_rate",
              "spread_median": "spread"}
    b = cfg["baseline"]
    for key, field in fields.items():
        b[key] = round(median([p["signals"][field] for p in posts]), 6)
    b["calibrated"] = True
    save_config(cfg, config_path)
    print(f"[calibrate] baselines from {len(posts)} in-niche posts written to {os.path.basename(config_path)}:")
    for k in fields:
        print(f"   {k}: {b[k]}")


def main():
    argv = sys.argv[1:]
    args = {"calibrate": "--calibrate" in argv, "dry_run": "--dry-run" in argv, "max_items": None}
    if "--max-items" in argv:
        args["max_items"] = int(argv[argv.index("--max-items") + 1])
    config_path = DEFAULT_CONFIG_PATH
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    cfg = load_config(config_path)
    if args["calibrate"]:
        calibrate(cfg, args, config_path)
    else:
        run(cfg, args, config_path)


if __name__ == "__main__":
    main()
