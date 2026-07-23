# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 本地情报雷达重构 (Local Intelligence Radar rebuild, R1–R7) — 分支 `feat/local-intelligence-radar`

> 把 RSS 聚合器重构为"事件线索雷达"：内容经 embedding 组织/去重/聚类，只呈现真实增量，多数内容不碰生成模型。设计见 `docs/vision_and_blueprint.md`，工程现状见 `docs/engineering_baseline.md`，测试/续作入口见 `docs/handoff_checklist.md`。当前状态：R1–R7 Phase 1 完成并经对抗审查加固；R7 Phase 2/3（Supabase 登录、多发布者、共享索引）未做。

#### Added
- **信任闭环/可观测性**：调度器心跳进 `/health` + Settings 引擎卡；滚动落盘日志 (`services/log_service.py`)；错误分类 (`services/error_classifier.py`)；统一 `PipelineTracer`（tracker + subscription 双管线合一，含 `NO_NEW_ITEMS` 语义）。
- **R1 获取运行时**：条件 GET (`services/http_client.py`，304/hash)；源健康度退避隔离 (`services/source_health.py`，per-endpoint `route_key`)；账号守卫三支柱 (`services/account_guard.py`：每账号预算 + AIMD + 熔断/半开探测 + 拟人化节奏 `services/humanized.py`)；持久化线程本地浏览器池 (`services/browser_pool.py`，重新授权失效)；readability 正文提取 (`services/content_extract.py`，无依赖 lxml)。
- **R3 语义层**：Provider 抽象 (`services/llm_provider.py`：Gemini / OpenAI 兼容[本地模型] / 无 key 兜底 embedder)；引擎无关余弦相关性门/去重/聚类/共振 (`services/semantic.py`)；线索模型 `StoryThread`（LEAD→CORROBORATED→CONFIRMED + resonance）+ `ArticleEmbedding` + `RawArticle.thread_id/relevance_gated`。
- **R4 Watch Target**：portfolio 规划器 (`services/portfolio_planner.py`，从 18 预设集合选源) + `POST /trackers/plan` + 建目标表单"选源可解释"预览；resolver 消费 `source_scope` 展开预设源路由 + 预算封顶。
- **R5 增量与告警**：`services/alert_engine.py`（共振/高关注触发，带"为什么提醒你"原因，幂等）+ `RadarAlert` 表 + `Tracker.is_high_attention` + `/intelligence/radar-alerts*`；Tauri 系统通知投递（App.tsx，isTauri 守卫）。
- **R6 UI 换心脏**：新增雷达页（阅读式信息流，按时间分组、内容优先）+ 追赶横幅 + "重点"过滤；落地页从 Dashboard 切到雷达页；Dashboard 省时间 KPI；Settings 账号保护面板；`radar_digest`（`/radar-stats` + `/catchup`）。
- **R7 Phase 1 发布层**：`services/publish_service.py` 发布导出器（本地线索 → 合规门 → PublishedDigest v0.1 JSON，契约 `docs/publish_contract.md`）+ `PUBLISH_ENABLED` 定时任务 + `POST /settings/publish` + generated RSS；公开分发站 `site/` 接真实 `digest.json`；`docs/official_feed_automation.md` 官方源自动化三形态。
- **测试**：`tests/` pytest 套件 24 项（语义/账号守卫/源健康/加密/发布合规门/管线流程），从空到覆盖对抗审查触及的核心逻辑。
- **公开分发站上线（onlyforbots.com）**：`site/` 拆为两类读者两页——介绍页 `/`（面向机器/开发者，含接入说明）+ 信息页 `/radar`（人类阅读的去噪线索流）+ `/llms.txt`（机器可读站点说明，只列现有 endpoint、规划中项归 planned）；渲染逻辑与视觉 token 隔离（`site/assets/`），只消费 `docs/publish_contract.md`（PublishedDigest v0.1）契约。部署到 Cloudflare Pages（Git 集成，push `main` 自动部署；apex/www 绑定 + HTTPS）。`docs/publish_contract.md`（契约 + 三阶段共享层演进）、`docs/official_feed_automation.md`（官方源自动化：无头实例、NAS Docker vs GitHub Actions、生成/分发端拆分）。

#### Changed
- **桌面端启动速度重构（22s → 3.7s 冷启动，作者反馈"不可接受"后）**：先测量定位——重库导入合计仅 0.59s，**冷启动几乎全是 PyInstaller `--onefile` 每次把 ~85MB 解压到临时目录的 I/O**（直接连跑 onefile sidecar：冷 ~13s、热 ~4s）。
  - **`--onefile` → `--onedir`**（`build_backend.py`）：解释器+依赖以解包形态随 app 打包（Tauri `bundle.resources` 的 `backend-bundle/`，替代 `externalBin`），启动不再解压。`lib.rs` 从 `resource_dir()/backend-bundle/backend-sidecar` 启动。实测打包后冷启动 **3.7s**。
  - **后端托盘常驻**（`lib.rs`）：关窗口本就隐藏到托盘；补上 Cmd+Q/退出也默认隐藏保活后端（`ReallyExitState`），仅托盘"退出应用"真退出。雷达持续在后台转，再开窗口连已运行后端 → 瞬间。
  - 跳过"懒加载重库"优化：测量显示导入非瓶颈（0.59s），不值改动风险。
- `llm/processor.py` 四个生成站点全迁到 provider 抽象（BYOK/本地模型对摘要生效，无 key 优雅降级）。
- `README.md` 重写为本地雷达（原为 Streamlit v1.2 时代）。
- `bundle.targets` `["nsis"]` → `"all"`（macOS 可构建 .app/.dmg）；补 `docs/packaging_guide.md` macOS 分发/签名指南（无 Apple 账号可构建+防篡改签名更新）。

