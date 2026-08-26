# MajorRSS 工程基准（Engineering Baseline）

> 最后更新：2026-08-13
>
> **本文档是现行唯一的工程状态基准。**
>
> `docs/` 下的其他文档定位为**设计意图档案**（长期有效，不更新实现审计部分）。**执行队列与裁决记录**在 [radar_quality_roadmap.md](radar_quality_roadmap.md)，**逐批实现史**在根目录 CHANGELOG.md。判断"某个问题现在还存在吗"，以本文档为准；判断"下一步做什么"，以路线图为准。
>
> 维护约定：每完成一轮改造，更新「当前架构」「差距地图」两节并改动顶部日期。本文档只保留当前状态，不保留历史（历史看 git log 与 CHANGELOG）。

---

## 1. 产品北极星（不变的约束）

来自设计意图档案，所有工程决策必须服务于它：

- **减噪，不是聚合。** 用户的心智是"我只想了解某件事"，不是"我想订阅一堆源"。系统的成功标准是用户看到的不相关内容更少，而不是抓到的内容更多。
- **四类关注意图**是用户层的一等概念：RSS/频道订阅、关键词探测、账号追踪、页面变化对比。RSSHub、Playwright、cookie、LLM 全部是实现手段，不得泄漏为用户必须理解的配置。
- **先选源 → 抓取 → 确定性过滤 → 缩小后才交给 AI。** LLM 不承担基础降噪成本；纯 RSS 模式（无 API Key）必须独立有价值——它是**永远的地板**，不是降级兜底。
- **每次抓取有预算**：最多几个源、每源几条、优先缓存。预设源库是信息地图，不是全量抓取清单。
- **失败必须可解释**：选了哪些路由、哪条成败、失败类型、fallback 是否触发，10 分钟内能回答"雷达在转吗、抓到了什么、为什么没抓到"。
- **本地优先**：任务默认在用户电脑上运行。OnlyFourBot 等共享网络是价值验证之后的事。
- **决策在规划期，运行时只执行**（2026-07-29 架构校正后明文化）：实体画像/语言地理/平台路由是规划器（P4.0）的产出；运行时的启发式只是无规划输出时的确定性兜底。
- **入口捕获，消费期只施加权重**（source_tiering §2）：provenance（层级、账号来源）在入库时盖章，绝不在消费期从 URL 重新推导。

## 2. 当前架构（as-is，2026-08-13）

```text
桌面端  desktop/          Tauri 2 (Rust) + React 19 + Mantine → 127.0.0.1:8765
                          macOS 原生窗饰/交通灯（tauri.macos.conf.json）；Win/Linux 自绘
后端    backend/main.py   FastAPI + uvicorn；lifespan 启动调度器守护线程；启动预载 .env/config
调度    scheduler.py      APScheduler 8 任务（poller/抓取/语义/融合/订阅diff/趋势/维护/心跳）
抓取    scraper_service → SourceResolver(路由分组+账号盖章) → adapters → SourceNormalizer
        护栏：source_health(端点退避/隔离/新鲜度断言) + host_politeness(主机限速/冷却/轮转)
        + account_guard(每账号预算/AIMD/熔断) + humanized(静默窗/抖动) + browser_pool(线程本地复用)
        错误归责：NOT_ENDPOINT_FAULT（429→主机层、能力缺失→自身诊断）不进端点健康
语义    semantic_ingest   embed(去均值) → 垃圾地板(0.05) → top-K 候选 + LLM 事件仲裁 → StoryThread
        生命周期 LEAD→CORROBORATED→CONFIRMED + 共振；账号线报走人物雷达豁免
融合    processor_service 按线索出摘要（P1.1 门控挣得制）；重摘要须实质增量
        （is_material_increment：出版方相对增长≥25% 或晋级——同一规则管排序诚实与重烧成本）
呈现    雷达页 = 唯一阅读面（P6）：AI 模式 提炼|线报 双 tab（卡片即摘要；线报按盖章分层，
        聚合器单源默认折叠）；纯 RSS 模式 = 原始订阅流本身。Dashboard = 纯 KPI 大屏
数据    SQLite（打包 ~/.majorss/，dev 在仓库根）；迁移 migrations/runner.py 0001–0015 幂等
观测    PipelineRun/Event trace · 滚动日志 · /health 心跳 · Billing 按动作/目标/日历热力图
发布    publish_service → 合规门 → PublishedDigest → onlyforbots.com（CF Pages 自动部署）
测试    tests/ 58 项 pytest（语义/守卫/健康/politeness/provenance/呈现层修复/发布合规）
```

关键机制的单一事实源（改动前先读对应文件头注释）：

| 关切 | 文件 | 要点 |
|---|---|---|
| 来源层级/一手判定 | `services/provenance.py` | 地板=前沿实验室自有频道档；组合型厂商博客**刻意不进**（Cloudflare 教训）；per-target 精确判定归 P4.0 |
| 账号来源 | `SourceRoute.is_account → RawArticle.from_account` | 入口盖章，消费期禁止 URL 猜（Drift 2 教训） |
| 端点健康 | `services/source_health.py` | 按端点退避；HTTP 200 ≠ 活着（按条目日期判活） |
| 主机礼貌 | `services/host_politeness.py` | 429 冻主机、5xx 连三冻主机、轮转防饿死 |
| 浏览器 | `services/browser_pool.py` | `ensure_browsers_path()` 对抗 Playwright frozen 假设；缺浏览器给安装指引 |
| 事件仲裁 | `services/semantic_ingest.py` | top-K(3) 候选逐个问；`rescued` 计数 = 旧 top-1 流程必错的合并 |
| 实质增量 | `services/processor_service.py` | `is_material_increment`；summarized_at 因此意为"最后实质变化" |
| RSS 时间 | `scrapers/tier1_rss.py` | `calendar.timegm`（mktime 会按本地标准时解释 UTC struct） |

