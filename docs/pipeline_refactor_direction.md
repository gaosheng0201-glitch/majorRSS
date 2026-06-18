# MajorRSS Pipeline Refactor Direction

## 背景

当前 MajorRSS 的数据获取主要由两类能力组成：

- RSSHub / RSS 路由：用于社交平台主页、RSS 源、新闻源、关键词源。
- Cookie 授权抓取：用于需要登录态或 JS 渲染的页面快照。

这两个方向本身是合理的，但当前实现中二者还没有统一成清晰的数据源管线，导致路由语义、任务状态、错误恢复、去重和后续 LLM 处理之间存在断点。

本文档作为后续重构方向，不要求一次性推倒重写。

## 设计初衷

MajorRSS 的核心目标不是“尽可能多地抓取内容”，而是帮助用户减少噪音，直达自己真正关注的信息。

用户通常有四类关注方式：

1. 明确 RSS / 频道订阅。
2. 关键词探测。
3. 账号 / 作者 / 博主追踪。
4. 页面变化对比。

RSSHub、cookie 授权、外部 CLI、Playwright、LLM 都只是为这四类目标服务的实现手段。

### 1. 明确 RSS / 频道订阅

用户已经知道自己要关注什么源，例如：

- OpenAI RSS。
- 官方博客 RSS。
- 科技媒体 RSS。
- 金融公告 RSS。
- GitHub releases / changelog feed。

设计目标：

```text
用户提供明确 RSS / channel URL
→ 系统按周期拉取
→ 只处理新增内容
→ 进入 RawArticle
→ LLM 判断是否有情报价值
→ 生成 IntelReport
```

这类源应是最稳定、最低噪音、最低成本的管线。

原则：

- 优先尊重用户输入的原始 RSS。
- 不应强行改写为 RSSHub，除非用户输入的是平台主页且 resolver 能确定对应 RSSHub route。
- 失败时清晰展示 HTTP 状态、parse error、最近成功时间。
- 不需要 cookie，除非该 RSS 或平台源本身需要授权。

### 2. 关键词探测

用户不输入账号或 URL，只输入关注主题，例如：

- AI agent。
- Gemini 新模型。
- OpenAI API。
- 金融监管。
- 半导体供应链。

设计目标：

```text
用户输入关键词
→ 默认探测管线覆盖主流媒体 / 搜索 / 社区 / 技术源
→ 轻量过滤噪音
→ 写入候选 RawArticle
→ LLM 进一步判断有效情报
```

这类管线天然噪音最高，必须和明确 RSS 源区别对待。

原则：

- 默认探测管线要广，但不能无差别写库。
- 每个 source route 应有权重和质量评分。
- Reddit、HN、Google News 等结果必须做轻量相关性过滤。
- 宽泛关键词应限制每轮最大写入数量。
- LLM 不应承担全部噪音过滤成本。
- UI 应明确展示“本轮探测来自哪些源、命中多少、过滤多少”。

### 3. 账号 / 作者 / 博主追踪

用户输入一个账号、作者主页、UP 主主页、频道、博客作者页等，目标是知道这个主体新发布了什么。

示例：

- X / Twitter 博主。
- B站 UP 主。
- YouTube channel。
- 小红书作者。
- 个人博客。
- 论文作者主页。
- GitHub organization / repository。

设计目标：

```text
用户输入账号或主页
→ resolver 识别平台
→ 优先使用轻量 discovery route
→ 发现新内容
→ 必要时 enrichment 获取正文、字幕、评论或详情
→ 进入 RawArticle / IntelReport
```

原则：

- RSSHub 可作为账号追踪的第一层 discovery。
- discovery 只负责发现“有新内容”，不一定负责拿到完整内容。
- B站视频、X 长文、小红书笔记等可通过 CLI / Agentic 做 enrichment。
- cookie 授权只是提高抓取成功率和内容完整度，不应成为 tracker 的产品语义。
- 写操作不进入情报采集管线。

### 4. 页面变化对比

用户关注的是某个网页本身是否发生变化，而不是新文章列表。

示例：

- OpenAI API 文档。
- 某个 pricing 页面。
- 某个产品 changelog 页面。
- 某个政策 / 法规页面。
- 某个招聘 / 发布页。

设计目标：

```text
用户输入网页
→ 周期性抓取页面快照
→ 清洗广告、导航、时间戳、推荐位等噪音
→ 生成结构化 diff
→ 只在有效内容变化时提醒
→ 可选 LLM 总结变化意义
```