#### Fixed
- 16 项对抗式多智能体审查发现全部修复（`docs/engineering_baseline.md` §2.9）：**关键** migration 0006 给已升级库补新列（否则 LLM 管线崩）；account_guard/source_health 并发 TOCTOU（进程锁 + 原子 `try_consume`）；browser_pool 重新授权后 cookie 陈旧；`db_cleanup` 无界 `.in_()` 超 SQLite 变量限；worker_subscription 早期异常 NameError；resonance 不衰减；共享健康键致一搜索失败退避全部 tracker；等。
- **作者验证阶段回归修复（打包应用实测暴露；症状都表现为"关键词目标出来全是 Google News、AI 功能像没生效"）**：
  - **Gemini 生成从未成功**（`services/llm_provider.py`）：`GeminiProvider.generate` 内联 `genai.Client().models.generate_content(...)`，临时 Client 无强引用、在阻塞 HTTP send 期间被 GC，其 `__del__` 关闭底层 httpx → 每次 "Cannot send a request, as the client has been closed."，静默退回无 AI（`embed()` 因把 client 绑到局部变量而幸免，掩盖了问题）。改：模块级按 key 缓存 Client（持强引用防 GC + 复用连接池）+ generate 显式持有引用；默认模型 `gemini-3-flash-preview` → `gemini-3.6-flash`（经 `models.list()` 对配置 key 核实）。**影响全部 AI 生成**：规划器/摘要/日报/趋势。
  - **保存的 API key 重启即失效**（`backend/main.py`）：`save_api_key` 只把 key 注入当前进程 `os.environ`，而 provider 从环境解析、启动从不预载 config.dat → 每次重开应用 key 静默失效、退回无生成兜底。改：lifespan 启动 `load_dotenv` + 从 config.dat 预载 `GEMINI_API_KEY`/`LLM_*` 到环境。
  - **关键词目标从不挂精选源**（`backend/api/trackers.py`）：创建目标时未持久化 `source_scope`（"预览会监听哪些源"是纯预览）→ 目标只跑关键词 OSINT、从不拉厂商一手 RSS/changelog/论文，塌缩成 Google News 元搜索。改：`create_tracker` 建目标时自动跑 portfolio 规划器补 `source_scope`。
  - **无 key 兜底规划器过弱**（`services/portfolio_planner.py`）：token 重叠对 grok/xai 等具名实体匹配不到 AI 集合、只落 general_baseline。改：加实体→领域词典（grok/xai/gpt/claude/bitcoin/cve…→对应精选集合），兑现"纯 RSS 模式无 key 也有价值"。
  - **溯源显示聚合器而非真实媒体**（`desktop/src/pages/Dashboard.tsx`）：原始流 Google News 条目显示 `news.google.com` 而非真实发布方。改：聚合器条目从标题后缀 "- Publisher" 提取真实媒体展示（图标仍按 host）。
  - **启动加载页抖动**（`desktop/src/App.tsx`）：健康轮询每 ~1.5s 往轨迹追加一条 + 失败时把多行运行时快照塞进详情，在垂直居中布局里导致整屏上下弹跳。改：状态框/轨迹框固定高度内部滚动；轮询只更新实时状态、轨迹只记状态转变、快照只进一次。
  - **新建探测向导步进错位**（`desktop/src/pages/Discovery.tsx`）：`handleNextStep` 在第 0 步就校验第 1 步的信号 → "下一步"永远报错无法前进。改：按步门控（第 0 步校验主题、第 1 步校验信号）。
  - **试运行/诊断误报超时**（`desktop/src/pages/Discovery.tsx`）：`/test-resolve-intent` 同步逐源联网抓取实测 ~22s，超过 axios 全局 15s 超时 → 假"测试失败"（后端其实成功）。改：该慢调用单独放宽超时（试运行 60s、诊断 180s）+ 有用的超时提示。已知更深缺口（后端并发化/异步，`docs/engineering_baseline.md` §4.2）留待处理。
- **同类设计审计的后续修复（按上面这批 bug 的特征回扫全库）**：
  - **订阅页"试运行 diff"同款超时**（`desktop/src/pages/Subscriptions.tsx`）：`test_diff_route_trace` 同步抓取 + 前端全局 15s 超时，与 tracker 试运行是同一个 bug，之前只修了 tracker 一半。改：同样放宽到 60s + 友好提示。
  - **Investigator 绕过 provider 抽象**（`llm/investigator.py`）：情报溯源两条流水线都硬走 `genai.Client(GEMINI_API_KEY)`、硬编码 `gemini-2.5-flash`、独立 token 记账 → 对本地/OpenAI 兼容模型用户完全不可用（违反愿景 #3 BYOK），且是 R3 provider 迁移的遗漏。改：自建漏斗（DDG→triage→抓取→verdict）的 LLM 调用改走 `get_provider().generate()`（任意后端可用）；原生 Google Search grounding 是 Gemini 专属，加守卫（非 Gemini 时给出改用漏斗的提示而非报错）；token 统一走 `_record_usage`（预算刹车可见）。
- **语义/嵌入层深挖 + 债务清偿（2026-07-23，从"关键词目标全是 Google News、同一事件重复推送"一路挖到根）**。审计与收口计划见 `docs/semantic_layer_audit.md`：
  - **根因链**：扇出（关键词目标只抓第一个源，抓到 Google News 就 `break`，精选一手源永远够不到）→ `create_tracker` 建目标时未持久化 `source_scope`（前已修）→ **embed 模型 `text-embedding-004` 已停服返回 404**，`run_semantic_ingest` 每 5 分钟静默抛异常，**整个语义层（embedding/聚类/去重/线索/告警）从打包第一天就 100% 死**，所有下游缺陷被掩盖。R3 当年只用 stub embedder 验证过，真实嵌入路径从未真跑。
  - **扇出**（`services/scraper_service.py`）：区分"独立来源全抓"与"同源多方法组内首成即停"，先临时 fanout、后重构为**路由分组**（组间全抓、组内第一成功即停）——通用修复 ACCOUNT 多账号只抓第一个、HYBRID 授权账号回退冗余重打。
  - **社交账号源路由**（`services/source_resolver.py`）：人物源 `source_type=account`（`x.com/<handle>`）此前落进 RSS 解析器每轮必败；改按账号走 RssHub twitter 路由 / 其他走 agentic 快照。
  - **embed 模型 404**（`services/llm_provider.py`）：`text-embedding-004` → `gemini-embedding-2`（`models.list` 核实可用），语义层首次真正运转。
  - **向量坍缩（各向异性）导致过度合并**（`services/semantic.py`）：真实嵌入挤在窄锥内（任意两条 AI 新闻余弦 0.6–0.9），阈值 0.62 把 44 篇不同事件揉成一条线索。改：聚类前**去均值**（各向异性校正，分离度约翻三倍）+ 候选地板（0.05，保证跨语言同事件成候选）。
  - **LLM 事件仲裁**（`services/semantic_ingest.py`）：embedding 提合并、LLM 判"是否同一事件"——把最强实体的不同事件也分开（"Gemini 3.6 发布" vs "Gemini 星座运势"）。成本可控：仅灰区合并触发、仅配了生成模型时启用、每轮上限、进 token 记账。实测 17 篇实体大杂烩 → 12 条事件级线索；跨语言（中英日）同事件正确合并成一条。
  - **fusion 唯一约束死循环**（`repositories/repository.py`）：`save_intel_report` 插入以 lead 文章 `raw_article_id`（唯一）为键的 IntelReport，若该文章已有报告（派生表被重置但 IntelReport 未清时）→ 唯一约束冲突 → 整批 rollback（含 `processed=True`）→ 文章保持未处理 → 每周期重试失败不止。改为幂等（存在则原地更新 + 始终标 processed）。
  - **`Optional` 未导入致 sidecar 启动崩**（`backend/api/settings.py`）：新配置模型用了 `Optional[str]` 但只导入了 `List`，`ast` 语法检查通过但打包 sidecar 启动即 `NameError`。已改用"真实 import 全部改动模块"作为验证关口。
  - **计费公式重构 + embedding 记账 + 真实模型名**（`services/pricing.py` + `Billing.tsx`）：此前成本 = `总 token × 单一混合费率`（前端硬编码 0.15 flash / 2.5 pro），忽略输出比输入贵数倍；`embed()` 从不记 token → embedding 消耗恒为 $0、预算刹车看不到；所有记录 model_name 都是 "gemini" 无法区分。改：后端按模型分输入/输出计价（官方价格，`ai.google.dev/gemini-api/docs/pricing`，2026-07-23 核实），embed 补估算记账，generate/embed 盖真实模型名。
  - **模型与后端配置 UI**（Settings「模型与后端」+ `/settings/llm-config`）：provider 抽象此前 env-only、打包用户改不到；新增 provider(Gemini/OpenAI 兼容/本地) + base_url + 生成/嵌入模型选择，落 `.env`（启动加载）。选「OpenAI 兼容」+ Base URL 即把生成与嵌入全走本地（Ollama/LM Studio/vLLM）——兑现愿景 #3 本地优先。

