import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper

def test_tier1():
    print("--- Testing Tier 1 (Basic RSS) ---")
    scraper = BasicRSSScraper("https://news.ycombinator.com/rss")
    results = scraper.fetch()
    print(f"Fetched {len(results)} items.")
    if results:
        print(f"Sample Item 1 Title: {results[0]['title']}")
        print(f"Sample Item 1 URL: {results[0]['url']}")
    print("-" * 40)

def test_tier3():
    print("--- Testing Tier 3 (Agentic Playwright) ---")
    scraper = AgenticScraper("https://github.com/trending")
    text = scraper.fetch_text_snapshot()
    print(f"Extracted Text Length: {len(text)} characters.")
    print("Sample Content (first 200 chars):")
    print(text[:200].replace('\n', ' | '))
    print("-" * 40)

if __name__ == "__main__":
    test_tier1()
    test_tier3()
