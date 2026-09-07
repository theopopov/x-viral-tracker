# Contributing

Thanks for your interest in improving x-viral-tracker. This is a small, dependency-free
tool; contributions that keep it that way are the most welcome.

## Ground rules

- **No third-party runtime dependencies.** The tool must keep running on the Python 3.8+
  standard library alone. If you think a dependency is unavoidable, open an issue first.
- **Configuration over code.** Anything niche-, topic-, or account-specific belongs in
  `config.json`, never hardcoded in `tracker.py`.
- **Never commit secrets.** No API tokens, account ids, or private data in code, config,
  examples, or commit history. `.gitignore` already excludes `.env`, `config.json`,
  `out/`, and `seen.json`.
- **Public data only.** Do not add features that scrape logged-in sessions, pool
  credentials, or circumvent access controls. The tool uses Apify's official actors on
  purpose.

## Development

```bash
git clone https://github.com/theopopov/x-viral-tracker.git
cd x-viral-tracker
cp config.example.json config.json
export APIFY_TOKEN=...            # only needed for live runs
```

Iterate for free without spending Apify credit using a saved raw pull:

```bash
mkdir -p out && cp examples/sample_raw.json out/last_raw.json
python3 tracker.py --dry-run
```

## Before opening a PR

- Keep `tracker.py` stdlib-only and behavior-compatible unless the PR is explicitly about
  changing the scoring/gate/dedup model (call that out clearly).
- Update `config.example.json` (with inline `_comment`s) and the README/docs for any new
  config key.
- If you change the scoring or dedup logic, include a before/after on a sample pull so
  reviewers can see the effect.

## Reporting bugs / ideas

Open an issue describing what you ran, the relevant (redacted) config, and what you
expected vs. observed. Please redact your token and any private handles.