原则：

- 页面 Diff 不应和 RSS article 管线混在一起。
- 应保存 clean snapshot，而不是直接 diff 原始 HTML。
- 需要噪音过滤规则，例如移除广告、导航、footer、推荐内容、计数器、动态时间。
- 应区分初始快照、无变化、有效变化、疑似噪音变化。
- 对重要页面可支持 selector / content region 配置。

### Cookie 授权的定位

Cookie 授权不是独立产品目标，而是抓取能力增强手段。

它服务于：

- 访问需要登录的页面。
- 获取更完整的 timeline / feed。
- 避免匿名访问看到登录墙。
- 读取用户本来有权限查看的内容。

它不应改变用户的高层意图。用户关注的仍然是：

- 频道。
- 关键词。
- 账号。
- 页面变化。

因此后续模型中，cookie/session 应从 tracker 配置中解耦为 Auth Profile，由 adapter 根据 route 需要按需使用。

## 当前主要问题

### 1. Tracker 语义和执行路径不一致

当前 `Tracker` 使用：

- `tracker_type`
- `target`
- `tier`
- `cookie_string`

但实际执行时，部分路径会忽略这些字段。例如 HYBRID tracker 的 `urls` 目前固定按 RSS 抓取，即使 tracker 本身设置了 `tier=3`，也不会进入授权/Agentic 抓取路径。

结果是：用户以为配置的是“网页快照”或“授权抓取”，实际代码仍然按 RSS parser 处理，导致 GitHub、普通网页、动态页面被错误解析。

### 2. RSSHub 和 Cookie 授权不是可组合能力

当前逻辑更像两个分叉：

- RSSHub / RSS：匿名、结构化、轻量。
- Cookie / Agentic：Playwright 页面快照、重、慢。

但产品上需要的是组合策略：

```text
目标 URL / 账号 / 关键词
→ 解析候选 source routes
→ 优先 RSSHub / RSS
→ 失败后按策略 fallback 到 CLI / Agentic / Cookie
→ 统一输出 SourceItem
```

也就是说，cookie 不应只绑在某个 tracker 分支上，而应该是 fetcher 能力之一。

### 3. 公共 RSSHub 实例不稳定

当前日志中已经出现：

- `rsshub.app 403`
- `rsshub.app 404`
- `hnrss.org 502`
- `nitter.net SSL EOF`
- `reddit.com SSL EOF`

因此公共实例不能作为生产级稳定依赖。应设计为：

```text
自建 RSSHub 实例优先
公共 RSSHub fallback
平台 CLI fallback
Agentic fallback
```

### 3.1 RSSHub 的产品定位需要降级

RSSHub 应保留，但不应被视为“全平台稳定抓取核心”。

推荐定位：

```text
RSSHub = 第一层轻量发现源
不是最终内容源
不是唯一平台适配方案
不是授权抓取替代品
```

它最适合做：

- 低频发现账号、频道、UP 主、公告页是否有新内容。
- 将部分平台主页转换为 RSS-like 列表。
- 在不需要登录态、不需要深度正文的场景中降低抓取成本。
- 作为进入后续深度抓取或 LLM 处理前的候选发现层。

它不适合作为：

- 强登录态平台的稳定数据源。
- 评论、弹幕、字幕、完整正文等深度内容源。
- 高频抓取源。
- 宽泛关键词搜索后的质量保证层。
- 公共实例 `rsshub.app` 的单点依赖。

更合理的组合方式：

```text
B站 UP 主
→ RSSHub 发现新视频
→ Bilibili CLI 获取字幕、评论、详情
→ RawArticle
→ LLM Fusion
```

```text
X / Twitter 账号
→ RSSHub / Nitter 尝试轻量 timeline
→ 失败或质量不足时 fallback 到 Twitter CLI
→ 必要时再进入 Agentic / Cookie
```

```text
普通网页
→ 先判断是否原生 RSS
→ 可映射则尝试 RSSHub
→ 否则不要硬塞 RSS parser，直接进入 WebpageSnapshot / Agentic
```

### 4. 任务状态缺少恢复机制

当前 `TaskRequest` 只处理 `PENDING`。如果 worker 中途退出，任务会永久停留在 `RUNNING`。

需要补充：

