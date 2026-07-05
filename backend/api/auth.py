import os
import uuid
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone
from db.database import get_session, get_api_session
from db.models import AuthProfile
from backend.schemas import AuthProfileCreate, AuthProfileResponse
from db.config import get_cookie_path
from scrapers.auth_helper import interactive_login, check_cookie_health, live_check_cookie_health, AUTH_PLATFORMS

router = APIRouter(prefix="/auth/profiles", tags=["auth"])

@router.get("/", response_model=List[AuthProfileResponse])
def get_auth_profiles(session: Session = Depends(get_api_session)):
    profiles = session.exec(select(AuthProfile)).all()
    # Static check can only DOWNGRADE a profile (missing/unreadable cookie →
    # Expired). It must never flip Expired back to Active: a cookie file can
    # still contain the named cookie long after the platform stopped accepting
    # it, and scrape-time login-wall detection is the authoritative signal.
    # Active is only restored by re-login or a successful live check.
    modified = False
    for p in profiles:
        cookie_path = get_cookie_path(p.storage_ref)
        is_healthy = check_cookie_health(p.platform, cookie_path)
        if not is_healthy and p.status != "Expired":
            p.status = "Expired"
            p.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(p)
            modified = True
    if modified:
        session.commit()
        profiles = session.exec(select(AuthProfile)).all()
    return profiles

