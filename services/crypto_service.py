import os
import sys

# Windows-specific imports and setup
is_windows = os.name == 'nt'

if is_windows:
    import ctypes
    from ctypes import wintypes
    
    # Define DATA_BLOB structure for DPAPI
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char))
        ]
        
    # Load crypt32.dll
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    
    def encrypt_data(data: str) -> bytes:
        """
        Encrypts a string using Windows Data Protection API (DPAPI).
        Bound to the current Windows user account and machine.
        """
        if not data:
            return b""
        data_bytes = data.encode('utf-8')
        
        # Prepare input blob
        in_blob = DATA_BLOB(
            len(data_bytes), 
            ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_char))
        )
        out_blob = DATA_BLOB()
        
        # CryptProtectData(pDataIn, szDataDescr, pOptionalEntropy, pReserved, pPromptStruct, dwFlags, pDataOut)
        # dwFlags = 1 -> CRYPTPROTECT_UI_FORBIDDEN (no UI prompt shown)
        success = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob)
        )
        if not success:
            raise OSError("Windows CryptProtectData encryption failed.")
            
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        return result

    def decrypt_data(encrypted_bytes: bytes) -> str:
        """
        Decrypts bytes encrypted with DPAPI.
        Only succeeds if run by the same Windows user on the same machine.
        """
        if not encrypted_bytes:
            return ""
            
        # Prepare input blob
        in_blob = DATA_BLOB(
            len(encrypted_bytes),
            ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char))
        )
        out_blob = DATA_BLOB()
        
        # CryptUnprotectData(pDataIn, ppszDataDescr, pOptionalEntropy, pReserved, pPromptStruct, dwFlags, pDataOut)
        success = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob)
        )
        if not success:
            raise OSError("Windows CryptUnprotectData decryption failed. The file may have been moved or permissions changed.")
            
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData).decode('utf-8')
        kernel32.LocalFree(out_blob.pbData)
        return result

else:
    # macOS / Linux: real symmetric encryption (Fernet/AES) with a per-install
    # key stored 0600 in the app data dir — replaces the old reversible base64
    # "developer only" fallback. (True OS-Keychain storage via `keyring` is a
    # future hardening; a 0600 key file is already a real improvement and needs
    # no extra PyInstaller-bundled dependency.)
    import base64
    from cryptography.fernet import Fernet, InvalidToken

    _KEY_CACHE = {}

    def _key_path() -> str:
        # Lazy import: db.config imports this module, so importing it at module
        # load time would be circular.
        from db.config import get_app_data_dir
        return os.path.join(get_app_data_dir(), ".enckey")

    def _get_key() -> bytes:
        if "k" in _KEY_CACHE:
            return _KEY_CACHE["k"]
        path = _key_path()
        if os.path.exists(path):
            with open(path, "rb") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key()
            with open(path, "wb") as f:
                f.write(key)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
        _KEY_CACHE["k"] = key
        return key

    def encrypt_data(data: str) -> bytes:
        if not data:
            return b""
        return Fernet(_get_key()).encrypt(data.encode("utf-8"))

    def decrypt_data(encrypted_bytes: bytes) -> str:
        if not encrypted_bytes:
            return ""
        # Current scheme: Fernet.
        try:
            return Fernet(_get_key()).decrypt(encrypted_bytes).decode("utf-8")
        except (InvalidToken, Exception):
            pass
        # Legacy: base64 (old fallback) then raw plaintext, so pre-upgrade
        # cookie/config files still open once, then get re-saved encrypted.
        try:
            return base64.b64decode(encrypted_bytes).decode("utf-8")
        except Exception:
            return encrypted_bytes.decode("utf-8")