- `RUNNING` 超时回收。
- `started_at` 超过阈值后自动标记 `FAILED` 或 `PENDING` 重试。
- `retry_count` / `max_retries`。
- `last_heartbeat_at`，用于区分长任务和僵尸任务。

### 5. Windows 日志编码可能中断抓取

项目包含大量中文、emoji、平台文本。Windows/PowerShell 下 stdout 可能是 GBK。抓取过程中如果直接 `print(title)`，遇到 emoji 可能抛编码异常，进而被错误归类为抓取失败。

后续日志层需要：

- 避免在核心抓取路径直接打印原文标题。
- 使用安全日志函数。
- 日志写数据库时保留原始文本，但终端输出应做编码容错。

### 6. 关键词 OSINT 噪音过大

当前 `use_default_osint` 会把关键词同时投递到 Google News、HN、Reddit 等源。对于宽泛关键词，Reddit 结果噪音很高，容易把无关内容写入 `RawArticle`，再交给 LLM 消耗 token。

需要在 LLM 前增加轻量过滤：

- 标题关键词匹配。
- 域名/source trust score。
- 语言过滤。
- 近似重复过滤。
- 最低相关性分数。

## 目标架构

重构目标不是替换 RSSHub，也不是废弃 cookie，而是把所有数据来源统一成 source adapter。

推荐分层：

```text
Tracker
→ Source Intent
→ Source Resolver
→ Fetcher / Adapter
→ SourceItem
→ Normalizer
→ RawArticle
→ Processor / LLM Fusion
→ IntelReport
```

其中 Source Intent 对应用户的高层目标：

- Tracker 管线：
  ```text
  RSS_FEED
  KEYWORD_DISCOVERY
  ACCOUNT_TRACKING
  HYBRID
  ```
- Subscription / Monitor 管线：
  ```text
  PAGE_DIFF
  ```

后续所有 route、adapter、auth、fallback 都应服务于 Source Intent，而不是反过来让技术实现决定产品行为。

### Source Resolver

负责把用户配置解析为候选数据源。

输入：

- source intent
- URL
- keyword
- account
- platform
- auth preference
- max age
- fetch mode

输出：

```text
SourceRoute[]
```

示例：

```text
twitter account @foo
→ rsshub:/twitter/user/foo
→ cli:twitter user-posts foo
→ agentic:https://x.com/foo
```

Source Resolver 还应返回每条 route 的意图和预期质量，而不是只返回 URL。

示例：

```text
route: rsshub:/bilibili/user/video/{uid}
purpose: discovery
expected_depth: shallow
requires_auth: false
fallback_priority: 1
```

```text
route: cli:bilibili video-detail
purpose: enrichment
expected_depth: deep
requires_auth: optional
fallback_priority: 2
```

### Fetcher / Adapter

每个 adapter 只负责一类获取方式。

建议内置：

- `RssAdapter`
- `RssHubAdapter`
- `AgenticAdapter`
- `ExternalCliAdapter`
- `WebpageSnapshotAdapter`

后续可扩展：

- `BilibiliCliAdapter`
- `TwitterCliAdapter`
- `XhsCliAdapter`
- `TelegramCliAdapter`

### SourceItem

所有 adapter 输出统一结构，不直接写 `RawArticle`。

建议字段：

```text
source_id
platform
route
title
url
author
content
summary
published_at
metrics
raw_payload
fingerprint
```

### Normalizer

负责：

- 去重。
- 质量过滤。
- URL canonicalization。
- content hash。
- 生成 `RawArticle`。
- 记录 source route 和 fetch metadata。

### Processor

LLM 层只处理已经标准化、过滤后的 `RawArticle`。

LLM 不应该承担过多基础清洗职责。

## Tracker 模型建议

现有模型可先兼容，不必立即大改。但后续建议把 `tracker_type/tier/cookie_string` 语义拆清楚。

建议逐步演进为：

```text
Tracker
- name
- source_intent: RSS_FEED | KEYWORD_DISCOVERY | ACCOUNT_TRACKING | HYBRID
- source_kind: URL | KEYWORD | ACCOUNT | HYBRID
- target
- platform
- fetch_policy
- auth_profile_id
- radar_section
- interval
- prompt_override
```

其中 `fetch_policy` 可表达：

```json
{
  "preferred_routes": ["rsshub", "rss", "cli", "agentic"],
  "fallback_enabled": true,
  "max_days": 7,
  "max_items": 30,
  "min_relevance": 0.35
}
```

