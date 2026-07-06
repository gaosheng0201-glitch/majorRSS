# MajorRSS 桌面端打包手册

> 本文档记录了 MajorRSS 桌面应用的打包流程、常见问题排查方法，以及新增依赖时需要同步更新的配置清单。

## 架构概览

```
┌──────────────────────────────────────────────────────┐
│                  Tauri Desktop Shell                 │
│  (Rust, desktop/src-tauri/)                          │
│                                                      │
│  ┌────────────────┐     ┌──────────────────────────┐ │
│  │ React Frontend │     │ Python Backend Sidecar    │ │
│  │ (Vite Build)   │────▶│ (PyInstaller --onefile)   │ │
│  │ desktop/src/   │ HTTP│ backend-sidecar.exe        │ │
│  │                │:8765│ backend/main.py            │ │
│  └────────────────┘     └──────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

- **前端**: React + Mantine + Vite → 打包为静态资源，由 Tauri WebView 加载
- **后端**: FastAPI + uvicorn → 由 PyInstaller 打包为单文件 EXE，作为 Tauri sidecar 运行
- **通信**: 前端通过 HTTP 请求 `http://127.0.0.1:8765/api/` 与后端 sidecar 通信

## 打包流程

### 1. 构建 Backend Sidecar

```bash
# 方式一：使用构建脚本（推荐）
python build_backend.py

# 方式二：使用 spec 文件
.venv\Scripts\pyinstaller.exe backend-sidecar.spec --clean --noconfirm
```

构建产物会被自动复制到 `desktop/src-tauri/bin/backend-sidecar-x86_64-pc-windows-msvc.exe`。

### 2. 构建 Tauri 桌面应用

```bash
cd desktop
npx tauri build
```

这会自动执行 `npm run build`（前端）并编译 Rust 代码，最终输出安装包。

## ⚠️ 新增依赖时的更新清单

> **这是最容易出问题的环节。** 每次新增 Python 模块或第三方包，必须同步更新以下配置，否则打包后的 EXE 会因缺少模块而无法启动。

### 新增第三方 Python 包

当你 `pip install` 了一个新包并在代码中 import 时：

| 步骤 | 文件 | 操作 |
|------|------|------|
| 1 | `requirements.txt` | 添加包名和版本 |
| 2 | `backend-sidecar.spec` | 在 `hiddenimports` 列表中添加模块名 |
| 3 | `build_backend.py` | 在 cmd 列表中添加 `"--hidden-import", "包名"` |
| 4 | （可选）如果包含数据文件 | 在 spec 中使用 `collect_all('包名')` |

**示例**：新增 `httpx` 包

```python
# backend-sidecar.spec — hiddenimports 列表中添加
'httpx', 'httpx._transports',

# build_backend.py — cmd 列表中添加
"--hidden-import", "httpx",
```

### 新增本地 Python 模块

当你创建了新的项目目录（如 `notifications/`）时：

| 步骤 | 文件 | 操作 |
|------|------|------|
| 1 | `backend-sidecar.spec` | `datas` 中添加 `('目录名', '目录名')` |
| 2 | `backend-sidecar.spec` | `hiddenimports` 中添加所有子模块 |
| 3 | `build_backend.py` | cmd 中添加 `"--add-data"` 和 `"--hidden-import"` |

**示例**：新增 `notifications/` 目录，包含 `push.py` 和 `email.py`

```python
# backend-sidecar.spec
datas += [
    # ... 现有条目 ...
    ('notifications', 'notifications'),
]
hiddenimports += [
    # ... 现有条目 ...
    'notifications', 'notifications.push', 'notifications.email',
]

# build_backend.py
"--add-data", f"notifications{os.pathsep}notifications",
"--hidden-import", "notifications.push",
"--hidden-import", "notifications.email",
```

### 新增前端 npm 包

前端包由 Vite 打包，通常不需要额外配置。但如果涉及以下情况需要注意：

| 情况 | 需要更新的文件 |
|------|---------------|
| 新增外部 CDN 资源（字体、图片等） | `tauri.conf.json` → CSP 策略 |
| 新增 WebSocket 连接地址 | `tauri.conf.json` → CSP `connect-src` |
| 新增 Tauri 插件 | `Cargo.toml` + `capabilities/default.json` |

### 新增 Tauri 插件

```
1. Cargo.toml        → 添加 tauri-plugin-xxx 依赖
2. lib.rs            → 注册插件 app.handle().plugin(...)
3. default.json      → 添加对应的 permissions
4. package.json      → npm install @tauri-apps/plugin-xxx
```

## 关键配置文件速查

| 文件 | 用途 |
|------|------|
| `backend-sidecar.spec` | PyInstaller 完整打包配置（spec 模式） |
| `build_backend.py` | PyInstaller 命令行打包脚本（script 模式） |
| `backend/main.py` | 后端入口，包含 frozen 模式的 `sys.path` 适配 |
| `desktop/src-tauri/tauri.conf.json` | Tauri 配置：CSP、窗口、sidecar 路径 |
| `desktop/src-tauri/capabilities/default.json` | Tauri 权限声明 |
| `desktop/src-tauri/Cargo.toml` | Rust 依赖（Tauri 插件） |

## PyInstaller 冻结模式注意事项

### sys.path 与 _MEIPASS

PyInstaller `--onefile` 会将所有文件打包进单个 EXE，运行时解压到临时目录 `sys._MEIPASS`。代码中任何基于 `__file__` 的路径计算在冻结模式下都会失效。

**正确做法**（已在 `backend/main.py` 中实现）：

