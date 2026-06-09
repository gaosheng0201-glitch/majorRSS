# MajorRSS 📡 `v1.2.0`

MajorRSS is an intelligent, automated intelligence-gathering and AI-denoising platform. It transforms raw, chaotic information streams (from RSS, web pages, to headless browser scraping) into a highly structured, high-value intelligence dashboard using Google's Gemini models.

## Features ✨
- **Interactive Cookie Auth**: Authenticate seamlessly via a real browser UI; state (including LocalStorage) is saved and injected into headless scrapers to bypass tough anti-bot checks (e.g., Twitter/X).
- **Multi-Tier Scraping Architecture**: From simple RSS parsing to advanced headless browser (Playwright) agentic scraping, bypassing complex anti-bot measures.
- **AI-Powered Denoising**: Uses Google Gemini 3 Flash for high-frequency text cleaning, translation, and entity extraction.
- **Automated Daily Briefings**: Uses Gemini 3.1 Pro to synthesize massive amounts of daily intelligence into a concise, readable global briefing.
- **Supabase-Style Dashboard**: A beautiful, minimalist Streamlit frontend featuring an icon-centric persistent sidebar and real-time monitoring.
- **Built-in Token Billing**: Locally tracks exact LLM token usage and estimated costs so you never face surprise bills.
- **Multi-Language Support**: Fully localized in English, Simplified Chinese, Japanese, Korean, and Russian, with automatic browser language detection.

## Tech Stack 🛠️
- **Frontend**: Streamlit
- **Database**: PostgreSQL with SQLModel
- **AI Engine**: Google Gemini API (`google-generativeai`)
- **Scraping**: `feedparser`, `BeautifulSoup4`, `Playwright`
- **Routing**: [RSSHub](https://github.com/DIYgod/RSSHub) (Auto-converts social media URLs to clean RSS feeds)
- **Task Scheduling**: `schedule`

## Acknowledgments 🤝
- **Powered by RSSHub**: This project leverages the URL routing capabilities of the MIT-licensed [RSSHub](https://github.com/DIYgod/RSSHub) project to bypass anti-bot mechanisms on major social media platforms. All generated RSS endpoints default to the public instance, but users are encouraged to self-host.

## Quick Start 🚀

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/majorRSS.git
   cd majorRSS
   ```

2. **Install Dependencies**
   We use `pip-tools` to manage dependencies. `requirements.txt` contains pinned versions.
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
   *Note: If you add new dependencies to `requirements.in`, generate the lockfile via `pip-compile requirements.in`.*

3. **Configure Environment**
   Create a `.env` file in the root directory (or configure via the UI later):
   ```env
   GEMINI_API_KEY=your_google_gemini_api_key_here
   ```

4. **Run the System**
   ```bash
   # Windows:
   start_major_rss.bat
   
   # Linux / macOS:
   python scheduler.py &
   streamlit run ui/app.py
   ```

## Disclaimer ⚠️
This project is for educational and personal intelligence-gathering purposes only. Please respect the `robots.txt` and Terms of Service of the websites you scrape. The author is not responsible for any misuse.