## 混合模式与 tier 的关系

原始产品设计中，混合模式允许用户同时输入：

- 社媒账号 / 作者主页。
- 关键词。
- URL / RSS / 普通网页。

非混合模式则只处理一种目标：

- URL 模式：只支持若干 URL。
- KEYWORD 模式：只支持若干关键词。
- ACCOUNT 模式：只支持若干账号或主页。

这个设计是合理的。当前问题在于 `tier` 和 `tracker_type` 表达的是两个不同维度，却在 UI 和后端中被并列使用。

```text
tracker_type / source_intent = 用户关注什么
tier = 技术上怎么抓
```

因此 `HYBRID + tier` 作为全局配置是不合理的。混合模式中，URL、关键词、账号本来就应该走不同抓取策略。

### tier 的定位

`tier` 应降级为 legacy technical field，不应继续作为用户可见的主配置。

旧含义可保留为兼容映射：

```text
tier=1 → rss_first / rsshub_first
tier=2 → reserved / markdown_snapshot / content_extract
tier=3 → agentic_browser_snapshot
```

新的 resolver 不应直接依赖全局 tier，而应读取：

```text
source_intent
target group
fetch_policy
platform
auth_profile
route health
```

### 推荐用户模型

用户层应看到的是：

```text
关注对象：RSS / URL / Keyword / Account / Hybrid
抓取策略：自动选择 / RSS 优先 / RSSHub 优先 / CLI 优先 / 网页快照 / 授权抓取
```

而不是：

```text
Tier 1 / Tier 2 / Tier 3
```

### 非混合模式策略

#### URL 模式

```text
输入：
- 多个 URL

默认策略：
- auto
```

Resolver 行为：

```text
RSS URL
→ RssAdapter

平台主页
→ RssHubAdapter discovery
→ optional enrichment

普通网页
→ WebpageSnapshotAdapter / AgenticAdapter
```

用户可选高级策略：

```text
auto
rss_first
rsshub_first
agentic
no_fallback
```

#### KEYWORD 模式

```text
输入：
- 多个关键词

默认策略：
- default_discovery
```

Resolver 行为：

```text
关键词
→ Google News / mainstream news
→ 技术社区 / HN
→ 可选社媒 / forum route
→ lightweight relevance filter
→ SourceItem
```

用户可选高级策略：

```text
default_discovery
news_only
tech_sources
social_forum
cli_search
```

#### ACCOUNT 模式

```text
输入：
- 多个账号 / 作者主页 / 平台主页

默认策略：
- auto
```

Resolver 行为：

```text
账号 / 主页
→ platform detection
→ RSSHub / native feed discovery
→ platform CLI enrichment
→ Agentic / Cookie fallback
```

用户可选高级策略：

```text
auto
rsshub_discovery
cli_first
agentic_authenticated
no_fallback
```

### 混合模式策略

混合模式不应使用一个全局 tier，而应至少按目标类型拆成 per-category strategy。

推荐结构：

```json
{
  "source_intent": "HYBRID",
  "target": {
    "urls": ["https://openai.com/news/rss.xml"],
    "keywords": ["AI agent", "OpenAI API"],
    "accounts": ["@sama", "space.bilibili.com/123"]
  },
  "fetch_policy": {
    "url_strategy": "auto",
    "keyword_strategy": "default_discovery",
    "account_strategy": "auto",
    "fallback_enabled": true,
    "max_days": 7,
    "max_items_per_route": 20
  }
}
```

Resolver 行为：

```text
HYBRID.urls
→ URL resolver

HYBRID.keywords
→ Keyword resolver

HYBRID.accounts
→ Account resolver
```

这样可以避免：

```text
HYBRID + tier=1
```

导致普通网页被错误交给 RSS parser，也避免：

```text
HYBRID + tier=3
```

导致所有目标都被重型 Agentic 抓取。

### API 兼容建议

短期可以保持旧字段：

```text
tracker_type
target
tier
cookie_string
```

同时新增：

```text
source_intent
fetch_policy
auth_profile_id
```

兼容层负责把旧 tracker 映射成新策略：

```text
tracker_type=URL, tier=1
→ source_intent=RSS_FEED
→ fetch_policy.url_strategy=rss_first

tracker_type=URL, tier=3
→ source_intent=RSS_FEED
→ fetch_policy.url_strategy=agentic

tracker_type=KEYWORD
→ source_intent=KEYWORD_DISCOVERY
→ fetch_policy.keyword_strategy=default_discovery

tracker_type=ACCOUNT
→ source_intent=ACCOUNT_TRACKING
→ fetch_policy.account_strategy=auto

tracker_type=HYBRID
→ source_intent=HYBRID
→ fetch_policy per category
```

