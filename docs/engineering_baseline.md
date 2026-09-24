# MajorRSS 工程基准（Engineering Baseline）

> 最后更新：2026-09-24
>
> **本文档是现行唯一的工程状态基准。**
>
> `docs/` 下的其他文档定位为**设计意图档案**（长期有效，不更新实现审计部分）。**执行队列与裁决记录**在 [radar_quality_roadmap.md](radar_quality_roadmap.md)，**逐批实现史**在根目录 CHANGELOG.md。判断"某个问题现在还存在吗"，以本文档为准；判断"下一步做什么"，以路线图为准；**排查具体症状**，看 [debugging_playbook.md](debugging_playbook.md)。
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

## 2. 当前架构（as-is，2026-09-24）

```text
桌面端  desktop/          Tauri 2 (Rust) + React 19 + Mantine → 127.0.0.1:8765
                          macOS 原生窗饰/交通灯（tauri.macos.conf.json）；Win/Linux 自绘
后端    backend/main.py   FastAPI + uvicorn；lifespan 启动调度器守护线程；启动预载 .env/config
调度    scheduler.py      APScheduler 7 任务（poller/抓取/语义[含合并遍+实体尖峰]/融合/订阅diff/维护/心跳）
规划    portfolio_planner.plan_intent  一句话 → IntentPlan（分道/多语言别名/官方域名/集合/建议源）
        建议源 = 模型发现（P4.1 新手问题）+ 话题→登记库映射（_REGISTRY_LEXICON,两条路径都走）
        经 source_verifier 存在性校验（FxTwitter 验 handle、RSS/页面/subreddit 探活）后才可选
发现    emergent_sources（P4.2）每日扫获注意力线索→反复被指向的 @handle/出版方→雷达页提示追踪
        追踪=同一套校验后追加为 selected 建议源;只加不减
抓取    scraper_service → SourceResolver(路由分组+账号盖章+建议源路由) → adapters → SourceNormalizer
        入库盖章:source_tier / from_account（文章只带出处;tracker_id 仅为"经谁发现"）
        护栏：source_health(端点退避/隔离/新鲜度断言) + host_politeness(主机限速/冷却/轮转)
        + account_guard(每账号预算/AIMD/熔断) + humanized(静默窗/抖动) + browser_pool(线程本地复用)
        错误归责：NOT_ENDPOINT_FAULT（429→主机层、能力缺失→自身诊断）不进端点健康
语义    semantic_ingest   embed(去均值) → 垃圾地板(按该文章涉及的目标中最匹配的画像) → 全局近 30 天候选池
        top-K + LLM 三分仲裁(event/story/different) → StoryThread（全局无主）→ ThreadTarget 关系（目标即查询）
        story → 认亲 Storyline（只链接不合并;出版方按整条去重——聚合不制造佐证;只给可见性）
        生命周期 LEAD→CORROBORATED→CONFIRMED + 共振；账号线报走人物雷达豁免
融合    processor_service 按线索走一遍（P1.1 门控挣得制;无目标关心不花钱）；摘要中立,涉及目标为独立结构化输出；重摘要须实质增量
        （is_material_increment：出版方相对增长≥25% 或晋级——同一规则管排序诚实与重烧成本）
呈现    雷达页 = 唯一阅读面（P6）：AI 模式 提炼|线报 双 tab（卡片即摘要；线报按盖章分层，
        线报三层:账号线报>故事线传闻(标签可见)>聚合器单条折叠）；目标筛选按 ThreadTarget 关系;行标签=线索涉及的全部目标;被模型判为同名撞车的在该目标下折叠。纯 RSS 模式 = 原始订阅流本身
监控    page_monitor/registry 类建议源 → Subscription 页面 diff（官方 newsroom listing 类漏网的唯一解）
数据    SQLite（打包 ~/.majorss/，dev 在仓库根）；迁移 migrations/runner.py 0001–0024 幂等
观测    PipelineRun/Event trace · 滚动日志 · /health 心跳 · Billing 按动作/目标/日历热力图
发布    publish_service → 合规门 → PublishedDigest → onlyforbots.com（CF Pages 自动部署）
测试    tests/ 110 项 pytest（语义/守卫/健康/politeness/provenance/呈现层/意图规划/建议源/全局线索/涌现源/故事线/发布合规）
```

