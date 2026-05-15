from playwright.sync_api import sync_playwright
import time
from bs4 import BeautifulSoup

class CookieExpiredException(Exception):
    pass

class AgenticScraper:
    """
    Tier 3 Scraper: Agentic Scraper
    Uses Playwright to render Javascript and bypass basic anti-bot screens,
    then extracts clean text to be consumed by an LLM for 'reading comprehension'.
    """
    def __init__(self, url: str, cookie_string: str = None):
        self.url = url
        self.cookie_string = cookie_string
        
    def fetch_text_snapshot(self, return_html: bool = False) -> str:
        print(f"Agentic Scraper launching browser for {self.url}...")
        import os
        from scrapers.auth_helper import AUTH_PLATFORMS
        
        # Detect platform
        detected_platform_key = None
        detected_platform = None
        for key, platform in AUTH_PLATFORMS.items():
            if any(d in self.url for d in platform["domains"]):
                detected_platform_key = key
                detected_platform = platform
                break
                
        cookie_file = None
        if detected_platform:
            cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", detected_platform["cookie_file"])
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Load specific platform cookie file if exists and no manual override
            if detected_platform and cookie_file and os.path.exists(cookie_file) and not self.cookie_string:
                context = browser.new_context(
                    storage_state=cookie_file,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            else:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                if self.cookie_string:
                    import urllib.parse
                    domain = "." + urllib.parse.urlparse(self.url).netloc.replace("www.", "")
                    cookies = []
                    for chunk in self.cookie_string.split(";"):
                        if "=" in chunk:
                            name, val = chunk.strip().split("=", 1)
                            cookies.append({"name": name, "value": val, "domain": domain, "path": "/"})
                    if cookies:
                        context.add_cookies(cookies)
                    
            page = context.new_page()
            try:
                # Wait for network idle to ensure JS has loaded
                page.goto(self.url, wait_until="networkidle", timeout=60000)
                
                # Check for platform-specific expired login walls
                if detected_platform:
                    for indicator in detected_platform.get("expired_indicators", []):
                        if indicator in page.url or indicator in page.content():
                            raise CookieExpiredException(f"{detected_platform['name']} Cookie 已过期或失效，请前往设置重新一键授权。")
                        
                # Simple human-like scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                
                html = page.content()
            except CookieExpiredException as ce:
                raise ce
            except Exception as e:
                print(f"Error scraping {self.url}: {e}")
                html = ""
            finally:
                browser.close()
            
            if not html:
                return ""
                
            if return_html:
                return html
                
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