### 前端表单建议

Trackers 页面应避免直接暴露 `tier`。

建议改成：

```text
模式：
- RSS / URL
- 关键词探测
- 账号追踪
- 混合模式
- 页面变化对比
```

高级设置中提供：

```text
抓取策略：
- 自动选择（推荐）
- RSS / RSSHub 优先
- CLI 优先
- 授权网页抓取
- 禁用 fallback
```

混合模式中分别提供：

```text
URL 策略
关键词策略
账号策略
```

默认情况下，用户只需要理解“关注什么”，不需要理解 `tier`。

## 认证设计方向

不要把 cookie 直接长期塞在 tracker 上。更好的方式是独立 Auth Profile。

```text
AuthProfile
- id
- platform
- display_name
- storage_path
- status
- last_checked_at
- expires_hint
```

Tracker 只引用：

```text
auth_profile_id
```

这样好处是：

- 一个平台账号可复用多个 tracker。
- UI 可以集中展示授权健康状态。
- Cookie/session 生命周期和 tracker 解耦。
- 后续可支持浏览器 cookie、QR login、外部 CLI session。

## External CLI 接入原则

第三方 CLI 适合先作为可选外部数据源，不应直接 vendor 到主代码。

调用方式：

```text
MajorRSS
→ ExternalCliAdapter
→ command --json
→ parse envelope
→ SourceItem
```

约束：

- 只接只读命令。
- 必须有超时。
- 必须校验 `ok/schema_version/data/error`。
- 必须限制频率。
- 失败不能阻断整个 tracker。
- 输出 schema 变更时要标记 adapter degraded。

优先级建议：

1. Telegram CLI：local-first，稳定，适合情报缓存。
2. Bilibili CLI：视频、字幕、评论适合情报源。
3. Twitter CLI：价值高，但风控与接口变化更频繁。
4. Xiaohongshu CLI：只读低频接入，风险最高。

## Route Test 与可观测性

当前用户很难判断 RSSHub 是否真的生效，也很难区分：

- Resolver 没有生成正确 route。
- RSSHub route 本身错误。
- HTTP 请求失败。
- RSS 解析失败。
- 抓到了内容但全是噪音。
- fallback 没有触发。
- 内容进入 RawArticle 后被后续处理卡住。

因此应增加 Route Test 能力，作为 UI 调试面板或后端 API。

### Route Test 输入

```text
target
source_kind: URL | ACCOUNT | KEYWORD
platform: optional
auth_profile_id: optional
fetch_policy: optional
```

### Route Test 输出

```text
original_target
normalized_target
resolved_routes[]
selected_route
fallback_routes[]
final_source_item_count
```

每条 route 应包含：

```text
route_id
adapter
url_or_command
purpose
requires_auth
started_at
finished_at
duration_ms
http_status
ok
error_type
error_message
item_count
latest_item_time
sample_titles
sample_urls
quality_score
fallback_triggered
```

### RSSHub Route Test 示例

```text
Input:
https://space.bilibili.com/123456

Resolver:
rsshub:/bilibili/user/video/123456

Fetcher result:
http_status: 200
item_count: 10
latest_item_time: 2026-06-09T12:30:00Z
sample_titles:
- 新视频标题 A
- 新视频标题 B

Decision:
RSSHub 可用于 discovery
需要深度内容时继续调用 Bilibili CLI enrichment
```

### Route Test 的产品意义

Route Test 不是开发调试小工具，而是 MajorRSS 后续 source system 的核心可观测能力。

它能帮助用户理解：

- 当前目标是否能被 RSSHub 覆盖。
- 是否需要授权。
- 是否应该启用 CLI adapter。
- 哪个 fallback 被触发。
- 为什么没有新 RawArticle。
- 为什么 LLM 没有生成 IntelReport。

它也能帮助系统自动决策：

- 某个 route 连续失败后降级。
- 公共 RSSHub 不可用时切换自建实例。
- 关键词源质量低时降低权重。
- 某个平台适合从 RSSHub 升级到 CLI adapter。

## 调度与任务状态

`TaskRequest` 建议增加或模拟以下字段：

