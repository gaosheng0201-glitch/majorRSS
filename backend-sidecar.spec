# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('db', 'db'), ('services', 'services'), ('scrapers', 'scrapers'), ('repositories', 'repositories'), ('migrations', 'migrations'), ('llm', 'llm'), ('backend', 'backend'), ('docs/source_presets.seed.json', 'docs')]
binaries = []
hiddenimports = ['scheduler', 'worker_subscription', 'db.database', 'db.config', 'db.models', 'services.crypto_service', 'services.scraper_service', 'services.processor_service', 'services.db_cleanup_service', 'services.source_resolver', 'services.host_politeness', 'services.browser_pool', 'repositories.repository', 'migrations.runner', 'scrapers.auth_helper', 'scrapers.tier1_rss', 'scrapers.tier3_agentic', 'scrapers.auto_detect', 'llm.processor', 'llm.investigator', 'dotenv', 'feedparser', 'bs4', 'requests', 'duckduckgo_search', 'google.genai']
tmp_ret = collect_all('uvicorn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sqlmodel')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('apscheduler')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['backend/main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['streamlit', 'flet', 'pytest', 'tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='backend-sidecar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend-sidecar',
)
