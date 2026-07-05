import time
import os
import json
import hashlib

from services.log_service import get_logger
from services.browser_pool import acquire_page
from services.content_extract import extract_main_text

logger = get_logger("scraper.tier3")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class CookieExpiredException(Exception):
    pass


class AgenticScraper:
    """
    Tier 3 Scraper: Agentic Scraper.
    Renders JS via a pooled, persistent browser context (fingerprint-stable per
    account, cheap to reuse) and extracts clean main-content text for the LLM.
    """
    def __init__(self, url: str, cookie_string: str = None):
        self.url = url
        self.cookie_string = cookie_string

    def _resolve_auth(self):
        """Returns (detected_platform, cookie_file, storage_state, context_key)."""
        from scrapers.auth_helper import AUTH_PLATFORMS
        detected_platform = None
        detected_key = None
        for key, platform in AUTH_PLATFORMS.items():
            if any(d in self.url for d in platform["domains"]):
                detected_platform = platform
                detected_key = key
                break

        cookie_file = None
        storage_state = None
        context_key = None  # None → shared anonymous context

        if detected_platform:
            from db.config import get_cookie_path
            cookie_file = get_cookie_path(detected_platform["cookie_file"])
            if cookie_file and os.path.exists(cookie_file) and not self.cookie_string:
                try:
                    with open(cookie_file, 'rb') as f:
                        content = f.read()
                    try:
                        from services.crypto_service import decrypt_data
                        storage_state = json.loads(decrypt_data(content))
                    except Exception:
                        storage_state = json.loads(content.decode('utf-8'))
                    # One reusable context per platform account.
                    context_key = f"platform:{detected_key}"
                except Exception as e:
                    logger.error(f"Failed to load secure cookie: {e}")

        if self.cookie_string and context_key is None:
            # Keep cookie-string sessions on their own stable context too.
            context_key = "cookiestr:" + hashlib.sha256(self.cookie_string.encode()).hexdigest()[:12]

        return detected_platform, cookie_file, storage_state, context_key

    def _drive_page(self, page, detected_platform, cookie_file, storage_state, has_storage) -> str:
        page.goto(self.url, wait_until="networkidle", timeout=60000)

        if detected_platform:
            from scrapers.auth_helper import detect_login_wall
            try:
                page_text = page.inner_text("body")
            except Exception:
                page_text = ""
            matched = detect_login_wall(detected_platform, page.url, page_text)
            if matched:
                raise CookieExpiredException(
                    f"{detected_platform['name']} Cookie 已过期或失效（检测到 {matched}），请前往设置重新一键授权。")

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        html = page.content()

        # Persist rotated session cookies: platforms refresh session tokens on
        # use, so saving the live context state after each authenticated visit
        # keeps the login alive far longer than the originally captured cookies.
        if has_storage and cookie_file:
            try:
                from services.crypto_service import encrypt_data
                new_state = page.context.storage_state()
                with open(cookie_file, 'wb') as f:
                    f.write(encrypt_data(json.dumps(new_state)))
                logger.info(f"Refreshed session state for {detected_platform['name']} after successful visit.")
            except Exception as e:
                logger.warning(f"Failed to persist rotated cookies: {e}")

        return html

    def _add_cookie_string(self, page):
        if not self.cookie_string:
            return
        import urllib.parse
        domain = "." + urllib.parse.urlparse(self.url).netloc.replace("www.", "")
        cookies = []
        for chunk in self.cookie_string.split(";"):
            if "=" in chunk:
                name, val = chunk.strip().split("=", 1)
                cookies.append({"name": name, "value": val, "domain": domain, "path": "/"})
        if cookies:
            page.context.add_cookies(cookies)

    def fetch_text_snapshot(self, return_html: bool = False) -> str:
        logger.info(f"Agentic Scraper fetching {self.url}...")
        detected_platform, cookie_file, storage_state, context_key = self._resolve_auth()
        has_storage = storage_state is not None

        # Preferred path: pooled persistent context (reused browser, stable
        # fingerprint). Fall back to a one-off browser only if the pool errors,
        # so a pool problem never silently loses a scrape.
        try:
            with acquire_page(context_key=context_key, storage_state=storage_state, user_agent=_UA) as page:
                if self.cookie_string:
                    self._add_cookie_string(page)
                html = self._drive_page(page, detected_platform, cookie_file, storage_state, has_storage)
        except CookieExpiredException:
            raise
        except Exception as e:
            logger.warning(f"Pooled fetch failed ({e}); falling back to one-off browser.")
            html = self._fetch_one_off(detected_platform, cookie_file, storage_state, has_storage)

        if not html:
            return ""
        if return_html:
            return html
        return extract_main_text(html)

    def _fetch_one_off(self, detected_platform, cookie_file, storage_state, has_storage) -> str:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                kwargs = {"user_agent": _UA, "viewport": {"width": 1280, "height": 800}}
                if storage_state:
                    kwargs["storage_state"] = storage_state
                context = browser.new_context(**kwargs)
                page = context.new_page()
                if self.cookie_string:
                    self._add_cookie_string(page)
                return self._drive_page(page, detected_platform, cookie_file, storage_state, has_storage)
            finally:
                browser.close()
