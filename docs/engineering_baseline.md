# MajorRSS 工程基准（Engineering Baseline）

> 最后更新：2026-09-28 · **项目于此日收口**：第一类遗留全部清零，其余在 §3 逐项写明「不做 / 下一期」及理由。
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
- **托盘常驻 = 静默的资源预算**（2026-09-27 明文化）：本机只做"新增量 × 向量比对"这类毫秒级工作，重活在云端模型。因此：①每轮成本只随**新增**内容增长，绝不随库大小增长（全表读/全量解析/纯 Python 向量循环都是违例）；②没有新内容的一轮什么都不做；③调度任务跑在 macOS 低 QoS（`utility`，日维护 `background`），用户触发的任务保持默认；④任务线程 CPU 超过间隔 20% 即告警（`Job X used Ns CPU`）；⑤**绝不替用户阻止睡眠**（不持有电源断言、不 caffeinate——作者 2026-09-28 裁决：那是用户的设备与权益）。睡眠期间的空窗由「醒来不漏」补（醒后立即补跑一轮 + 回来时列出离开期间的要点 + 菜单栏计数），全天候靠 P8 常驻机。9/22–9/27 违反①导致 sidecar 常驻 100% CPU / 6 GB（见 debugging_playbook §7.5）。

## 2. 当前架构（as-is，2026-09-28）

