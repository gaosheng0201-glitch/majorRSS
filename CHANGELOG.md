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

##### 架构复盘六项修复（2026-07-23，作者要求"不欠债"：对 changelog 已修项做成熟度审查，6 项实测证实后全部修复）

- **①迁移只加列不建索引（系统性）**：`thread_id`/`relevance_gated`/`source_tier` 模型声明 `index=True`，但 `create_all` 只在新库建索引、`ALTER TABLE` 不会补 → 升级库热路径全表扫。迁移 `0009` 补 `CREATE INDEX IF NOT EXISTS`×3。
- **②relevance 门从未生效（死门）**：实测 0/1590 篇被 gate——真实嵌入的原始余弦全在 0.41–0.81 锥内，阈值 0.35 在分布之外。病根与聚类同款（各向异性），当年只修了聚类没修 relevance。改：relevance 与聚类共用去均值空间；**校准实测**（21 噪音/64 信号样本）定为**垃圾地板 0.05**——挡 156/1614 篇明确跑题（"Claude 拒绝改邮件"、手机求助帖），**已知信号零损失**（最低信号 0.066=xAI 诉讼；0.07+ 就开始误杀）。高权重层（curated/primary）不参与。明确降级定位：这是垃圾地板不是信号选择器，编辑判别归 P5。
- **③线索按 tracker 隔离 → 跨目标重复摘要**：4 个高重叠 AI 目标下同一事件各成线索（实测 7+ 对同题跨 tracker 线索）。有界修复：入库近重去重改全局（与 URL 全局唯一语义一致）+ 融合前跨 tracker 近重摘要守卫（已有摘要的事件不再二次付费）。线索全局化留作结构性后续。
- **④门控线索永不 processed**：285 条被门线索成员永远 `processed=0` → Dashboard "pending" 永久虚高 301 且每 5 分钟全量重评（churn 随积压线性涨）。改：gate-miss 标记成员 processed + 盖 `gate_checked_at`（0009 新列），backlog 查询只重评 `last_update_at > gate_checked_at` 的线索——新成员到达自动重触发，静止线索零 churn。
- **⑤共振=传播速度非独立确认**：P0.4 数了真实出版方，但同一通稿多家转载仍伪装成多源。改：`distinct_source_count = min(独立出版方, 近重标题家族)`（复用 P0.5 机器）。实测：67 条 dsc≥2 线索中 14 条虚高、8 条纯转载伪佐证正确降回单源（含审计点名的"马斯克谢美光"实体光环项），真佐证大事件（12→10）安然保级。
- **⑥IntelReport 三个死方法删除**（save_intel_report/get_recent_reports/append_sources_to_report，grep 证实无调用者），防"IntelReport 还在写"的误导；表保留作回滚。
- **实机部署验证（21:09 版装机后探针实测）**：迁移 0009 落库、3 索引建立、`gate_checked_at` 实时递增（61→67）、pending 从 313 开始排空、日志零错误。全部六项在真实运行中生效。
- **中断纠偏记录**：实现过程中会话被中断，恢复后逐文件甄别半成品——迁移 0009/去均值结构/gate 列保留；**中断前定的阈值 0.10 被边际校准推翻**（会误杀 4 条已知信号，含 0.086 的 Gemini 3.6 上线与 0.066 的 xAI 诉讼）改为 0.05；③④⑤⑥ 从零补齐。全部单测+集成测试+实机验证后一次提交。
- **元教训（今后的验证关口）**：①②同属"changelog 写着已做、现实中从未生效"——relevance 门跑了数月拦截数为 0、索引声明了却不存在。验证必须验**效果**（真拦到东西没有、索引真的在不在），不能只验**行为**（代码跑通不报错）。

##### 第一梯队：供给侧与健康（2026-07-28，B1–B6 —— "噪音问题有一半是供给问题"）

审计结论是屏幕被垃圾填满、部分原因是**好的那一层是黑的**：7 个追踪账号 0 成功、21/39 精选源零产出、gemini 目标裸奔。本梯队专修供给侧。

