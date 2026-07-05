# MajorRSS 工程基准（Engineering Baseline）

> 最后更新：2026-07-05
>
> **本文档是现行唯一的工程状态基准和路线图。**
>
> `docs/` 下的其他文档（`local_radar_upgrade_plan.md`、`pipeline_refactor_direction.md` 等）定位为**设计意图档案**：它们记录产品思考和方向，长期有效，不再更新其中的实现审计部分。判断"某个问题现在还存在吗 / 下一步做什么"，以本文档为准。
>
> 维护约定：每完成一轮改造，更新「已落地」和「差距地图」两节并改动顶部日期。审计快照会过时，所以本文档只保留当前状态，不保留历史（历史看 git log）。

---

## 1. 产品北极星（不变的约束）

来自设计意图档案，所有工程决策必须服务于它：

- **减噪，不是聚合。** 用户的心智是"我只想了解某件事"，不是"我想订阅一堆源"。系统的成功标准是用户看到的不相关内容更少，而不是抓到的内容更多。
- **四类关注意图**是用户层的一等概念：RSS/频道订阅、关键词探测、账号追踪、页面变化对比。RSSHub、Playwright、cookie、LLM 全部是实现手段，不得泄漏为用户必须理解的配置。
- **先选源 → 抓取 → 确定性过滤 → 缩小后才交给 AI。** LLM 不承担基础降噪成本；纯 RSS 模式（无 API Key）必须独立有价值。
- **每次抓取有预算**：最多几个源、每源几条、优先缓存。预设源库是信息地图，不是全量抓取清单。
- **失败必须可解释**：选了哪些路由、哪条成败、失败类型、fallback 是否触发，用户和开发者都能在 10 分钟内回答"雷达在转吗、抓到了什么、为什么没抓到"。
- **本地优先**：任务默认在用户电脑上运行。OnlyFourBot 等共享网络是价值验证之后的事。

## 2. 当前架构（as-is）

```text
桌面端  desktop/          Tauri 2 (Rust shell) + React 19 + Mantine，HTTP → 127.0.0.1:8765
后端    backend/main.py   FastAPI + uvicorn；lifespan 启动调度器守护线程
调度    scheduler.py      APScheduler；7 个任务（见下）；心跳写入 services/scheduler_state
抓取    services/scraper_service.py → SourceResolver → adapters(Rss/RssHub/Agentic) → SourceNormalizer → RawArticle
订阅    worker_subscription.py      页面快照 diff 管线（PageSnapshot / SubscriptionUpdate）
LLM     services/processor_service.py + llm/   消费 RawArticle(processed=False) → IntelReport
数据    db/models.py      SQLite 默认（打包模式 ~/.majorss/），可选 Postgres（5s 超时回退 SQLite）
观测    PipelineRun/PipelineEvent trace；logs/majorss.log 滚动日志；/api/settings/health 心跳
遗留    ui/(Streamlit) flet_main.py(Flet) worker.py —— 已被桌面端取代，仅作参考
```

调度任务（除 trend_scan 外全部**启动即跑**一轮）：

| 任务 | 周期 | 说明 |
|---|---|---|
| task_poller | 30s | 消费 UI 触发的 TaskRequest（含僵尸任务回收、重试） |
| tracker_scraping | 5min | 外层闸门；per-tracker `fetch_interval_minutes` 真实生效 |
| intelligence_fusion | 5min | LLM 处理未加工文章（pure_rss 模式跳过） |
| subscription_check | 5min | 页面 diff |
| trend_scan | 2h | 耗 LLM token，不在启动时触发 |
| db_maintenance | 24h（首轮延迟 15min） | 用户数据保留策略 + 遥测表保留（trace 14 天、快照每订阅 3 份） |
| heartbeat | 30s | 写 scheduler_state，供 /health 与 Settings 页引擎状态卡 |

PipelineRun 状态语义：`SUCCESS`（有新文章入库）/ `NO_NEW_ITEMS`（源可达但无新内容，**不是失败**，不触发浏览器兜底）/ `FAILED`（所有路由失败，`error_summary` 带分类错误码）。