```text
retry_count
max_retries
last_heartbeat_at
locked_by
lock_expires_at
```

短期即使不改 schema，也应增加启动时清理逻辑：

```text
RUNNING 且 started_at 超过 N 分钟
→ FAILED 或重新置为 PENDING
```

任务执行建议拆为：

```text
SCRAPE_TRACKER
PROCESS_TRACKER
REFRESH_AUTH
TEST_ROUTE
TREND_SCAN
SUBSCRIPTION_CHECK
```

## 错误分类

统一错误类型，避免所有失败都叫 Probe Failed。

建议：

```text
AUTH_EXPIRED
RATE_LIMITED
CAPTCHA_REQUIRED
SOURCE_UNAVAILABLE
RSS_PARSE_FAILED
NETWORK_ERROR
ENCODING_ERROR
SCHEMA_CHANGED
DUPLICATE
LOW_RELEVANCE
LLM_FAILED
```

UI 展示时按错误类型给用户明确动作：

- 重新授权。
- 降低频率。
- 切换 RSSHub 实例。
- 禁用某个 source route。
- 查看原始错误。

## 阶段计划

## 当前实现审计

审计时间：2026-06-10。

当前代码已经完成前端形态更替：

```text
Streamlit / Flet
→ Tauri + React + FastAPI sidecar
```

这解决了桌面 UI 载体问题，但尚未完成本文档定义的管线重构。当前状态可概括为：

```text
前端替换已基本完成
后端 API 已接入桌面端
核心抓取管线仍主要是旧实现
Source Intent / Resolver / SourceItem 尚未落地
```

### 已完成或基本完成

- 已新增 `desktop/` Tauri + React 前端。
- 已新增 `backend/` FastAPI 本地 API。
- Tauri 已通过 sidecar 启动 `backend-sidecar`。
- Dashboard、Trackers、Monitors、Settings、Briefing、Billing 等页面已有 React 实现。
- 前端生产构建通过。
- Settings 中已加入 API key、授权状态、数据库配置、应用模式等管理入口。
- Dashboard 已区分 AI Feed 和 Raw Feed，用于支持 `pure_rss` / `ai_fusion` 两种模式。

### 与设计文档尚未对齐的部分

#### 1. Source Intent 还不是一等模型

文档定义的高层用户意图是：

- Tracker 管线：
  ```text
  RSS_FEED
  KEYWORD_DISCOVERY
  ACCOUNT_TRACKING
  HYBRID
  ```
- Subscription / Monitor 管线：
  ```text
  PAGE_DIFF
  ```

但当前代码仍主要使用旧模型：

```text
tracker_type: URL | KEYWORD | ACCOUNT | HYBRID
tier: 1 | 2 | 3
cookie_string
```

涉及位置：

- `db/models.py`
- `backend/schemas.py`
- `desktop/src/pages/Trackers.tsx`

问题：

- 用户设计意图没有进入数据库和 API。
- RSS 频道订阅、关键词探测、账号追踪仍由技术类型混合表达。
- 页面 Diff 独立存在于 `Subscription`，但未和统一 source intent 体系打通。

#### 2. Source Resolver / SourceItem 尚未实现

当前抓取逻辑仍集中在 `services/scraper_service.py` 中，由 `scrape_single_tracker()` 直接决定：

- 目标如何解析。
- RSSHub / Nitter / Google News / HN / Reddit 如何拼接。
- fallback 何时触发。
- RawArticle 何时写入。

尚未实现：

- `SourceResolver`
- `SourceRoute`
- `SourceItem`
- `Normalizer`
- route metadata
- quality score
- source route 可追溯字段

结果是：

- RSSHub 成功与否不可观测。
- fallback 过程不可系统化。
- 后续无法清楚判断某条 RawArticle 来自哪个 route。
- LLM 只能看到混合后的 RawArticle，无法感知 source quality。

#### 3. HYBRID URL 仍固定走 RSS parser

当前 HYBRID tracker 的 `urls` 仍固定执行：

```text
_fetch_url(..., tier=1)
```

这会忽略 tracker 的 `tier` 配置。

后果：

- 普通网页可能被强行交给 RSS parser。
- GitHub organization、产品页面、文档页面等容易出现 RSS parse error。
- 用户以为配置的是 Agentic / 授权抓取，实际仍走 RSS。

这与本文档中的原则冲突：