- **B1 新鲜度断言**（`services/source_health.py` + `scraper_service.py`）：**HTTP 200 不等于源还活着**。实地验证的三类"看着健康实则已死"：`syndication.twitter.com` 返回 200 + 格式完好的 JSON，但最新条目 **8 个月前**（该账号天天发）；`nitter.net` 对脚本 UA 和限流都返回 **200 + 空体**；第三方生成 feed 仓库还在动、发布的 XML 早已冻结。对雷达而言**静默陈旧比明确报错更危险**——它悄悄抽掉一整个话题，仪表盘却全绿。新增 `record_fetch` 改按**条目日期**判活：投递过却持续空返回（`EMPTY_RESPONSE`）、有条目但最新超期且此前更新鲜（`STALE_CONTENT`）→ 走 `record_failure` 退避/隔离并让同组回退梯队接手。三条护栏：无投递历史的新源/低频源永不惩罚、无日期条目不误判、恢复新内容即转健康。
- **B2′ 早期信号源（纯数据，零新机制）**：新增 `ai_early_signals` 预设集合——TestingCatalog 泄露 feed（实测当日头条即「Anthropic preparing for potential Claude Opus 5 rollout」，正是作者最初追问的那条爆料）+ 库中已有的 SDK releases。OpenRouter `/models`、models.dev 属**会变的文档**，按架构裁决归**监控道**而非雷达管线，连同实测体积（585KB / 3.2MB）与配置建议写入 `docs/early_signal_sources.md`。
- **B3/B4 人物雷达复活**（`services/source_resolver.py` + `scraper_service.py`）：7 个追踪账号从未成功，两个原因叠加——预设账号源被锁死在**单条 rsshub 路由**（无回退）而公共实例已永久禁用 twitter 路由；且其 `platform="rsshub"` 导致 `_enrich_routes_with_auth` 永远匹配不上 twitter 授权档案，**授权了也用不上**。改：预设与关键词账号共用同一 helper 生成三级回退——**nitter.net 优先**（零凭证，7/7 实测通过）→ rsshub（自建实例才有意义）→ 授权 agentic 快照，全部 `platform="twitter"` 以便挂授权；`_route_group` 认得预设梯队命名，三级同组、首成即停，避免每轮都触发昂贵的浏览器梯队。**依赖 B1**：没有新鲜度断言，nitter 的空响应会被读成"今天没新闻"而永不回退。
- **B5 `keep_keywords` 只作用于聚合层**（`services/source_normalizer.py`）：查"21/39 精选源零产出"，根因出人意料——**这些源根本没坏**：各有约 **510 次成功抓取**且内容新鲜（arXiv 每天 340 篇、HuggingFace 833 篇、Cloudflare/Anthropic Status 均为当日）。全部在入库时被 `keep_keywords` 丢弃：该过滤器要求标题/正文含品牌词，而**官方发布很少重复自己的品牌名**，聚合器条目却必然命中（关键词本就是搜索词）。于是过滤器把用途搞反了——**该收窄的消防栓一条没拦，用户亲手挑的精选源被删干净**，这正是 94% 语料来自聚合器的结构性根因之一。改为仅对 AGGREGATED 生效；精选/一手源整体信任（质量由垃圾地板 + 融合门控把关）。顺带给 **gemini 目标补上它从未有过的 `source_scope`**（此前纯关键词裸奔，是最大碰撞簇来源）。
- **B6 一手信任按路径细分**（`services/provenance.py`）：PRIMARY 无条件绕过融合门，于是**域名级信任被对方公关部消费**——审计抓到 openai.com 的客户故事与社论享受和模型发布同等付费待遇。`/customer-stories`、`/global-affairs`、`/careers`、`/pricing` 等营销路径降为 CURATED（仍受信任、仍免关键词过滤，但要像其他源一样挣摘要）；`/index/`、`/news/` 等真公告路径保持 PRIMARY。

##### 多日实跑暴露的两个"未结算"缺陷（2026-07-28，作者连跑数日后反馈）

作者报告三个体感：待处理任务每天变多、老新闻被顶上 feed 但没有内容增量、新闻不够新。查证后：**两个真缺陷 + 一个误会**，两者同属一类病——**某阶段"故意不处理"某些内容，却没把它们标记为已结算**，于是在别处表现为无限增长或反复重做。

- **①垃圾地板拦下的文章永不结算 → 待处理无限增长**（`services/semantic_ingest.py`）：地板标了 `relevance_gated=True` 却留 `processed=False`，**572 条待处理里 526 条是被地板故意排除的**，Dashboard KPI 只增不减。与架构复盘④（门控线索永不 processed）**同一病灶的漏网路径**——当时修了 P1.1 融合门控那条，漏了 relevance 地板这条；而且正因为②把地板从"死门"修活，这个洞才开始每天涨几百。改：地板拦下即结算；迁移 `0010` 清历史积压。实测 **pending 613→87**。
- **②重摘要不要求实质增量 → 老闻反复重烧并顶回 feed 顶部**（`services/processor_service.py` + 迁移 `0010`）：任何新成员都触发整条线索重摘要并刷新 `summarized_at`，**实测 560 次融合调用只产出 145 条摘要（3.9× 重烧）**，首见 4–5 天前的线索长期占据 feed 顶部而内容无变化。改：线索已有摘要时，重摘要须有**实质增量**（新增独立出版方 或 生命周期晋级），对照上次融合时的信号快照（新增 `fused_source_count`/`fused_lifecycle`，迁移回填 145/145 避免升级后集体重摘）；同一故事的更多副本只结算——**零 LLM 调用、feed 位置不动**。这关闭了 P2.1 遗留 #7，同时省掉 3.9 倍重烧开销。
- **③"新闻不够新"= 误会**：应用被作者手动停止 12 小时（日志停在 03:27、进程为空、抓取断在 07:16 UTC），非代码问题；但②会加重该体感（老闻反复占顶）。已重启恢复。
- **实机验证（15:14 版）**：迁移 0010 应用、pending=87、快照回填 145/145、零新报错。
- **概念澄清（作者提问）**：lead ≠ "未翻译的 feed 流"——lead 是**已嵌入/去重/聚类成事件、但未挣得 LLM 摘要**的线索；未加工的逐条文章是「原始订阅数据流」。

##### 作者实测阶段的回归修复（2026-07-23 装包实跑暴露）

