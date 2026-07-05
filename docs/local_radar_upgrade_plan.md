# MajorRSS 本地雷达升级方案

> **定位说明（2026-07-05）**：本文档是设计意图档案（产品定位、关注目标、SourceSelector 方向），长期有效。当前工程状态与路线图以 [engineering_baseline.md](engineering_baseline.md) 为准。

> 创建时间：2026-06-20
>
> 本文用于定义 MajorRSS 作为“个人本地信息助手 / 本地雷达”的升级方向，并说明 OnlyFourBot 在其中只承担可选的共享与复用角色。

## 产品定位

MajorRSS 的核心不是让用户订阅更多信息源，而是帮助用户减少不相关信息带来的时间和心智消耗。

用户真正想做的不是：

```text
我想订阅一堆 RSS
```

而是：

```text
我只想了解某件事
请你从合适的渠道帮我持续获取、过滤、整理相关信息
```

RSS、RSSHub、新闻、博客、网页、GitHub release、社交媒体账号、浏览器快照，都只是实现手段。

产品的用户心智应该是：

```text
关注目标
→ 本地雷达持续监听
→ 只把相关信息推给我
```

OnlyFourBot 不是中心化运行平台，也不是替用户完成所有抓取的云端服务。

它的定位是可选的共享与复用层：

- 分享有用的来源组合。
- 分享成功的任务配置。
- 分享可复用的抓取结果或 digest。
- 发现别人整理过的 source pack。
- 把社区资产导入到自己的本地 MajorRSS 任务中。

最终任务默认仍然在用户自己的电脑上运行。

## 两层使用模式

### 1. 纯 RSS / 本地阅读模式

用户没有 API Key，或不希望接入 AI 时，MajorRSS 仍然应该有价值。

运行方式：

```text
预设源 / 自定义源 / 社区导入源
→ 本地抓取
→ 本地过滤
→ 本地阅读
```

纯 RSS 模式不做 AI 判断，也不做 AI 摘要。

如果用户订阅了某个人物账号源，例如 Karpathy、Sam Altman、李飞飞，那么这些人发布的内容会进入 Raw Feed。

是否过滤，取决于用户任务配置：

- keep keywords
- ignore keywords
- 订阅哪些 collection
- 是否启用更窄的任务

纯 RSS 模式的价值是：

```text
用户不需要模型，也可以把自己关心的信息源集中到一个本地雷达里。
```

### 2. BYOK AI 模式

用户接入自己的模型 Key 后，MajorRSS 可以增加语义判断、摘要和重要性排序。

运行方式：

```text
关注目标
→ 本地选源
→ 本地抓取
→ 本地去重和初筛
→ AI 相关性判断
→ AI 摘要 / digest / alert
```

AI 不应该盲目读取所有内容。

正确顺序应该是：

```text
先选源
再抓取
再确定性过滤
再把缩小后的内容交给 AI
```

## 从关键词任务升级为关注目标

现在的关键词任务更像：

```text
用户输入关键词
→ Google News / HN / Reddit 搜索
→ 抓取结果
```

这能用，但不够接近用户真实需求。

更好的抽象是：

```text
Watch Target
关注目标
```

股票 App 的“关注某只股票后推送相关资讯”就是这种模式。

用户关注的不是一个字符串，而是一个实体：

```text
NVDA
```

系统内部会扩展成：

```text
NVIDIA
英伟达
NVDA.O
Jensen Huang
Blackwell
CUDA
GPU
AI chip
```

然后系统监听：

- 新闻。
- 公司公告。
- 监管公告。
- 研报。
- 行情异动。
- CEO / 高管发言。
- 行业政策。
- 上下游产业链消息。

MajorRSS 应该借鉴这种设计，但不局限于股票。

用户可以关注：

```text
某个公司
某个疾病
某个论文方向
某个 AI 模型公司
某个 Web3 协议
某个政策领域
某个创始人
某个产品
```

关注目标应包含：

```json
{
  "target": "NVIDIA AI chip",
  "entities": ["NVIDIA", "NVDA", "英伟达", "Jensen Huang", "Blackwell", "CUDA"],
  "source_collections": ["general_baseline", "ai_infra_radar", "market_and_economy_baseline"],
  "keep_keywords": ["GPU", "AI chip", "Blackwell", "inference"],
  "ignore_keywords": ["gaming sale", "coupon"],
  "push_policy": {
    "importance_threshold": 0.6,
    "dedupe_window_hours": 24
  }
}
```

这样系统就不是简单“搜关键词”，而是在本地运行一个关注雷达。

## 当前应用状态

当前应用已经有一套可用的底层抓取管线。

已有能力：

- `Tracker`：本地任务对象，支持 RSS、关键词发现、账号追踪和混合任务。
- `Subscription`：本地网页 / RSS 监控对象。
- `SourceResolver`：把任务意图转换成具体抓取路线。
- `RssAdapter`：抓取 RSS / Atom。
- `RssHubAdapter`：抓取 RSSHub route。
- `AgenticAdapter`：抓取网页快照。
- `HYBRID`：混合关键词、账号、网站。
- Pipeline trace：记录路线解析、抓取状态、失败原因、条目数量。
- AuthProfile：支持部分需要登录态的账号或页面。

