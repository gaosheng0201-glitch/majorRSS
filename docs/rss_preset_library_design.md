# RSS Preset Library 设计方向

> 创建时间：2026-06-10
>
> 本文用于定义 MajorRSS 是否需要内置 RSS / Source 预设库，以及预设库和信息降噪、共享 token、OnlyFouBot 的关系。

## 结论

MajorRSS 有必要整合一个 RSS / Source 预设库。

但它不应该是一个“手工维护的大而全 RSS 地址列表”，而应该是：

```text
可验证
可评分
可订阅
可共享
可复用 AI 处理结果
的 Source Preset Library
```

它的目标不是收集最多 RSS，而是帮助用户快速建立高质量关注面。

## 为什么需要预设库

MajorRSS 的目标是让用户减少噪音，直接获得自己关心的信息。

如果用户每次都要自己寻找 RSS、判断站点质量、配置 RSSHub route、测试可用性，那么产品门槛仍然很高。

预设库可以解决这些问题：

1. 新用户开箱即用。
2. 系统能主动推荐高质量源。
3. 关键词探测可以优先从高质量源开始，而不是直接全网乱搜。
4. RSSHub route 可以被产品化封装，避免用户直接面对复杂 route。
5. 公共源可以统一抓取、统一去重、统一摘要。
6. OnlyFouBot 可以基于共享源和 collection 复用 token 成本。

## 不要做成什么

### 不要做成 RSS 地址大全

RSS 地址大全的问题：

- 很快腐烂。
- 大量源没人维护。
- 噪音水平不可控。
- 质量参差不齐。
- 用户看到太多选择反而不知道怎么选。

MajorRSS 不应该追求：

```text
收录最多 RSS
```

而应该追求：

```text
高质量、低噪音、可解释、可复用
```

### 不要等同于 RSSHub route 大全

RSSHub 是能力层，Source Preset Library 是产品判断层。

RSSHub route 表示：

```text
这个站点有办法抓
```

预设库应该表示：

```text
这个源值得关注
适合哪些用户
噪音水平如何
更新频率如何
是否适合共享摘要
```

所以预设库不能只是 RSSHub route 的镜像。

## 三层结构

### 1. Built-in Presets：内置精选库

由 MajorRSS 官方维护。

特点：

- 数量少。
- 质量高。
- 稳定性优先。
- 默认适合新用户。
- 主要覆盖 AI、科技、金融、政策、论文、开源等高价值领域。

初期建议规模：

```text
30 - 50 个
```

成熟后可以扩展到：

```text
100 - 150 个
```

不建议一开始超过 200 个。

适合内置的源类型：

- 官方博客 RSS。
- 官方 changelog。
- GitHub release feed。
- 重要研究机构 blog。
- arXiv 分类 feed。
- 政策 / 监管公告。
- 低噪音财经公告源。
- 高质量技术媒体。

不适合内置的源：

- 娱乐化内容。
- 高频低价值新闻流。
- 未验证的个人博客集合。
- 容易失效的反爬 route。
- 需要 cookie 的私有源。

### 2. Community Presets：社区共享库

由用户贡献和维护。

特点：

- 用户可以发布 source。
- 用户可以发布 collection。
- 其他用户可以订阅。
- 系统记录健康度、噪音率、订阅数、复用次数。

社区库是 OnlyFouBot 的基础。

它的价值不是简单分享 RSS，而是分享关注判断：

```text
我关注什么
为什么这个源重要
它适合哪个领域
它的噪音水平如何
```

示例 collection：

- AI Infra Radar。
- OpenAI Ecosystem Watch。
- Crypto Regulation Watch。
- Semiconductor Supply Chain。
- China Tech Media。
- Frontier Model Labs。
- Developer Tools Changelog。

### 3. Private Presets：本地私有库

由用户自己维护。

包括：

- 用户手动添加的 RSS。
- 用户手动添加的 RSSHub route。
- 账号追踪。
- 页面 diff。
- cookie / AuthProfile 授权源。
- 私有关键词组合。

原则：

- 默认不共享。
- 涉及 AuthProfile / cookie 的源永远不自动共享。
- 用户可以显式把公开源发布为 community source。
- 发布时必须移除私有凭证、cookie、header、token、个人配置。

## 数据模型建议

### SourcePreset

预设库的核心对象不是简单 URL，而是 SourcePreset。

示例：