错误分类（services/error_classifier.py）：`AUTH_EXPIRED / RATE_LIMITED / CAPTCHA_REQUIRED / SOURCE_UNAVAILABLE / RSS_PARSE_FAILED / NETWORK_ERROR / ENCODING_ERROR / UNKNOWN_ERROR`，写入 PipelineEvent.error 与 run.error_summary。

## 2.9 对抗式代码审查与修复（2026-07-06，16 个确认发现全修）

多智能体对抗审查（4 维度并行找 + 逐发现对抗验证）扫描 R1-R6 未提交 diff，16 个发现全部对抗验证通过（零假阳性）——暴露了冒烟测试的系统盲区（尤其总用全新库，漏掉迁移/并发问题）。全部已修并回归验证：

**CRITICAL**：`migrations/runner.py` 加 0006 迁移——create_all 只建新表不给已有表加列，`relevance_gated/thread_id/is_high_attention` 在**升级库上永不创建**，导致 LLM 管线在真实升级场景崩溃（实测预升级库验证修复）。

**HIGH**：account_guard TOCTOU → `try_consume` 原子门控+消费（进程锁，恰好一个半开探测，stale 探测自愈）；account_guard 读路径提交副作用 → 全部锁保护；browser_pool 缓存忽略新 storage_state → 全局 generation 计数器，重新授权 bump 使 cookie 轮转生效；db_cleanup 无界 `.in_()` 超 SQLite 999 变量限 → 子查询谓词；worker_subscription RESOLVE 期异常 NameError → 变量前置初始化；Radar/Dashboard feed 链接 `javascript:` XSS → `safeHref` 只放行 http(s)+rel=noopener。

**MEDIUM**：source_health 竞态 → 进程锁；订阅共享 session 中毒 → 失败 rollback；resonance 不衰减 → `refresh_resonance` 周期扫描（接语义任务）；portfolio `max_items_per_source` 键不匹配执行器 → 改 `max_items_per_route`；共享健康键致一个 Google News 搜索失败退避所有关键词 tracker → `route_key` per-endpoint 键。

**LOW**：Postgres dbname 解析遇 query 参数 → `current_database()`；预算封顶丢弃目标自身浏览器兜底 → 预设降 priority=5；target=_blank 补 rel=noopener。

## 3. 已落地（2026-07-05，信任闭环 + 工程卫生）

- 调度任务启动即跑；调度线程启动失败会记录到 scheduler_state 并在 /health 和 UI 显示，不再无声死亡
- `/api/settings/health` 返回调度器四态（running/starting/stalled/error）+ 各任务下次执行时间；Settings 页顶部有引擎状态卡（5s 轮询）
- 三处吞异常修复：线程池 future 异常逐个检查落日志；Tier3 抓取异常向上抛（不再吞成空页面）；`scrape_single_tracker` 整体兜底（任何崩溃都落 PipelineRun.FAILED + 日志，session 必然关闭）
- 日志落盘：`services/log_service.py`，滚动文件（数据目录 `logs/majorss.log`，5MB×3），控制台编码容错（解决 Windows GBK/emoji 中断），APScheduler 日志纳管；`GET /api/settings/app-logs?lines=N` 查尾部
- SQLite `busy_timeout=5000`（多线程写不再直接抛 database is locked）
- API 会话泄漏修复：所有路由改用 `Depends(get_api_session)`（请求后自动关闭）
- 遥测表保留策略：PipelineRun/Event 14 天（`PIPELINE_TRACE_RETENTION_DAYS`）、PageSnapshot 每订阅 3 份（`PAGE_SNAPSHOTS_KEEP_PER_SUBSCRIPTION`），随 db_maintenance 每日执行
- `db/database.py` 缺 `import sys` 的潜伏 NameError 修复；`__pycache__` 取消追踪并忽略
- 澄清一条过时审计：db-status **不再**回传 Postgres 明文密码（返回 `********`，写路径支持掩码回传复用旧密码）