#### 雷达质量与成本路线图执行（2026-07-23，`docs/radar_quality_roadmap.md`）

> 北极星（成本梯度三段式）：以最低成本获得**广+深+新**的抓取 → **冲合并**（廉价向量把量坍缩成事件线索）→ **LLM 只处理合并后的线索**。终态：智能摘要与雷达合并为一——feed 卡片 = 每个事件线索上的一段摘要。实测对比与设计见 `docs/radar_quality_roadmap.md`、`docs/source_tiering.md`。

- **P0.1 gnews 源头日期限定** (`services/source_resolver.py`)：查询拼 `when:{max_days}d`，源头拦截优于抓后过滤。新鲜度成为一等设置项、与探测强度解耦（`Discovery.tsx`）。
- **P0.2 融合标签诚实化** (`services/processor_service.py`)：`摘要引用来源` / `重复·佐证来源`，不再把同事件他源报道误称"被过滤的噪音"。
- **P0.3 修复向量层卡死** (`services/llm_provider.py` + `services/semantic_ingest.py`)：整批 embed 一次失败即整批回滚、什么都不落库 → 同一批永远重试，向量层冻结在 100/1101。改：`GeminiProvider.embed` 逐条节流+瞬时错误退避重试，永久失败项返回 `None` 由摄入跳过——一颗坏文章不再阻塞整批；致命鉴权错误照常抛出。实测越过 id-100 卡点。
- **P0.4 真实出版方计数 + 来源分层捕获**：① `distinct_source_count` 改数**真实出版方**（从 Google News 标题 " - Publisher" 提取），不再数聚合器域名——此前 reddit/gnews 占 80% 语料全塌成 1 源，佐证/共振/生命周期信号 100% 死；实测线程 1→8 真实出版方，信号复活。② 新 `services/provenance.py`（共享 `Tier`/`is_first_party`/`real_publisher`），入库全链路盖来源层级章 `SourceRoute.tier → SourceItem.tier → RawArticle.source_tier`（迁移 0007），一手域名精修为 `primary`，raw-feed API 暴露。抽走 `semantic_ingest`/`publish_service` 各自复制的一手判定。
- **P2.1 融合作用于事件线索（智能摘要与雷达合一）**：融合从"盲批 10 条 → IntelReport"改为"**每事件线索一次摘要 → `StoryThread.summary`**"（`services/processor_service.py`，迁移 0008）。消除同事件被切成多份、去掉跨报告去重机制（线索即去重单元）、强制"先聚类再 LLM"（无 `thread_id` 的文章等待语义层）。`/feed`、每日简报、趋势扫描、Dashboard、`radar_digest`、`cli.py get`(MIP/agent 面) 全部改读线索；`/feed` 响应结构不变，前端零改动。IntelReport 表与旧数据保留（休眠、可回滚）。经 4 路对抗式代码审查加固：backfill 折进融合查询（部署后 feed 自动回填、无死代码）；送 LLM 的成员（`FUSION_MAX_MEMBERS` 封顶）与 provenance/计数（全体成员）解耦（溢出成员不再被静默丢弃）；重融不降级已 VALID 线程、保留最高 importance、保证原始 lead 入摘要；`db_cleanup` 按 retention 清理 StoryThread（FK 安全）；旧 TrendAlert（存 IntelReport id）在 0008 清空；补 `summarized_at` 索引。
- **P1.1 渠道分层/共振门控** (`services/processor_service.py:_thread_worth_summary`)：只有值得的线索才烧 LLM——高权重（`source_tier` primary/curated、CONFIRMED 生命周期、高关注目标）直接过门；聚合消防栓要靠**共振**或 `distinct_source_count ≥ FUSION_MIN_SOURCES`(默认 3) 挣得摘要。未过门线索停在 lead（不烧生成模型），信号变了下轮再评估。配合 P2.1 backfill：回填只摘"值得的"线索，聚合噪音不烧钱。
- **P0.5 入库近重去重** (`services/dedup.py` + `services/source_normalizer.py`)：廉价确定性预过滤，剥掉近乎逐字的转载（同标题多站重发）以免白花 embed+fusion。**身份护栏**（版本号/日期周期/退化标题）杜绝把序列/版本兄弟误合并（月度 "Developer Update"、`v0.117.1` vs `.0`）——审计证明护栏而非阈值才是过度合并的控制点。约 3–4% 体积，安全网而非成本杠杆（真正的去重靠向量语义合并）。
- **P1.2 Billing 按动作/目标拆分** (`backend/api/settings.py` + `desktop/src/pages/Billing.tsx`)：`/settings/token-usage` 新增 `by_category`（向量 vs 融合 vs 趋势 vs 简报）/`by_target`（每探测目标）/`by_action`，每类带真实费用；Billing 页新增两张卡（成本构成条形 + 按目标表）。实测拆解：融合 76% · 向量 8% · 趋势 10% · 简报 5%——省钱杠杆在融合、不在向量（向量还可切本地 Ollama 归零）。

