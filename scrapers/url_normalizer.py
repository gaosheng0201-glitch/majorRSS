"""
URL Normalizer for MajorRSS
Transparently maps social media URLs to RSSHub endpoints to bypass anti-bot mechanisms.

Acknowledgments:
This module leverages the routing logic of the MIT-licensed RSSHub project (https://github.com/DIYgod/RSSHub).
"""

import os
import re
import urllib.parse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

def get_rsshub_base():
    return os.environ.get("RSSHUB_BASE_URL", "https://rsshub.app").rstrip("/")

def auto_route(url: str) -> str:
    """
    Sniffs the provided URL. If it matches a known social media profile,
    it seamlessly transforms it into an RSSHub endpoint.
    Otherwise, returns the original URL.
    """
    if not url:
        return url
        
    base = get_rsshub_base()
    
    # 1. Bilibili (space.bilibili.com/{uid})
    bilibili_match = re.search(r'space\.bilibili\.com/(\d+)', url)
    if bilibili_match:
        uid = bilibili_match.group(1)
        return f"{base}/bilibili/user/video/{uid}"
        
    # 2. Twitter / X (twitter.com/{user} or x.com/{user})
    # Ignore status/post URLs as they are not user profiles
    twitter_match = re.search(r'(?:twitter\.com|x\.com)/([^/]+)/?$', url)
    if twitter_match and twitter_match.group(1).lower() not in ['home', 'explore', 'notifications', 'messages']:
        user = twitter_match.group(1)
        return f"{base}/twitter/user/{user}"
        
    # 3. Weibo (weibo.com/u/{uid} or weibo.com/{user})
    weibo_u_match = re.search(r'weibo\.com/u/(\d+)', url)
    if weibo_u_match:
        uid = weibo_u_match.group(1)
        return f"{base}/weibo/user/{uid}"
        
    # 4. YouTube
    # Channel ID
    yt_channel_match = re.search(r'youtube\.com/channel/([^/]+)', url)
    if yt_channel_match:
        cid = yt_channel_match.group(1)
        return f"{base}/youtube/channel/{cid}"
    # Custom URL (@handle)
    yt_custom_match = re.search(r'youtube\.com/(@[^/]+)', url)
    if yt_custom_match:
        handle = yt_custom_match.group(1)
        return f"{base}/youtube/custom/{handle}"
        
    # 5. TikTok (tiktok.com/@{user})
    tiktok_match = re.search(r'tiktok\.com/(@[^/]+)', url)
    if tiktok_match:
        # RSSHub uses the username without the @ for TikTok sometimes, but /tiktok/user/username
        user = tiktok_match.group(1).lstrip('@')
        return f"{base}/tiktok/user/{user}"
        
    # 6. Xiaohongshu (xiaohongshu.com/user/profile/{uid})
    xhs_match = re.search(r'xiaohongshu\.com/user/profile/([^/]+)', url)
    if xhs_match:
        uid = xhs_match.group(1)
        return f"{base}/xiaohongshu/user/{uid}"

    # If no match, return original URL
    return url

def is_rss_url(url: str) -> bool:
    """
    Checks if a URL is likely an RSS feed based on its extension or presence of rsshub.
    """
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if path.endswith('.xml') or path.endswith('.rss') or path.endswith('.atom'):
        return True
    
    base = get_rsshub_base()
    base_netloc = urllib.parse.urlparse(base).netloc
    if parsed.netloc == base_netloc:
        return True
        
    return False
