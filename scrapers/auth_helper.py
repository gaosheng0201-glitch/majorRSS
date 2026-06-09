import os
import json
from playwright.sync_api import sync_playwright

AUTH_PLATFORMS = {
    "twitter": {
        "name": "Twitter / X",
        "login_url": "https://twitter.com/login",
        "cookie_file": "twitter_cookies.json",
        "success_cookies": ["auth_token"],
        "domains": ["twitter.com", "x.com"],
        "expired_indicators": ["/i/flow/login", "Log in to X"]
    },
    "instagram": {
        "name": "Instagram",
        "login_url": "https://www.instagram.com/accounts/login/",
        "cookie_file": "instagram_cookies.json",
        "success_cookies": ["sessionid"],
        "domains": ["instagram.com"],
        "expired_indicators": ["/accounts/login/", "Log In"]
    },
    "reddit": {
        "name": "Reddit",
        "login_url": "https://www.reddit.com/login/",
        "cookie_file": "reddit_cookies.json",
        "success_cookies": ["reddit_session", "session_tracker"],
        "domains": ["reddit.com"],
        "expired_indicators": ["/login", "Log in"]
    },
    "linkedin": {
        "name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "cookie_file": "linkedin_cookies.json",
        "success_cookies": ["li_at"],
        "domains": ["linkedin.com"],
        "expired_indicators": ["/uas/login", "Sign in"]
    },
    "bilibili": {
        "name": "Bilibili (B站)",
        "login_url": "https://passport.bilibili.com/login",
        "cookie_file": "bilibili_cookies.json",
        "success_cookies": ["SESSDATA"],
        "domains": ["bilibili.com"],
        "expired_indicators": ["passport.bilibili.com/login"]
    },
    "xiaohongshu": {
        "name": "Xiaohongshu (小红书)",
        "login_url": "https://www.xiaohongshu.com/explore",
        "cookie_file": "xiaohongshu_cookies.json",
        "success_cookies": ["web_session"],
        "domains": ["xiaohongshu.com"],
        "expired_indicators": ["/explore", "登录"]
    },
    "weibo": {
        "name": "Weibo (微博)",
        "login_url": "https://weibo.com/login.php",
        "cookie_file": "weibo_cookies.json",
        "success_cookies": ["SUB"],
        "domains": ["weibo.com", "weibo.cn"],
        "expired_indicators": ["/login.php"]
    },
    "tiktok": {
        "name": "TikTok",
        "login_url": "https://www.tiktok.com/login",
        "cookie_file": "tiktok_cookies.json",
        "success_cookies": ["sessionid", "sid_tt"],
        "domains": ["tiktok.com"],
        "expired_indicators": ["/login"]
    },
    "vk": {
        "name": "VKontakte (VK)",
        "login_url": "https://vk.com/login",
        "cookie_file": "vk_cookies.json",
        "success_cookies": ["remixsid"],
        "domains": ["vk.com"],
        "expired_indicators": ["/login"]
    },
    "naver": {
        "name": "Naver (네이버)",
        "login_url": "https://nid.naver.com/nidlogin.login",
        "cookie_file": "naver_cookies.json",
        "success_cookies": ["NID_SES"],
        "domains": ["naver.com"],
        "expired_indicators": ["nidlogin.login"]
    },
    "niconico": {
        "name": "Niconico (ニコニコ)",
        "login_url": "https://account.nicovideo.jp/login",
        "cookie_file": "niconico_cookies.json",
        "success_cookies": ["user_session"],
        "domains": ["nicovideo.jp"],
        "expired_indicators": ["/login"]
    }
}

def check_cookie_health(platform_key: str, cookie_path: str) -> bool:
    """
    Statically checks if the saved cookie JSON contains the required success_cookies.
    Supports both DPAPI encrypted and plaintext cookie files.
    """
    if not os.path.exists(cookie_path):
        return False
    try:
        platform = AUTH_PLATFORMS.get(platform_key)
        if not platform: return False
        
        with open(cookie_path, 'rb') as f:
            content = f.read()
            
        try:
            from services.crypto_service import decrypt_data
            decrypted = decrypt_data(content)
            state = json.loads(decrypted)
        except Exception:
            state = json.loads(content.decode('utf-8'))
            
        for c in state.get("cookies", []):
            if c.get("name") in platform["success_cookies"]:
                return True
        return False
    except Exception:
        return False


def interactive_login(platform_key: str):
    """
    Launches a headful browser to allow the user to log in manually to the specific platform.
    Waits for the user to close the browser, then saves the storage state securely.
    Returns:
        tuple (bool, str): (Success, Message)
    """
    if platform_key not in AUTH_PLATFORMS:
        return False, f"❌ 未知的平台标识符: {platform_key}"
        
    platform = AUTH_PLATFORMS[platform_key]
    from db.config import get_cookie_path
    output_file = get_cookie_path(platform["cookie_file"])
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(platform["login_url"])
            print(f"Interactive Auth: Waiting for user to login to {platform['name']} and close the browser...")
            
            # Wait for the user to close the page
            page.wait_for_event("close", timeout=0)
            
            # Save storage state in memory
            state = context.storage_state()
            state_str = json.dumps(state)
            
            has_auth = False
            for c in state.get("cookies", []):
                if c.get("name") in platform["success_cookies"]:
                    has_auth = True
                    break
            
            if has_auth:
                # Encrypt and save
                from services.crypto_service import encrypt_data
                encrypted_bytes = encrypt_data(state_str)
                with open(output_file, 'wb') as f:
                    f.write(encrypted_bytes)
                return True, f"✅ 授权成功！已保存 {platform['name']} 的核心登录凭证。"
            else:
                if os.path.exists(output_file):
                    os.remove(output_file)
                return False, f"❌ 授权可能未完成：未在保存的状态中检测到有效的 {platform['name']} 认证 Cookie。请确保您已完全登录。"
                
        except Exception as e:
            if os.path.exists(output_file):
                try: os.remove(output_file)
                except: pass
            return False, f"❌ 授权过程发生错误: {e}"
        finally:
            if browser.is_connected():
                browser.close()
