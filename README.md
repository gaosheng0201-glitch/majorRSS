# MajorRSS 📡 `v1.0.0`

MajorRSS is an intelligent, automated intelligence-gathering and AI-denoising platform. It transforms raw, chaotic information streams (from RSS, web pages, to headless browser scraping) into a highly structured, high-value intelligence dashboard using Google's Gemini models.

## Features ✨
- **Multi-Tier Scraping Architecture**: From simple RSS parsing to advanced headless browser (Playwright) agentic scraping, bypassing complex anti-bot measures.
- **AI-Powered Denoising**: Uses Google Gemini 1.5 Flash for high-frequency text cleaning, translation, and entity extraction.
- **Automated Daily Briefings**: Uses Gemini 1.5 Pro to synthesize massive amounts of daily intelligence into a concise, readable global briefing.
- **Supabase-Style Dashboard**: A beautiful, minimalist Streamlit frontend featuring an icon-centric persistent sidebar and real-time monitoring.
- **Built-in Token Billing**: Locally tracks exact LLM token usage and estimated costs so you never face surprise bills.
- **Multi-Language Support**: Fully localized in English, Simplified Chinese, Japanese, Korean, and Russian, with automatic browser language detection.

## Tech Stack 🛠️
- **Frontend**: Streamlit
- **Database**: SQLite with SQLModel
- **AI Engine**: Google Gemini API (`google-generativeai`)
- **Scraping**: `feedparser`, `BeautifulSoup4`, `Playwright`
- **Task Scheduling**: `schedule`

## Quick Start 🚀

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/majorRSS.git
   cd majorRSS
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

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
   python worker.py &
   streamlit run ui/app.py
   ```

## Disclaimer ⚠️
This project is for educational and personal intelligence-gathering purposes only. Please respect the `robots.txt` and Terms of Service of the websites you scrape. The author is not responsible for any misuse.
