from playwright.sync_api import sync_playwright
import time
from bs4 import BeautifulSoup

class AgenticScraper:
    """
    Tier 3 Scraper: Agentic Scraper
    Uses Playwright to render Javascript and bypass basic anti-bot screens,
    then extracts clean text to be consumed by an LLM for 'reading comprehension'.
    """
    def __init__(self, url: str):
        self.url = url
        
    def fetch_text_snapshot(self) -> str:
        print(f"Agentic Scraper launching browser for {self.url}...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            try:
                # Wait for network idle to ensure JS has loaded
                page.goto(self.url, wait_until="networkidle", timeout=60000)
                
                # Simple human-like scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                
                html = page.content()
            except Exception as e:
                print(f"Error scraping {self.url}: {e}")
                html = ""
            finally:
                browser.close()
            
            if not html:
                return ""
                
            # Extract plain text from HTML to save LLM tokens
            soup = BeautifulSoup(html, 'html.parser')
            # Remove scripts, styles, header, footer, nav
            for el in soup(["script", "style", "nav", "header", "footer", "aside"]):
                el.extract()
            text = soup.get_text(separator='\n')
            
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text
