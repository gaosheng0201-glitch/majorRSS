import re
import urllib.parse

# PII patterns for the publish compliance gate (publish_contract.md §6.3).
# Conservative redaction of things that must never leave the machine in a public
# digest: emails, phone numbers, government IDs, and precise coordinates.
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
# Chinese mainland ID (18 digits) and passport-ish; generic long digit runs.
_CN_ID_RE = re.compile(r'\b\d{17}[\dXx]\b')
# Phone: intl +country or CN mobile 1xx-xxxx-xxxx / grouped digits (loose but
# only fires on phone-shaped runs, not on years/counts).
_PHONE_RE = re.compile(r'(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:1[3-9]\d{9}|\d{3}[\s-]\d{3,4}[\s-]\d{4})(?!\d)')
# Lat,long coordinate pairs.
_COORD_RE = re.compile(r'[-+]?\d{1,3}\.\d{3,},\s*[-+]?\d{1,3}\.\d{3,}')


def clean_pii(text: str) -> str:
    """Redact PII before content leaves the machine for public distribution.
    Order matters: coordinates and IDs before the looser phone pattern."""
    if not text:
        return ""
    try:
        text = _EMAIL_RE.sub('[email]', text)
        text = _COORD_RE.sub('[location]', text)
        text = _CN_ID_RE.sub('[id]', text)
        text = _PHONE_RE.sub('[phone]', text)
        return text
    except Exception:
        return text


def desensitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        clean_path = parsed.path
        if len(clean_path) > 30:
            clean_path = clean_path[:15] + "..." + clean_path[-15:]
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}"
    except:
        return url[:30] + "..."

def scrub_sensitive_info(text: str) -> str:
    if not text:
        return ""
    # Regex to match http/https URLs
    url_pattern = re.compile(r'https?://[^\s()<>]+')
    
    def replace_url(match):
        u = match.group(0)
        return desensitize_url(u)
        
    try:
        scrubbed = url_pattern.sub(replace_url, text)
        scrubbed = re.sub(r'(?i)(token|key|cookie|auth|password|secret|credential|pass|pwd|sign|signature)=[^\s&,;?\'"]+', r'\1=[REDACTED]', scrubbed)
        return scrubbed
    except:
        return text[:100]