## 3. 差距地图（当前仍存在的）

### 3.1 需作者裁决（挂起中）
- **浏览器分发**：测试期不带（现依赖机器上的 `playwright install`），正式发布要带。三档已量化：全带 525M / 只带 headless_shell 189M（抓取即用，授权时按需下载完整版）/ 全按需。见路线图。
- **P5 编辑价值门方案**：候选=负样本原型（纯向量零成本），等作者定。
- **授权态端到端**：链路已验证到登录弹窗（2026-08-05），cookie 抓取一段等作者小号。AUTH_PLATFORMS 11 平台的指示器仍是未经真实账号验证的假设。

### 3.2 结构性（记录不排期，见路线图同名节）
- **线索全局化 / 跨线索合并**：同事件可跨 tracker、也可同 tracker 分裂成多条（实测 3.7 Flash 两条并存）；现有近重守卫是有界兜底。
- **仲裁"同一故事线"语义**：严格 same-event 下高拆分率部分是诚实的；等 top-K 后的 splits/rescued 数据再定，动语义有过度合并回归风险。
- **容量余量薄**：稳态进入≈消化≈16 条/分钟，无余量；再加探测目标 pending 将单调增长。是容量上限不是泄漏。
- **优先级倒挂**：`max_sources_per_run` 封顶时 keyword 源(priority=1)压过精选源(priority=5)。
- **慢滴积累跨过 25% 增量阈值**时最后一滴获"进展"标记——按裁决语义诚实，真故事线级进展识别归仲裁语义工作。

### 3.3 功能与工程（可穿插）
- `POST /trackers/{id}/run` 无 task id；`run-trace`/试运行仍在 HTTP 请求内同步抓取（前端已放宽超时，后端异步化未做）。
- pure_rss 模式下 PROCESS/TREND 任务跳过却标 COMPLETED（任务日志失真）。
- `tracker_type/tier/cookie_string` 旧语义仍是主模型；`source_intent/fetch_policy` 迁移未完成；HYBRID 的 urls 固定走 RSS parser。
- 前端 `dangerouslySetInnerHTML` 已过 DOMPurify（RawFeed/Dashboard/Briefing 主要路径），未全量审计。
- macOS 密钥为 Fernet + 0600 文件（真加密，非 Keychain）；lib.rs 进程树清理在 macOS 是 no-op（Win 迁移遗留）。
- requirements.txt 不含 fastapi/uvicorn/pyinstaller（.venv 实际有，重建环境会踩）。
- Auth：Expired profile 的授权路由仍会被尝试；后台低频活体巡检未做。
- 提炼卡片的「摘要引用来源 vs 重复佐证来源」区分在 P6 搬迁中退化为统一成员列表（数据仍在附录里，展示层待恢复——作者已知，待排期）。

## 4. 路线图位置

R1–R7 Phase 1 全部完成（2026-07 上旬）；之后执行队列以 [radar_quality_roadmap.md](radar_quality_roadmap.md) 的 P 序列为准。当前位置：

```
✅ P0.1–P0.5 · P1.1/P1.2 · P2.1 · 架构复盘六项 · B1–B6 · 未结算两项
✅ P4 前置（管线可信性：agentic 0/399→通、reddit 24%→治理、429/能力归责、账号盖章）
✅ 呈现层三修（RSS 时间戳 +5h、一手地板、仲裁 top-K）
✅ P6 雷达收口 + 当日补丁（时间诚实、板块筛选）
✅ P4.0a/b（意图探索 schema+分道+路由派生,2026-08-20）
▶ 下一步：P4.0c 建议源(见 p4_intent_design.md §7,含归属混乱新动机) → P4.1/P4.2 → P5(等方案) → P7a/b → P3.1(最后)
⚠ 快讯通道离线:nitter.net 已 410,授权 agentic(等作者小号)是唯一恢复路径
   随时可插：P2.2 简报接地性
```

## 5. 开发速查

```bash
# 后端（dev；注意 dev 模式数据库在仓库根，不是 ~/.majorss）
source .venv/bin/activate && python backend/main.py   # :8765

# 桌面端（dev）
cd desktop && npx tauri dev
# 只看前端：npm --prefix desktop run dev → localhost:5173（Tauri 专有功能自动跳过）

# 打包安装（beforeBuildCommand 会先跑 build_backend.py 重建 sidecar）
cd desktop && npm run tauri:build
# 产物 desktop/src-tauri/target/release/bundle/macos/MajorRSS.app（dmg 步骤已知会失败，无碍）

# 测试（58 项）。数据库相关测试必须显式 DATABASE_URL 指向副本，严禁碰 ~/.majorss/major_rss.db
pytest -q
DATABASE_URL="sqlite:////tmp/copy.db" python -c "from migrations.runner import run_migrations; run_migrations()"

# 健康与日志
curl http://127.0.0.1:8765/api/settings/health
# 日志：dev 在仓库根 logs/majorss.log；打包在 ~/.majorss/logs/majorss.log（5MB×3 滚动）
# 时区注意：日志是本地时间(EDT)，数据库 created_at 是 UTC（差 4 小时）

# 授权浏览器（dev 机需要一次）：playwright install chromium
```