```python
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### 数据文件路径

如果代码需要读取数据文件（非 Python 模块），使用以下方式获取路径：

```python
import sys, os

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发和打包模式"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)
```

### 用户数据目录

用户数据（数据库、配置文件、cookies）不应打包进 EXE，而是存放在持久化目录：

```
~/.majorss/
├── .env              # 环境变量
├── config.dat        # DPAPI 加密的 API Key
├── major_rss.db      # SQLite 数据库
└── *_cookies.dat     # 加密的 cookies
```

这个逻辑在 `db/config.py` 的 `get_app_data_dir()` 中实现。

## 排查打包后启动失败

### 快速诊断流程

```
1. 直接在命令行运行 sidecar EXE：
   desktop\src-tauri\bin\backend-sidecar-x86_64-pc-windows-msvc.exe

2. 观察输出：
   - ModuleNotFoundError → 缺少 hidden import，更新 spec
   - ImportError → 模块存在但内部依赖缺失
   - 正常启动（Uvicorn running...） → 问题在 Tauri 层

3. 如果 sidecar 正常但 Tauri 内仍无限加载：
   - 浏览器直接访问 http://127.0.0.1:8765/api/settings/health
   - 检查 Tauri 控制台日志（开发模式下 F12）
   - 检查 CSP 策略是否阻断了请求
```

### 常见错误与解决方案

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| `ModuleNotFoundError: No module named 'xxx'` | PyInstaller 未打包该模块 | 在 spec 的 `hiddenimports` 中添加 |
| `FileNotFoundError: .env` | 首次运行无配置文件 | 正常现象，`load_dotenv` 会跳过 |
| `OSError: CryptProtectData failed` | DPAPI 加密异常 | 检查 Windows 用户权限 |
| `Address already in use :8765` | 端口被占用 | 结束旧的 sidecar 进程 |
| Tauri 窗口白屏 | 前端未构建或 CSP 阻断 | 检查 `desktop/dist/` 是否存在 |

## 完整打包命令速查

```bash
# 0. 确保依赖已安装
pip install -r requirements.txt
pip install pyinstaller
cd desktop && npm install && cd ..

# 1. 构建 sidecar
python build_backend.py

# 2. 验证 sidecar 可独立运行
desktop\src-tauri\bin\backend-sidecar-x86_64-pc-windows-msvc.exe
# 看到 "Uvicorn running on http://127.0.0.1:8765" 后 Ctrl+C 退出

# 3. 构建 Tauri 桌面应用
cd desktop
npx tauri build
# 产物在 desktop/src-tauri/target/release/bundle/
```

---

## macOS 分发与签名（2026-07-06）：没有 Apple 开发者账号能做什么

> 简答：**没有 Apple 账号不影响你构建和自用，也不影响防篡改更新的核心安全**。只有"让别人的 Mac 打开时不弹警告"这一件事需要 $99/年的账号。

### 现在就能做（免费，无需任何账号）

1. **构建可用的 .app / .dmg**
   ```bash
   cd desktop && npm run tauri:build
   # 产物：desktop/src-tauri/target/release/bundle/{macos/*.app, dmg/*.dmg}
   ```
   `bundle.targets` 已设为 `"all"`——在 macOS 上产出 .app + .dmg，在 Windows 上产出 nsis。图标 icon.icns 已就位。产物**未签名**，在你自己的机器上直接能跑。

2. **分发未签名版给别人**（会遇到 Gatekeeper 警告，但能打开）
   - 对方右键点 App → **打开**（而不是双击），首次会有"未识别开发者"确认，之后正常。
   - 或对方执行 `xattr -cr /Applications/MajorRSS.app` 清除隔离属性。
   - 官网下载页公示每个包的 SHA256，让人能核对没被篡改。

3. **签名更新（防木马的核心安全，愿景 #9）——完全免费，与 Apple 无关**
   Tauri updater 用它自己的 ed25519 密钥，跟 Apple 签名是两回事：
   ```bash
   # 生成密钥对（一次性）
   npx tauri signer generate -w ~/.tauri/majorss.key
   # 私钥 + 口令存进密码管理器，永不进仓库、永不上传
   ```
   然后在 `tauri.conf.json` 里：
   ```jsonc
   "plugins": { "updater": {
     "pubkey": "<粘贴 signer generate 输出的公钥>",
     "endpoints": ["https://你的域名/updates/{{target}}/{{arch}}/{{current_version}}"]
   }},
   "bundle": { "createUpdaterArtifacts": true }
   ```
   并安装插件：`npm i @tauri-apps/plugin-updater` + Cargo.toml 加 `tauri-plugin-updater`，在 lib.rs 注册。
   CI 出包时用 `TAURI_SIGNING_PRIVATE_KEY` / `..._PASSWORD` 环境变量注入。
   **这样即使更新服务器被攻破，客户端也会因验签失败拒绝安装被篡改的包**——不需要 Apple 账号。

### 只有这一件事需要 $99/年 Apple 开发者账号

**Developer ID 签名 + 公证（notarization）**——目的是让**别人的 Mac** 双击就能打开、没有任何 Gatekeeper 警告。拿到账号后（Tauri 内置支持，无需改代码，只加环境变量）：
```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: 你的名字 (TEAMID)"
export APPLE_ID="你的AppleID" APPLE_PASSWORD="app-专用密码" APPLE_TEAM_ID="TEAMID"
npm run tauri:build   # Tauri 自动签名 + 提交公证
```

### 结论

| 能力 | 需要 Apple 账号？ |
|---|---|
| 自己构建、自己用 | ❌ 不需要 |
| 防篡改的签名更新（核心安全） | ❌ 不需要（Tauri 自有 ed25519） |
| 发给别人（可接受一次右键"打开"） | ❌ 不需要 |
| 别人双击零警告打开 | ✅ 需要（$99/年） |

Windows 同理：NSIS 包免费可发（有 SmartScreen 警告），去掉警告需 Authenticode 证书（另付费，与 Apple 无关）。
