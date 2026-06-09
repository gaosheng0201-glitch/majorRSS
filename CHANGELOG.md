# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-06-09

### Added
- **Dual-Mode Trackers Input**: Added Simple Mode (for bulk copy-pasting newline-separated lists of URLs, keywords, or accounts) and Hybrid Mode (three separate textarea inputs for mixing urls, keywords, accounts, OSINT options, and max age) in the client's Tracker Modal form.
- **Contextual Deduplication & Source Merging**:
  - Automatically queries the 8 most recent intelligence reports as context (`RECENT_REPORTS_CONTEXT`).
  - Instructs Gemini to compare new content against recent reports and return the duplicate report ID if similar.
  - Automatically appends/merges new valid sources and raw URLs into the existing report and marks them as processed instead of generating duplicate cards on the dashboard.
- **Scheduler Concurrency & Rate Limit Safeguards**:
  - Implemented sequential loop batching of 10 articles per batch with a `1.5s` delay between batches to protect Gemini API RPM/TPM limits.
  - Sequentially executes AI processing tasks across trackers in the scheduler.
  - Restricts background Playwright crawler concurrency to `max_workers=2` to prevent memory/CPU spikes and queue clogging.
- **SQLAlchemy Session Management & Leak Fixes**:
  - Configured `expire_on_commit=False` on the DB sessionmaker to eliminate detached instance errors across backend threads.
  - Updated all database sessions across LLM processor and investigator tasks to use proper context managers or close connections explicitly.
- **Naive UTC Timezone Standardization**:
  - Added `utc_now_naive()` helper to strip timezone offsets before database writes.
  - Standardized all `created_at` fields and scraper daemons to store naive UTC datetimes. This prevents connection-timezone skew where Shanghai local time was treated as future UTC time, causing the scheduler to freeze.
  - Cleaned up database stuck states and repaired historical future-skewed timestamps.
- **Token Auditing & Chart Calculations**:
  - Logged LLM token usage for all investigator fact-checking queries.
  - Aggregated trend data over all database records on the backend, resolving the discrepancy where the Billing trend chart's sum did not match the totals.
- **Card Clutter & Title-Summary Alignment**:
  - Enforced client-preferred language output (defaulting to Chinese, English, Korean, Japanese, or Russian) inside `FactCheckResult`.
  - Implemented automatic custom title extraction (`[TITLE: ...]`) and 80-character default title truncation to prevent long social media titles from cluttering the dashboard cards.
- **Dynamic Client-Controlled LLM Generation Language**:
  - Added backend settings API `POST /api/settings/system-language` to save the active client language context to the local `.env` environmental configuration.
  - Linked the frontend language selector in `Settings.tsx` to automatically update the backend's environmental settings.
  - Configured all asynchronous Gemini extraction, briefing, trend alert, and diff summary prompts to dynamically adapt to the user's active client language preference instead of locking to Chinese.
- **Interactive Cookie Auth Portal Restoration**:
  - Restored the 11-platform interactive cookie authentication grid inside the Settings page (`Settings.tsx`), showing status indicators (Active, Expired, Not Authorized) and last login timestamps.
  - Added backend status check (`GET /api/settings/auth/status`) and headful Playwright browser login trigger (`POST /api/settings/auth/login`) API endpoints.
  - Implemented full multi-lingual (i18n) translation dictionaries for the auth portal UI elements.

## [2.0.0] - 2026-06-09

### Added
- **Desktop Architecture Migration (Tauri 2 + React + Mantine 9.3)**: Migrated the entire user interface from Streamlit to a desktop application powered by Tauri 2, React 19, and Mantine 9.3, providing a smooth desktop app experience with native-feeling responsive views.
- **FastAPI API Server Integration**: Restructured the backend python pipeline into a FastAPI web API server (`backend/main.py`), utilizing APIRouter for trackers, settings, and intelligence feeds. Decoupled the worker queues and scheduler to run within FastAPI's lifespan startup hook.
- **NotebookLM-Style Tabbed Sources Layout**:
  - Implemented a vertical list sources panel inside a glassmorphic container (`rgba(21, 23, 27, 0.6)`) featuring dynamic counts in pill badges (`在报告中引用的来源数` / `未引用的来源数`).
  - Integrated Google Favicon API for loading source site icons, with robust React `SourceIcon` fallbacks to Lucide icons upon loading failure.
  - Replaced plain text urls and simple cards with `<Anchor>` components and subtext descriptions showing actual cited text/quotes.
  - Added a `折叠来源分析 ∧` action button at the bottom of the scroll area for collapsing the sources panel easily.