关键机制的单一事实源（改动前先读对应文件头注释）：

| 关切 | 文件 | 要点 |
|---|---|---|
| 来源层级/一手判定 | `services/provenance.py` | 地板=前沿实验室自有频道档；组合型厂商博客**刻意不进**；per-target 由 intent_plan.official_domains 授予；**只在入口调用**——盖章无 NULL(迁移 0020),消费期零推导 |
| 账号来源 | `SourceRoute.is_account → RawArticle.from_account` | 入口盖章，消费期禁止 URL 猜（Drift 2 教训） |
| 端点健康 | `services/source_health.py` | 按端点退避；HTTP 200 ≠ 活着（按条目日期判活） |
| 主机礼貌 | `services/host_politeness.py` | 429 冻主机、5xx 连三冻主机、轮转防饿死 |
| 浏览器 | `services/browser_pool.py` | `ensure_browsers_path()` 对抗 Playwright frozen 假设；缺浏览器给安装指引 |
| 生命周期 | `services/lifecycle.py` | 唯一规则:任一 primary 盖章→CONFIRMED,≥2 出版方→CORROBORATED;运行中只升不降 |
| 目标定义 | `services/target_profile.py` | 一个对象三个视图:terms()(相关性门) / describe()(摘要模型) / matcher()(跨目标可见性) |
| 别名路由 | `source_resolver._resolve_keyword_routes` | 具体别名各自成 gnews 路由（`gnews_alias_N`,版本词优先,上限 8）+ 后继版本自动探测（`_successor_probes`）;其他语言版本 OR 合并 |
| 合并策略 | `services/merge_policy.py` | 唯一声明:入库（地板/置信线/top-K/每轮上限）+ 事后（相似/窗口/对数）+ 校准依据 |
| 事后合并 | `services/thread_merge.py` | 阈值取自 merge_policy;event 并入较早线索,story 认亲;判定记忆 `ThreadPairVerdict` |
| 事件仲裁 | `services/semantic_ingest.py` | top-K(3) 候选逐个问三分法；`rescued` 计数 = 旧 top-1 流程必错的合并；**预算耗尽/出错=不并**（错并不可逆,拆分可逆）；一字答案用低思考等级（`thinking_level="low"`,成本 -50%,正确率不降） |
| 实质增量 | `services/processor_service.py` | `is_material_increment`；summarized_at 因此意为"最后实质变化" |
| RSS 时间 | `scrapers/tier1_rss.py` | `calendar.timegm`（mktime 会按本地标准时解释 UTC struct） |
| 学出来的关系 | `services/relation_model.py` + `TargetModel` | 每目标线性探针,每日从自身标签重训,AUC≥0.90 启用;只高置信补漏/否决;匹配器为冷启动地板 |
| 目标匹配器 | `services/attribution.py` | 对全部目标对称判定:官方域名/标题实体/正文≥2实体且导语内出现;ignore 否决;被比较≠参与 |
| 目标即查询 | `services/thread_targets.py` + `ThreadTarget` | 线索/文章全局无主;关系=对称匹配+聚合发现路由+模型判定（False 只折叠）;融合按线索一遍、摘要中立;无目标关心不花钱。设计记录 docs/targets_are_queries.md |
| 建议源校验 | `services/source_verifier.py` | 只认正面证据;FxTwitter 档案端点验 X handle（无账号、不受 C&D） |
| 故事线 | `StoryThread.storyline_id` → `Storyline` | 认亲不合并;出版方整条去重;线报面第二层;提炼卡"传闻自 X 起" |
| 接地词汇刷新 | `services/vocab_refresh.py` | 模型读目标线报标题提案,数据裁决（逐字/≥2 支持/非他目标别名/争议归支持最高）;模型逐词判 core（自动成别名）/ context（只建议）;每目标每日一次 |
| 涌现源/关键词 | `services/emergent_sources.py` | "已追踪"按数据判定;代码托管不抽 @;出版方门槛 6;**版本短语**（别名锚定,标题,≥3 线索,版本≥已知）→ **自动**成别名,不问用户（规划器给不出"下一代"） |

