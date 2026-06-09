import os
import sys
import json
from services.crypto_service import encrypt_data, decrypt_data

def get_app_data_dir() -> str:
    """
    Returns the persistent application data directory.
    - Packaged mode: ~/.majorss
    - Development mode: Root workspace directory
    """
    if getattr(sys, 'frozen', False):
        app_data_dir = os.path.join(os.path.expanduser("~"), ".majorss")
        os.makedirs(app_data_dir, exist_ok=True)
        return app_data_dir
    
    # Dev mode: use current workspace root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    return root_dir

def get_env_path() -> str:
    """
    Returns the path to the environment/configuration file.
    In packaged mode, this resides in ~/.majorss/.env.
    In development mode, this is .env in the root folder.
    """
    return os.path.join(get_app_data_dir(), ".env")

def get_db_url(default_url: str = None) -> str:
    """
    Resolves the database URL.
    - If DATABASE_URL is set in environment, uses it.
    - Otherwise, falls back to sqlite in App Data directory.
    """
    env_db_url = os.environ.get("DATABASE_URL")
    if env_db_url:
        return env_db_url
    if default_url:
        return default_url
    
    db_path = os.path.join(get_app_data_dir(), "major_rss.db")
    return f"sqlite:///{db_path}"

def get_cookie_path(cookie_filename: str) -> str:
    """
    Resolves the path to the authentication cookies.
    - Packaged mode: ~/.majorss/{platform}_cookies.dat (encrypted)
    - Dev mode: root/{platform}_cookies.json (plaintext) / root/{platform}_cookies.dat (encrypted)
    """
    # For backward compatibility and ease of development:
    # If it's a JSON file and we are in dev mode, we can read/write directly.
    # But in packaged mode, we always save cookies as encrypted DAT files.
    if getattr(sys, 'frozen', False):
        # Change extension to .dat for encrypted version in packaged mode
        base, _ = os.path.splitext(cookie_filename)
        cookie_filename = f"{base}.dat"
        
    return os.path.join(get_app_data_dir(), cookie_filename)

def save_secure_config(key: str, value: str):
    """
    Encrypts and saves a key-value configuration pair to config.dat.
    """
    config_path = os.path.join(get_app_data_dir(), "config.dat")
    config = {}
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                encrypted_bytes = f.read()
            if encrypted_bytes:
                decrypted_str = decrypt_data(encrypted_bytes)
                config = json.loads(decrypted_str)
        except Exception:
            # Reset config if decryption or JSON parsing fails
            config = {}
            
    config[key] = value.strip()
    
    try:
        config_bytes = encrypt_data(json.dumps(config))
        with open(config_path, "wb") as f:
            f.write(config_bytes)
    except Exception as e:
        print(f"[ERROR] Failed to save secure config: {e}")

def load_secure_config(key: str) -> str:
    """
    Loads and decrypts a key-value configuration pair from config.dat.
    """
    # Backward compatibility: first check environment variable or .env
    # If GEMINI_API_KEY is defined in environment or .env, we can return it as fallback.
    config_path = os.path.join(get_app_data_dir(), "config.dat")
    val = ""
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                encrypted_bytes = f.read()
            if encrypted_bytes:
                decrypted_str = decrypt_data(encrypted_bytes)
                config = json.loads(decrypted_str)
                val = config.get(key, "")
        except Exception as e:
            print(f"[WARNING] Failed to load secure config: {e}")
            
    # Fallback to os.environ or .env
    if not val:
        val = os.environ.get(key, "")
        
    return val