- **Rotating Warning Alerts Carousel**: Designed a clean, rotating warning alert carousel showing one trend trigger card at a time with a 5-second auto-rotate loop and indicator dots.
- **Redesigned Trend Alert Detail Modal**: Hidden inline source badges from the warning alert card, moving them into the detail modal in a matching NotebookLM vertical layout.
- **Multi-Language (i18n) & Theme Toggle**: Integrated dynamic client-side language switching across 5 system languages (English, Chinese, Korean, Japanese, Russian) and a Light/Dark color scheme selector.

### Changed
- Replaced deprecated Mantine layout properties (such as `align` on `Paper`/`Text`) with standard style parameters (`mah` and `ta`) to resolve React console warning logs.
- Expanded `TrendAlertSource` schema to support and return source descriptions extracted from the database report summaries.

## [1.5.1] - 2026-06-03

### Fixed
- **Underlying Network Engine Refactoring (SSL Fix)**: Completely replaced the legacy `urllib` backend used by `feedparser` with the robust `requests` library in the foundational Tier 1 Scraper (`scrapers/tier1_rss.py`). This permanently resolves widespread `[SSL: UNEXPECTED_EOF_WHILE_READING]` EOF handshake errors and `HTTP Error 502` blocks caused by modern CDNs and firewalls on Windows systems, restoring reliable probing across all basic RSS and Hub endpoints.

## [1.5.0] - 2026-05-28

### Added
- **Transparent RSSHub Engine (智能嗅探与路由)**: Implemented a seamless middleware (`scrapers/url_normalizer.py`) that acts as a universal adapter for social media URLs. When users input a Bilibili, Twitter, YouTube, Weibo, TikTok, or Xiaohongshu profile URL into *any* part of the system (Tracker or Webpage Monitor), it is instantly and invisibly converted into a highly stable RSSHub XML endpoint, completely bypassing aggressive anti-bot mechanisms.
- **Hybrid Subscription Architecture**: Upgraded the `worker_subscription.py` daemon. The Webpage Monitor now dynamically detects the underlying protocol. If it sniffs an RSS/XML stream (e.g., routed via the new transparent engine), it bypasses the heavy Playwright headless browser entirely, utilizing a blazing-fast `requests` pipeline to fetch and diff the latest XML entries. This reduces server memory usage and eliminates captcha blocking for social media targets.

### Changed
- **Separation of Authentication Concerns**: The Interactive Cookie Auth feature is now strictly reserved for the Fact-Checker (溯源竞技场) module's deep-dive investigations. Everyday broad intelligence gathering is fully delegated to the new RSSHub engine.

## [1.3.1] - 2026-05-16

### Fixed
- **Source Evidence Hallucination Fix**: Resolved a critical UX issue where the AI's "Source Evidence" block would display completely irrelevant URLs (e.g., noisy fallback posts from Reddit's search API). Upgraded the `FactCheckResult` JSON schema with a `relevant_source_indices` array, forcing Gemini to explicitly cite the exact sources it utilized and dynamically filtering out all unmentioned noise from the frontend display.
- **High-Concurrency PostgreSQL Bottlenecks**: Fixed recurring `QueuePool limit of size 5 overflow 10 reached` TimeoutErrors during heavy scraping and intelligence fusion loads. Upgraded the SQLAlchemy engine initialization for PostgreSQL with enterprise-grade pooling limits (`pool_size=30`, `max_overflow=50`) and enabled `pool_pre_ping` to ensure connection health and eliminate threading deadlocks.

