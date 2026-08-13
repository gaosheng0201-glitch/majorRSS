# MajorRSS 📡

A **local, personal intelligence radar**. You set what you care about; MajorRSS
scrapes the sources, de-noises and clusters what comes in, and surfaces only the
genuine increments — *what happened, when* — instead of a bottomless feed. It
runs entirely on your machine: your keys, your cookies, your data.

Not an aggregator. The goal isn't more information — it's **less noise and less
time spent**. Most content is organized and de-duplicated by cheap embeddings
and never reaches a generation model.

## How it works

```
Watch Target ──► source portfolio (planned once)
   │
   ▼  fetch runtime (conditional GET · browser pool · per-source backoff · account protection)
Unified SourceItem ──► semantic layer (embed · relevance gate · dedup · cluster)
   │
   ▼  Story Threads:  LEAD ──► CORROBORATED ──► CONFIRMED  (+ resonance)
   ▼
Radar (reading feed) · quiet alerts on real increments · daily briefing
```

- **Radar** — the single reading surface, grouped by time (*today / this
  week*) and filterable by target. In AI mode it has two faces: **Refined**
  (events that earned a fused summary — the card *is* the summary, stamped
  "first seen / updated" honestly) and **Leads** (clustered but unsummarised;
  tips from accounts you named are shown and labelled *unverified*, aggregator
  singletons collapse by default). In pure-RSS mode the surface is the raw,
  unfiltered subscription stream itself.
- **Story threads** — the same event across languages and outlets is merged into
  one thread; lifecycle tracks LEAD → CORROBORATED → CONFIRMED, and cross-source
  **resonance** ("everyone is talking about it") is the key importance signal.
- **Account protection** — scraping with your own social logins is rationed
  per-account with humanized pacing and a risk circuit-breaker, so a busy radar
  doesn't get your account limited.
- **BYOK / local models** — bring your own Gemini key, point at any
  OpenAI-compatible endpoint (Ollama / LM Studio / vLLM), or run key-free: a
  fallback embedder keeps relevance and dedup working with no model at all.

## Tech stack

- **Desktop**: Tauri 2 (Rust shell) + React 19 + Mantine, talking to a local
  FastAPI backend over HTTP (`127.0.0.1:8765`).
- **Backend**: FastAPI + SQLModel (SQLite by default at `~/.majorss/`, optional
  Postgres) + APScheduler. Playwright for JS/anti-bot pages; feedparser + lxml
  for feeds and readability extraction.
- **AI**: pluggable `LLMProvider` (Gemini / OpenAI-compatible / fallback
  embedder). Semantic ops are engine-agnostic cosine, no vector DB required.

## Run it (dev)

```bash
# Backend (Python 3.10+)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python backend/main.py                 # serves 127.0.0.1:8765

# Desktop (in another shell)
cd desktop && npm install
npx tauri dev                          # or `npm run dev` to open the UI in a browser
```

A Gemini key (or any OpenAI-compatible endpoint) enables AI summaries, briefings
and semantic relevance filtering. Without one, MajorRSS still fetches,
de-duplicates, and clusters locally (pure-RSS mode). Configure keys and mode in
**Settings** (no `.env` required).

Package the desktop app with `cd desktop && npm run tauri:build` (bundles the
Python backend as a sidecar via PyInstaller).

## Tests

```bash
pytest -q
```

## Status

Actively evolving from a v2.x RSS aggregator into the radar described above.
Design intent and the current engineering state live in [`docs/`](docs/)
(`vision_and_blueprint.md`, `engineering_baseline.md`).

## Disclaimer

For personal, educational intelligence-gathering. Respect the `robots.txt` and
Terms of Service of the sites you scrape, and use your own authenticated
accounts responsibly. The author is not responsible for misuse.