**Token 经济性（同日第二批）：**
- LLM 打包截断：每篇文章上限 `LLM_MAX_CHARS_PER_ARTICLE`（默认 6000 字符，Agentic 整页快照不再吞掉数万 token），批次总量上限 `LLM_MAX_CHARS_PER_BUNDLE`（默认 36000，放不下的文章留到下一批）
- 每日 token 预算刹车：`LLM_DAILY_TOKEN_BUDGET`（默认 0=不限）；超额后融合/趋势扫描自动跳过并在活动日志说明，次日（UTC）恢复
- token 记账失败不再被 `except: pass` 吞掉（预算刹车依赖 TokenUsage 表，记账必须可见）

**Auth 稳定性（同日第二批）：**
- **Cookie 轮转回存**：Agentic 授权访问成功后，把浏览器上下文里平台刷新过的 session 状态加密回存 —— 会话寿命从"首次抓取到的 cookie 自然过期"延长为"随使用持续续期"
- **过期状态闭环**：抓取撞到登录墙（CookieExpiredException）时自动把关联 AuthProfile 标为 Expired（按 profile id，无 id 时按 URL 域名匹配平台），Settings 页即刻可见
- **状态不再来回翻转**：列表页静态检查只降级不升级（cookie 文件里字段还在 ≠ 平台还认）；恢复 Active 只能通过重新登录或活体检测
- **活体检测**：`live_check_cookie_health` 用无头浏览器带 session 真实访问平台并检查登录墙指示器；"测试"按钮改用它（网络失败返回"不确定"，不误标过期）

## 4. 差距地图（按层）

### 4.1 资源纪律（架构层，当前最高优先）
- Tier3 每个 URL 每轮启动一个全新 Chromium（`tier3_agentic.py` 每次 `sync_playwright()` + `launch()`）——需进程内浏览器复用
- 抓取无重试/退避：一次 DNS 抖动即 FAILED；失败源以全速被永久重打——需按源的指数退避（source health 的前半段）
- 无 per-domain 限速/politeness

### 4.2 触发与反馈（功能层）
- `POST /trackers/{id}/run` 只回 "queued"，不给 task id，UI 无法把点击和结果关联——需返回 id + 查询端点
- `run-trace` 系列接口在 HTTP 请求内同步跑分钟级抓取，会超时并占死 worker——需转异步任务
- pure_rss 模式下 PROCESS/TREND 任务被跳过却标 COMPLETED（任务日志失真）

### 4.3 安全边界（意图档案 P0 中仍未落地的部分）
- Tauri `csp: null`
- 前端多处 `dangerouslySetInnerHTML` 直接渲染外部内容（LLM 摘要、RawArticle、Briefing）——需 sanitizer + 默认纯文本
- macOS 密钥存储是明文 base64 回退（`crypto_service.py` 只有 DPAPI 实现）——需 Keychain

### 4.4 功能语义（意图进入模型）
- HYBRID tracker 的 urls 固定走 RSS parser（忽略 tier 配置），普通网页被硬塞 RSS 解析——意图档案 P1 首条，仍在
- 关键词探测无相关性过滤、无每轮写入上限、无 route 权重——噪音直达库和 LLM，违反北极星
- `tracker_type/tier/cookie_string` 旧语义仍是主模型；`source_intent/fetch_policy` 迁移未完成
- Route Test 后端已有 `run_route_test`，未接入 UI

### 4.5 Token 经济与 Auth 稳定（本轮后剩余）
- 语义级去重仍完全靠 LLM（重复事件批次仍付一次全额 prompt）——可用标题/内容指纹或本地 embedding 预筛，命中直接合并不进 LLM
- 确定性相关性过滤缺失（见 4.4 关键词项）——这是最大的剩余 token 浪费源：无关内容先入库再由 LLM 判 NOISE
- recent_context 去重上下文固定 8 条报告——可按 key_entities 相交度筛选更小的上下文
- Auth：后台低频活体巡检（如每日一次）未做；Expired profile 的授权路由仍会被尝试（可跳过并直接记 AUTH_EXPIRED，省浏览器启动且降低风控暴露）；auth 失败无退避
- **Auth 平台定义未实测（作者 2026-07-05 确认）**：AUTH_PLATFORMS 的 11 个平台（登录 URL、成功 cookie、过期指示器）是未经真实账号验证的假设。已修：小红书 `/explore` 必然假阳性指示器已移除；指示器匹配收紧为 URL 型只匹配跳转地址、文本型只匹配可见文本（原先子串匹配整页 HTML 是假阳性源）。**真实验证需要作者账号配合，计划 R1 做授权诊断面板**：分平台全链路自检（文件存在 → 解密 → 静态 cookie → 活体访问 → 模拟抓取），每阶段输出结论，按作者实际使用的平台排优先级