```text
普通网页
→ 先判断是否原生 RSS
→ 可映射则尝试 RSSHub
→ 否则不要硬塞 RSS parser，直接进入 WebpageSnapshot / Agentic
```

#### 4. Route Test 尚未实现

文档要求增加 Route Test，用于解释：

- resolver 生成了哪些 route。
- RSSHub route 是否有效。
- HTTP status 是什么。
- item count 是多少。
- fallback 是否触发。
- 最终写入多少 SourceItem / RawArticle。

当前前端和后端均未提供 Route Test API 或 UI。

结果：

- 用户无法判断 RSSHub 是否真正生效。
- 失败只能从 pipeline logs 中猜测。
- 无法区分“route 不存在”“HTTP 失败”“解析失败”“抓到了但被过滤”“后续处理卡住”。

#### 5. RUNNING 任务缺少回收机制

当前 `scheduler.py` 只拉取 `PENDING` 任务，然后将其标记为 `RUNNING`。

如果 worker / sidecar 中断，任务会永久停留在：

```text
RUNNING
```

尚未实现：

- stale task cleanup。
- retry count。
- heartbeat。
- lock expiry。
- 启动时恢复。

这会导致 UI 上看起来任务仍在执行，但实际上没有进展。

#### 6. Cookie 仍绑定在 Tracker 上

当前 `cookie_string` 仍在：

- `Tracker`
- `TrackerCreate`
- Trackers 表单

这与本文档的 Auth Profile 方向不一致。

问题：

- 授权状态和 tracker 配置耦合。
- 同一平台账号难以复用。
- cookie 容易被理解为 tracker 产品语义，而不是 fetcher 能力。
- 不利于后续支持浏览器 cookie、QR login、CLI session 等多种授权来源。

#### 7. 关键词探测仍是高噪声硬编码源

当前关键词探测仍固定使用：

```text
Google News RSS
HN RSS
Reddit RSS search
```

尚未实现：

- route 权重。
- source trust score。
- 轻量相关性过滤。
- 每轮最大写入数量。
- 被过滤数量统计。
- 低质量 route 自动降权。

这与关键词探测的设计目标不完全一致：

```text
默认探测管线要广，但不能无差别写库。
LLM 不应承担全部噪音过滤成本。
```

### 安全与工程风险

#### 1. 外部内容直接进入 HTML 渲染

当前前端多处使用 `dangerouslySetInnerHTML` 渲染：

- LLM 摘要。
- RawArticle 内容。
- Trend Alert。
- Briefing 内容。

这些内容来自：

- 外部网页。
- RSS 源。
- LLM 输出。
- 用户配置的抓取目标。

它们都不能被视为可信内容。

同时 Tauri 配置中 CSP 当前为：

```json
"csp": null
```

风险：

- 桌面端 XSS。
- 恶意 HTML / Markdown 注入。
- 与本地 API、数据库配置、授权状态等信息形成组合风险。

建议：

- 使用受控 Markdown renderer。
- 引入 HTML sanitizer。
- RawArticle 默认纯文本显示。
- 尽快设置 CSP。

#### 2. Postgres 密码会返回前端

当前数据库状态接口会返回 parsed `postgres_info`，其中包含明文 `password`。

本地桌面场景风险较低，但不应长期保留。

建议：

- `/db-status` 不返回 password。
- 前端只显示 masked password。
- 修改连接时用户重新输入密码。

#### 3. Lint 与测试未对齐

当前验证结果：

```text
npm run build: pass
npm run lint: fail
pytest -q: fail
```

测试失败原因：

- 测试仍 mock 旧 `worker.process_article` / `worker.BasicRSSScraper`。
- 实现已经迁移到 `services.processor_service` / `services.scraper_service`。

Lint 失败主要包括：

- ESLint 扫描了 `src-tauri/target` 生成物。
- React/TypeScript 中存在 `any`、未使用变量、effect 依赖、声明前引用等问题。

建议：

- lint ignore `src-tauri/target`、`dist`、`build`。
- 更新 Python 测试指向 services 层。
- 修复真实前端 lint 问题。

### 审计后的优先级建议

#### P0: 先处理安全边界

- 移除或约束 `dangerouslySetInnerHTML`。
- 增加 sanitizer。
- 设置 Tauri CSP。
- 数据库状态接口不返回明文 Postgres 密码。

#### P1: 修管线止血项

