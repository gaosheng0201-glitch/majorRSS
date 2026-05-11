import requests
import re
from urllib.parse import urljoin

def probe_url_for_tier(url: str) -> tuple[int, str, str]:
    """
    Probes a URL to automatically determine the best scraping tier.
    Returns:
        tier (int): 1 (RSS), 2 (API/Mirror), or 3 (Agentic HTML)
        resolved_url (str): The best URL to use (e.g. replacing HTML with the discovered RSS link)
        message (str): A user-friendly message explaining the decision
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        # Check if it's already an XML/RSS feed
        content_type = response.headers.get("Content-Type", "").lower()
        content_start = response.text[:500].lower()
        
        if "xml" in content_type or "<rss" in content_start or "<feed" in content_start:
            return 1, url, "直接侦测到标准 RSS/XML 格式，已自动配置为基础直连 (Tier 1)。"
            
        # It's an HTML page, search for alternate RSS/Atom links
        rss_link_pattern = re.compile(r'<link\s+[^>]*rel=["\']alternate["\'][^>]*type=["\']application/(rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
        # Handle case where href comes before rel/type
        rss_link_pattern_2 = re.compile(r'<link\s+[^>]*href=["\']([^"\']+)["\'][^>]*type=["\']application/(rss|atom)\+xml["\']', re.IGNORECASE)
        
        match = rss_link_pattern.search(response.text)
        if not match:
            match = rss_link_pattern_2.search(response.text)
            href = match.group(1) if match else None
        else:
            href = match.group(2)
            
        if href:
            # Resolve relative URLs
            absolute_rss_url = urljoin(url, href)
            return 1, absolute_rss_url, "从网页底层挖掘出隐藏的 RSS 订阅源，已自动优化路径为基础直连 (Tier 1)。"
            
        # If no RSS link is found, fallback to Agentic Scraper
        return 3, url, "普通网页且无隐藏订阅源，已自动分配智能体无头浏览器 (Tier 3) 进行视觉快照解析。"
        
    except Exception as e:
        # If network error or blocked, use Agentic Scraper as fallback since Playwright might bypass it
        return 3, url, f"网络直连受阻 ({type(e).__name__})，已自动调度无头浏览器智能体 (Tier 3) 强行突破抓取。"

if __name__ == "__main__":
    # Test cases
    print(probe_url_for_tier("https://www.theverge.com/rss/index.xml"))
    print(probe_url_for_tier("https://news.ycombinator.com/"))