```json
{
  "id": "openai_blog",
  "title": "OpenAI Blog",
  "description": "Official OpenAI product and research updates.",
  "source_type": "rss",
  "url": "https://openai.com/news/rss.xml",
  "route": null,
  "category": ["AI", "Company News"],
  "tags": ["OpenAI", "LLM", "API"],
  "language": "en",
  "region": "global",
  "importance": "high",
  "noise_level": "low",
  "update_frequency": "medium",
  "requires_auth": false,
  "owner_type": "built_in",
  "default_fetch_policy": {
    "url_strategy": "rss_first",
    "fallback_enabled": true,
    "max_days": 14,
    "max_items_per_route": 20,
    "min_relevance": 0.35
  },
  "quality": {
    "health_score": null,
    "success_rate": null,
    "avg_items_per_week": null,
    "noise_rate": null,
    "last_checked_at": null
  },
  "sharing": {
    "can_share_summary": true,
    "token_reuse_score": null,
    "subscriber_count": 0
  },
  "content_rights": {
    "access_type": "public_web",
    "redistribution_allowed": false,
    "summary_allowed": "public_summary",
    "quote_allowed": "short_excerpt",
    "source_link_required": true,
    "license_url": null,
    "risk_level": "low"
  }
}
```

### 字段解释

#### source_type

建议枚举：

```text
rss
rsshub
web_page
account
api
github_release
arxiv
page_diff
```

说明：

- `rss`：明确 RSS / Atom / JSON Feed。
- `rsshub`：RSSHub route。
- `web_page`：普通网页，需要 resolver 判断是否可抓取。
- `account`：账号追踪源。
- `api`：公开 API。
- `github_release`：GitHub release / commits / tags。
- `arxiv`：论文分类或搜索 feed。
- `page_diff`：页面变化监控。

#### importance

建议枚举：

```text
critical
high
medium
low
```

作用：

- 决定默认推荐权重。
- 决定 keyword discovery 是否优先命中。
- 决定是否适合进入内置库。

#### noise_level

建议枚举：

```text
low
medium
high
unknown
```

作用：

- 影响默认过滤强度。
- 影响是否推荐给新用户。
- 影响是否值得共享 token。

#### owner_type

建议枚举：

```text
built_in
community
private
```

作用：

- 控制同步和共享权限。
- 控制是否允许公共缓存。
- 控制是否可被其他用户订阅。

#### requires_auth

布尔值。

如果为 true：

- 不进入公共抓取队列。
- 不共享原文内容。
- 不共享 cookie / header。
- 只能共享源元信息，且需要用户明确确认。

### SourceCollection

SourceCollection 是一组 SourcePreset 的组合。

示例：

```json
{
  "id": "ai_infra_radar",
  "title": "AI Infra Radar",
  "description": "High-signal sources for AI infrastructure, model serving, GPUs, inference, and developer tooling.",
  "category": ["AI", "Infrastructure", "Developer Tools"],
  "owner_type": "community",
  "source_ids": [
    "openai_blog",
    "anthropic_news",
    "nvidia_blog",
    "huggingface_blog",
    "github_blog"
  ],
  "default_keywords": [
    "inference",
    "agent",
    "GPU",
    "model serving",
    "tool calling"
  ],
  "default_summary_style": "technical_brief",
  "sharing": {
    "subscriber_count": 0,
    "weekly_token_saved_estimate": null
  }
}
```

## 和 Tracker / Subscription 的关系

SourcePreset 不是 Tracker。

SourcePreset 是可复用源定义。

Tracker / Subscription 是用户自己的关注任务。

关系应是：

```text
SourcePreset
→ 用户一键订阅
→ 创建 Tracker 或 Subscription
```

具体映射：

| SourcePreset 类型 | 创建对象 | source_intent |
|---|---|---|
| rss | Tracker | RSS_FEED |
| rsshub | Tracker | RSS_FEED / ACCOUNT_TRACKING |
| account | Tracker | ACCOUNT_TRACKING |
| web_page | Tracker 或 Subscription | RSS_FEED / PAGE_DIFF |
| page_diff | Subscription / Monitor | PAGE_DIFF |
| arxiv | Tracker | RSS_FEED / KEYWORD_DISCOVERY |
| github_release | Tracker | RSS_FEED |

注意：

- PAGE_DIFF 应继续归 Subscription / Monitor，不应混入普通 Tracker。
- 同一个 SourcePreset 可以被多个用户任务引用。
- 用户任务可以覆盖默认 fetch_policy、prompt、提醒规则。