##### 作者实测阶段的回归修复（2026-07-23 装包实跑暴露）

- **去均值路径崩溃,整个语义层再度冻结**（`services/semantic_ingest.py`）：各向异性校正读存量向量时写的是 `for (vjson,) in s.exec(select(ArticleEmbedding.vector)).all()`，但 SQLModel 的 `session.exec(单列 select)` 返回的是**标量**而非 1-元组 → 一旦 `ArticleEmbedding` 有行就抛 `too many values to unpack`，**每轮 semantic 整个崩掉、什么都不落库**。此前被 P0.3 的批量嵌入卡死所掩盖（根本走不到这行）；P0.3 修好后执行推进到这里，症状换了根因不变：嵌入停在 100、线索冻在 10:43、feed 空。改为标量/Row 双兼容。**测试盲区归因**：集成测试用 fallback embedder，`gating_enabled=False` 恰好跳过该分支——此后动语义层必须专门跑一遍真 embedder 的 gating 路径。修复后实测解冻：嵌入 100→430+、线索时间戳恢复推进、生命周期出现 CORROBORATED(最高 11 个真实出版方)与 RESONANT。
- **广告混入雷达：相关性门是"话题相关"不是"编辑价值"**（新增 `services/noise_filter.py` + `services/source_normalizer.py`）：reddit `r/DiscountOffer90` 的「[OFFER] Gemini Ai Pro 代金券 $4.99」广告，对 Gemini 目标的相关度高达 **0.648**（阈值 0.35）——因为它字面就是"关于 Gemini"。**向量无法区分"关于 X 的新闻"与"卖 X 的广告"**，调高阈值只会先杀死真新闻。故加一道**正交的确定性入库筛**：① 社区市场标签（`[OFFER]/[WTS]/[WTB]/[H]…[W]` 等结构化前缀）；② 促销子版块（`/r/<sub>` 名按 camelCase/数字分词后匹配 discount/deal/coupon/giveaway… ，故 `r/IdealSociety` 不会被 "Ideal" 里的 "deal" 误伤）。**刻意不用松散词**（coupon / "30% off" / cheap）——"Nvidia 降价 30% off"是真新闻；此处精度优先于召回：漏掉一条广告只是小烦扰，误杀一条独家是产品事故。在 embed/fusion 之前拦下，零成本。
  - **同轮迭代（实测驱动）**：首版只按 camelCase/数字/下划线分词，漏掉**全小写连写**的版块名（`r/subscriptionsharing`、`r/DiscountandVouchers`）→ 补一道**高辨识度子串**匹配（discount/coupon/giveaway/forsale/cheap/promo/subscriptionsharing/accountsharing…），仍刻意排除 `deal`/`sale`/`share` 这类会命中 `IdealSociety`、`wholesale` 的词。回溯全库共识别并清理 **16 条**促销贴（账号代购、Steam key 交易、游戏飞船交易、银币买卖等，全部来自 reddit 关键词搜索）。

#### Security
- macOS/Linux 密钥存储 base64 明文回退 → 真 Fernet 加密（`services/crypto_service.py`，0600 密钥文件，兼容旧文件迁移）。
- 前端 feed 链接 `javascript:` XSS → `safeHref` 只放行 http(s)。
- R7 发布合规门：摘要非全文、PII 清洗、授权（登录态）来源内容硬排除、溯源三件套、AI 诚实标注。

#### Removed
- 三代旧 UI 墓地（Streamlit `ui/`、Flet `flet_main.py`/`ui/flet_views/`、`worker.py` shim、`*.bat`）+ streamlit/flet 依赖。

### Added
- **Source Preset Seed Library**:
  - Added an audited seed library in `docs/source_presets.seed.json` with broad baseline sources, regional perspectives, AI, developer tools, healthcare, academic research, policy, cybersecurity, finance, and crypto/Web3 collections.
  - Added `docs/source_preset_classification.md` to define the split between broad baseline sources, vertical source packs, high-weight non-RSS sources, and source trust labels.
  - Added `docs/rss_feed_generation_method.md` documenting how MajorRSS can adapt an Olshansk-style generated RSS pipeline for high-value public pages without native feeds.
  - Added `docs/local_radar_upgrade_plan.md` describing MajorRSS as a local personal information radar with OnlyFourBot as an optional sharing and reuse layer.
- **Application Mode Helper**:
  - Added `services/app_mode.py` as a shared backend helper for checking `APP_MODE` and pure RSS mode.
- **Source Preset Database Seed**:
  - Added database-backed source preset tables for built-in sources, collections, and collection membership.
  - Added startup seeding from `docs/source_presets.seed.json`, syncing 133 sources, 18 collections, and 177 collection links into the local database.
  - Added `/api/source-presets/collections`, `/api/source-presets/sources`, and `/api/source-presets/seed` endpoints for preset library access.
  - Wired the Sources page preset tab to the local source preset API, replacing the old Coming Soon placeholder with collection filtering, source counts, trust badges, and a manual re-seed action.
  - Bundled `docs/source_presets.seed.json` into the PyInstaller backend sidecar so packaged installs can seed the official preset library without the source tree.

### Changed
- **Pure RSS Mode Backend Behavior**:
  - Pure RSS mode now skips scheduled AI processing jobs and scheduled trend scans in `scheduler.py`.
  - Manual tracker runs now queue only scraping tasks in pure RSS mode instead of also queuing AI processing.
  - Manual trend scan requests now return a skipped response in pure RSS mode instead of queuing an AI-dependent trend scan.
  - `services/processor_service.py` now uses the shared app mode helper for pure RSS checks.