当前路线行为：

- `RSS_FEED`：RSS 抓取，可选网页 fallback。
- `KEYWORD_DISCOVERY`：主要走 Google News RSS、Hacker News RSS、Reddit RSS。
- `ACCOUNT_TRACKING`：走 Nitter / RSSHub / 浏览器快照等账号路线。
- `HYBRID`：组合关键词、账号、网站信号。

这说明底层管线已经有基础。

缺的不是“更多抓取器”，而是：

```text
用户目标
→ 实体画像
→ 正确选源
→ 小范围可靠抓取
→ 严格降噪
```

## 主要产品缺口

当前用户仍然需要手动提供很多信号：

- 关键词。
- 账号。
- 网站。
- RSS。

系统可以执行路线，但还不会稳定判断：

- 这个目标属于哪个领域？
- 应该启用哪些 source collection？
- 哪些来源不该抓？
- 哪些来源最近不健康？
- 是否应该先查本地缓存？
- 是否需要提示用户补充自定义来源？

示例：

```text
用户目标：关注某个罕见病的新进展
```

当前可能变成：

```text
Google News RSS
HN RSS
Reddit RSS
```

期望行为应该是：

```text
识别为医疗 / 生物医药目标
→ 扩展疾病别名、药物名、相关机构
→ 使用 healthcare_medicine 的少量高权重源
→ 通用基座只作为背景兜底
→ 提示用户添加患者组织、药企管线、ClinicalTrials、FDA 页面等自定义来源
→ 避免扫描无关科技、Web3、泛娱乐来源
```

## 预设源库的角色

预设源库不是每次任务都要扫描的清单。

它是一张信息地图。

它帮助应用判断：

- 某个主题可能出现在哪里。
- 哪些源是通用基座。
- 哪些源是垂直专家源。
- 哪些源是人物账号源。
- 哪些源是昂贵或不稳定的。
- 哪些源需要登录。
- 哪些源是第三方生成 RSS。
- 哪些源应该避开当前任务。

核心规则：

```text
预设源库 ≠ 每次任务的全量抓取列表
```

每个任务都必须有预算：

- 最多抓几个源。
- 每个源最多抓几条。
- 是否优先查本地缓存。
- 是否启用 Google News fallback。
- 是否启用社交论坛。
- 是否允许浏览器快照。

## 必须新增的组件：SourceSelector

需要新增一个本地 `SourceSelector` 服务。

输入：

```text
用户目标
实体画像
关键词
当前模式
用户启用的预设 collection
用户自定义源
社区导入 source pack
抓取预算
source health
```

输出：

```text
本次选择哪些 source_id
转换成哪些 route signals
为什么选择它们
为什么跳过其他源
```

示例输出：

```json
{
  "topic": "rare disease therapy updates",
  "detected_domain": "healthcare",
  "selected_collections": ["general_baseline", "healthcare_medicine"],
  "selected_sources": [
    "who_news",
    "cdc_newsroom",
    "fda_news_candidate",
    "nature_journal",
    "science_journal"
  ],
  "skipped_sources": [
    {
      "source_id": "crypto_web3_watch",
      "reason": "category_mismatch"
    }
  ],
  "budget": {
    "max_sources_per_run": 8,
    "max_items_per_source": 10,
    "prefer_cached_articles": true
  }
}
```

## 执行策略

不要每次任务都重新抓取 collection 里的所有源。

建议顺序：

```text
1. 先查本地最近缓存
2. 根据目标选择少量来源
3. 只 fresh fetch 选中的源
4. 做确定性相关性过滤
5. 按 URL 和内容指纹去重
6. BYOK 模式下再使用 AI 做语义判断和摘要
7. 在 Trace 中显示来源覆盖和失败原因
```

建议 fetch policy：

```json
{
  "source_scope": ["general_baseline", "healthcare_medicine"],
  "max_sources_per_run": 8,
  "max_items_per_source": 10,
  "fresh_fetch_budget": 5,
  "prefer_cached_articles": true,
  "fallback_to_google_news": true,
  "fallback_to_social_forums": false,
  "min_relevance": 0.35
}
```

## 可靠性目标

MVP 阶段最重要的目标不是无限扩源，而是让自定义源和明确来源任务抓得稳。

优先级应该是：

```text
减少不相关内容
减少失败路线
明确 fallback 行为
建立 source health
提升 trace 可解释性
```

### Source Health

每个源应该记录：

- 最近成功时间。
- 最近失败时间。
- 成功率。
- 平均响应时间。
- feed parse 成功率。
- 每周平均新增条目数。
- 403 / 429 / captcha 频率。
- 重复率。
- 空结果率。
- 是否需要 auth。
- 当前状态：healthy、degraded、failed、quarantined。

自动选源时应该避开不健康来源。

### 相关性过滤

展示或摘要前应先做本地过滤：

