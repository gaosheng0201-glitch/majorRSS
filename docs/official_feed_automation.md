# 官方分发源的自动化更新发布

> 创建：2026-07-16
>
> 补愿景与平台设计都没有回答的缺口：**作者本机不可能 24 小时开着，官方站怎么保持更新？**
> 数据形状见 [publish_contract.md](publish_contract.md)；本文只解决"谁在什么环境、以什么节奏生成并推送"。

## 关键洞察：合规规则使无头化天然可行

发布合规的两条铁律（[security_and_sharing_boundary_plan.md](security_and_sharing_boundary_plan.md)）：

```text
授权（登录态）内容永不出本机
付费 / 权利不明内容不进公共摘要
```

推论：**公开 digest 只能由匿名路由生成**（公开 RSS、公开网页 diff、generated feed、
Google News 检索）。而匿名路由恰好不需要作者 cookie、不需要账号守卫、不需要拟人化节奏——
雷达管线里最难无人值守的部分（授权会话保护）**本来就与官方发布无关**。

所以官方源自动化 ≠ 把作者桌面搬上云，而是：

```text
官方发布实例 = 同一套 headless 后端（FastAPI + scheduler，无 Tauri 壳）
              + 仅匿名路由的 portfolio
              + 语义层（embedding 走 API 或轻量本地模型）
              + R7 发布导出器（合规门 → PublishedDigest JSON → 推送静态托管）
作者桌面     = 私人雷达（含授权路由），与官方实例互不依赖
```

两者共享同一代码库、同一契约。到共享层 Phase 2（多发布者）时，
官方实例就是编号第一的 publisher，桌面实例可以是第二个。

## 三种运行形态

| 形态 | 新鲜度 | 成本 | 状态持久化 | 适合阶段 |
|---|---|---|---|---|
| A. 桌面在线时推送 | 开机才更新 | 零 | 本机 SQLite，天然 | R7 第一步，先跑通闭环 |
| B. GitHub Actions 定时跑 | cron 粒度（如 2h/daily） | 免费额度内 | 需搬运（见下） | 过渡态 |
| C. 常驻无头实例（$5 VPS / 家里 mini PC / NAS） | 任意，可事件驱动 | ~$5/月或电费 | 本地 SQLite，天然 | 目标态 |

### A. 桌面推送（先做这个）

- scheduler 加 `publish_digest` 任务：每轮雷达周期后（或每日定点）跑导出器 → 合规门 →
  推送 `digest.json`（+ generated RSS）到静态托管（GitHub Pages / Cloudflare Pages / R2 任一）。
- 机器不在线 → 站点停留在上一期。分发页面已用「截至 <时间>」诚实标注数据窗口，
  陈旧是显式的、不是坏的。官方 digest 本就定位低频（蓝图：官方摘要每日/每周级）。
- 价值：R7 导出器、合规门、推送通道全部先在最简环境验证，B/C 复用全部代码。

### B. GitHub Actions（可跳过）

即 [rss_feed_generation_method.md](rss_feed_generation_method.md) 研究过的 Olshansk/rss-feeds
模式（Actions 定时跑生成器、把产物提交回仓库）。对我们：

- 私有 repo + cron workflow：拉起 headless 后端跑一轮匿名抓取 + 语义摄入 + 导出 → 产物推静态托管。
- **难点是状态**：线索连续性（StoryThread/embedding/HttpCacheEntry）要求 SQLite 跨 run 存活。
  可行做法：db 文件提交到私有 repo 的 data 分支（db_cleanup 的保留策略已把体积封顶）或 R2 拉推。
  能用但别扭——这是它只作过渡态的原因。
- API key 走 Actions secrets；无 cookie 上云问题（官方实例没有 AuthProfile）。

### C. 常驻无头实例（目标态）

- 任何便宜常驻环境：$5 VPS、家里 mini PC/NAS、闲置笔记本。`python backend/main.py` 即全部。
- 官方 portfolio 只配匿名路由；LLM 用作者 key + 每日预算刹车（已有 `LLM_DAILY_TOKEN_BUDGET`）。
- 新鲜度从 cron 粒度升级为**事件驱动**：共振告警触发即时重新导出推送——
  官方站也能吃到"线报早媒体数天"的时效红利（LEAD 照常明确标注未证实）。
- 桌面照常跑私人雷达；两实例各自独立，互不同步（未来若要合并视角，走共享层 Phase 3 的索引，不走私联）。

## 推荐路径

```text
R7 第一步：形态 A（导出器 + 推送通道 + 站点消费真实 JSON，端到端闭环）
        ↓ 跑顺后
直接上形态 C（同一套代码换个常驻环境 + 开事件驱动推送）
形态 B 仅当短期内不想碰任何服务器时作垫脚石
```

## 部署设计定稿（2026-07-16，作者选型：GitHub 免费 vs NAS Docker）

### 总原则：生成端与分发端拆开

```text
生成端（可替换）：NAS Docker 或 GitHub Actions —— 定时跑管线，产出 digest.json + RSS
        │  推送（git push 或 wrangler deploy，一次配置）
        ▼
分发端（永远不变）：免费静态托管 —— Cloudflare Pages（推荐）或 GitHub Pages
                     承载 site/ 页面 + digest.json + rss.xml，绑作者域名
```

站点、域名、契约固定在分发端；生成端哪天从 Actions 换到 NAS（或反过来），
只是换"谁在推送"，其他零改动。

### 方案一（推荐，有 NAS 就选它）：NAS Docker