## [1.3.0] - 2026-05-15
### Added
- **Webpage Subscription & Diff Monitoring**: Architected a new top-level parallel business line specifically for tracking non-RSS entities (API documentation, Bilibili/YouTube dynamic homepages, personal blogs).
- **Smart Diff Filter**: A specialized `BeautifulSoup` engine that intelligently strips out volatile DOM noise (e.g., dynamic view counts, follower numbers, `<time>` tags) and anchors on structural skeleton changes (`<a>` links and long paragraphs) to eliminate false-positive alerts.
- **On-Demand AI Summarization (Dialog UX)**: Leveraged Streamlit's `@st.dialog` to provide a lightweight, popup-based Diff viewer. Users can inspect the exact code-level additions/deletions and trigger a single-shot Gemini LLM summary only when deemed necessary, drastically reducing token waste.
- **Global Auth Registry Expansion**: Extensively scaled the interactive cookie auth helper to support 11 international platforms, including VK, Naver, Niconico, Reddit, LinkedIn, Twitter, Xiaohongshu, Bilibili, TikTok, Weibo, and Instagram. Added a dynamic cookie health-check diagnostic function.

### Changed
- **Modernized UI Typology**: Completely phased out legacy operating-system emojis from the sidebar and navigation UI in favor of precise, scalable `Streamlit Material Icons` (SVG) for a cleaner, unified aesthetic.

## [1.2.0] - 2026-05-14
### Added
- **Interactive Cookie Auth**: Implemented a state-of-the-art interactive login helper using Playwright's `storage_state`. Allows users to bypass strict anti-bot measures by authenticating in a real headful browser window with one click from the UI. The state (including LocalStorage) is seamlessly injected into the headless scraper.
- **Dynamic Scrape Intervals**: Users can now configure custom scraping intervals (in minutes) for individual trackers, avoiding rate-limiting on high-frequency monitors while saving resources on low-priority ones.
- **Editable Data Grids**: The active trackers management dashboard now supports inline editing via Pandas DataFrames for quick adjustments to status, intervals, and names without navigating to a new form.

### Changed
- **Database Architecture Migration**: Successfully migrated the entire backend persistence layer from local SQLite to robust PostgreSQL, resolving concurrency locking issues and enabling high-availability deployments.

## [1.1.0] - 2026-05-12

### Added
- **Chronological Event Timeline**: The LLM processor now acts as a "Time Detective," actively extracting the true publish/event time from raw article content. The UI Dashboard now sorts intelligence primarily by this `event_timestamp` rather than the system scraping time.
- **Dynamic Noise Deduplication**: Introduced a zero-cost Python `difflib` similarity engine for the Agentic Scraper. If a website's snapshot changes by < 5% (e.g., ticking clocks, ad rotations), it is immediately discarded to prevent LLM hallucination duplicates. RSS feeds now also feature dual-layer URL and Title exact-match deduplication.

## [1.0.0] - 2026-05-11

### Added
- **Global i18n Support**: Introduced a robust multi-language architecture supporting English, Simplified Chinese, Japanese, Korean, and Russian.
- **Smart Language Sniffing**: The backend now automatically reads the browser's `Accept-Language` HTTP header to seamlessly render the correct local language without page reload flashes.
- **Supabase-Style UI**: A completely redesigned, ultra-minimalist `64px` persistent sidebar using native Streamlit routing and CSS overriding. 
- **Agentic Scraper (Tier 3)**: Integrated a Playwright-based headless browser to defeat advanced JavaScript rendering and anti-bot systems.
- **LLM Cost Auditing**: A built-in Dashboard to track all local token usage (differentiating Gemini Flash and Pro) and estimate costs based on real-time API pricing.
- **Automated Daily Briefing**: Scheduled synthesis of global intelligence using Gemini 1.5 Pro to connect the dots across 24 hours of data.

### Security
- Shifted all frontend JS-based parameter injections to secure backend native parsing to completely resolve cross-origin iframe sandbox `SecurityError` vulnerabilities.