## 和关键词探测的关系

关键词探测不应该一上来就全网乱搜。

更好的默认流程：

```text
用户输入关键词
→ 先在高质量预设源中检索
→ 再跑 Google News / HN / Reddit / RSSHub routes
→ 再必要时使用浏览器 / Agentic fallback
→ 最后进入 LLM 判断
```

预设库可以为关键词探测提供：

- 默认搜索范围。
- 行业源集合。
- 噪音权重。
- 来源可信度。
- 语言 / 地区约束。

示例：

用户输入：

```text
OpenAI API pricing
```

系统可以优先查：

- OpenAI Blog。
- OpenAI Docs changelog。
- GitHub openai/openai-python releases。
- Hacker News。
- Google News。

而不是直接“全网搜索 + 所有社交平台”。

## 和共享 token 的关系

预设库是共享 token 的前提。

因为共享 token 需要稳定的复用单位：

```text
同一个 source
同一个 URL
同一个 content fingerprint
同一个 diff fingerprint
同一个 summary prompt version
```

如果每个用户都独立输入一份 URL，系统很难判断是否可以复用。

如果用户订阅的是同一个 SourcePreset：

```text
SourcePreset.id = openai_blog
```

那么系统可以：

1. 只抓取一次。
2. 只清洗一次。
3. 只生成一次公共摘要。
4. 多个用户复用结果。
5. 用户只在私有过滤 / 私有 prompt 上额外消耗 token。

这里的共享 token 不应被理解成所有用户必须复用同一份最终摘要。

更合理的理解是：

```text
共享源
共享抓取结果
共享清洗结果
共享公共事实摘要
共享官方 digest
```

然后用户或 Agent 可以在此基础上继续生成自己的日报、摘要、研究报告或工作流产出。

这符合 MajorRSS / OnlyFourBot 的社区创建理念：

```text
一次创建的关注源和 AI 产出
不应该用完即丢
而应该成为可以继续订阅、复用、扩展的社区资产
```

## OnlyFouBot 中的角色

OnlyFouBot 可以承载社区共享库。

它不是单纯的 bot，而是：

```text
共享关注源网络
```

它可以提供：

- 公共 SourcePreset 仓库。
- 公共 SourceCollection。
- 订阅关系。
- 公共摘要缓存。
- 热门源健康度。
- token 节省估算。
- 用户贡献排行榜。
- collection 订阅入口。
- 官方摘要日报。
- Agent / MCP / CLI / API 订阅入口。
- collection 二次产出统计。

MajorRSS 桌面端可以：

- 从 OnlyFouBot 拉取公共预设库。
- 订阅公共 collection。
- 将用户私有配置叠加在公共源之上。
- 将非敏感源发布回 OnlyFouBot。
- 基于公共源生成用户自己的个人日报。
- 允许本地 Agent 订阅公共源并做个性化处理。

## 健康度与质量评分

每个 SourcePreset 都应该有健康度。

### health_score

建议由以下指标计算：

- 最近 7 天成功率。
- 最近一次成功时间。
- 平均响应时间。
- feed parse 成功率。
- 平均新增条目数。
- 是否频繁返回 403 / 429 / captcha。

### noise_rate

可由以下指标估算：

- 被 LLM 判定为低价值的比例。
- 被用户标记为无用的比例。
- 标题重复比例。
- 内容过短比例。
- 广告 / 推荐内容比例。

### token_reuse_score

可由以下指标估算：

- 订阅人数。
- 相同内容被复用次数。
- 公共摘要命中次数。
- 每周节省 token 估算。

## 初期内置库建议

### AI / Frontier Labs

可优先收录：

- OpenAI Blog。
- Anthropic News。
- Google AI Blog。
- DeepMind Blog。
- Meta AI Blog。
- Microsoft Research Blog。
- NVIDIA Blog。
- Hugging Face Blog。

### 开发者与开源

可优先收录：

- GitHub Blog。
- GitHub Changelog。
- GitHub Releases for key repos。
- Vercel Blog / Changelog。
- Cloudflare Blog。
- Supabase Blog / Changelog。
- LangChain Blog。
- LlamaIndex Blog。

### 论文

可优先收录：

- arXiv cs.AI。
- arXiv cs.LG。
- arXiv cs.CL。
- arXiv cs.CV。

### 金融 / 监管

可优先收录：

- SEC press releases。
- Federal Reserve press releases。
- Treasury press releases。
- ECB press releases。
- BIS publications。