```text
桌面端  desktop/          Tauri 2 (Rust) + React 19 + Mantine → 127.0.0.1:8765
                          macOS 原生窗饰/交通灯（tauri.macos.conf.json）；Win/Linux 自绘
后端    backend/main.py   FastAPI + uvicorn；lifespan 启动调度器守护线程；启动预载 .env/config
调度    scheduler.py      APScheduler 7 任务（poller/抓取/语义[含合并遍+实体尖峰]/融合/订阅diff/维护/心跳）
                          每个任务经 _job() 包装:设 macOS 线程 QoS + CPU 预算告警（20% 间隔）
                          语义任务整轮持 THREAD_WRITE_LOCK,融合逐线索取锁（pipeline_lock.py:一次只有一个写线索者）
用户运行 task_runner      "运行并追踪/试运行/立即检查监控"=后台任务(2 线程池,复用浏览器),端点回 {task_id},
                          GET /tasks/{id} 轮询;POST /trackers/{id}/run 回排队任务 id;TaskRequest 有 SKIPPED
预算    llm_budget        LLM_DAILY_TOKEN_BUDGET 管全部后台花费(融合/嵌入/仲裁/合并/告警/维护模型步),系统设置可改;
                          每目标 fetch_policy.daily_token_budget 管该目标的摘要花费;用户主动操作不受限
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
        向量运算:semantic.CentroidIndex（去均值+归一化 float32 矩阵,近邻=一次 mat-vec,全对=一次 mat-mat）;
        语料均值=增量累加和,线索质心按内容哈希缓存,均值状态持久化在 <数据目录>/cache/（可删,自动重建）;
        合并遍输入未变且上轮已判完则整轮跳过。稳态一轮 ~1 s（改前 ~5 分钟）
融合    processor_service 按线索走一遍（P1.1 门控挣得制;无目标关心不花钱）；摘要中立,涉及目标为独立结构化输出；重摘要须实质增量
        （is_material_increment：出版方相对增长≥25% 或晋级——同一规则管排序诚实与重烧成本）
呈现    雷达页 = 唯一阅读面（P6）：AI 模式 提炼|线报 双 tab（卡片即摘要；线报按盖章分层，
        线报三层:账号线报>故事线传闻(标签可见)>聚合器单条折叠）；目标筛选按 ThreadTarget 关系;行标签=线索涉及的全部目标;被模型判为同名撞车的在该目标下折叠。纯 RSS 模式 = 原始订阅流本身
监控    page_monitor/registry 类建议源 → Subscription 页面 diff（官方 newsroom listing 类漏网的唯一解）
数据    SQLite（打包 ~/.majorss/，dev 在仓库根）；迁移 migrations/runner.py 0001–0024 幂等
观测    PipelineRun/Event trace · 滚动日志 · /health 心跳 · Billing 按动作/目标/日历热力图
        db-status.pipeline_health（未成线索/未嵌入计数,应为 0,非 0 时系统设置页提示）
发布    publish_service → 合规门 → PublishedDigest → onlyforbots.com（CF Pages 自动部署）
测试    tests/ 129 项 pytest（语义/守卫/健康/politeness/provenance/呈现层/意图规划/建议源/全局线索/涌现源/故事线/发布合规）
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

> 2026-09-28 收口：原 §3.3「功能与工程」与 P2.2 / P1.2+ / §G 遗留已全部清零（提交 6cde29d · 8c8ffee · a866539，逐项先对照代码核实再改）。下面只剩**有意不做**或**下一期**的事，每条写明理由，免得被当成欠账。

### 3.1 收口时挂起的裁决（不做，除非作者重启）
- **浏览器分发**：测试期不带（现依赖机器上的 `playwright install`），正式发布要带。三档已量化：全带 525M / 只带 headless_shell 189M（抓取即用，授权时按需下载完整版）/ 全按需。见路线图。
- **P5 编辑价值门**：负样本原型方案已验证否决（AUC 增益 +0.005）;替代路线=用 validity 标签在探针机器上训"编辑价值"探针（与 relation_model 同构）。作者暂放。
- **向量改二进制存储**（`articleembedding.vector` / `storythread.centroid` 为 JSON 文本,占 3.8 GB 库大半）:稳态已不解析（增量+缓存+持久化）,剩启动首轮 30 天线索池 ~6 s 与每日探针训练 ~11 s。改 float32 BLOB 可降到 1 s 内、库 → ~1.3 GB,但需迁移且旧版本读不了新库。
- **授权态端到端 / X 通道**：链路已验证到登录弹窗（2026-08-05），cookie 段等作者小号;AUTH_PLATFORMS 11 平台指示器仍是未经真账号验证的假设。无账号 X 路径=Grok relay（等 xAI key）;twitter-cli（B7）同样等小号+代理实跑。
- **改名 MajoSleuth + 域名**：等名字最终锁定后统一改一轮（仓库名、`~/.majorss`、`MAJORSS_DATA_DIR`、包名）;公开发布前买 majosleuth.com。
- **签名与分发**：Tauri updater 签名密钥（`tauri signer generate`）、Apple 开发者账号（零警告分发）、Windows Authenticode——其余打包已就绪（macOS 只打 .app）。
- **官方源无人值守发布**：`official_feed_automation.md` 形态 B（GitHub Actions）/ C（VPS）二选一。
- **系统钥匙串**：当前 Fernet + 0600 文件（真加密）;换 Keychain 需引入 keyring 依赖。

### 3.2 结构性（记录不排期）
- **学出来的关系只在 AI 四目标启用**（标签 ≥20/侧才训;渐冻症/大谷等仍靠匹配器地板,攒够标签自动启用）;探针否决=折叠可核对,纠错入口归 P3.1。
- **线索分裂**：入库仍宁拆勿错并;事后合并遍在下一轮语义任务里并回——分裂只在两轮之间短暂存在。
- **仲裁语义**：same-event 严格（拆分率高部分是诚实的）;可能同故事线被判 different（漏认亲,只影响可见性）。
- **容量余量薄**：稳态进入≈消化≈16 条/分钟;再加探测目标 pending 将单调增长。是容量上限不是泄漏。
- **慢滴积累跨过 25% 增量阈值**时最后一滴获"进展"标记——按裁决语义诚实。
- **有意保留的小边界**：每目标上限只计摘要（嵌入/仲裁是共享的入库成本,归全局预算）;`tracker_type`/`tier`/`cookie_string` 列保留不删（路由从不读;SQLite 删列需重建表）;`/trackers/test-route` 与 `/{id}/test-route` 两个无前端调用的接口仍同步执行;嵌入连续失败 3 次的文章本次进程内搁置、重启后再试;保留期/体积清理会让被删线索的旧成员失去线索（已嵌入不会重聚,按保留期语义正确）。

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
✅ 后台功耗治理（09-27）· 收口：§G 遗留 / P2.2 接地性 / P1.2+ 预算 / 工程 §3.3 全部清零（09-28）
■ 已收口（2026-09-28）。下一期候选（有设计、无实现,均不在当前承诺内）：
   **P8 云端分体排第一**（cloud_split_design.md;C0+C1+C3 ≈1.5 天即可公开源全天候 + 手机推送）——2026-09-28 Sonnet 5.5
   发布时 Mac 睡眠 15:04–19:10,本机方案的上限就是"醒着";待作者定:常驻机(NAS/VPS/树莓派)、Tailscale、ntfy
   · P7a 订阅频道（纯透传,工作量极低）· P9 监控 diff 判读（monitor_diff_design.md）
   · P7b 先查共享索引 · R7 Phase 2/3 共享层（Supabase 登录/多发布者）· 情报溯源重设计（investigator_redesign.md）
   · 页面 diff 并入统一 SourceItem · P3.1 反馈闭环（铁律:最后做）
⚠ 快讯通道离线:nitter.net 已 410;无账号唯一结构路径=Grok relay(等作者 xAI key),一手路径=授权 agentic(等小号)
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
# 产物 desktop/src-tauri/target/release/bundle/macos/MajorRSS.app（macOS 只打 .app；要 dmg 用 npx tauri build --bundles app,dmg）

# 测试（129 项）。数据库相关测试必须显式 DATABASE_URL 指向副本，严禁碰 ~/.majorss/major_rss.db
pytest -q
DATABASE_URL="sqlite:////tmp/copy.db" python -c "from migrations.runner import run_migrations; run_migrations()"

# 健康与日志
curl http://127.0.0.1:8765/api/settings/health
# 日志：dev 在仓库根 logs/majorss.log；打包在 ~/.majorss/logs/majorss.log（5MB×3 滚动）
# 时区注意：日志是本地时间(EDT)，数据库 created_at 是 UTC（差 4 小时）

# 授权浏览器（dev 机需要一次）：playwright install chromium

# 排查：症状 → 表/日志/脚本 见 docs/debugging_playbook.md
```
