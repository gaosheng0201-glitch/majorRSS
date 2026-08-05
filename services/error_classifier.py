"""
Maps raw exceptions to the stable error taxonomy defined in
docs/pipeline_refactor_direction.md, so the UI can suggest a concrete action
(re-authorize, lower frequency, switch RSSHub instance, ...) instead of
showing every failure as an opaque "Probe Failed".
"""

AUTH_EXPIRED = "AUTH_EXPIRED"
RATE_LIMITED = "RATE_LIMITED"
CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
RSS_PARSE_FAILED = "RSS_PARSE_FAILED"
NETWORK_ERROR = "NETWORK_ERROR"
ENCODING_ERROR = "ENCODING_ERROR"
UNKNOWN_ERROR = "UNKNOWN_ERROR"
# Our side is missing something the fetch needs (today: a Playwright browser).
# Distinct from every other type here because the source did nothing wrong and
# no source could have avoided it — see NOT_ENDPOINT_FAULT in scraper_service.
CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"

_CAPABILITY_HINTS = ("browsers are not installed", "executable doesn't exist",
                     "playwright install", "browsertype.launch")
_RATE_LIMIT_HINTS = ("429", "rate limit", "too many requests", "quota")
_CAPTCHA_HINTS = ("captcha", "challenge", "cloudflare", "verify you are human")
_UNAVAILABLE_HINTS = ("403", "404", "410", "500", "502", "503", "504", "gone", "forbidden", "not found")
_PARSE_HINTS = ("bozo", "not well-formed", "syntax error", "xml", "malformed", "no parseable feed", "parse")
_NETWORK_HINTS = (
    "timeout", "timed out", "connection", "dns", "ssl", "eof", "reset",
    "refused", "unreachable", "getaddrinfo", "net::", "proxy",
)


def classify_error(exc: Exception) -> str:
    """Best-effort classification from exception type and message."""
    # Local import to avoid a hard dependency cycle at module load time.
    try:
        from scrapers.tier3_agentic import CookieExpiredException
        if isinstance(exc, CookieExpiredException):
            return AUTH_EXPIRED
    except Exception:
        pass

    if isinstance(exc, (UnicodeEncodeError, UnicodeDecodeError)):
        return ENCODING_ERROR

    msg = f"{type(exc).__name__}: {exc}".lower()

    # Checked first: a missing browser is our fault, and must not be mistaken
    # for the source being unavailable just because its message mentions a path.
    if any(h in msg for h in _CAPABILITY_HINTS):
        return CAPABILITY_UNAVAILABLE
    if any(h in msg for h in _RATE_LIMIT_HINTS):
        return RATE_LIMITED
    if any(h in msg for h in _CAPTCHA_HINTS):
        return CAPTCHA_REQUIRED
    if any(h in msg for h in _NETWORK_HINTS):
        return NETWORK_ERROR
    if any(h in msg for h in _UNAVAILABLE_HINTS):
        return SOURCE_UNAVAILABLE
    if any(h in msg for h in _PARSE_HINTS):
        return RSS_PARSE_FAILED
    return UNKNOWN_ERROR


def format_error(exc: Exception, max_len: int = 200) -> str:
    """'<TYPE>: <message>' — the string stored in PipelineEvent.error."""
    return f"{classify_error(exc)}: {exc}"[:max_len]
