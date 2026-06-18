import re
import urllib.parse

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