@router.post("/", response_model=AuthProfileResponse)
def create_auth_profile(profile_in: AuthProfileCreate, session: Session = Depends(get_api_session)):
    if profile_in.platform not in AUTH_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {profile_in.platform}")
        
    # Generate profile-scoped UUID reference
    profile_uuid = str(uuid.uuid4())
    # Example storage_ref: auth_profiles/twitter/uuid.dat
    # Note: we use forward slashes for cross-platform compatibility
    storage_ref = f"auth_profiles/{profile_in.platform}/{profile_uuid}.dat"
    
    # Pre-create the directory structure under app data directory
    full_cookie_path = get_cookie_path(storage_ref)
    os.makedirs(os.path.dirname(full_cookie_path), exist_ok=True)
    
    # We trigger the interactive login. But wait, interactive_login helper expects platform_key
    # and originally wrote to get_cookie_path(platform["cookie_file"]).
    # Let's mock or override the cookie output file for interactive login!
    # Let's import interactive_login and temporarily redirect its write target, or simply execute the login logic here
    # to write directly to the UUID storage_ref.
    from playwright.sync_api import sync_playwright
    import json
    
    platform = AUTH_PLATFORMS[profile_in.platform]
    success = False
    msg = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(platform["login_url"])
            print(f"Interactive Auth: Waiting for user to login to {platform['name']} and close the browser...")
            page.wait_for_event("close", timeout=0)
            
            state = context.storage_state()
            state_str = json.dumps(state)
            
            has_auth = False
            for c in state.get("cookies", []):
                if c.get("name") in platform["success_cookies"]:
                    has_auth = True
                    break
            
            if has_auth:
                from services.crypto_service import encrypt_data
                encrypted_bytes = encrypt_data(state_str)
                with open(full_cookie_path, 'wb') as f:
                    f.write(encrypted_bytes)
                # Invalidate pooled contexts so refreshed cookies take effect.
                try:
                    from services.browser_pool import bump_generation
                    bump_generation()
                except Exception:
                    pass
                success = True
                msg = f"Successfully authenticated {platform['name']}."
            else:
                msg = "Authorization did not complete successfully (required cookie not found)."
        except Exception as e:
            msg = f"Auth error: {e}"
        finally:
            if browser.is_connected():
                browser.close()
                
    if not success:
        if os.path.exists(full_cookie_path):
            try: os.remove(full_cookie_path)
            except: pass
        raise HTTPException(status_code=400, detail=msg)
        
    db_profile = AuthProfile(
        platform=profile_in.platform,
        display_name=profile_in.display_name,
        storage_ref=storage_ref,
        status="Active",
        last_checked_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    session.add(db_profile)
    session.commit()
    session.refresh(db_profile)
    return db_profile

@router.delete("/{profile_id}")
def delete_auth_profile(profile_id: int, session: Session = Depends(get_api_session)):
    profile = session.get(AuthProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Auth Profile not found")
        
    # Delete the profile-scoped session file safely
    full_cookie_path = get_cookie_path(profile.storage_ref)
    if os.path.exists(full_cookie_path):
        try:
            os.remove(full_cookie_path)
        except Exception as e:
            print(f"[ERROR] Failed to delete session file: {e}")
            
    session.delete(profile)
    session.commit()
    return {"message": f"Auth Profile {profile_id} deleted successfully"}

@router.post("/{profile_id}/test")
def test_auth_profile(profile_id: int, session: Session = Depends(get_api_session)):
    profile = session.get(AuthProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Auth Profile not found")

    cookie_path = get_cookie_path(profile.storage_ref)
    # Fast static gate first: no readable cookie file means Expired without
    # paying for a browser launch.
    if not check_cookie_health(profile.platform, cookie_path):
        is_healthy, message = False, "No valid session file"
    else:
        # Explicit user-triggered test: do a real headless visit and check for
        # a login wall — the only way to know the platform still accepts the
        # session. Returns None (inconclusive) on network failure.
        is_healthy, message = live_check_cookie_health(profile.platform, cookie_path)

    if is_healthy is not None:
        profile.status = "Active" if is_healthy else "Expired"
        profile.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(profile)
        session.commit()
        session.refresh(profile)

    return {"is_healthy": bool(is_healthy), "status": profile.status, "message": message}


@router.get("/{profile_id}/diagnostics")
def diagnose_auth_profile(profile_id: int, session: Session = Depends(get_api_session)):
    """Full-chain self-check for one profile, so 'is my auth working?' has a
    per-stage answer instead of a single opaque pass/fail. Each stage runs only
    if the previous passed; the first failing stage localizes the problem.
    Also folds in the account guard state (budget / circuit / utilization) so
    over-protection is as visible as breakage."""
    profile = session.get(AuthProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Auth Profile not found")

    cookie_path = get_cookie_path(profile.storage_ref)
    stages = []

    def stage(name, ok, detail):
        stages.append({"stage": name, "ok": ok, "detail": detail})
        return ok

    # 1. Session file exists on disk.
    exists = os.path.exists(cookie_path)
    stage("file_exists", exists, cookie_path if exists else "No session file at expected path")

    decrypt_ok = False
    if exists:
        # 2. File decrypts / parses to a storage state.
        try:
            from scrapers.auth_helper import _load_storage_state
            state = _load_storage_state(cookie_path)
            n_cookies = len(state.get("cookies", []))
            decrypt_ok = stage("decrypt", True, f"{n_cookies} cookies in session state")
        except Exception as e:
            stage("decrypt", False, f"Cannot decrypt/parse session file: {e}")

    static_ok = False
    if decrypt_ok:
        # 3. Required success cookie is present (static check).
        static_ok = stage("static_cookie", check_cookie_health(profile.platform, cookie_path),
                           "Required success cookie present" if check_cookie_health(profile.platform, cookie_path)
                           else "Required success cookie missing")

    if static_ok:
        # 4. Live visit: platform still accepts the session (no login wall).
        healthy, msg = live_check_cookie_health(profile.platform, cookie_path)
        if healthy is None:
            stage("live_visit", False, f"Inconclusive (network): {msg}")
        else:
            stage("live_visit", bool(healthy), msg)
            new_status = "Active" if healthy else "Expired"
            profile.status = new_status
            profile.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(profile); session.commit()

    # Account guard snapshot (utilization / circuit / budget).
    from services.account_guard import account_status
    guard = account_status(f"{profile.platform}:profile_{profile.id}")

    overall = all(s["ok"] for s in stages) if stages else False
    return {
        "profile_id": profile.id,
        "platform": profile.platform,
        "overall_ok": overall,
        "stages": stages,
        "account_guard": guard,
    }
