"""Source health, error classification, crypto, extraction, humanized pacing."""
from datetime import datetime, timedelta

from services import source_health as sh
from services import error_classifier as ec
from services import crypto_service as cs
from services.content_extract import extract_main_text
from services.humanized import in_quiet_window, jitter_delay_seconds


def test_route_key_isolates_search_endpoints():
    k1 = sh.route_key("https://news.google.com/rss/search?q=apple")
    k2 = sh.route_key("https://news.google.com/rss/search?q=bitcoin")
    assert k1 != k2  # one failing search must not back off the other


def test_source_health_backoff_isolation():
    k1 = sh.route_key("https://news.google.com/rss/search?q=apple-hc")
    k2 = sh.route_key("https://news.google.com/rss/search?q=btc-hc")
    t0 = datetime(2026, 7, 6, 12, 0, 0)
    sh.record_failure(k1, "NETWORK_ERROR", now=t0)
    assert sh.should_skip(k1, now=t0 + timedelta(seconds=30))[0]
    assert not sh.should_skip(k2, now=t0 + timedelta(seconds=30))[0]


def test_error_classification():
    assert ec.classify_error(Exception("HTTP 429 Too Many Requests")) == ec.RATE_LIMITED
    assert ec.classify_error(Exception("connection timed out")) == ec.NETWORK_ERROR
    assert ec.classify_error(Exception("captcha challenge required")) == ec.CAPTCHA_REQUIRED
    assert ec.classify_error(UnicodeDecodeError("utf-8", b"", 0, 1, "bad")) == ec.ENCODING_ERROR


def test_crypto_roundtrip_and_legacy():
    import base64
    enc = cs.encrypt_data("secret-value-xyz")
    assert b"secret-value" not in enc  # actually encrypted, not reversible base64
    assert cs.decrypt_data(enc) == "secret-value-xyz"
    # Legacy base64 files still open (migration path).
    assert cs.decrypt_data(base64.b64encode(b"legacy")) == "legacy"
    assert cs.encrypt_data("") == b"" and cs.decrypt_data(b"") == ""


def test_readability_strips_chrome():
    html = ("<html><body><nav><a href=/>Home</a><a href=/login>Log in</a></nav>"
            "<article class=post><h1>Title</h1><p>The quick brown fox jumps over "
            "the lazy dog, repeatedly and clearly.</p></article>"
            "<footer>Cookie settings. Subscribe now!</footer></body></html>")
    text = extract_main_text(html)
    assert "quick brown fox" in text
    assert "Cookie settings" not in text and "Log in" not in text


def test_quiet_window_and_jitter():
    assert in_quiet_window(datetime(2026, 7, 6, 3, 0)) is True    # default 02-07
    assert in_quiet_window(datetime(2026, 7, 6, 12, 0)) is False
    # wrap past midnight
    assert in_quiet_window(datetime(2026, 7, 6, 23, 30), start_hour=23, end_hour=5) is True
    d1 = jitter_delay_seconds("twitter:1")
    assert d1 == jitter_delay_seconds("twitter:1")            # deterministic per key
    assert jitter_delay_seconds("weibo:2") != d1              # varies across sources