- HYBRID URL 不再固定 `tier=1`。
- 增加 RUNNING 任务超时回收。
- 修复 Windows stdout 编码导致抓取失败的问题。
- 给 RSS parse / network / auth / rate limit 做明确错误分类。

#### P2: 让设计意图进入模型

- 增加 `source_intent`。
- UI 表单先按四类意图组织：
  - RSS 频道订阅。
  - 关键词探测。
  - 账号追踪。
  - 页面变化对比。
- `tracker_type/tier` 逐步退为兼容字段或内部 fetch policy。

#### P3: 建立 Route Test

- 新增后端 Route Test API。
- 前端 Trackers 页面增加“测试目标”入口。
- 输出 route、HTTP 状态、items、fallback、样本标题、错误类型。

#### P4: SourceItem / Resolver 正式落地

- 新增 `SourceItem`。
- RSS / Agentic adapter 返回 SourceItem。
- Normalizer 统一写 RawArticle。
- RawArticle 可追溯 source route。

### Phase 1: 止血

目标：不改大架构，先修最明显断点。

- HYBRID URL 使用 per-category/per-url route strategy，不再依赖全局 tier。
- 修复安全日志，避免 Windows GBK/emoji 打断抓取。
- 增加 RUNNING 任务超时回收。
- 给 RSSHub 失败、RSS parse 失败、network 失败做明确分类。
- 给 Reddit/HN/Google keyword 结果加轻量相关性过滤。

### Phase 2: 统一 SourceItem

目标：抓取结果先进入统一中间结构。

- 新增 `SourceItem` dataclass / Pydantic model。
- `RssAdapter` 返回 `SourceItem[]`。
- `AgenticAdapter` 返回 `SourceItem[]`。
- Normalizer 统一写 `RawArticle`。
- 记录 route、platform、fingerprint。

### Phase 3: Source Resolver

目标：把 route 决策从 scraper 中抽出来。

- `RSS_FEED` (对 URL 目标) 根据域名决定 RSSHub/native RSS/agentic。
- `ACCOUNT_TRACKING` 根据 platform 决定 RSSHub/CLI/agentic。
- `KEYWORD_DISCOVERY` 根据配置决定 Google News/HN/Reddit/CLI。
- 支持 route fallback。

### Phase 4: Auth Profile

目标：授权和 tracker 解耦。

- 增加 Auth Profile 管理。
- 迁移 `cookie_string` 到 auth profile 或本地 secure storage。
- UI 中集中展示各平台授权健康状态。
- fetcher 根据 route/platform 获取授权。

### Phase 5: External CLI Adapter

目标：用外部 CLI 快速扩展平台源。

- 定义 `ExternalCliAdapter`。
- 先接 Telegram / Bilibili。
- 再试 Twitter / Xiaohongshu。
- 只读低频，输出 schema 校验。

## 验收标准

### 抓取层

- 同一个 tracker 的多个 source route 互不阻塞。
- 单个源失败不会导致整个 tracker 失败。
- 每个 RawArticle 可追溯到 source route。
- 公共 RSSHub 失败时有清晰 fallback 或错误提示。
- RSSHub 仅作为 discovery route 时，系统能明确展示后续 enrichment route。
- Route Test 能展示 route 生成、请求、解析、fallback 和样本数据。

### 任务层

- 不再出现永久 `RUNNING` 任务。
- 任务失败有错误类型和可读信息。
- worker 重启后能恢复或清理旧任务。

### 数据质量

- 宽泛关键词不会大量写入明显无关内容。
- LLM 前的 RawArticle 数量可控。
- IntelReport source evidence 清晰可追溯。

### 授权层

- Cookie/session 不再散落在 tracker 配置里。
- 授权状态可集中查看。
- 授权过期时能明确提示用户重登。

## 不建议做的事

- 不要把所有平台逆向逻辑一次性写进 MajorRSS。
- 不要把第三方 CLI 代码直接复制进主仓库。
- 不要让 UI 直接调用外部 CLI。
- 不要让 LLM 承担基础过滤和去重。
- 不要依赖公共 RSSHub 作为唯一稳定源。
- 不要让写操作进入情报采集管线。

## 推荐结论

MajorRSS 应继续保留 RSSHub + Cookie 授权两类能力，但应把它们统一为 source adapter 和 route fallback 体系。

短期先修管线断点；中期建立 SourceItem/Normalizer；长期把 Telegram、Bilibili、Twitter、小红书等 CLI 作为可选外部数据源接入。
