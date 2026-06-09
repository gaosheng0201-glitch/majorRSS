import sys
import os
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def run_tests():
    print("========================================")
    print("      MajorRSS Core Sanity Check        ")
    print("========================================\n")
    
    passed = 0
    failed = 0

    def assert_test(name, condition, error_msg=""):
        nonlocal passed, failed
        if condition:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name} - {error_msg}")
            failed += 1

    # 1. Test URL Normalizer (RSSHub Sniffing)
    print("--- 1. Testing URL Normalizer ---")
    try:
        from scrapers.url_normalizer import auto_route, is_rss_url, get_rsshub_base
        base = get_rsshub_base()
        
        url_bili = "https://space.bilibili.com/2267573"
        routed_bili = auto_route(url_bili)
        assert_test("Bilibili Routing", routed_bili == f"{base}/bilibili/user/video/2267573")
        
        url_twitter = "https://twitter.com/elonmusk"
        routed_twitter = auto_route(url_twitter)
        assert_test("Twitter Routing", routed_twitter == f"{base}/twitter/user/elonmusk")
        
        url_normal = "https://example.com"
        assert_test("Normal URL ignored", auto_route(url_normal) == url_normal)
        
        assert_test("is_rss_url with RSSHub", is_rss_url(f"{base}/twitter/user/elonmusk"))
        assert_test("is_rss_url with .xml", is_rss_url("https://example.com/feed.xml"))
        assert_test("is_rss_url with normal HTML", not is_rss_url("https://example.com"))
    except Exception as e:
        assert_test("URL Normalizer Tests", False, str(e))
        
    print("\n--- 2. Testing HTML Diff Engine ---")
    try:
        from worker_subscription import clean_html_for_diff
        html1 = "<html><body><h1>Title</h1><p>Test Content</p><span>Noise 123</span></body></html>"
        html2 = "<html><body><h1>Title</h1><p>Updated Content</p><span>Noise 456</span></body></html>"
        
        clean1 = clean_html_for_diff(html1)
        clean2 = clean_html_for_diff(html2)
        
        assert_test("Diff Engine parses text", "TEXT: Title" in clean1 and "TEXT: Test Content" in clean1)
        assert_test("Diff Engine ignores noise", "Noise" not in clean1)
        assert_test("Diff Engine detects changes", clean1 != clean2)
    except Exception as e:
        assert_test("Diff Engine Tests", False, str(e))
        
    print("\n--- 3. Testing Database Connection ---")
    try:
        from db.database import get_session
        from db.models import Tracker
        from sqlmodel import select
        
        with get_session() as session:
            # Create a mock tracker
            mock_tracker = Tracker(name="Sanity_Test_Tracker", tracker_type="URL", target="https://test.com", radar_section="TEST")
            session.add(mock_tracker)
            session.commit()
            
            # Fetch it
            db_tracker = session.exec(select(Tracker).where(Tracker.name == "Sanity_Test_Tracker")).first()
            assert_test("DB Insert & Select", db_tracker is not None)
            
            # Clean up
            session.delete(db_tracker)
            session.commit()
            assert_test("DB Delete", True)
    except Exception as e:
        assert_test("Database Tests", False, str(e))
        
    print("\n--- 4. Testing Scraper Service (Tier 1) ---")
    try:
        from scrapers.tier1_rss import BasicRSSScraper
        scraper = BasicRSSScraper("https://hnrss.org/newest?count=3")
        items = scraper.fetch()
        assert_test("RSS Scraper fetches items", len(items) > 0)
        if len(items) > 0:
            assert_test("RSS Item has required fields", 'title' in items[0] and 'url' in items[0])
    except Exception as e:
        assert_test("Scraper Service Tests", False, str(e))
        
    print("\n========================================")
    print(f"Summary: {passed} PASSED, {failed} FAILED")
    print("========================================")
    
if __name__ == "__main__":
    run_tests()