### 4.6 平台与工程质量
- macOS 打包：`tauri.conf.json` bundle.targets 仅 nsis，需加 dmg/app；lib.rs 进程树清理在 macOS 是 no-op
- requirements.txt 缺 fastapi/uvicorn/pyinstaller
- tests/ 为空，旧测试 mock 已不存在的接口；README 停留在 Streamlit 时代；三代 UI 共存待清理
- FastAPI `run_subscription_job` 的 session 生命周期与逐事件 commit 模式偏重（SQLite 已有 busy_timeout 缓解，暂不阻塞）

## 5. 路线图

> **2026-07-05 起，路线图以 [vision_and_blueprint.md](vision_and_blueprint.md) 的 R1-R7 为准**（作者亲述愿景后从零重构的蓝图：获取运行时 → 统一主干 → 语义层 → Watch Target → 增量与告警 → UI 换心脏 → 发布层）。本文档负责跟踪执行位置和已落地内容。
>
> **R3（语义层）第一增量已落地（2026-07-05，未提交）**：Provider 抽象 services/llm_provider.py（LLMProvider：generate+embed；GeminiProvider、OpenAICompatibleProvider 一实现覆盖 OpenAI/Ollama/LM Studio/vLLM 全部本地运行时[requests 零新依赖]、FallbackEmbedder 无 key 哈希 embedding 保证纯 RSS 地板；env 选择 LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL）；语义向量运算 services/semantic.py（引擎无关暴力余弦：相关性门/去重/线索聚类/质心增量，18 项含多语言同事件聚类单测通过）；语义摄入 services/semantic_ingest.py（embed→线索聚类→LEAD/CORROBORATED 生命周期，注入 stub embedder 端到端验证：3 篇同事件[含中文]→1 条 CORROBORATED 线索 3 来源，加密币独立，幂等）；调度加 semantic_clustering 任务（fusion 前，两模式都跑）；新表 StoryThread/ArticleEmbedding + RawArticle.thread_id。**诚实局限**：兜底哈希 embedder 是词袋，跨改写/语言聚类需真实模型；它作去重/相关性地板够用，聚类失败模式是"欠合并"（更多细线索）而非"错合并"，安全。**R3 第二增量已落地（2026-07-05）**：llm/processor.py 四个生成站点（process_article/generate_daily_briefing/scan_trends/summarize_diff）全部迁到 provider 抽象——BYOK Gemini/OpenAI 兼容/本地模型现在对摘要也生效，无 key 优雅降级（supports_generation=False 时明确报错而非崩溃）；token 记账统一走 _record_usage（预算刹车依赖，可见）；共振检测 services/semantic.py resonance_score/is_resonant（distinct sources/hour，媒体+社交跨源汇聚=愿景 #2 信号）接入 semantic_ingest，StoryThread 加 resonance_score/is_resonant 字段。stub provider 端到端验证生成解析+记账+降级；共振 5 源快速汇聚→标记 resonant 验证通过。**R3 收尾（2026-07-05）**：相关性门接入——ArticleEmbedding.relevance + RawArticle.relevance_gated（低相关项留 Raw Feed 但排除出 LLM 融合，repository 两查询已过滤）；**安全保证**：仅真实 embedder（name≠fallback）启用过滤，兜底词袋一个不杀（端到端验证 fallback gated=0）；线索 CONFIRMED（services/semantic_ingest._is_first_party 一手来源启发式：gov/edu/arxiv/github/厂商 newsroom，一手源直接 CONFIRMED，R4 portfolio 会补每目标官方域名）。端到端验证：off-topic 被 gate、github 源→CONFIRMED、融合仅取非 gated。**R3 完成。剩余仅共振信号接入告警引擎（属 R5）**。
>
> **R2（统一主干）已落地（2026-07-05，未提交）**：删除三代旧 UI 墓地（ui/ Streamlit、flet_main.py + ui/flet_views/ Flet、worker.py shim、start/stop_major_rss.bat、scratch_summary_inspect.py）并从 requirements 移除 streamlit/flet；统一 trace（services/pipeline_trace.py PipelineTracer——两条管线 tracker 抓取与 subscription 页面 diff 从各写一套发散实现合并到单一 API；订阅侧同时 print→logger、加错误分类、加 NO_NEW_ITEMS 语义）；修订阅 job 的 session 泄漏 + 逐订阅异常隔离。真实 HN feed 与 example.com 端到端验证两条管线 trace step_index 连续、状态语义一致。R2 剩余（并入后续）：SourceItem 作为文档化主干契约、页面 diff 真正并入统一 item（判断留到 R3 语义层，线索层本就在更高层统一 article 与 page-change，过早强并会造错误抽象）。
>
> **R6 前端雷达视图已落地并浏览器验证（2026-07-06，未提交）**：确认桌面端 Tauri+React 前端可在纯浏览器跑（isTauri 守卫所有 Tauri 专有 API），用预览工具建立了"改前端→浏览器验证"闭环；`.claude/launch.json` 起 Vite dev。新建 desktop/src/pages/Radar.tsx（雷达页：事件线索按生命周期 CONFIRMED/CORROBORATED/LEAD 分组，每线索显示共振徽章、来源数、"为什么提醒你"告警原因、可展开来源溯源链接），App.tsx 5 处接入路由+nav（两模式都显示），i18n 5 语言加 nav_radar。后端 GET /intelligence/threads（批量查询避免 N+1）。Dashboard 加"本周雷达战绩"KPI 面板（消费 /radar-stats）。**真实数据浏览器验证通过**：调度器抓真实 Apple Siri 新闻→聚成 1 条 CONFIRMED+共振×4 线索（bloomberg/reuters/github/9to5mac 溯源链接可点）+ 7 条单源 LEAD 线索；截图确认视觉、溯源展开、告警原因展示。**这是"聚合器→雷达"的视觉兑现。**