- **去均值路径崩溃,整个语义层再度冻结**（`services/semantic_ingest.py`）：各向异性校正读存量向量时写的是 `for (vjson,) in s.exec(select(ArticleEmbedding.vector)).all()`，但 SQLModel 的 `session.exec(单列 select)` 返回的是**标量**而非 1-元组 → 一旦 `ArticleEmbedding` 有行就抛 `too many values to unpack`，**每轮 semantic 整个崩掉、什么都不落库**。此前被 P0.3 的批量嵌入卡死所掩盖（根本走不到这行）；P0.3 修好后执行推进到这里，症状换了根因不变：嵌入停在 100、线索冻在 10:43、feed 空。改为标量/Row 双兼容。**测试盲区归因**：集成测试用 fallback embedder，`gating_enabled=False` 恰好跳过该分支——此后动语义层必须专门跑一遍真 embedder 的 gating 路径。修复后实测解冻：嵌入 100→430+、线索时间戳恢复推进、生命周期出现 CORROBORATED(最高 11 个真实出版方)与 RESONANT。
- **广告混入雷达：相关性门是"话题相关"不是"编辑价值"**（新增 `services/noise_filter.py` + `services/source_normalizer.py`）：reddit `r/DiscountOffer90` 的「[OFFER] Gemini Ai Pro 代金券 $4.99」广告，对 Gemini 目标的相关度高达 **0.648**（阈值 0.35）——因为它字面就是"关于 Gemini"。**向量无法区分"关于 X 的新闻"与"卖 X 的广告"**，调高阈值只会先杀死真新闻。故加一道**正交的确定性入库筛**：① 社区市场标签（`[OFFER]/[WTS]/[WTB]/[H]…[W]` 等结构化前缀）；② 促销子版块（`/r/<sub>` 名按 camelCase/数字分词后匹配 discount/deal/coupon/giveaway… ，故 `r/IdealSociety` 不会被 "Ideal" 里的 "deal" 误伤）。**刻意不用松散词**（coupon / "30% off" / cheap）——"Nvidia 降价 30% off"是真新闻；此处精度优先于召回：漏掉一条广告只是小烦扰，误杀一条独家是产品事故。在 embed/fusion 之前拦下，零成本。
  - **同轮迭代（实测驱动）**：首版只按 camelCase/数字/下划线分词，漏掉**全小写连写**的版块名（`r/subscriptionsharing`、`r/DiscountandVouchers`）→ 补一道**高辨识度子串**匹配（discount/coupon/giveaway/forsale/cheap/promo/subscriptionsharing/accountsharing…），仍刻意排除 `deal`/`sale`/`share` 这类会命中 `IdealSociety`、`wholesale` 的词。回溯全库共识别并清理 **16 条**促销贴（账号代购、Steam key 交易、游戏飞船交易、银币买卖等，全部来自 reddit 关键词搜索）。

##### P4 前置：每条获取管线都要真的能跑（2026-07-29 ~ 08-05，作者要求"p4 之前要确保每个获取信息管线正确运行，auth 态的我还完全没有测试呢"）

先按 `pipelineevent` 实测每条入口的健康度，而不是凭日志印象：

| 路由 | 运行 | 成功 | 症状 |
|---|---|---|---|
| preset | 17486 | 13086 (75%) | 主力，正常 |
| gnews | 2167 | 2155 (99%) | 健康 |
| hn | 2157 | 1321 (61%) | 416× 502 |
| reddit | 2157 | 511 (**24%**) | 498× 429 |
| nitter | 420 | 219 (52%) | B3/B4 后恢复 |
| rsshub | 399 | **0** | 公共实例已永久停用 twitter 路由（已知，非缺陷） |
| agentic | 399 | **0** | 浏览器找不到 |

`authprofile` 表为空——**授权态从未运行过一次**。本轮修复的四类问题有一个共同点：**它们都自我掩盖**，看到的症状从来不是原因。

- **①agentic 0/399：Playwright 自己假设打包应用自带浏览器**（`services/browser_pool.py` + `scrapers/tier3_agentic.py` + `backend/api/auth.py` + `scrapers/auth_helper.py`）。根因是 Playwright `_transport.py` 里的一行——`if getattr(sys, "frozen", False): env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")`。`"0"` 意为"浏览器在包内"，对打包时收了浏览器的应用成立，我们没收，于是打包版永远去 `driver/package/.local-browsers/` 找一个**从未存在过的目录**。整个浏览器能力（连同通往登录墙平台的唯一路径）静默下线。因其用的是 `setdefault`，抢先设好即可覆盖：新增 `ensure_browsers_path()`（有打包浏览器则用包内，否则指向 OS 缓存；确实缺失时返回**可执行的安装指引**而非启动失败），授权建档 / cookie 活检 / 交互登录三条路径同样接入——它们本会以完全相同的方式失败。
  - 连带三个**被它掩盖**的缺陷：`_fetch_one_off` 在池子已起过 Playwright 的同一线程里再起一个（sync API 每线程限一个），抛出的 "Sync API inside the asyncio loop" 是**关于回退本身**的错误，把真正的原因挡在后面（改用 `one_off_browser()` 复用本线程驱动）；回退对**任何**池内失败都触发，包括页面超时——第二个浏览器会以同样方式失败，等于给注定失败的抓取加倍计价（改为只在**取页失败**时回退，那是它唯一能修的东西）；`goto` 用 `wait_until="networkidle"`，而**需要浏览器的站点恰恰是持续轮询的那些**，networkidle 永不触发、每次烧满 60s 超时，x.com 要 120s 才失败（改 `domcontentloaded` + 5s 有界沉降，**120s → 15s**）。
  - **渲染后正文不足 200 字符视为空**：未登录的 x.com 恰好只抽得出 `<title>`（25 字符），而 `adapters.py` 只挡 `if not text` —— 页面标题一直在被当作正文；对监控道更糟，标题一变就是一次**假变更事件**。
