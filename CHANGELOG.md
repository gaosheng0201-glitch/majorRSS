# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