### 中文科技

需要谨慎选择。

优先考虑：

- 官方博客。
- 公司公告。
- GitHub / 开源项目源。
- 低噪音技术社区。

不建议一开始放大量泛科技媒体，因为噪音高，维护成本高。

## MVP 实现建议

### 文件形态

初期可以先用 JSON 文件：

```text
docs/source_presets.example.json
```

或应用内：

```text
backend/data/source_presets.json
```

优点：

- 简单。
- 容易审计。
- 容易版本控制。
- 不需要一开始设计复杂后台。

### 后端 API

建议提供：

```text
GET /api/source-presets
GET /api/source-presets/{id}
GET /api/source-collections
POST /api/source-presets/{id}/subscribe
POST /api/source-collections/{id}/subscribe
POST /api/source-presets/test
```

### 前端 UI

建议先做一个简单入口：

```text
Presets / Source Library
```

功能：

- 按分类筛选。
- 搜索。
- 显示健康度。
- 显示噪音等级。
- 显示重要度。
- 一键订阅。
- 一键加入 Tracker / Monitor。

### 与当前 Tracker 表单结合

当前创建 Tracker 的地方可以增加：

```text
从预设库选择
```

用户选择后自动填充：

- name。
- tracker_type。
- source_intent。
- target。
- fetch_policy。
- radar_section。
- prompt_override。

用户仍可修改。

## 风险

### 维护成本

预设库如果追求大而全，会很快失控。

应通过：

- health_score。
- last_checked_at。
- community reports。
- 自动失效标记。
- source owner / maintainer。

来控制维护成本。

### 版权与内容边界

预设库只应该保存：

- 源元信息。
- 公开 URL。
- route。
- 质量指标。
- 摘要缓存。

不应无边界保存全文内容，尤其是需要授权的内容。

SourcePreset 应明确记录内容权利状态。

建议枚举：

```text
public_domain
open_access
creative_commons
public_web
paid_report
licensed_partner_content
user_private_content
unknown_rights
```

默认规则：

```text
paid_report / user_private_content / unknown_rights
→ 不进入公共摘要缓存
→ 不允许全文展示
→ 不允许公共下载
→ 不允许作为官方 digest 的主要替代内容
→ 只允许元信息、链接和有限原创评论
```

如果是机构报告、金融研报、付费论文、行业数据库等高价值内容，应默认 `risk_level=high`。

MajorRSS / OnlyFourBot 可以帮助用户发现这些内容，但不应把购买后的报告内容再分发给订阅用户。

更稳妥的方式是：

- 保存报告元信息。
- 链接到原始购买 / 阅读入口。
- 写原创评论。
- 基于公开来源做交叉验证。
- 或通过正式授权合作分发内容。

### 私有凭证泄露

涉及 AuthProfile / cookie 的源：

- 默认 private。
- 不允许自动发布。
- 不允许把 cookie/header/token 带入共享层。
- 发布时必须做敏感字段检查。

### 共享摘要的个性化不足

同一个公共摘要不一定满足所有用户。

解决方式：

- 公共摘要只做事实层。
- 用户私有层再做个性化解释。
- 缓存按 summary_style / language / prompt_version 划分。

## 推荐实施顺序

### Step 1：本地内置 JSON

- 建立 30-50 个高质量源。
- 只覆盖 AI / 科技 / 金融 / 论文。
- 加入一键订阅。

### Step 2：健康度检测

- 定期测试 feed。
- 记录成功率。
- 记录最近更新时间。
- 标记失效源。

### Step 3：和关键词探测联动

- 关键词探测优先搜索相关分类的预设源。
- 高质量源优先。
- 噪音源降权。

### Step 4：SourceCollection

- 内置几个 collection。
- 允许用户一键订阅 collection。

### Step 5：OnlyFouBot 同步

- 公共预设库远程同步。
- 用户发布 collection。
- 订阅公共 collection。

### Step 6：共享 token 缓存

- 相同 SourcePreset 的抓取结果复用。
- 相同 fingerprint 的 AI 摘要复用。
- 显示 token 节省。

## 最终目标

RSS Preset Library 不是 RSS 地址库。

它应该成为 MajorRSS / OnlyFouBot 的信息网络基础：

```text
用户不需要懂 RSS
用户只需要选择自己关心的领域
系统提供高质量源
社区共享关注包
公共源统一处理
AI 摘要被复用
token 消耗被降低
噪音被压制
```