- **②reddit 24%：作用域错误，不是端点故障**（新增 `services/host_politeness.py`）。单条路由都没问题。`source_health` 按**端点**退避（有意为之：一条失效的 gnews 关键词搜索不该拖垮共享 `news.google.com` 的所有目标，其 docstring 一直写着"域名级礼貌是另一件事"——那件事从未被实现）。而 429 是按**主机**下发的：一轮生成 ~23 条 reddit 路由连发，第一个 429 教不会另外 22 个。新模块补上缺失的作用域：同主机请求间隔化（未授权 reddit 6s、HN 2s、志愿者维护的公共实例 5s）、429 冻结整个主机（翻倍至 1 小时）、单次 5xx 是噪音但连续 3 次是主机在要求让路、任何成功即解除。
  - 只加间隔会**把限速换成饿死**：6s 间隔下 23 条需两分多钟，而路由顺序稳定，同样几条会永远抢到名额、其余永不运行。故每轮**从上轮用尽名额处接着服务**——实测每轮 4 条、6 轮覆盖全部 23 条。被让路的路由记为 SKIPPED 并带原因，让上限出现在管线日志里，而不是伪装成"已覆盖"。
- **③一次主机级拒绝被记了两笔账**（`services/scraper_service.py` + 迁移 `0012`）。冷却生效后日志仍满是 `quarantined` 和 `backoff:8732s`——旧规则把一次 host-wide 拒绝同时记到主机和当时在飞的每个端点头上，而**端点付出的代价高得多**：隔离是自我维持的，被隔离的路由永不运行 → 永不成功 → 永不解除。实测 16 条 reddit 端点背着 `RATE_LIMITED` 处罚（5 条已彻底隔离、退避最长 2.4 小时），无一条是它自己造成的。
- **④同一条规则的另一半：能力缺失也不是端点的错**（`services/error_classifier.py` + 迁移 `0013`）。装上修好的构建跑第一轮，浏览器管线明明活了却仍**全部跳过**——`source_health:backoff:19682s`。旧版找不到浏览器的那些天，每一次失败都被记在端点头上：7 条 x.com 路由全是 `7 次失败 / 0 次成功`，**再失败一次就永久隔离，而错在我们自己**。③当时是按特例处理的；它不是特例，是一条规则：**端点健康回答的是"这个源值不值得重试"，那么源没造成、也无法避免的失败就不该塑造它**。两类统一为 `NOT_ENDPOINT_FAULT`（`RATE_LIMITED` 归主机层 / 新增 `CAPABILITY_UNAVAILABLE` 归其自身诊断），而非继续堆 if 分支。`CAPABILITY_UNAVAILABLE` 排在 `SOURCE_UNAVAILABLE` 之前分类，免得错误信息里的浏览器路径被误读成"源挂了"。迁移按"从未成功 + 错误未分类"定范围（**正是浏览器停摆的签名**，实测 7 行全为 x.com），刻意宽松：误放的路由一轮内会再失败并重新挣回退避，而漏放则让一个已修好的能力持续数小时看起来是坏的。
- **⑤账号来源改为入口盖章**（`services/provenance.py` → `SourceRoute.is_account` → `SourceItem.from_account` → `RawArticle.from_account`，迁移 `0011`）。见下方架构审查 Drift 2。
- **实机前后对比（同一天，旧构建全天 vs 新构建修复后一轮）**：429 **15 → 1**、502 **8 → 0**、浏览器缺失 **7 → 0**、成功 58；剩余 8 条 `endpoint health` 跳过全部核实为**真实故障**（rsshub 公共实例永久停用 ×6、HN 真 502 ×2），不该被"修"。agentic 路由现为 `SUCCESS / 0 items`——**这正是未授权下的正确行为**：空壳被 200 字符下限如实报告为"没有内容"，而不是伪造成正文。
- **授权流程首次运行**：交互登录窗口确实弹出（`[browser_pool] Playwright browsers: …` + `Waiting for user to login`），作者选择暂不登录（等准备小号，避免主账号风险）。原实现失败时只给一行"required cookie not found"并丢弃全部证据，无从区分"没登录就关窗"与"登录了但 session cookie 落在没查的地方"——这正是它长期无法测试的一大原因。改为报告捕获到多少 cookie、来自哪些域、分别是什么，**只记名称与域名**：cookie 的值就是凭据本身，绝不可进日志或 API 响应。
- **测试 24 → 41**：新增 `tests/test_host_politeness.py`（作用域 bug 本身、冷却范围、5xx 阈值、增长与解除、轮转公平与覆盖、被让路不占名额、能力缺失 vs 真实源故障的分类）与 `tests/test_account_provenance.py`（旧启发式的两个失效方向、关键词消防栓永非人物雷达、门控读取盖章）。
- **仍挂账（需作者裁决）**：打包不含浏览器（chromium 336M + headless_shell 189M）。当前依赖机器上已有的 `playwright install`——开发机有，新用户没有。选项：打进安装包 / 首次运行按需下载 / 让 agentic 保持可选能力。