> **R6 后端件已落地（2026-07-06，未提交）**：services/radar_digest.py——省时间可视化（盲区 #8）GET /intelligence/radar-stats（窗口内 ingested/noise_filtered[relevance_gated]/duplicates_merged[线索多成员]/events_tracked/resonant/alerts，讲"省了多少时间"的故事，也是节目演示素材）+ 追赶简报（盲区 #7）GET /intelligence/catchup?since=（离开后"这些线索有真实增量"，按共振/来源数排序，不是一堆未读）。端到端验证（摄入 4→过滤 1 噪音+合并 2 重复+追踪 1 事件+2 告警；catchup 列增量线索带 alert_reasons）。**R6 剩余=纯前端**：目标→线索→增量视图、追赶简报/统计面板 UI、告警"为什么打扰我"展示。

> **R5（增量与告警）第一增量已落地（2026-07-06，未提交）**：默认安静仪表盘，只有值得打扰的增量才建告警。services/alert_engine.py：三类触发——RESONANCE（线索共振=跨源汇聚）、CONFIRMED_HIGH_ATTENTION（高关注目标线索确证）、CORROBORATED_HIGH_ATTENTION（高关注多源佐证）；每告警存触发原因（愿景 #2 "为什么打扰你" 可答）；(thread,reason) 幂等不重复告警；LLM 可用时合成增量摘要带引用溯源，无 model 降级为纯引用列表（永不编造、永远可溯源）。db/models.py 加 RadarAlert 表 + Tracker.is_high_attention。接入 semantic_job（聚类后评估，两模式都跑）。API：GET /intelligence/radar-alerts、/radar-alerts/undelivered（桌面通知投递轮询用）、POST .../delivered、.../read。端到端验证：共振+确证双触发、引用可溯源、幂等、未投递队列。**R5 剩余（前端）**：Tauri 系统通知投递（轮询 undelivered→通知→标记 delivered）；线索/增量视图（R6）；追赶简报、省时间可视化（R6）。
>
> **R4（Watch Target + portfolio 规划器）第一增量已落地（2026-07-05，未提交）**：架构决策——绞杀者演进 Tracker 而非另起新模型（Tracker 已有 source_intent/fetch_policy/normalized_intent，Watch Target = 被规划过 portfolio 的 Tracker，避免高风险迁移）。services/portfolio_planner.py（愿景的 SourceSelector）：给定目标产出选源组合——实体别名[多语言]、从真实 18 预设集合按域匹配选择+理由、keep/ignore 关键词、每目标预算；LLM 路径规划（provider 抽象，schema PortfolioPlan，过滤不存在的集合 id）+ 确定性关键词重叠兜底（纯 RSS 无 model 仍能规划）。POST /api/trackers/plan 端点（建目标前预览"会监听哪些源、为什么"=选源可解释）。端到端验证：罕见病→healthcare_medicine+academic_research、crypto→crypto_web3_watch、LLM 扩展多语言实体+过滤无效 id、无 key 走兜底。**portfolio 执行已接入（2026-07-06）**：source_resolver._append_portfolio_routes 把 source_scope[选中集合] 展开成预设库真实源路由（SourcePresetCollectionItem→SourcePreset.url，按 source_type 映射 adapter），_apply_budget 按 max_sources_per_run 封顶。端到端验证：healthcare_medicine→WHO/CDC 源路由、预算 cap 生效、无 scope 行为不变。**R4 剩余（前端/次要）**：/plan 接入建 tracker 表单（前端 React）；旧 tracker 迁移（空库暂无对象）；定期重规划（保守起见默认关，待有真实目标）。
>
> **当前位置**：R1（获取运行时）基本完成。**第一增量（2026-07-05）**：条件 GET（services/http_client.py + HttpCacheEntry 表，304/body-hash 双判据，接入 BasicRSSScraper）；源健康度/退避/隔离（services/source_health.py + SourceHealth 表，指数退避 2→360min、8 连败隔离，接入抓取循环 should_skip 门控）；账号守卫三支柱（services/account_guard.py + AccountGuardState 表：每账号时预算、AIMD 加性增/乘性减、熔断+半开恢复、利用率哨兵，接入抓取循环 spend/yield/risk）。**第二增量（2026-07-05）**：持久化浏览器池（services/browser_pool.py，线程本地 browser + 每账号 context 复用，替换每 URL 启 Chromium；scheduler 改用模块级持久线程池实现跨轮复用+防泄漏）；拟人化节奏（services/humanized.py，夜间静默窗+确定性抖动，接入抓取循环授权路由）；readability 正文提取（services/content_extract.py，无依赖 lxml 文本密度打分+chrome 结构剥离，替换 tier3 的 BeautifulSoup 粗提取）；授权诊断面板后端（GET /auth/profiles/{id}/diagnostics，分平台全链路自检 file→decrypt→static→live + account_guard 快照）。全部单测/集成测试通过，真实 Chromium 验证浏览器复用+提取。**R1 剩余**：诊断面板前端 UI；account_status 暴露到 Settings；trafilatura 作为可选提取升级（暂用 lxml 方案，避免 PyInstaller 体积）。
>
> 旧路线图中不属于蓝图主线但仍要做的独立事项（可穿插）：触发闭环（/run 返回 task id、run-trace 转异步）、安全边界（CSP、sanitizer、macOS Keychain）、HYBRID tier=1 断点止血。

**明确不做（修订）**：OnlyFourBot 共享层**要做**（R7：共享 token + Supabase 登录 + 发布合规，见蓝图）；仍然不做的是——开放投稿前的重型防投毒/信誉系统（第一阶段仅作者实例+受邀发布）、多平台 CLI adapter 直接 vendor 进主仓库。

## 6. 开发速查

```bash
# 后端（dev）
source .venv/bin/activate && python backend/main.py   # :8765，需 .env 里 GEMINI_API_KEY
# 桌面端（dev）
cd desktop && npx tauri dev
# 打包
cd desktop && npm run tauri:build                     # beforeBuildCommand 会先跑 build_backend.py
# 健康与日志
curl http://127.0.0.1:8765/api/settings/health        # scheduler 区块 = 引擎是否在转
curl "http://127.0.0.1:8765/api/settings/app-logs?lines=200"
# 日志文件：dev 在仓库根 logs/majorss.log；打包在 ~/.majorss/logs/majorss.log
```