这就是形态 C 落在自有硬件上：状态天然连续、可事件驱动、LLM key 留在家里、零月费。

**镜像**：基于 Playwright 官方 Python 镜像（chromium 依赖已装好，amd64/arm64 都有）：

```dockerfile
# deploy/Dockerfile.official
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium
COPY . .
ENV MAJORSS_DATA_DIR=/data
CMD ["python", "backend/main.py"]
```

```yaml
# deploy/docker-compose.yml
services:
  majorss-official:
    build: { context: .., dockerfile: deploy/Dockerfile.official }
    restart: unless-stopped          # NAS 重启 / 容器崩溃后自动拉起
    volumes:
      - /volume1/docker/majorss:/data   # SQLite + 日志 + 发布密钥，全在这个目录
    environment:
      - LLM_PROVIDER=...
      - LLM_API_KEY=...              # 或走 NAS 的 secrets 机制
      - LLM_DAILY_TOKEN_BUDGET=...   # 预算刹车必开
      - OFFICIAL_INSTANCE=1          # 官方模式：无 AuthProfile、仅匿名路由（R7 实现）
```

**推送通道（最小权限）**：为"站点仓库"单独生成一把 deploy key（只对那一个 repo 有写权限），
放进 `/data`；导出器产出后 `git push` 到站点仓库 → Pages 自动上线。
NAS 被攻破的最坏损失 = LLM 预算 + 篡改一次站点（可撤销、Phase 2 签名后可发现）。

**NAS 要求**：Docker 支持（Synology Container Manager / QNAP Container Station / 绿联皆可）、
x86_64 或 arm64、建议预留 2GB 内存（chromium 峰值）。**NAS 不开任何入站端口**——
容器只有出站流量（抓取 + 推送），不暴露 8765，不做端口转发。

**维护**：日常零操作；代码更新 = `git pull && docker compose up -d --build`（可选做成脚本）。

### 方案二（没有 NAS 才用）：GitHub Actions

私有仓库 + cron workflow，白嫖但有两个结构性妥协——**状态搬运**和**节奏上限**。

**免费额度算术**：私有仓库 2000 分钟/月。一次 run ≈ 5-8 分钟（依赖安装走缓存 + 抓取 + 语义 +
导出）。每日 3 次 ≈ 540-720 分钟/月 ✅；每 2 小时 ≈ 1800-2880 分钟/月 ⚠️ 顶到上限。
结论：**Actions 模式官方站是"每日三期"，不是准实时**；且 GitHub 高峰期 cron 延迟 15-60 分钟。

**状态搬运**（SQLite 跨 run 存活，线索连续性所在）：

```yaml
# .github/workflows/official-digest.yml（骨架）
on:
  schedule: [{ cron: "0 0,8,16 * * *" }]   # 每日三期（UTC）
  workflow_dispatch:                        # 手动触发兜底
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - uses: actions/cache@v4              # 第一层：cache 恢复数据库
        with: { path: data/, key: "radar-db-${{ github.run_id }}", restore-keys: radar-db- }
      - run: pip install -r requirements.txt && playwright install chromium --with-deps
      - run: python -m official_run          # R7：抓取→语义→导出（单轮模式，非常驻调度器）
        env: { LLM_API_KEY: "${{ secrets.LLM_API_KEY }}" }
      - run: ./deploy/push_site.sh           # 推送产物到站点仓库 / CF Pages
        env: { SITE_DEPLOY_KEY: "${{ secrets.SITE_DEPLOY_KEY }}" }
      - run: ./deploy/backup_db.sh           # 第二层：db 快照 force-push 到私有 data 分支
```

- cache 是主通道，但 GitHub 会清（7 天未用 / 总量超限）；data 分支单提交 force-push
  作恢复兜底（不留历史，仓库不膨胀）。cache 丢失 + 兜底也坏 → 线索从零重聚，
  站点不坏，只是几天内"增量"退化为"新发现"。这个失败模式可接受但真实存在。
- 需要一个 `official_run` 单轮入口（跑一轮就退出，区别于常驻调度器）——R7 顺手做，
  对 NAS 方案也有用（诊断/补跑）。

### 何时能做

两个方案都依赖 R7 发布导出器（重构 session 的地盘）。**现在就能做的**：
选静态托管 + 绑域名 + 把 site/ 原型（样例数据）部署上去——分发端先立起来，
生成端接上只是换掉 digest.json。deploy key / secrets 的申请也可以提前配好。

## 永远不上发布实例的东西（硬边界）

- AuthProfile / cookie / storage_state —— 官方实例没有授权路由，字段都不该存在。
- Tauri updater 签名私钥 —— 更新信任链与发布管线彻底隔离（蓝图分发安全条）。
- 用户（含作者）私人雷达数据 —— 官方实例的库从公开源从零长出来，不从桌面迁移。
- 实例被攻破的最坏损失应收敛于：作者 LLM key 的预算额度 + 一次可撤销的 digest 篡改
  （Phase 2 签名上线后，站点校验 publisher 签名可发现篡改）。

## 对现有设计的两处小修正

1. 平台设计文档里"官方 digest 由平台服务端生成"的心智：生成者不是"平台"，
   是**一个跑着 MajorRSS 的官方无头实例**——吃自己的狗粮，客户端即基础设施。
2. 蓝图 R7 验收（"不用软件的人在网站看到去噪信息"）应补一句时效前提：
   **站点新鲜度不依赖作者桌面在线**（形态 C 达成）。