##### 呈现层三修（2026-08-13，作者两问"为什么没抓到"——布林接管 Gemini、Gemini 3.7 Flash 发布）

查证结论：**两个都不是抓取层的问题**。布林故事线在库里有 50 篇（英文 8/5 起、中文 8/11 才跟进，滞后 6 天）、主线索 4217 有 21 家出版方且有摘要；3.7 Flash 官方公告 17:04:18 UTC 进 feed、应用 17:01:48 刚查完（**差 2.5 分钟**）、下轮 17:31 即入库；泄漏预告 8/11 就抓到了，比官方早两天。**坏的是呈现层：早期的、单源的、权威的信号被系统性静音** —— 恰是愿景最看重的那类（"社交源天然领先媒体数天"）。三个缺陷，全部当日修复并实机验证：

- **①RSS 时间戳全体 +5 小时**（`scrapers/tier1_rss.py`，抽出 `entry_published_at()`）：feedparser 的 `published_parsed` 是 UTC struct，旧代码 `time.mktime()` 按本地**标准时**解释（EST=UTC-5，`tm_isdst=0` 连夏令时都不理）→ 每条 RSS 的发布时间被推向未来 5 小时。三个 DeepMind 样本零例外（17:04→22:04、14:01→19:01、15:06→20:06）。作者起初猜是纽约/太平洋时区显示差 —— 8 月的纽约是 EDT(-4)、太平洋是 -7，**恰好 +5 = EST** 才是 mktime 的指纹。修：`calendar.timegm`。对溯源产品，"谁先报"曾被按源类别系统性搅乱。
- **②`deepmind.google` 不在一手地板**（`services/provenance.py` + 迁移 `0014`）：`blog.google` 在名单、DeepMind 自己的域名不在 → gemini 目标最权威的公告以 CURATED 入库 → 单篇 LEAD → 过不了 ≥3 家门 → 永不出摘要。**实机预测并应验**（公告 17:31 入库时 tier=curated）。清查：110 个 official_feed preset 中 77 个不被认作一手，但**大多数是对的** —— 媒体该是 CURATED；组合型厂商博客（cloudflare 等）**不能**加，否则实测过的 5/5 跑题免检复活。只加前沿实验室自有频道档（deepmind.google/mistral.ai/x.ai/claude.com/ai.meta.com/engineering.fb.com/research.facebook.com/huggingface.co[code-host 路径守卫仍生效]/github.blog）+ `.gov.uk` 后缀。per-target 精确判定归 P4.0（provenance.py 注释本就写着"这是地板"）。迁移 0014 经真实 `tier_for_url` 重盖旧行：实库 **95 篇 → primary、76 条线索晋级 CONFIRMED** 并清 gate 标记排队重评。
- **③事件仲裁只看 top-1 候选**（`services/semantic.py::assign_thread_candidates` + `semantic_ingest.py`）：布林那篇的最近邻是另一条同产品单篇线索，仲裁否得**对**（确实非同一事件）——但它真正所属的 21 家出版方线索排第二、从未上桌。一个错误但最近的邻居，否决了它身后所有正确答案。实测代价：**仲裁 80% 拆分率（666 调用 533 拆）、88% 线索为单篇（5750/6515）、dsc≥3 仅 1.8%** —— 聚类层近乎失效。修：top-1 → top-K（K=3），仲裁沿列表问到"是"为止，**判断标准一字未动**；新增 `rescued` 计数（= 旧流程必然错拆的合并），预算语义保守化（列表中途预算耗尽 → 新线索，不回退到已被否决的候选）。
- **刻意不动**：仲裁提示词的"同一故事线"语义（严格 "same event" 下，卸任→接管→砍版本本来就是不同事件）。先量 top-K 后的拆分率/rescued 率再定 —— 动语义有重新引入过度合并的风险。单篇 lead 可见性归 P6。
- 测试 41 → 53：`tests/test_surfacing_fixes.py` 钉死三修（UTC struct 不再漂移、实验室域名 PRIMARY / 媒体与组合博客不升级 / code-host 守卫仍生效 / AGGREGATED 永不升级、候选列表有序有底且布林形态的第二候选可达）。

##### P6 雷达视图收口（2026-08-13 —— 三处重叠展示合一，回到愿景 41 行"日用界面只有一个"）

作者 7-29 的原始困惑"雷达和 feed 的关系我一直没看明白"，根因是它们本就该是一个东西：「AI 智能提炼情报」「原始订阅数据流」「雷达页」三处展示相似内容。按作者 UX 裁决（按模式切换第二个 tab）落地：

