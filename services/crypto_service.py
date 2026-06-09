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
    # Fallback implementation for developer testing on Linux/macOS
    import base64
    print("[WARNING] Non-Windows OS detected. Using base64 encoding fallback for developer testing ONLY.")
    
    def encrypt_data(data: str) -> bytes:
        if not data:
            return b""
        return base64.b64encode(data.encode('utf-8'))
        
    def decrypt_data(encrypted_bytes: bytes) -> str:
        if not encrypted_bytes:
            return ""
        return base64.b64decode(encrypted_bytes).decode('utf-8')