### Fixed
- **Desktop Installer Backend Packaging Guardrail**:
  - Updated the Tauri production build flow so `npx tauri build` rebuilds the PyInstaller backend sidecar before compiling the desktop installer.
  - Limited Tauri bundle targets to NSIS and MSI installers to avoid producing the misleading standalone `app-portable.exe`, which did not carry the backend sidecar and caused the frontend to keep waiting for `127.0.0.1:8765`.
  - Added `npm run build:backend` and `npm run tauri:build` scripts for a single explicit packaging entry point from `desktop/`.
  - Verified the new release app starts `backend-sidecar.exe` and returns `200` from `/api/settings/health` locally.
  - Removed stale files from `builds/` so manual testing uses the freshly generated installers under `desktop/src-tauri/target/release/bundle/`.
  - Added NSIS installer hooks that prompt before upgrades/uninstalls and attempt to close `app.exe` plus `backend-sidecar.exe`, preventing file overwrite failures when an older MajorRSS backend is still running.
  - Hardened app shutdown so the tray Exit action and global Tauri exit events both stop the saved sidecar child and, on Windows, also terminate the PyInstaller `backend-sidecar.exe` process tree by PID/name to handle onefile parent/child process leftovers.
  - Added a system-tray tooltip and a one-time desktop notification when the main window is closed, clarifying that MajorRSS is still running in the tray and must be exited from the tray menu for a full shutdown.
  - Added detailed startup diagnostics to the desktop loading screen, including sidecar command resolution, sidecar spawn status, backend stdout/stderr, health-check attempts, elapsed time, and the exact local health endpoint being tested.
  - Extended startup diagnostics with sidecar termination/error events plus Windows `tasklist` and `netstat` snapshots so failed test machines can distinguish "sidecar process did not start" from "process exists but port 8765 is not listening".
  - Added a packaged-mode database startup guard: stale or unreachable Postgres `DATABASE_URL` settings now use a short connection timeout and fall back to local SQLite for the current session instead of preventing the backend from listening on port 8765.
  - Included database startup diagnostics in `/api/settings/health`, including database kind, config path, and any startup database error summary.
  - Delayed scheduler workload execution so scraping, processing, trend scans, and webpage monitoring no longer run immediately during backend startup.
  - Limited Windows packaging output to NSIS only because the current upgrade/uninstall process cleanup hooks are NSIS-specific.
  - Fixed packaged Tauri WebView CORS by allowing `http://tauri.localhost`; affected builds could show a backend connection failure even while `backend-sidecar.exe` was listening on `127.0.0.1:8765` and returning `200 OK`.
  - Documented the packaging assumption that end-user machines do not need Python installed because the backend sidecar is a PyInstaller onefile executable; the Windows installer still relies on Tauri's WebView2 bootstrapper flow for WebView2 availability.
  - Pending external validation: install the new package on another Windows machine and confirm the backend sidecar starts correctly in a clean environment.

## [2.5.1] - 2026-06-19

### Fixed
- **Desktop Sidecar Infinite Loading**: Fixed the packaged EXE showing infinite loading screen caused by the backend sidecar failing to start.
  - Fixed `sys.path` resolution in `backend/main.py` to use `sys._MEIPASS` in PyInstaller frozen mode, preventing `ModuleNotFoundError` on all local modules (`db`, `services`, `scrapers`, `llm`, etc.).
  - Rewrote `backend-sidecar.spec` and `build_backend.py` to include all hidden imports (both local project modules and third-party packages like `apscheduler`, `dotenv`, `feedparser`, `bs4`, `duckduckgo_search`, `google.genai`) and bundle local module directories as data files.
  - Excluded unnecessary packages (`streamlit`, `flet`, `pytest`, `tkinter`, `matplotlib`) from the sidecar build to reduce binary size.
- **Tauri Capabilities**: Added missing `shell:allow-spawn`, `shell:allow-open`, and window operation permissions (`allow-show`, `allow-hide`, `allow-set-focus`, `allow-is-visible`, `allow-is-maximized`) to `capabilities/default.json`.
- **CSP Policy**: Extended Content Security Policy in `tauri.conf.json` to include `ws://127.0.0.1:8765` (WebSocket), `font-src 'self' data:`, and `blob:` for images, preventing silent request failures in production.

## [2.5.0] - 2026-06-10