- **雷达页成为唯一阅读面**。AI 模式两个 tab：`提炼`（挣得摘要的线索，**卡片即摘要**——P2.1 终态"feed 卡片 = 线索上的一段摘要"就此兑现；`/threads` 新增 `view=refined|leads`，服务端裁掉摘要的机器附录 `--- **:material/…** …` 并采用融合标题）｜`线报`（已聚类未挣得摘要的线索）。纯 RSS 模式：雷达页即**订阅流本身**（全量未过滤）——一等模式，非降级（愿景 147 行）。
- **线报按入口盖章分层**（`from_account`/`aggregated_only`，按全部成员计算）：追踪账号线报可见并标注「**未证实线报**」（愿景 95-102"第一时间可见而不冒充新闻"）；**聚合器单源默认折叠**（实测 156/200 —— 正是把真线报淹没的那 90%），一行计数可展开。折叠判据刻意排除 curated 单源：用户自选源的产出保持可见（B5 教训）。
- **意料之外但正确的发现**：人物雷达豁免让账号线报很快挣得摘要，所以多数线报住在提炼 tab —— 那里同样标注（实测 14 条，全是追踪账号 Grok 爆料），单源账号摘要不冒充新闻。
- **Dashboard 1218 → 470 行**：底部两个重复 feed 区、`IntelReportCard` 及其孤儿辅助函数整体移除，回归纯 KPI 大屏；`RawArticleCard` 与来源显示辅助抽为共享组件（`components/RawFeed.tsx`、`components/sourceDisplay.tsx`）。
- **信任闭环**：AI 模式下线报 tab 底部保留「查看原始订阅数据流（含已过滤条目）」折叠入口 —— relevance_gated 条目只存在于原始流，隐藏它会把垃圾地板从软过滤变成不可见过滤。
- 浏览器双模式实测：提炼卡片标题/摘要干净（附录裁除验证）、折叠组 156 条可展开、原始流入口加载 50 卡、纯 RSS 模式导航自动瘦身、情报大屏纯 KPI 正常。

##### P6 当日补丁：时间诚实 + 板块筛选（2026-08-13，作者实测反馈）

- **老闻顶帖的根治（作者裁决：整套方案）**。病例实测：3.6 Flash 线索（首见 7/23、39 家出版方）因第 38、39 家媒体迟到转载，当天**重烧融合 2 次**、盖着"刚刚"排在当天真正的新闻（3.7 发布）之前。根因是 7-28 定的实质增量"任何新增出版方"没有建模**边际递减**——3→4 家真的改变可信度，37→39 家什么都不是。三件事一个根：
  - `is_material_increment`（`services/processor_service.py`）：实质 = 出版方**相对增长 ≥25%** 或生命周期晋级。同一条规则同时修**排序污染**和**大线索重烧成本**。
  - 提炼面按 `summarized_at` 排序分桶（收紧后它就意味着"最后实质变化时间"），线报面按首见（线报的价值就是新）；`last_update_at` 不再参与排序——它逢成员加入就动，正是顶帖的元凶。
  - 行内双时间戳「**首见 X · 进展 Y**」（差距 >24h 才显示进展）——迟到转载既不产生"进展"也不改"首见"，无法再把旧闻装扮成新闻。
  - 迁移 `0015`：按新规则**回放**每条已摘要线索的出版方到达序列（基线仅在实质点推进，镜像融合快照语义），把旧规则写高的时间戳退回真实实质点。实库 964/972 条回退；只回退不前移。验证：3.7 线索排位升至 3.6 之前。
- **板块筛选恢复**：P6 执行时丢了旧卡片的 `radar_section`/探测器标识（遗漏而非决定）。雷达页 tab 下补目标筛选行（全部/各目标），「全部」视图行内带目标名。实测：筛 `sports-Ohtani-EN` 后重点计数联动，MVP 线索显示「首见 8月6日 · 进展 刚刚」。
- 测试 53 → 58：增量规则五例钉死（小线索增长过、大线索迟到转载不过、晋级任意规模过、零增长永不过、从零起步过）。
- 顺带记录：3.7 Flash 当天存在两条独立线索——跨线索合并缺口，归「结构性后续·线索全局化」。

##### P4.0a 意图探索第一刀（2026-08-20 —— 架构中枢开工,合同 docs/p4_intent_design.md）

