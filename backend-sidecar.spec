# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# ---------- Third-party packages ----------
tmp_ret = collect_all('uvicorn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sqlmodel')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('apscheduler')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Third-party hidden imports that PyInstaller static analysis may miss
hiddenimports += [
    'dotenv', 'python-dotenv',
    'feedparser',
    'bs4', 'beautifulsoup4',
    'requests',
    'duckduckgo_search',
    'google.genai', 'google.generativeai',
    'pydantic', 'pydantic.deprecated.decorator',
    'sqlalchemy', 'sqlalchemy.pool', 'sqlalchemy.event',
    'email_validator',
]

# ---------- Local project modules ----------
# PyInstaller traces from backend/main.py but may miss modules imported
# inside functions, threads, or via string-based dynamic imports.
hiddenimports += [
    # Core
    'scheduler', 'worker_subscription', 'cli', 'worker',
    # db package
    'db', 'db.__init__', 'db.database', 'db.config', 'db.models', 'db.init_db',
    # backend package
    'backend', 'backend.main', 'backend.schemas',
    'backend.api', 'backend.api.trackers', 'backend.api.intelligence',
    'backend.api.briefing', 'backend.api.monitors', 'backend.api.settings', 'backend.api.auth',
    # services package
    'services', 'services.crypto_service', 'services.scraper_service',
    'services.processor_service', 'services.db_cleanup_service',
    'services.adapters', 'services.intent_normalizer', 'services.privacy',
    'services.source_normalizer', 'services.source_resolver',
    # repositories
    'repositories', 'repositories.repository',
    # scrapers
    'scrapers', 'scrapers.__init__', 'scrapers.auth_helper',
    'scrapers.auto_detect', 'scrapers.tier1_rss',
    'scrapers.tier3_agentic', 'scrapers.url_normalizer',
    # llm
    'llm', 'llm.__init__', 'llm.processor', 'llm.investigator',
    # migrations
    'migrations', 'migrations.runner',
]

# Include local module directories as data files so they are bundled
datas += [
    ('db', 'db'),
    ('services', 'services'),
    ('scrapers', 'scrapers'),
    ('repositories', 'repositories'),
    ('migrations', 'migrations'),
    ('llm', 'llm'),
    ('backend', 'backend'),
]

a = Analysis(
    ['backend\\main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude packages not needed at runtime in sidecar
        'streamlit', 'flet', 'flet_desktop', 'flet_web',
        'pytest', 'tkinter', 'matplotlib',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='backend-sidecar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