### Added
- **3-Layer Pipeline Tracing & Observation System**:
  - Introduced `PipelineRun` and `PipelineEvent` database tables to log granular execution history (stages: `RESOLVE`, `FETCH`, `DEDUPLICATE`, `LLM_FILTER`, `SAVE`, `DIFF`), total/accepted counts, latency metrics, error stack traces, and cost indicators.
  - Automatically records pipeline diagnostics during background scheduled cron tasks in [scraper_service.py](file:///d:/majorRSS/services/scraper_service.py) and webpage checks in [worker_subscription.py](file:///d:/majorRSS/worker_subscription.py).
  - Added fast FastAPI diagnostic REST endpoints (dry-runs, trace histories, manual run-traces, and JSON trace log exports).
  - Enforced strict trace privacy rules: desensitizes targets, and completely scrubs raw HTML/parsed text, cookies, and authentication headers.
- **Intent-First Wizard Forms & Developer Accordion**:
  - Revamped topic-based `Discovery` and `Subscriptions` modals into clear, intent-centric step-by-step form wizards.
  - Completely hides low-level technical parameters (`tier`, `max_items_per_route`, `js_rendering`, custom selectors, route strategies) under a developer-only accordion.
  - Added a global "启用开发人员模式 (Enable Developer Mode)" switch in Settings, which unlocks advanced options in forms and diagnostic "诊断 / Pipeline Trace" dashboards on lists.
- **Unified Sources Library Dashboard**:
  - Built a new `Sources.tsx` dashboard containing credentials (Auth Profiles), local subscribed feeds, active discovery keyword signals, and preset collections.

### Changed
- **Dynamic Auth Credentials Routing**:
  - Removed static task-level credentials. The route resolver now automatically queries and maps active `AuthProfile` sessions on resolved platform routes at runtime.
- **Strict Mode Keyword Safeguards**:
  - Enabled the `trusted_news_only` keyword strategy to automatically query Google News and filter out public forums (HN/Reddit), avoiding query dry-outs.

### Fixed
- **FastAPI Main Import Failure**: Resolved module-scope `NameError: name 'PipelineRunResponse' is not defined` inside `backend/api/trackers.py` by ensuring proper import order at load-time.
- **Frontend TS6133 Compiler Errors**: Removed unused imports and variables in React pages (`Discovery.tsx`, `Subscriptions.tsx`, `Settings.tsx`, `Sources.tsx`) to resolve production build (`npm run build`) and linting (`npm run lint`) blocks.
- **Canonical Intent Mapping**: Centralized the `normalized_intent` caching and override flow inside `services/intent_normalizer.py`.
- **Trace Sensitive Data Protection**: Implemented regex-based token/cookie/auth header scrubbing in `services/privacy.py` for trace database writes.


## [2.4.0] - 2026-06-09


### Added
- **Welcome Onboarding Wizard (First-time Onboarding Modal)**:
  - Implemented a welcome onboarding modal that triggers on the very first launch, helping users easily configure their desired experience (AI Intelligence Fusion vs Pure Local RSS Mode).
  - Designed the modal dismissing mechanism to only persist `onboarding_completed: true` in `localStorage` if the user explicitly checks the dismissal checkbox, preventing accidental bypasses.
  - Skips background AI processing worker pipelines programmatically when running in Pure Local RSS mode (`APP_MODE = 'pure_rss'`).
- **Segmented Native Language Selector**:
  - Integrated a highly visible native language switcher at the top of the onboarding modal utilizing Mantine's `SegmentedControl`.
  - Supports English, Simplified Chinese, Japanese, Korean, and Russian in their native scripts ("English", "简体中文", "日本語", "한국어", "Русский").
  - Instantly updates all localized text of the onboarding modal on a single click, preventing user confusion upon first open.
- **Pure Local Raw Articles Feed & HTML Rendering**:
  - Added a dedicated raw article list feed inside the Dashboard page layout, which displays raw, unprocessed RSS feeds and webpage articles.
  - Replaced plain text rendering with native HTML parsing utilizing `dangerouslySetInnerHTML` inside `RawArticleCard` in `Dashboard.tsx` to prevent raw HTML markup tags (like `<p>`, `<a>`, comment blocks) from cluttering the reader view.
  - Configured CSS styled overrides (`.raw-article-html-content`) in `index.css` to format paragraphs, clickable accented links, margins, and fluid responsive images within raw HTML articles.
  - Localized expand/collapse toggle buttons in raw article views using new keys `dash_show_content` ("展开正文") and `dash_hide_content` ("折叠正文") in translations.

### Fixed
- **Misleading Mode Switch Alert**:
  - Changed the misleading "Database configurations saved successfully" popup alert during application mode switches to a localized run-mode-specific confirmation ("系统运行模式切换成功！" / "Application run mode updated successfully!").
- **TypeScript Compiler Warnings & Type Inference Errors**:
  - Resolved `Unused setRawLoading state warning` in `Dashboard.tsx` by using it to manage active fetching indicators.
  - Eliminated implicit `any` type warnings for parameters inside alert lists and notification mapping routines.
  - Successfully verified a 100% green compilation build for production Tauri packaging.

## [2.3.0] - 2026-06-09

### Added
- **Database Storage & Lifecycle Management**:
  - Implemented SQLite WAL (Write-Ahead Logging) mode and `synchronous = NORMAL` settings via SQLAlchemy connection listeners in [database.py](file:///d:/majorRSS/db/database.py) to prevent concurrency write locking.
  - Created a database status utility [db_cleanup_service.py](file:///d:/majorRSS/services/db_cleanup_service.py) to calculate db file size (SQLite and PostgreSQL), table row counts, retention limits, and flag size limits and count expired records.
  - Added cleanups to delete expired records, trim the oldest 25% of data when size exceeds limits, and execute connection-level `VACUUM` (SQLite) / `VACUUM ANALYZE` (PostgreSQL) to compact storage.
  - Added new REST API endpoints `/settings/db-status`, `/settings/db-settings`, `/settings/db-cleanup`, `/settings/db-test-connection`, and `/settings/db-switch` inside [settings.py](file:///d:/majorRSS/backend/api/settings.py).
  - Automatically extracts and decrypts active PostgreSQL credentials to return and populate form fields in the frontend.
  - Integrated the **Database & Storage Management** panel card in [Settings.tsx](file:///d:/majorRSS/desktop/src/pages/Settings.tsx) with warning alerts, size and table counts grids, retention dropdowns, and an interactive database engine switcher.
  - Added translation keys inside [translations.ts](file:///d:/majorRSS/desktop/src/i18n/translations.ts) across English, Chinese, Korean, Japanese, and Russian.

### Fixed
- **Tauri Windows App Packaging**: Rebuilt the frozen Python sidecar executable to package the new cleanup/PostgreSQL helper services, and successfully packaged production MSI installer and NSIS standalone setup EXE bundles with `npx tauri build`.

## [2.2.0] - 2026-06-09

### Added
- **Integrated Codex-Style Custom Titlebar**: Hidden native OS window borders and title bars (`"decorations": false`) in Tauri configuration. Implemented a custom window titlebar in React (`TitleBar.tsx` / `TitleBar.css`) supporting dragging, minimization, maximization, and close operations via native Tauri APIs.
- **Collapsible Sidebar Layout**: Added a toggle button in the header (`PanelLeftClose` / `PanelLeftOpen` icon) to collapse or expand the navigation sidebar. When collapsed, the sidebar width scales down to `54px` (previously `70px`), displaying centered icon buttons with zero horizontal padding and hover tooltips. Placed the header toggle button inside a width-dynamic wrapper to align its center vertically with the sidebar icons on a single layout grid axis.
- **Cleaned Header & Title Layout**: Simplified the custom TitleBar title to just "MajorRSS" (English name only), removed the redundant shield logo and title text, and reduced the AppShell Header height from `60px/92px` to a compact `48px/80px` to save vertical space.
- **Adjusted Default Window Scale**: Changed default desktop app window startup size in `tauri.conf.json` from `800x600` to `1280x800` to provide a comfortable default layout proportion.
- **Rounded Card Window Layout**: Configured transparent window support (`"transparent": true`) in Tauri. Applied 12px rounded borders and a thin, glowing border to the `#root` wrapper in windowed mode, which smoothly transitions to sharp corners and removes borders when the window is maximized. Resolved visual artifacts by setting transparency on both `html` and `body` elements to eliminate sharp dark corner highlights.

### Fixed
- **ASGI Module Import Crash in Frozen Sidecar**: Fixed a critical crash where the compiled backend sidecar binary failed to start with `Error loading ASGI app. Could not import module "main"`. Modified `backend/main.py` to check `sys.frozen` and pass the FastAPI `app` object directly (`uvicorn.run(app, ...)`) in frozen mode.
- **Sidebar Toggle Button Alignment**: Fixed toggle button horizontal alignment mismatch in both collapsed and expanded states by removing the default padding on AppShell.Header and mathematically matching the padding-left and container centering widths to the vertical axis of the navbar icons.
- **Light Mode Style and Contrast Audit**: Fixed poor text contrast in light mode by replacing hardcoded dark-mode backgrounds and white text with theme-dynamic styles (`className="title-text-color"`, `c="dimmed"`) and `isDark` conditionals across all pages (Dashboard, Briefing, FactChecker, Billing, Monitors, Trackers, Settings).
- **Dynamic Titlebar Background Color Scheme**: Enabled the custom window TitleBar background and button hover states to adapt along with the active dark/light theme (matching `#101113` in dark mode and `#ffffff` in light mode).
- **Internal Vertical Scroll Constraint**: Fixed content overflow cutoffs in windowed mode by setting `overflowY: "auto"` and constraining the height (`calc(100vh - header_offset)`) on the main `AppShell.Main` content container.
- **Localization of Auth Portal Architecture Tip**: Localized the Interactive Cookie Auth Portal warning tip into all 5 system languages using `set_auth_architecture_tip` inside translations, resolving the Chinese-only warning box issue.

## [2.1.0] - 2026-06-09

### Added
- **Dual-Mode Trackers Input**: Added Simple Mode (for bulk copy-pasting newline-separated lists of URLs, keywords, or accounts) and Hybrid Mode (three separate textarea inputs for mixing urls, keywords, accounts, OSINT options, and max age) in the client's Tracker Modal form.
- **Contextual Deduplication & Source Merging**:
  - Automatically queries the 8 most recent intelligence reports as context (`RECENT_REPORTS_CONTEXT`).
  - Instructs Gemini to compare new content against recent reports and return the duplicate report ID if similar.
  - Automatically appends/merges new valid sources and raw URLs into the existing report and marks them as processed instead of generating duplicate cards on the dashboard.
- **Scheduler Concurrency & Rate Limit Safeguards**:
  - Implemented sequential loop batching of 10 articles per batch with a `1.5s` delay between batches to protect Gemini API RPM/TPM limits.
  - Sequentially executes AI processing tasks across trackers in the scheduler.
  - Restricts background Playwright crawler concurrency to `max_workers=2` to prevent memory/CPU spikes and queue clogging.
- **SQLAlchemy Session Management & Leak Fixes**:
  - Configured `expire_on_commit=False` on the DB sessionmaker to eliminate detached instance errors across backend threads.
  - Updated all database sessions across LLM processor and investigator tasks to use proper context managers or close connections explicitly.
- **Naive UTC Timezone Standardization**:
  - Added `utc_now_naive()` helper to strip timezone offsets before database writes.
  - Standardized all `created_at` fields and scraper daemons to store naive UTC datetimes. This prevents connection-timezone skew where Shanghai local time was treated as future UTC time, causing the scheduler to freeze.
  - Cleaned up database stuck states and repaired historical future-skewed timestamps.
- **Token Auditing & Chart Calculations**:
  - Logged LLM token usage for all investigator fact-checking queries.
  - Aggregated trend data over all database records on the backend, resolving the discrepancy where the Billing trend chart's sum did not match the totals.
- **Card Clutter & Title-Summary Alignment**:
  - Enforced client-preferred language output (defaulting to Chinese, English, Korean, Japanese, or Russian) inside `FactCheckResult`.
  - Implemented automatic custom title extraction (`[TITLE: ...]`) and 80-character default title truncation to prevent long social media titles from cluttering the dashboard cards.
- **Dynamic Client-Controlled LLM Generation Language**:
  - Added backend settings API `POST /api/settings/system-language` to save the active client language context to the local `.env` environmental configuration.
  - Linked the frontend language selector in `Settings.tsx` to automatically update the backend's environmental settings.
  - Configured all asynchronous Gemini extraction, briefing, trend alert, and diff summary prompts to dynamically adapt to the user's active client language preference instead of locking to Chinese.
- **Interactive Cookie Auth Portal Restoration**:
  - Restored the 11-platform interactive cookie authentication grid inside the Settings page (`Settings.tsx`), showing status indicators (Active, Expired, Not Authorized) and last login timestamps.
  - Added backend status check (`GET /api/settings/auth/status`) and headful Playwright browser login trigger (`POST /api/settings/auth/login`) API endpoints.
  - Implemented full multi-lingual (i18n) translation dictionaries for the auth portal UI elements.

## [2.0.0] - 2026-06-09

### Added
- **Desktop Architecture Migration (Tauri 2 + React + Mantine 9.3)**: Migrated the entire user interface from Streamlit to a desktop application powered by Tauri 2, React 19, and Mantine 9.3, providing a smooth desktop app experience with native-feeling responsive views.
- **FastAPI API Server Integration**: Restructured the backend python pipeline into a FastAPI web API server (`backend/main.py`), utilizing APIRouter for trackers, settings, and intelligence feeds. Decoupled the worker queues and scheduler to run within FastAPI's lifespan startup hook.
- **NotebookLM-Style Tabbed Sources Layout**:
  - Implemented a vertical list sources panel inside a glassmorphic container (`rgba(21, 23, 27, 0.6)`) featuring dynamic counts in pill badges (`在报告中引用的来源数` / `未引用的来源数`).
  - Integrated Google Favicon API for loading source site icons, with robust React `SourceIcon` fallbacks to Lucide icons upon loading failure.
  - Replaced plain text urls and simple cards with `<Anchor>` components and subtext descriptions showing actual cited text/quotes.
  - Added a `折叠来源分析 ∧` action button at the bottom of the scroll area for collapsing the sources panel easily.
- **Rotating Warning Alerts Carousel**: Designed a clean, rotating warning alert carousel showing one trend trigger card at a time with a 5-second auto-rotate loop and indicator dots.
- **Redesigned Trend Alert Detail Modal**: Hidden inline source badges from the warning alert card, moving them into the detail modal in a matching NotebookLM vertical layout.
- **Multi-Language (i18n) & Theme Toggle**: Integrated dynamic client-side language switching across 5 system languages (English, Chinese, Korean, Japanese, Russian) and a Light/Dark color scheme selector.

### Changed
- Replaced deprecated Mantine layout properties (such as `align` on `Paper`/`Text`) with standard style parameters (`mah` and `ta`) to resolve React console warning logs.
- Expanded `TrendAlertSource` schema to support and return source descriptions extracted from the database report summaries.

## [1.5.1] - 2026-06-03

### Fixed
- **Underlying Network Engine Refactoring (SSL Fix)**: Completely replaced the legacy `urllib` backend used by `feedparser` with the robust `requests` library in the foundational Tier 1 Scraper (`scrapers/tier1_rss.py`). This permanently resolves widespread `[SSL: UNEXPECTED_EOF_WHILE_READING]` EOF handshake errors and `HTTP Error 502` blocks caused by modern CDNs and firewalls on Windows systems, restoring reliable probing across all basic RSS and Hub endpoints.

## [1.5.0] - 2026-05-28

### Added
- **Transparent RSSHub Engine (智能嗅探与路由)**: Implemented a seamless middleware (`scrapers/url_normalizer.py`) that acts as a universal adapter for social media URLs. When users input a Bilibili, Twitter, YouTube, Weibo, TikTok, or Xiaohongshu profile URL into *any* part of the system (Tracker or Webpage Monitor), it is instantly and invisibly converted into a highly stable RSSHub XML endpoint, completely bypassing aggressive anti-bot mechanisms.
- **Hybrid Subscription Architecture**: Upgraded the `worker_subscription.py` daemon. The Webpage Monitor now dynamically detects the underlying protocol. If it sniffs an RSS/XML stream (e.g., routed via the new transparent engine), it bypasses the heavy Playwright headless browser entirely, utilizing a blazing-fast `requests` pipeline to fetch and diff the latest XML entries. This reduces server memory usage and eliminates captcha blocking for social media targets.

### Changed
- **Separation of Authentication Concerns**: The Interactive Cookie Auth feature is now strictly reserved for the Fact-Checker (溯源竞技场) module's deep-dive investigations. Everyday broad intelligence gathering is fully delegated to the new RSSHub engine.

## [1.3.1] - 2026-05-16

### Fixed
- **Source Evidence Hallucination Fix**: Resolved a critical UX issue where the AI's "Source Evidence" block would display completely irrelevant URLs (e.g., noisy fallback posts from Reddit's search API). Upgraded the `FactCheckResult` JSON schema with a `relevant_source_indices` array, forcing Gemini to explicitly cite the exact sources it utilized and dynamically filtering out all unmentioned noise from the frontend display.
- **High-Concurrency PostgreSQL Bottlenecks**: Fixed recurring `QueuePool limit of size 5 overflow 10 reached` TimeoutErrors during heavy scraping and intelligence fusion loads. Upgraded the SQLAlchemy engine initialization for PostgreSQL with enterprise-grade pooling limits (`pool_size=30`, `max_overflow=50`) and enabled `pool_pre_ping` to ensure connection health and eliminate threading deadlocks.

## [1.3.0] - 2026-05-15
### Added
- **Webpage Subscription & Diff Monitoring**: Architected a new top-level parallel business line specifically for tracking non-RSS entities (API documentation, Bilibili/YouTube dynamic homepages, personal blogs).
- **Smart Diff Filter**: A specialized `BeautifulSoup` engine that intelligently strips out volatile DOM noise (e.g., dynamic view counts, follower numbers, `<time>` tags) and anchors on structural skeleton changes (`<a>` links and long paragraphs) to eliminate false-positive alerts.
- **On-Demand AI Summarization (Dialog UX)**: Leveraged Streamlit's `@st.dialog` to provide a lightweight, popup-based Diff viewer. Users can inspect the exact code-level additions/deletions and trigger a single-shot Gemini LLM summary only when deemed necessary, drastically reducing token waste.
- **Global Auth Registry Expansion**: Extensively scaled the interactive cookie auth helper to support 11 international platforms, including VK, Naver, Niconico, Reddit, LinkedIn, Twitter, Xiaohongshu, Bilibili, TikTok, Weibo, and Instagram. Added a dynamic cookie health-check diagnostic function.

### Changed
- **Modernized UI Typology**: Completely phased out legacy operating-system emojis from the sidebar and navigation UI in favor of precise, scalable `Streamlit Material Icons` (SVG) for a cleaner, unified aesthetic.

## [1.2.0] - 2026-05-14
### Added
- **Interactive Cookie Auth**: Implemented a state-of-the-art interactive login helper using Playwright's `storage_state`. Allows users to bypass strict anti-bot measures by authenticating in a real headful browser window with one click from the UI. The state (including LocalStorage) is seamlessly injected into the headless scraper.
- **Dynamic Scrape Intervals**: Users can now configure custom scraping intervals (in minutes) for individual trackers, avoiding rate-limiting on high-frequency monitors while saving resources on low-priority ones.
- **Editable Data Grids**: The active trackers management dashboard now supports inline editing via Pandas DataFrames for quick adjustments to status, intervals, and names without navigating to a new form.

### Changed
- **Database Architecture Migration**: Successfully migrated the entire backend persistence layer from local SQLite to robust PostgreSQL, resolving concurrency locking issues and enabling high-availability deployments.

## [1.1.0] - 2026-05-12

### Added
- **Chronological Event Timeline**: The LLM processor now acts as a "Time Detective," actively extracting the true publish/event time from raw article content. The UI Dashboard now sorts intelligence primarily by this `event_timestamp` rather than the system scraping time.
- **Dynamic Noise Deduplication**: Introduced a zero-cost Python `difflib` similarity engine for the Agentic Scraper. If a website's snapshot changes by < 5% (e.g., ticking clocks, ad rotations), it is immediately discarded to prevent LLM hallucination duplicates. RSS feeds now also feature dual-layer URL and Title exact-match deduplication.

## [1.0.0] - 2026-05-11

### Added
- **Global i18n Support**: Introduced a robust multi-language architecture supporting English, Simplified Chinese, Japanese, Korean, and Russian.
- **Smart Language Sniffing**: The backend now automatically reads the browser's `Accept-Language` HTTP header to seamlessly render the correct local language without page reload flashes.
- **Supabase-Style UI**: A completely redesigned, ultra-minimalist `64px` persistent sidebar using native Streamlit routing and CSS overriding. 
- **Agentic Scraper (Tier 3)**: Integrated a Playwright-based headless browser to defeat advanced JavaScript rendering and anti-bot systems.
- **LLM Cost Auditing**: A built-in Dashboard to track all local token usage (differentiating Gemini Flash and Pro) and estimate costs based on real-time API pricing.
- **Automated Daily Briefing**: Scheduled synthesis of global intelligence using Gemini 1.5 Pro to connect the dots across 24 hours of data.

### Security
- Shifted all frontend JS-based parameter injections to secure backend native parsing to completely resolve cross-origin iframe sandbox `SecurityError` vulnerabilities.
