import os
import uuid
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone
from db.database import get_session
from db.models import AuthProfile
from backend.schemas import AuthProfileCreate, AuthProfileResponse
from db.config import get_cookie_path
from scrapers.auth_helper import interactive_login, check_cookie_health, AUTH_PLATFORMS

router = APIRouter(prefix="/auth/profiles", tags=["auth"])

@router.get("/", response_model=List[AuthProfileResponse])
def get_auth_profiles(session: Session = Depends(get_session)):
    profiles = session.exec(select(AuthProfile)).all()
    # Statically check health of each profile
    modified = False
    for p in profiles:
        cookie_path = get_cookie_path(p.storage_ref)
        is_healthy = check_cookie_health(p.platform, cookie_path)
        new_status = "Active" if is_healthy else "Expired"
        if p.status != new_status:
            p.status = new_status
            p.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(p)
            modified = True
    if modified:
        session.commit()
        profiles = session.exec(select(AuthProfile)).all()
    return profiles

@router.post("/", response_model=AuthProfileResponse)
def create_auth_profile(profile_in: AuthProfileCreate, session: Session = Depends(get_session)):
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
def delete_auth_profile(profile_id: int, session: Session = Depends(get_session)):
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
def test_auth_profile(profile_id: int, session: Session = Depends(get_session)):
    profile = session.get(AuthProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Auth Profile not found")
        
    cookie_path = get_cookie_path(profile.storage_ref)
    is_healthy = check_cookie_health(profile.platform, cookie_path)
    
    profile.status = "Active" if is_healthy else "Expired"
    profile.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    
    return {"is_healthy": is_healthy, "status": profile.status}
