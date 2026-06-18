import os
import sys
import shutil
import subprocess

def build_backend():
    print("========================================")
    print("      MajorRSS Backend Sidecar Builder  ")
    print("========================================")
    
    # 1. Verify environment
    venv_py = os.path.join(".venv", "Scripts", "python.exe") if os.name == 'nt' else os.path.join(".venv", "bin", "python")
    pyinstaller_exe = os.path.join(".venv", "Scripts", "pyinstaller.exe") if os.name == 'nt' else os.path.join(".venv", "bin", "pyinstaller")
    
    if not os.path.exists(pyinstaller_exe):
        print(f"[ERROR] PyInstaller not found at {pyinstaller_exe}. Please run pip install pyinstaller.")
        sys.exit(1)
        
    # 2. Determine Tauri target triple
    # Standard compilation for local machine target
    # Windows 64-bit target triple is x86_64-pc-windows-msvc
    target_triple = "x86_64-pc-windows-msvc"
    if os.name != 'nt':
        # Fallback target triples for developer reference
        import platform
        machine = platform.machine().lower()
        if 'arm' in machine or 'aarch64' in machine:
            target_triple = f"aarch64-unknown-linux-gnu" if sys.platform.startswith('linux') else "aarch64-apple-darwin"
        else:
            target_triple = f"x86_64-unknown-linux-gnu" if sys.platform.startswith('linux') else "x86_64-apple-darwin"
            
    print(f"Target Triple: {target_triple}")
    
    # Define paths
    sidecar_dir = os.path.join("desktop", "src-tauri", "bin")
    sidecar_name = f"backend-sidecar-{target_triple}"
    if os.name == 'nt':
        sidecar_name += ".exe"
        
    # 3. Execute PyInstaller command
    # We collect uvicorn, playwright, and sqlmodel to make sure uvicorn loops and sqlmodel tables are included
    cmd = [
        pyinstaller_exe,
        "--clean",
        "--name", "backend-sidecar",
        "--onefile",
        "--noconfirm",
        "--paths", ".",
        # Third-party packages
        "--collect-all", "uvicorn",
        "--collect-all", "sqlmodel",
        "--collect-all", "apscheduler",
        "--collect-all", "playwright",
        # Local module directories as data
        "--add-data", f"db{os.pathsep}db",
        "--add-data", f"services{os.pathsep}services",
        "--add-data", f"scrapers{os.pathsep}scrapers",
        "--add-data", f"repositories{os.pathsep}repositories",
        "--add-data", f"migrations{os.pathsep}migrations",
        "--add-data", f"llm{os.pathsep}llm",
        "--add-data", f"backend{os.pathsep}backend",
        # Hidden imports - local modules
        "--hidden-import", "scheduler",
        "--hidden-import", "worker_subscription",
        "--hidden-import", "db.database",
        "--hidden-import", "db.config",
        "--hidden-import", "db.models",
        "--hidden-import", "services.crypto_service",
        "--hidden-import", "services.scraper_service",
        "--hidden-import", "services.processor_service",
        "--hidden-import", "services.db_cleanup_service",
        "--hidden-import", "services.source_resolver",
        "--hidden-import", "repositories.repository",
        "--hidden-import", "migrations.runner",
        "--hidden-import", "scrapers.auth_helper",
        "--hidden-import", "scrapers.tier1_rss",
        "--hidden-import", "scrapers.tier3_agentic",
        "--hidden-import", "scrapers.auto_detect",
        "--hidden-import", "llm.processor",
        "--hidden-import", "llm.investigator",
        # Hidden imports - third-party
        "--hidden-import", "dotenv",
        "--hidden-import", "feedparser",
        "--hidden-import", "bs4",
        "--hidden-import", "requests",
        "--hidden-import", "duckduckgo_search",
        "--hidden-import", "google.genai",
        # Exclude unnecessary packages
        "--exclude-module", "streamlit",
        "--exclude-module", "flet",
        "--exclude-module", "pytest",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        os.path.join("backend", "main.py")
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("[ERROR] PyInstaller compilation failed!")
        sys.exit(1)
        
    print("[SUCCESS] PyInstaller compilation finished.")
    
    # 4. Copy to Tauri sidecars folder
    os.makedirs(sidecar_dir, exist_ok=True)
    compiled_file = os.path.join("dist", "backend-sidecar.exe" if os.name == 'nt' else "backend-sidecar")
    destination = os.path.join(sidecar_dir, sidecar_name)
    
    if not os.path.exists(compiled_file):
        print(f"[ERROR] Compiled binary not found at {compiled_file}!")
        sys.exit(1)
        
    print(f"Copying {compiled_file} to {destination}...")
    shutil.copy2(compiled_file, destination)
    print(f"[SUCCESS] Sidecar binary is ready at: {destination}")
    
    # 5. Cleanup build files
    print("Cleaning up PyInstaller temporary build artifacts...")
    try:
        shutil.rmtree("build")
        shutil.rmtree("dist")
        os.remove("backend-sidecar.spec")
        print("[SUCCESS] Cleanup completed.")
    except Exception as e:
        print(f"[WARNING] Cleanup failed slightly: {e}")
        
    print("\nAll done! You can now run 'npx tauri dev' inside the desktop/ folder.")

if __name__ == "__main__":
    build_backend()