- 标题匹配。
- 正文匹配。
- keep / ignore keywords。
- source category 匹配。
- 时间窗口。
- URL 去重。
- canonical URL 去重。
- 内容指纹去重。
- source importance 加权。

然后再决定是否交给 AI。

### 失败解释

每次失败都应该能解释：

- 选了哪些源。
- 哪些成功。
- 哪些失败。
- 失败类型是什么。
- 是否用了 fallback。
- 是否来自缓存。
- 是否建议用户添加来源或授权。

## 人物账号和自定义来源

人物账号是有效来源，但不是官方机构 RSS。

它们应该使用：

```json
{
  "source_type": "account",
  "platform": "twitter",
  "target": "karpathy",
  "verification_status": "person_account"
}
```

或者在混合任务里：

```json
{
  "type": "account",
  "value": "twitter:karpathy"
}
```

当前支持情况：

- Twitter/X：Nitter RSS、RSSHub、浏览器快照 fallback。
- Bilibili：RSSHub、浏览器快照 fallback。
- Weibo：RSSHub。
- Instagram / TikTok / Reddit：generic RSSHub 路径，稳定性不确定。

人物源应该作为可选子包：

- AI People Radar
- Tech Founders People Radar
- Crypto People Radar

不应该静默混入通用基座。

纯 RSS 模式下，如果用户订阅人物源且没有过滤，那么这些账号发什么就会进入 Raw Feed。

这是预期行为。

降噪应该发生在任务配置中。

## OnlyFourBot 的角色

OnlyFourBot 支持共享和复用，但不替代本地执行。

用户可以分享：

- source collection。
- 任务模板。
- 成功的 route 配置。
- generated RSS。
- 抓取结果元数据。
- public digest。
- source health 报告。

其他用户可以导入：

- 别人的 source pack。
- 别人的任务配置。
- 已生成的 digest。
- 已验证的 generated RSS。

导入后，这些资产变成本地任务输入。

示例：

```text
用户 A 分享 “AI Research Leaders” source pack：
- arXiv cs.LG
- DeepMind Blog
- OpenAI News
- Fei-Fei Li account
- Andrej Karpathy account
- selected GitHub release feeds

用户 B 导入：
→ MajorRSS 把这些来源加入本地任务
→ 用户 B 的电脑本地抓取和过滤
→ BYOK AI 模式下本地摘要
```

## 开发者维护重点

开发者要维护两层可靠性。

### 1. 本地抓取管线

优先事项：

- RSS 解析稳定。
- RSSHub 集成稳定。
- 网页快照 fallback 可用。
- 账号追踪知道何时需要 auth。
- source health 可记录。
- trace 足够清楚。
- 相关性过滤可靠。

### 2. Generated RSS 维护

对没有官方 RSS 的高价值公开页面，可以使用 Olshansk 风格方法：

```text
feed registry
per-source generator
requests / browser 分流
cache
dedupe
health check
generated RSS output
failure quarantine
```

Generated RSS 必须标注：

- `third_party_generated`
- `generated_by_majorss`

不能伪装成 `official_feed`。

## 实施路线

### Phase 1：让自定义源抓取更稳

MVP 阶段优先确保这些场景可靠：

- 用户给 RSS URL，能抓取、去重、展示。
- 用户给普通网页，能快照或 fallback。
- 用户给账号，能解释 RSSHub / auth / fallback 结果。
- 用户给混合任务，能清楚显示每条 route 成败。
- 纯 RSS 模式不运行 AI processing 和 trend scan。

### Phase 2：让预设源可执行

- 把 `docs/source_presets.seed.json` 迁到应用数据目录。
- 增加 sources / collections API。
- 支持从 collection 创建 Tracker signals。
- 保留 docs 版本用于审计和维护。

### Phase 3：关注目标与 SourceSelector

- 把 keyword task 升级为 Watch Target。
- 增加实体别名、相关人物、相关产品、相关机构。
- 根据目标领域选择少量 source。
- 记录为什么选这些源。
- 记录为什么跳过其他源。

### Phase 4：健康度和可靠性

- 增加 source health 表或本地 JSON 缓存。
- 从 pipeline run 中记录 route-level health。
- 自动隔离不稳定源。
- fresh fetch 前优先查本地缓存。

### Phase 5：相关性和去重

- AI 前增加确定性 relevance scoring。
- 增加内容指纹。
- 增加 canonical URL normalization。
- 在 trace 中显示接受 / 丢弃原因。

### Phase 6：OnlyFourBot 共享

- 导出 / 导入 source collection。
- 导出 / 导入 task template。
- 分享 generated feed 元数据。
- 分享 public digest 和 fetch result fingerprint。
- 把社区 source pack 导入成本地任务。

## 成功标准

MajorRSS 成功时应该表现为：

- 用户不用反复手动刷信息源。
- 用户看到的不相关内容更少。
- 纯 RSS 模式不用 AI 也有价值。
- BYOK AI 模式只处理缩小后的高相关内容。
- 失败原因可解释。
- 自定义源和账号源抓取更稳定。
- source pack 可以复用。
- 社区资产能增强本地任务，但不会夺走本地控制权。
