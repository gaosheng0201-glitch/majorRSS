# RSS Feed Generation Method

> Created: 2026-06-20
>
> Purpose: summarize what MajorRSS can learn from `Olshansk/rss-feeds` for official sites that do not publish a native RSS or Atom feed.

## What Was Learned

`Olshansk/rss-feeds` is not a generic crawler. It is a registry-driven collection of per-site feed generators.

Important traits:

- `feeds.yaml` is the source registry. Each entry declares the script name, fetch type, original blog URL, and enabled status.
- Generators are split into `requests` and `selenium` types.
- `run_all_feeds.py` reads the registry and can run all feeds, one feed, requests-only feeds, or Selenium-only feeds.
- GitHub Actions runs requests-based feeds hourly and Selenium-based feeds on a separate hourly schedule.
- Generated XML files are committed back into the repository under `feeds/`.
- Each generator extracts article title, URL, date, category, summary, and then merges with a local cache before writing RSS.
- A stable fallback date is used when pages do not expose a parseable publish date, preventing feed churn.
- Selenium generators explicitly click `See more` or `Load more` buttons for React/SPA sites such as Anthropic News and AI at Meta.

Sources:

- Repository: https://github.com/Olshansk/rss-feeds
- Feed registry: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds.yaml
- Runner: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feed_generators/run_all_feeds.py
- Utilities: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feed_generators/utils.py
- Requests workflow: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/.github/workflows/run_feeds.yml
- Selenium workflow: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/.github/workflows/run_selenium_feeds.yml

## Suitability For MajorRSS

MajorRSS should copy the architecture, not blindly vendor the scripts.

Good fit:

- Official page has no RSS, but page structure is stable enough to parse.
- Source is high value, low noise, and worth maintaining.
- Page has public content and does not require cookies or auth.
- Generated feed is clearly labeled as generated or unofficial.
- Parser failures can be health-scored and quarantined.

Bad fit:

- Sites with frequent layout churn and low value.
- Sites requiring account login, cookies, or private headers.
- Pages where generated RSS would appear official when it is not.
- High-volume news pages that create more noise than signal.

## Proposed MajorRSS Model

Add source-origin and generator metadata to SourcePreset:

```json
{
  "verification_status": "official_feed | third_party_generated | generated_by_majorss | web_page_candidate",
  "canonical_site": "https://example.com/blog",
  "generator": {
    "method": "requests | browser",
    "script": "feed_generators/example.py",
    "selector_profile": "example_blog_v1",
    "schedule": "hourly | daily | manual",
    "max_clicks": 3
  }
}
```

This keeps trust boundaries explicit:

- `official_feed`: publisher provides RSS/Atom.
- `third_party_generated`: external project generates feed from public pages.
- `generated_by_majorss`: MajorRSS generates feed from public pages.
- `web_page_candidate`: known valuable page, no generated feed yet.

## Suggested Implementation Stages

### Stage 1: Consume Existing Third-party Feeds

Use Olshansk feeds as community or experimental presets for sources with no official RSS:

- Anthropic News
- Anthropic Research
- Anthropic Engineering
- Claude Blog
- AI at Meta Blog

Show them as "third-party generated RSS", not official feeds.

### Stage 2: Add Health Checks

Before subscribing users by default, check:

- HTTP status.
- Feed parse success.
- Last item date.
- Duplicate item ratio.
- Canonical article URLs still resolve.
- Feed item URLs stay inside the declared canonical domain.

### Stage 3: Build MajorRSS Generated Feed Pipeline

Create a small generator subsystem:

```text
feed_registry.json
feed_generators/
  base.py
  anthropic_news.py
  claude_blog.py
generated_feeds/
cache/feed_entries/
```

Each generator should implement:

```text
fetch()
parse_entries()
normalize_entry()
merge_cache()
write_feed()
```

Start with `requests` generators first. Add browser/Selenium/Playwright only for high-value sources where static HTML is insufficient.

### Stage 4: Integrate With Preset Library

Generated feeds should not be treated as normal official sources.

Recommended behavior:

- Official feed sources can be `built_in`.
- MajorRSS-generated feeds start as `experimental`.
- Generated feeds require a visible source-origin label.
- Generated feeds need health score before promotion.
- Generated feeds should fall back to page-diff if parsing fails repeatedly.

## Design Notes

Olshansk's approach is intentionally simple and auditable: a small Python parser per source, a registry, a runner, cache merge, and generated XML output.

For MajorRSS, the same pattern should be adapted into a local pipeline with source health scoring, trust labels, and UI disclosure. The key product distinction is that a generated feed is a convenience layer over a public page, not proof that the publisher offers or endorses RSS.