- **一句话 → 结构化任务提案**：`plan_intent()` 产出 IntentPlan——雷达/监控**分道判断**（P4.0 核心新增）、语言无关实体画像（每别名带 lang/regions,执行语言三原则①②）、**per-target 官方域名**（provenance 地板注释欠的那笔,b 刀接入消费）、排除歧义词、回填窗与节奏。`POST /trackers/plan-intent`。
- **幻觉守卫**：集合 id 过滤、域名格式校验、无确切 URL 的 monitor 自动降级回 radar、warmup/interval 钳制。提案永不自动落库——Discovery 第 0 步渲染提案卡,「应用到表单」后仍可逐项编辑,确认保存才生效（可解释 > 自动化）;监控道给「确认建为页面监控」直达订阅管理（作者裁决默认:直接建但明示）。
- **绞杀者存储**：完整 plan 存 `fetch_policy.intent_plan`,同时下转旧键（entities/keep/ignore/source_scope/max_days）——现运行时立即受益,行为零变化;b 刀让 resolver 直接消费 AliasSpec 后,运行时字形猜测正式退居兜底。
- **纯 RSS 地板不动**：无 key 走确定性规划,lane 默认 radar,叙述语言按输入字形判定;手动表单原样保留。
- **真实 LLM 三个裁决边界例实测**：大谷翔平 → 「大谷翔平」按 zh(CN,TW,HK) 与 ja(JP) 分成两个 AliasSpec + Shohei Ohtani(en/US);gemini → 排除词一次覆盖 horoscope/astrology/双子座/运势/**Winklevoss/exchange**（比当初"招来星座"的投诉考虑得还全）,官方域名 deepmind.google/blog.google/ai.google.dev/ai.googleblog.com 全对;「这个页面价格表变了告诉我 <URL>」 → monitor 道带确切 URL。浏览器全流程验证:提案卡渲染、应用回填、进入第二步可编辑。
- 测试 58 → 66（`tests/test_intent_plan.py`:schema 往返与下转、伪造域名/集合过滤、monitor 降级、钳制、兜底与叙述语言判定）。

##### P4.0b 路由派生 + 语言语义修正（2026-08-20 同日第二刀）

- **语义修正（作者指出的合同缺口）**：验证例句里带了"中日文都要",等于没验"用户不说"的情形——而语言三原则①恰恰是关于不说的情形。提示词强化为"话题地理由你判断,每个目标都判,与请求无关",不提语言重验:「帮我盯大谷翔平的动向」→ ja(JP)+zh(CN,TW,HK)+en 自动全出;英文输入 track BYD → 比亚迪/仰望/腾势/方程豹 zh 别名 + 比亜迪 ja,叙述语言仍 en。
- **AliasSpec → 显式版本路由**（`gnews_edition_params(lang, region)`）：规划期决定的 (语言,地区) 直接生成 hl/gl/ceid,"Shohei Ohtani" 能进 CA:en 版——字形猜测对拉丁别名永远做不到;猜测降为无 plan 的兜底,**7-29"启发式降级为 fallback"的裁决就此彻底落地**。端到端:一句话 → 6 条路由横跨 JP:ja/US/CA:en/CN:zh-Hans/TW:zh-Hant/HK:zh-Hant,零运行时猜测。
- **per-target 一手判定**（`tier_for_url` 加 `extra_first_party`,scraper 从 `intent_plan.official_domains` 传入）：Cloudflare 教训的正解——组合博客的 PRIMARY 只对拥有它的目标成立,现在就是这么实现的;营销路径守卫对授予域名同样生效,全局地板不动,AGGREGATED 永不升级。
- **CONFIRMED 改读入库盖章**（semantic_ingest）:又消灭一处消费期 URL 重推导(source_tiering §2),per-target 一手因此自然参与生命周期。
- 测试 66 → 70。

##### 架构漂移审查（2026-07-29，作者要求）

作者原话：*"明明是架构层偏移了但是通过局部补丁去修复，最后架构层还是偏移的但是局部修复了感觉不到，容易在积累很多后爆发。"* 查到 3 处漂移（2 处系本人近期造成）、5 处干净：

- **Drift 1（本人）：规划期决策塞进运行时**。`gnews_locale_params()` 用正则看关键词字形猜 Google News 版本，但愿景语言三原则①明确"**话题的信源地理分布是话题属性**"——那是**懂话题的规划器**该决定的（Apple Siri = EN 一手 + ja 供应链 + zh 爆料），正则只知道"这个词是汉字"。且愿景里 gnews 的 `hl/gl` 只是**分路机制的例子**，Portfolio 本该驱动全部路由（reddit 版块、账号、地区媒体、登记库）。成因是连日"观察症状→测量→打补丁"丢了中枢。**校正**：2026-07-29 那批语言修复降级为**兜底**（无规划器输出时的确定性 fallback），**P4.0 重新定位为架构中枢而非"以后要加的功能"**。作者裁决：接入 P4 之前，手填多语言关键词 + 手建实体（xai / spacexai / elon musk）是可接受的过渡。
- **Drift 2（本人）：provenance 在消费期重新推导**，违反 `docs/source_tiering.md` §2「入口捕获、消费期只施加权重」——`source_tier` 遵守了，人物雷达豁免没有。融合门用 `is_tracked_account(item.url)` 对着主机白名单猜，而 **URL 主机回答的是另一个问题**，两个方向都错：话题源里一条**指向** x.com 的链接会命中并白嫖豁免（跳过收紧 CURATED 时专门引入的相关性与佐证检查）；同一账号经 rsshub 或任何不在名单上的镜像读取，则**丢掉**它本该有的豁免——而那正是设计最看重的外语快讯通道。**只有 resolver 知道一条路由为何存在**，故由它盖章（迁移 0011，`_resolve_account_routes` 在函数出口统一盖，新平台分支无法悄悄漏掉）。`is_tracked_account` 与主机名单一并删除而非留着不用——**留一个看起来权威的死启发式，正是下次再漂移的入口**。旧数据默认 0，走常规门控路径，是安全的出错方向。
- **Drift 3（历史遗留，非本轮引入）**：`PortfolioPlan` 仅 6 个字段，撑不起愿景 3.1 的架构——Drift 1 其实是它的**症状**。归入 P4.0 一并解决。
- **干净的部分**（记录以免重复审查）：`IntelReport` 已零写入（P2.1 收口彻底）；`SubscriptionUpdate` 仅在简报中被读，两条泳道没有交叉；`process_article` 只在门控之后被调用；tier 全程只当布尔用，未偷偷引入数值权重；筛选逻辑集中在 `source_normalizer`，无散落的私有副本。

#### Security
- macOS/Linux 密钥存储 base64 明文回退 → 真 Fernet 加密（`services/crypto_service.py`，0600 密钥文件，兼容旧文件迁移）。
- 授权失败诊断只输出 cookie **名称与域名**，绝不输出值（`backend/api/auth.py`）——cookie 的值就是凭据本身。
- 前端 feed 链接 `javascript:` XSS → `safeHref` 只放行 http(s)。
- R7 发布合规门：摘要非全文、PII 清洗、授权（登录态）来源内容硬排除、溯源三件套、AI 诚实标注。

#### Removed
- 三代旧 UI 墓地（Streamlit `ui/`、Flet `flet_main.py`/`ui/flet_views/`、`worker.py` shim、`*.bat`）+ streamlit/flet 依赖。

##### 跨目标可见性 · P4.0c 建议源 · 线索全局化（2026-08-26 ~ 09-01 —— 作者三连报"信息滞后 / 官博没进线索 / Claude 内容进了 gemini"的根治）

- **诊断先行（08-26）**：三真一误——nitter.net 被 X Corp 8-24 C&D 永久 410（人物雷达自 8/20 全黑,滞后体感主因）;Claude 官博实际在流（22/22 已提炼,经 Olshansk 第三方 feed 滞后≤1 天）;串目标=共享集合 + URL 先抓归先（缓存副作用,非设计规则）;融合零积压。社区/GitHub 调研:无账号读 X 时间线的路线已不存在（Squawker/Scweet/RSS-Bridge 全是账号池或付费 API;syndication 200+0B;FxTwitter 无时间线端点）,唯一结构性无账号路径=Grok relay（雪花 ID 解时间戳,待 xAI key）。
- **跨目标可见性（08-26,作者裁决"同一篇,两边都显示"）**：`services/attribution.py` 入库对全部活跃目标画像做确定性匹配（官方域名命中 / 标题实体词界匹配 / 正文≥2 实体;keep_keywords 刻意不用）→ `RawArticle.also_tracker_ids`;雷达筛选按集合过滤——同一线索同一摘要,相关目标都可见。迁移 0016 回填近 30 天;维护任务新增存量目标 `official_domains` 回填 + 重盖章（`backfill_official_domains` / `restamp_recent`）。旗舰病例《The AI-Native SDLC playbook》（owner=grok）在 claude 筛选下可见。提炼面加载窗 100→400（实测 ~100 条/天）。
- **P4.0c 建议源 + 存在性校验（09-01）**：规划器提示词第 6 条改为要求 `suggested_sources`（rss/account/subreddit/page_monitor/registry ≤8,带理由）;`_guard_suggestions` 整形去重;`services/source_verifier.py` 并行 6s 校验（RSS 可解析、页面 200、X handle 经 FxTwitter 档案端点验活、subreddit new.rss;只认正面证据）→ 通过默认勾选、未通过可见不勾;Discovery 提案卡逐条勾选;`SourceResolver._append_suggested_routes` 消费 `selected`（优先级 4）;page_monitor/registry 建目标时 `materialize_page_monitors` 物化为 Subscription;`POST /trackers/{id}/replan` + 订阅管理菜单「重新规划（补充源）」（决策点①手动,只补缺）。实测 claude 4/4 通过、渐冻症编造 RSS 被拦。
- **线索全局化（09-01）**：语义层候选池改全局近 30 天（`_load_thread_pool`,每轮一次内存维护）;`StoryThread.tracker_ids` 透镜随成员扩张;垃圾地板按透镜内最匹配目标画像算;`/threads?tracker_id=` 按透镜过滤;雷达行标签显示透镜全部目标;归属匹配加 `ignore_keywords` 否决。迁移 0017 回填 13,500 条线索透镜（2,368 条含 ≥2 目标）,不做追溯合并。
- **Fable 5.1 缺失案（09-01）**：当天发布;官方公告 URL `anthropic.com/claude-fable-and-mythos-5-1` 不在 `/news/` 下,第三方 feed 按路径过滤未收录;gnews 一天滞后;X 通道黑——线索为零。page_monitor 类建议（newsroom listing / what's-new 页）是此类漏网的唯一解,已由 c 刀提供。
- **P4.1 收口（09-01）**：规划提示词改为"新手不知道该找的一手源"框架;`_REGISTRY_LEXICON` 话题→结构化源映射（ClinicalTrials / NVD / FilmFreeway / arXiv / EDGAR）在 LLM 与无 key 两条路径都注入,仍过护栏与校验。
- **P4.2 涌现源发现（09-01）**：`services/emergent_sources.py`（扫获注意力线索→按透镜计去重线索数→`EmergentSource` pending;"已追踪"按 curated/primary 到达域名与 from_account handle 判定;X 镜像/arxiv 归噪音、代码托管不抽 @、出版方门槛 6）;`/api/emergent/`（list/scan/accept/dismiss）;雷达页顶部一行提示 追踪/忽略;追踪过存在性校验后追加为 selected 建议源;维护任务每日扫描。实库干跑 7 候选（@ClaudeDevs/@OpenAI/@SpaceXAI…）。
- 测试 70 → 85。

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