## 3. 差距地图（当前仍存在的）

### 3.1 需作者裁决（挂起中）
- **浏览器分发**：测试期不带（现依赖机器上的 `playwright install`），正式发布要带。三档已量化：全带 525M / 只带 headless_shell 189M（抓取即用，授权时按需下载完整版）/ 全按需。见路线图。
- **P5 编辑价值门**：负样本原型方案已验证否决（AUC 增益 +0.005）;现有替代路线=用 validity 标签在探针机器上训"编辑价值"探针（与 relation_model 同构）。作者暂放。
- **授权态端到端**：链路已验证到登录弹窗（2026-08-05），cookie 抓取一段等作者小号。AUTH_PLATFORMS 11 平台的指示器仍是未经真实账号验证的假设。

### 3.2 结构性（记录不排期，见路线图同名节）
- **学出来的关系只在 AI 四目标启用**（标签 ≥20/侧才训;渐冻症/大谷等仍靠匹配器地板,几天后自动启用）;探针否决=折叠可核对,纠错入口归 P3.1。
- **线索分裂**：入库仍宁拆勿错并;事后合并遍（`thread_merge.py`,≥0.70 相似对逐对问仲裁）在下一轮语义任务里把同事件线索并回——2026-09-22 起,分裂只在两轮之间短暂存在。
- **仲裁语义**：same-event 仍严格（拆分率 91% 部分是诚实的）；"同一故事线"已作为第三答案落地为认亲而非合并（2026-09-03），过度合并风险因此不存在；仍可能同故事线被判 different（漏认亲,只影响可见性）。
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
- ~~提炼卡片的「摘要引用来源 vs 重复佐证来源」区分退化~~（2026-09-22 恢复：`cited_article_ids` + 卡片两组）。

## 4. 路线图位置

R1–R7 Phase 1 全部完成（2026-07 上旬）；之后执行队列以 [radar_quality_roadmap.md](radar_quality_roadmap.md) 的 P 序列为准。当前位置：

```
✅ P0.1–P0.5 · P1.1/P1.2 · P2.1 · 架构复盘六项 · B1–B6 · 未结算两项
✅ P4 前置（管线可信性：agentic 0/399→通、reddit 24%→治理、429/能力归责、账号盖章）
✅ 呈现层三修（RSS 时间戳 +5h、一手地板、仲裁 top-K）
✅ P6 雷达收口 + 当日补丁（时间诚实、板块筛选）
✅ P4.0a/b（意图探索 schema+分道+路由派生,2026-08-20）
✅ 跨目标可见性（2026-08-26）· P4.0c 建议源+存在性校验 · 线索全局化 · P4.1 · P4.2（2026-09-01）
✅ 目标即查询（09-17）· 消防栓层级/盖章不变量（09-06~07）· 别名路由+涌现关键词+接地词汇刷新（09-18~22）· 事后合并+合并策略（09-22）· 引用 vs 佐证恢复（09-22）· TrendScan 并入告警 · 学出来的关系（09-24）
▶ 下一步：P8 云端分体 / P9 监控判读（设计合同待审：cloud_split_design.md / monitor_diff_design.md）→ P7a/b → P3.1(最后)；P5 暂放（验证已否决原方案,替代路线记于路线图）
⚠ 快讯通道离线:nitter.net 已 410;无账号唯一结构路径=Grok relay(等作者 xAI key),一手路径=授权 agentic(等小号)
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

# 测试（110 项）。数据库相关测试必须显式 DATABASE_URL 指向副本，严禁碰 ~/.majorss/major_rss.db
pytest -q
DATABASE_URL="sqlite:////tmp/copy.db" python -c "from migrations.runner import run_migrations; run_migrations()"

# 健康与日志
curl http://127.0.0.1:8765/api/settings/health
# 日志：dev 在仓库根 logs/majorss.log；打包在 ~/.majorss/logs/majorss.log（5MB×3 滚动）
# 时区注意：日志是本地时间(EDT)，数据库 created_at 是 UTC（差 4 小时）

# 授权浏览器（dev 机需要一次）：playwright install chromium

# 排查：症状 → 表/日志/脚本 见 docs/debugging_playbook.md
```
