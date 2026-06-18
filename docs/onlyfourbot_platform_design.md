# OnlyFourBot 共享平台设计方向

> 创建时间：2026-06-10
>
> 本文用于定义 OnlyFourBot 站点的共享、订阅、鉴权、信用体系，以及 MCP / CLI / API / Agent 扩展方向。

## 设计目标

OnlyFourBot 不是普通 RSS 聚合站，也不是开放投稿目录。

它的目标是：

```text
让用户从 MajorRSS 应用中生成可信关注源
再通过 OnlyFourBot 分享、订阅、复用和扩展
```

核心原则：

1. 只能分享从 MajorRSS 应用诞生的内容。
2. 避免恶意污染源。
3. 避免投毒信息进入公共摘要和共享缓存。
4. 建立用户、设备、应用实例、源、collection、agent 的信用体系。
5. 允许人类用户订阅，也允许 Agent / MCP / CLI / API 订阅。
6. 共享公共源和公共摘要，减少重复 token 消耗。

## 核心理念：社区创建与产出复利

OnlyFourBot 的核心不是商业化 token 平台，而是一个社区创建网络。

它要解决的问题是：

```text
很多 AI 产出被一次性消费后就丢弃
很多用户反复为同一个源、同一条信息、同一个摘要支付 token
很多高质量关注源只存在于个人配置里，无法沉淀为社区资产
```

OnlyFourBot 的理念是：

```text
让关注源、摘要、日报、diff、collection、Agent 处理结果
在被创建之后继续产生复利
```

这里的复利不是单纯省钱，而是：

- 一个用户整理的高质量源，可以被更多人订阅。
- 一个用户创建的 collection，可以成为社区的信息入口。
- 官方生成的 digest，可以服务低需求用户。
- 高需求用户可以订阅同一组源，用自己的 Agent 做更深入分析。
- Agent / MCP / CLI 可以把公共源网络接入自己的工作流。
- 公共摘要和公共事实层可以被复用，而不是每个人重复消耗 token。

因此平台不应强迫所有用户使用同一套摘要逻辑。

更合理的分层是：

```text
公共层：
可信源、源健康度、collection、公共事实摘要、官方 digest

个人 / Agent 层：
私有过滤、私有 prompt、自定义日报、行业视角、工作流集成
```

低需求用户可以直接看官方摘要日报。

高需求用户可以订阅源之后，使用自己的 Agent、MCP、CLI、API 做个性化摘要、日报、研究、提醒或二次创作。

OnlyFourBot 提供可信的信息源网络和默认公共结果，但不垄断所有解释方式。

更准确的定位是：

```text
OnlyFourBot 是面向人和 Agent 的可信关注源网络
MajorRSS 是它的桌面客户端和个人雷达
```

token 节省是结果，不是唯一叙事。

真正的产品叙事是：

```text
让信息关注和 AI 产出成为可复用的社区资产
而不是用完即丢的一次性消耗
```

## 为什么必须限制来源

如果 OnlyFourBot 允许任意用户直接提交 RSS / URL / route，会出现这些问题：

- 恶意提交钓鱼源。
- 提交伪装成官方源的假 RSS。
- 提交污染 prompt 的内容源。
- 伪造热门 collection。
- 大量低质量源淹没高质量源。
- 通过源内容污染公共摘要缓存。
- 利用平台作为抓取代理。

因此 OnlyFourBot 的分享入口必须受控：

```text
只能从 MajorRSS 客户端创建和发布
```

这不意味着用户不能添加自定义源。

用户可以在 MajorRSS 中添加自定义源，但发布到 OnlyFourBot 时必须经过：

- 客户端签名。
- 源规范化。
- 敏感字段剥离。
- 安全检查。
- 健康度检测。
- 信用评分。
- 可能的人工 / 半自动审核。

## 核心实体

### User

用户账号。

字段建议：

```text
id
display_name
email / oauth_provider
created_at
trust_level
reputation_score
verified_status
violation_count
```

### AppInstance

MajorRSS 应用实例。

用于证明内容来自官方客户端。

字段建议：

```text
id
user_id
device_name
app_version
public_key
created_at
last_seen_at
revoked_at
trust_level
```

说明：

- 每个 MajorRSS 客户端生成本地密钥对。
- 公钥注册到 OnlyFourBot。
- 发布 source / collection / digest 时由客户端私钥签名。
- 服务端验证签名和 app_version。

### SourcePreset

共享源定义。

只能由 MajorRSS 应用发布。

字段建议：

```text
id
canonical_url
source_type
title
description
category
tags
language
region
importance
noise_level
requires_auth
owner_user_id
created_by_app_instance_id
signature
status
trust_score
health_score
created_at
updated_at
```

### SourceCollection

源集合。

字段建议：

```text
id
title
description
category
source_ids
default_keywords
default_summary_style
owner_user_id
created_by_app_instance_id
signature
visibility
status
trust_score
subscriber_count
created_at
updated_at
```

### Subscription

订阅关系。

订阅主体可以是：

- 人类用户。
- Agent。
- CLI token。
- MCP client。
- 外部 API client。

字段建议：

```text
id
subscriber_type
subscriber_id
target_type
target_id
created_at
filters
delivery_config
```

### AgentClient

Agent / MCP / CLI / API 客户端身份。

字段建议：

```text
id
owner_user_id
name
client_type
public_key
api_key_hash
scopes
rate_limit_tier
trust_level
created_at
last_used_at
revoked_at
```

client_type：

```text
mcp
cli
api
agent
webhook
```

## 分享流程

### 1. 用户在 MajorRSS 中创建源

示例：

```text
用户添加 OpenAI Blog RSS
```

客户端保存本地 SourcePreset。

### 2. 用户选择分享

客户端准备发布 payload：

```json
{
  "source_type": "rss",
  "canonical_url": "https://openai.com/news/rss.xml",
  "title": "OpenAI Blog",
  "category": ["AI", "Company News"],
  "language": "en",
  "requires_auth": false,
  "app_version": "0.1.0",
  "created_at": "2026-06-10T00:00:00Z"
}
```

发布前客户端必须剥离：

- cookie。
- Authorization header。
- API key。
- 私有 prompt。
- 本地路径。
- 用户个人标签中可能包含的隐私字段。

### 3. 客户端签名

客户端用 AppInstance 私钥签名 payload。

服务端验证：

- app_instance 是否存在。
- app_version 是否允许发布。
- 签名是否有效。
- payload 是否被篡改。
- 用户是否被封禁。
- 该源是否需要审核。

### 4. 服务端安全检测

服务端执行：

- URL canonicalization。
- 域名信誉检测。
- 是否伪装官方域名。
- 是否命中 blocklist。
- 是否需要登录。
- feed parse 测试。
- MIME 类型检查。
- 内容抽样。
- prompt injection 检测。
- malware / phishing 基础检查。

### 5. 状态进入 pending / published

状态建议：

```text
pending
published
quarantined
rejected
deprecated
blocked
```

低风险源可以自动 published。

高风险源进入 pending 或 quarantined。

## 订阅流程

用户或 Agent 可以订阅：

- SourcePreset。
- SourceCollection。
- SharedDigest。
- SharedDiff。

订阅之后，用户或 Agent 可以有两种使用方式。

### 轻量使用

轻量用户直接消费官方或社区生成的公共结果：

- 官方日报。
- 官方摘要。
- collection digest。
- 重要源变化摘要。
- 页面 diff 解释。

这种模式成本低，适合不想配置 Agent、不想维护 prompt、不想自己处理信息的人。

### 深度使用

高需求用户或 Agent 订阅源后自行处理：

- 用自己的模型摘要。
- 用自己的 prompt 生成日报。
- 用自己的行业视角判断重要性。
- 接入 MCP / CLI / API 工作流。
- 与本地知识库、项目、任务系统结合。

这种模式保留用户自由度。

OnlyFourBot 只提供可信源和可复用的公共事实层，不强迫所有用户共享同一个最终结论。

订阅时可以叠加私有过滤：

```json
{
  "keywords": ["API", "pricing", "agent"],
  "min_importance": 4,
  "language": "zh",
  "delivery": "mcp"
}
```

注意：

```text
公共源结果可以共享
私有过滤结果只属于订阅者
```

## 鉴权体系

### 用户鉴权

建议支持：

- Email magic link。
- OAuth。
- Passkey。
- 本地客户端登录绑定。

### AppInstance 鉴权

MajorRSS 首次连接 OnlyFourBot 时：

1. 本地生成密钥对。
2. 用户登录 OnlyFourBot。
3. 客户端注册公钥。
4. 服务端返回 app_instance_id。
5. 后续发布请求必须签名。

好处：

- 可以证明内容来自 MajorRSS。
- 可以吊销恶意实例。
- 可以区分用户账号和设备实例。
- 可以限制旧版本客户端发布。

### API / CLI / MCP 鉴权

建议支持两类：

#### API Key

适合 CLI 和服务端脚本。

字段：

```text
api_key_hash
scopes
rate_limit
expires_at
last_used_at
```

#### Signed Request

适合 Agent / MCP。

方式：

- client 注册公钥。
- 请求体签名。
- 服务端验证签名和 nonce。

防止：

- token 泄露后被长期滥用。
- replay attack。
- 未授权写入。

## Scope 设计

Agent / CLI / MCP / API 不应该默认拥有全部权限。

建议 scopes：

```text
read:sources
read:collections
read:digests
read:diffs
subscribe:sources
subscribe:collections
create:private_source
publish:source
publish:collection
write:feedback
read:token_savings
admin:moderation
```

默认 Agent 只应拥有：

```text
read:sources
read:collections
read:digests
subscribe:sources
subscribe:collections
```

发布能力需要额外授权。

## 信用体系

OnlyFourBot 需要多维信用，不应只看用户。

### User Trust

用户信用。

影响：

- 是否可以直接发布。
- 发布是否需要审核。
- collection 推荐权重。
- API rate limit。

指标：

- 账号年龄。
- 发布源数量。
- 源通过率。
- 被订阅数。
- 被举报数。
- 被删除 / quarantine 数。
- 贡献源的健康度。
- 贡献源的噪音率。

### Source Trust

源信用。

指标：

- feed 成功率。
- 内容稳定性。
- 域名信誉。
- 被订阅数。
- 被用户保留率。
- 噪音率。
- LLM 判定有效率。
- 是否命中过 prompt injection。

### Collection Trust

集合信用。

指标：

- 订阅人数。
- 源平均健康度。
- 源平均噪音率。
- 用户保留率。
- 被 fork / reuse 次数。
- token 节省估算。

### AppInstance Trust

客户端实例信用。

指标：

- app version。
- 最近活动。
- 签名有效率。
- 发布失败率。
- 是否触发异常流量。
- 是否被用户主动吊销。

### Agent Trust

Agent / API client 信用。

指标：

- 请求量。
- 错误率。
- rate limit 命中率。
- 是否尝试越权。
- 是否订阅异常大量源。
- 是否发布低质量反馈。

## 投毒防护

OnlyFourBot 的风险点不在于用户私下订阅了低质量源，而在于低质量源、广告源、虚假消息源进入公共库、公共推荐、公共摘要缓存和共享 token 体系。

因此平台治理的第一原则是：

```text
私有订阅自由
公共发布受控
公共摘要隔离
高影响内容人工仲裁
```

用户可以在 MajorRSS 中订阅任意自定义 RSS、账号、网站或页面，但这些源默认只能影响用户自己。

只有当用户主动发布到 OnlyFourBot 时，才进入公共审核流程。

### 内容投毒

风险：

- 源内容包含 prompt injection。
- 源伪装为官方公告。
- 源诱导 LLM 输出错误结论。
- 源夹带广告、诈骗、恶意链接。

防护：

- 对源内容做 prompt injection 检测。
- LLM 输入前加 source boundary。
- 公共摘要只基于可信源或多源交叉验证。
- 对低 trust source 不进入公共摘要缓存。
- 高风险内容只做原文索引，不做公共摘要。

### 恶意低质量源

风险：

- 用户故意提交广告 RSS。
- 用户提交充满虚假消息的网站。
- 用户提交自己控制的低质量账号。
- 用户通过多个账号互相订阅、刷热度。
- 用户将垃圾源包装成热门领域 collection。

应对原则：

```text
允许私有使用
限制公共传播
不让低信源进入公共摘要缓存
```

处理方式：

- 新用户发布默认进入 `pending` 或 `experimental`。
- 低信用源不进入推荐。
- 低信用源不参与公共 digest。
- 单一低信源内容只能标记为 `observed`，不能标记为事实。
- 高风险领域源需要更严格审核。
- 订阅数异常增长需要风控。

### 源污染

风险：

- 大量提交低质量源。
- 伪造相似域名。
- 提交不稳定 RSS。
- 提交需要登录的源伪装成公开源。

防护：

- URL canonicalization。
- 域名 allowlist / blocklist。
- whois / DNS / HTTPS 基础检测。
- feed parse 健康检查。
- 相似域名检测。
- 发布速率限制。
- trust level 控制自动发布权限。

### Collection 投毒

风险：

- 好源中混入坏源。
- 伪装高质量主题包。
- 通过 collection 间接传播恶意源。

防护：

- collection trust 受 source trust 约束。
- 新 collection 默认 pending。
- collection 修改后重新评分。
- 订阅页显示风险源数量。
- 用户可查看源清单和变更记录。

## 审核体系

OnlyFourBot 不应只依赖人工审核，也不应只依赖 AI 审查。

推荐采用：

```text
规则检测
→ AI Risk Reviewer
→ 信用评分
→ 自动分流
→ 人工仲裁
```

### 审核流水线

公共发布建议流程：

```text
用户在 MajorRSS 创建私有源
→ 用户申请发布到 OnlyFourBot
→ MajorRSS 客户端签名提交
→ 服务端基础校验
→ 抽样抓取最近 N 条内容
→ 规则审查
→ AI Risk Reviewer 审查
→ 计算 risk_score / trust_score
→ 决策：experimental / pending / quarantined / rejected
```

基础校验包括：

- URL canonicalization。
- 域名检查。
- HTTPS 检查。
- blocklist 检查。
- feed parse 检查。
- MIME 类型检查。
- 是否需要登录态。
- 是否包含明显敏感 token / cookie / header。

规则审查包括：

- 广告密度。
- 外链比例。
- 重复标题比例。
- 内容过短比例。
- 可疑关键词。
- 伪装官方域名。
- 近期内容主题漂移。
- 是否频繁返回 403 / 429 / captcha。

### AI Risk Reviewer

平台可以设置 AI 审查员，但它的定位应是：

```text
风险审查员
```

而不是最终事实裁判。

AI Risk Reviewer 适合判断：

- 源描述和实际内容是否一致。
- 是否像广告站。
- 是否像软文站。
- 是否存在明显虚假信息风险。
- 是否存在 prompt injection。
- 是否伪装官方源。
- 是否为低信号内容源。
- 是否适合进入公共摘要缓存。

建议输出结构化结果：

```json
{
  "risk_score": 0.72,
  "risk_labels": [
    "ad_farm",
    "low_signal",
    "misinformation_risk"
  ],
  "source_matches_description": false,
  "prompt_injection_detected": false,
  "recommended_action": "pending_manual_review",
  "reason": "Recent items contain repeated promotional language and unverifiable claims."
}
```

AI Risk Reviewer 不应单独决定：

- 政治事实真伪。
- 金融投资结论。
- 医疗建议可信度。
- 法律判断。
- 高影响公共推荐。

这些需要进入人工仲裁或更严格的多源验证。

### 人工审核

人工审核不应覆盖所有提交，否则平台运营成本会失控。

人工审核适合处理：

- 高订阅量 source。
- 高风险领域 source。
- 被多人举报的 source。
- AI 判定不确定的 source。
- 官方源认证。
- 申诉。
- maintainer 权限申请。
- collection 被怀疑投毒。

推荐规则：

```text
机器负责规模化筛查
AI 负责语义风险判断
人工负责高影响决策
```

### 高风险领域

以下领域应默认更严格：

- 金融。
- 医疗。
- 政治。
- 法律。
- 投资建议。
- 突发新闻。
- 灾害安全。
- 加密货币喊单。

处理原则：

```text
更高 Source Trust
更高 User Trust
更严格摘要措辞
更明确来源展示
更少自动推荐
```

这些领域的公共摘要必须避免把单一来源包装成确定事实。

### 公共摘要事实等级

公共摘要不应把所有抓到的内容都当成事实。

建议为内容声明增加事实等级：

```text
observed
verified
disputed
low_confidence
```

含义：

- `observed`：某源声称发生了某事。
- `verified`：多个可信源确认。
- `disputed`：可信源之间说法冲突。
- `low_confidence`：低信源或单一来源，可信度不足。

公共 digest 生成时：

- 低信用源只能进入 `observed` 或 `low_confidence`。
- 高风险领域需要多源确认才可进入 `verified`。
- `disputed` 内容必须显示冲突来源。
- 单一来源内容必须显示来源，不做强结论。

### 发布状态分级

Source / Collection 不应该只有 published / rejected。

建议状态：

```text
private
pending
experimental
listed
recommended
verified
quarantined
rejected
blocked
deprecated
```

解释：

- `private`：只在用户本地或私有空间使用。
- `pending`：等待审核。
- `experimental`：可被订阅，但不进入推荐和公共摘要缓存。
- `listed`：可被搜索。
- `recommended`：可进入推荐。
- `verified`：官方或高可信源。
- `quarantined`：隔离观察，不可新增订阅或需要强警告。
- `rejected`：本次发布被拒绝。
- `blocked`：禁止再次发布。
- `deprecated`：源长期失效或被替代。

### 持续监控

审核不是一次性动作。

Source 发布后仍需持续评分：

- 7 天成功率。
- 最近成功时间。
- 被取消订阅率。
- 被标记无用率。
- 广告比例。
- 重复内容比例。
- AI 判定低价值比例。
- 外链可疑比例。
- 是否频繁改标题。
- 是否突然切换主题。
- 是否出现 prompt injection。

异常时状态可以自动降级：

```text
recommended
→ listed
→ experimental
→ quarantined
→ blocked
```

### 用户反馈

用户反馈是重要治理信号。

建议反馈类型：

```text
useful
noisy
broken
spam
ad_farm
misinformation
impersonation
prompt_injection
copyright_risk
```

反馈权重不能一视同仁。

应考虑：

- 用户 trust level。
- 用户订阅时长。
- 用户历史反馈准确度。
- 是否存在批量刷反馈。
- 是否多个新账号同时举报同一源。

高信用用户反馈权重更高，新账号批量反馈权重更低。

## Agent / MCP / CLI / API 扩展

OnlyFourBot 应支持非人类订阅者。

这会让它不仅是分享站点，也成为信息源基础设施。

### MCP Server

OnlyFourBot 可以提供 MCP Server。

典型 tools：

```text
search_sources(query, category, language)
list_collections(category)
subscribe_source(source_id)
subscribe_collection(collection_id)
get_latest_digest(collection_id)
get_source_health(source_id)
get_diff_updates(source_id)
submit_feedback(source_id, rating, reason)
```

典型 resources：

```text
onlyfourbot://collections/{id}
onlyfourbot://sources/{id}
onlyfourbot://digests/{id}
onlyfourbot://diffs/{id}
```

Agent 使用场景：

- 自动订阅 AI Infra Radar。
- 定期读取最新摘要。
- 查询某个源健康度。
- 将用户项目相关关键词叠加到公共 collection。

### CLI

CLI 可以支持：

```text
onlyfourbot login
onlyfourbot sources search "openai"
onlyfourbot collections list --category AI
onlyfourbot subscribe collection ai_infra_radar
onlyfourbot digest latest ai_infra_radar
onlyfourbot source publish ./source.json
onlyfourbot feedback source openai_blog --rating useful
```

CLI 用途：

- 开发者快速订阅。
- CI / cron 获取摘要。
- 本地调试 MajorRSS 发布 payload。
- 给 Agent 提供轻量入口。

### REST API

REST API 用于通用集成。

建议 endpoint：

```text
GET /v1/sources
GET /v1/sources/{id}
POST /v1/sources
GET /v1/collections
GET /v1/collections/{id}
POST /v1/collections
POST /v1/subscriptions
GET /v1/digests/latest
GET /v1/diffs/latest
POST /v1/feedback
GET /v1/token-savings
```

### Webhook

允许用户或 Agent 接收推送：

```text
new_digest
source_changed
diff_detected
source_unhealthy
collection_updated
```

Webhook 必须：

- 签名。
- 支持重试。
- 支持事件 id 去重。
- 支持订阅范围限制。

## 共享 token 缓存策略

OnlyFourBot 的共享 token 价值来自公共缓存。

需要注意：

```text
共享 token 不等于所有用户共享同一份最终摘要
```

更准确的设计是：

```text
共享源
共享抓取结果
共享 normalized item
共享 diff fingerprint
共享公共事实摘要
共享官方 digest
```

然后允许用户和 Agent 在此基础上做自己的个性化处理。

缓存 key 需要包含：

```text
source_id
content_fingerprint
diff_fingerprint
model
prompt_version
summary_style
language
created_at_bucket
```

公共摘要只适用于：

- public source。
- high trust source。
- 不包含用户私有 prompt。
- 不依赖用户 cookie。

私有层可以复用公共事实摘要，再做个性化改写：

```text
public factual summary
→ user-specific relevance explanation
```

这样既减少 token，又保留个性化。

公共摘要适合承担：

- 事实摘录。
- 事件基础描述。
- 关键来源列表。
- 时间线。
- diff 解释。
- 低需求用户的默认日报。

私有 / Agent 层适合承担：

- 投资视角。
- 技术架构视角。
- 产品策略视角。
- 用户自定义关键词。
- 私有知识库关联。
- 私有行动建议。

这样平台既可以让低需求用户直接使用公共产出，也不会限制高需求用户用自己的 Agent 继续创造。

## BYOK 与 LLM 成本边界

MajorRSS 的默认 LLM 成本模型应是 BYOK：

```text
Bring Your Own Key
```

也就是：

```text
每个用户使用自己的模型 API key
在自己的 MajorRSS / Agent / CLI 环境中完成摘要、日报、分析和分享
```

这点非常关键。

因为 OnlyFourBot 的“共享 token”理念不是指平台替所有用户支付 token，而是：

```text
用户用自己的 token 创造了源、摘要、日报、分析或 collection
这些产出可以在可信边界内继续复用
避免同一份信息被社区重复处理后用完即丢
```

### 成本分摊原则

#### 用户侧承担

用户自己的 MajorRSS / Agent 应承担：

- 私有源摘要。
- 私有关键词分析。
- 私有账号追踪总结。
- 私有日报。
- 自定义 prompt。
- 自定义模型。
- 私有知识库关联。
- 高频个人任务。

这些任务使用用户自己的 API key，平台不承担模型费用。

#### 官方侧承担

OnlyFourBot 官方只承担有限公共任务：

- 官方精选 collection 的轻量摘要。
- 官方日报。
- 公共源健康度的轻量审查。
- 必要的 AI Risk Reviewer。
- 少量公共事实层处理。

官方摘要应优先使用轻量模型。

日报或高质量综合分析可以使用更高推理等级模型，但应低频运行，例如：

```text
每日 / 每周 / 特定高价值 collection
```

而不是对所有源、所有用户、所有事件实时运行。

### BYOK 下的共享成立方式

BYOK 不削弱共享价值，反而让共享更成立。

共享对象不是用户的 API key，而是：

- SourcePreset。
- SourceCollection。
- 源健康度。
- normalized item。
- content fingerprint。
- diff fingerprint。
- 用户愿意公开的摘要 / 日报。
- 官方 digest。
- Agent 工作流产出。

用户可以选择：

```text
用自己的 key 生成个人产出
→ 只自己使用
```

也可以选择：

```text
用自己的 key 生成高质量产出
→ 发布到 OnlyFourBot
→ 让其他用户或 Agent 订阅、引用、复用
```

这样 token 变成了社区创造资产的成本，而不是一次性消耗。

### 官方不应承担的模型成本

官方默认不应承担：

- 任意用户的私有摘要。
- 任意 URL 的实时总结。
- 每个订阅者的个性化日报。
- 私有报告全文分析。
- 私有账号追踪分析。
- 大规模 Agent 调用模型。

这些能力应由：

- 用户 BYOK。
- 用户本地模型。
- 用户自有 Agent。
- 付费额度。
- 企业私有部署。

来承担。

## 成本治理

OnlyFourBot 需要从第一天就考虑成本边界。

平台要支持用户共享、Agent 订阅、MCP / CLI / API 调用，但不能变成：

```text
公共免费代理
公共免费抓取器
公共免费 LLM 摘要服务
无限制 API 数据出口
```

成本治理目标：

1. 公共源尽量一次抓取，多人复用。
2. 公共摘要尽量一次生成，多人复用。
3. 私有个性化处理优先由用户 BYOK 承担。
4. Agent / API 调用必须限流和计量。
5. 高成本能力默认不开放或需要授权。
6. 防止爬虫、刷接口、批量导出、恶意订阅造成费用失控。

### 成本分类

OnlyFourBot 的主要成本来自：

- 抓取成本：HTTP 请求、Playwright、代理、反爬重试。
- 存储成本：原文、快照、diff、摘要、索引。
- LLM 成本：摘要、分类、风险审查、多源融合。
- 数据出口成本：API、MCP、CLI、大量列表分页、webhook。
- 数据库成本：搜索、排序、推荐、聚合统计。
- 风控成本：审核、检测、举报处理。

不同能力的成本等级不同：

| 能力 | 成本 | 默认策略 |
|---|---|---|
| 查询公开 source 元信息 | 低 | 可开放，强缓存 |
| 查询 collection 元信息 | 低 | 可开放，强缓存 |
| 查询已生成 digest | 低 | 可开放，强缓存 |
| 订阅公共 collection | 低 | 配额内开放 |
| 触发公共源刷新 | 中 | 不允许普通用户频繁触发 |
| 私有源抓取 | 中/高 | 用户本地 / BYOK / 配额承担 |
| Playwright / Agentic 抓取 | 高 | 严格配额，默认不公共开放 |
| LLM 个性化摘要 | 高 | 用户 BYOK 优先，平台付费额度次之 |
| 大规模 API 导出 | 高 | 限流，分页，可能付费 |
| Webhook 高频推送 | 中 | 合并推送，限速 |

### 公共缓存优先

OnlyFourBot 的核心成本优势来自公共缓存。

公共源处理流程应是：

```text
source_id
→ scheduled fetch
→ content fingerprint
→ normalize
→ public factual summary
→ cache
→ fan-out 给订阅者
```

不要让每个订阅者各自触发：

```text
fetch + clean + summarize
```

同一个 SourcePreset 的公共处理结果应按以下 key 复用：

```text
source_id
content_fingerprint
diff_fingerprint
summary_style
language
model
prompt_version
```

用户私有层只做轻量 overlay：

```text
公共事实摘要
→ 用户关键词过滤
→ 用户提醒规则
→ 必要时个性化解释
```

### 分层缓存

建议至少有四层缓存：

#### 1. Source Metadata Cache

缓存：

- source 列表。
- source 详情。
- health_score。
- trust_score。
- collection 列表。

策略：

- CDN / edge cache。
- TTL 5 - 30 分钟。
- `ETag` / `Last-Modified`。
- 支持 `If-None-Match`。

#### 2. Fetch Result Cache

缓存：

- feed 原始条目 fingerprint。
- 最近 N 条 normalized item。
- last_success_at。
- last_error。

策略：

- 按 source_id 缓存。
- 不同用户共享公共源抓取结果。
- 失败结果也短 TTL 缓存，避免雪崩重试。

#### 3. LLM Result Cache

缓存：

- 风险审查结果。
- 内容摘要。
- 多源融合结果。
- diff 解释。

策略：

- 按 fingerprint + prompt_version + model + language 缓存。
- 公共源摘要可多人复用。
- 私有源摘要不进入公共缓存。
- 低信源摘要不进入公共推荐缓存。

#### 4. API Response Cache

缓存：

- latest digest。
- collection digest。
- source health。
- public diff list。

策略：

- CDN / edge cache。
- 对 Agent / CLI / MCP 返回稳定分页 cursor。
- 支持 `since` 参数，避免重复拉全量。

### 配额体系

所有用户和 Agent 都应该有配额。

配额对象：

- user。
- app_instance。
- agent_client。
- api_key。
- IP / ASN。

建议配额维度：

```text
requests_per_minute
requests_per_day
llm_tokens_per_day
private_fetches_per_day
agentic_fetches_per_day
webhook_events_per_day
publish_attempts_per_day
exports_per_day
```

免费层应主要支持：

- 浏览公开源。
- 订阅少量 collection。
- 读取公共 digest。
- 少量私有源。

高成本能力应限制：

- Playwright 抓取。
- 大量私有源。
- 高频 webhook。
- 个性化 LLM 摘要。
- 大规模 API / MCP 拉取。

### Rate Limit 分层

建议按 trust / plan / client_type 分层。

示例：

```text
anonymous
free_user
verified_user
trusted_user
agent_readonly
agent_write
paid_user
maintainer
admin
```

匿名访问：

- 只能看公开 landing、少量 source 元信息。
- 强缓存。
- 严格限流。

登录用户：

- 可订阅公共 collection。
- 可读公共 digest。
- 有基础 API 配额。

Agent / API client：

- 必须使用 API key 或 signed request。
- 必须声明 scope。
- 独立限流。
- 默认 read-only。

高信用 / 付费用户：

- 更高 API 配额。
- 更多私有源。
- 更多个性化摘要。
- 更高 webhook 限额。

### 防止平台变成免费抓取代理

普通用户和 Agent 不应随意触发任意 URL 抓取。

应禁止：

```text
POST /fetch?url=任意URL
```

替代方式：

```text
提交 SourcePreset
→ 审核 / health check
→ 进入调度
→ 结果缓存
```

也就是说，OnlyFourBot 提供的是：

```text
可治理的信息源网络
```

不是：

```text
任意 URL 抓取 API
```

### 调度策略

公共源抓取必须由调度器控制。

调度频率应由以下因素决定：

- source importance。
- update_frequency。
- subscriber_count。
- health_score。
- cost_score。
- 最近是否有新内容。
- 是否高风险领域。

示例：

```text
高重要 + 高订阅 + 稳定源：更频繁
低订阅 + 高噪音 + 不稳定源：更少
长期无更新源：自动降频
连续失败源：指数退避
```

不要让每个订阅者触发独立刷新。

### 结果 Fan-out，而不是重复处理

正确流程：

```text
公共源更新一次
→ 生成公共结果
→ 通知所有订阅者
```

错误流程：

```text
每个订阅者各自刷新
→ 每个订阅者各自摘要
→ 成本线性增长
```

Webhook 也应合并：

- digest batch。
- hourly summary。
- daily summary。
- importance threshold。

避免每条小更新都推送。

### Agent 订阅的成本控制

Agent 很容易造成高频轮询。

因此 Agent / MCP / CLI 应优先使用：

- cursor。
- `since`。
- ETag。
- webhook。
- batch endpoint。
- digest endpoint。

避免：

- 高频 list all。
- 高频全文拉取。
- 对每个 source 单独请求。

MCP tools 应设计成高层能力：

```text
get_latest_digest(collection_id)
get_updates_since(collection_id, cursor)
search_sources(query)
```

不建议暴露高成本低层能力：

```text
fetch_url(url)
summarize_url(url)
refresh_source_now(source_id)
```

这些能力如果存在，也应需要高权限 scope 和严格配额。

### 数据出口控制

公共数据也不能无限导出。

建议：

- 所有列表分页。
- 最大 page size。
- cursor 过期。
- 禁止匿名批量导出。
- 大规模导出需要异步任务和配额。
- API 返回摘要优先，全文按需。
- 私有内容不允许公共 API 导出。

### 存储成本控制

不要永久保存所有原文和快照。

建议：

- 保存 normalized item 元信息。
- 公共摘要长期保存。
- 原始 HTML 短期保存。
- 页面 diff 快照按重要度保留。
- 低价值源保留期更短。
- 高频源只保留最近 N 条。

按数据类型设置 TTL：

| 数据 | 建议保留 |
|---|---|
| Source metadata | 长期 |
| Public digest | 长期 |
| Normalized item metadata | 中长期 |
| Raw feed payload | 短期 |
| Raw HTML snapshot | 短期 |
| Page diff snapshot | 按重要度 |
| Failed fetch log | 短期 |
| API request log | 按合规需要 |

### LLM 成本控制

LLM 是高成本项。

建议策略：

- MajorRSS 默认 BYOK。
- 先规则过滤，再 LLM。
- 先轻模型分类，再重模型总结。
- 多条内容 batch。
- 公共摘要缓存。
- 低信源不做重摘要。
- 低价值内容不做多语言摘要。
- 用户私有个性化摘要使用用户自己的 API key。
- 官方 digest 优先轻量模型，高推理模型低频使用。

推荐流水线：

```text
rule filter
→ cheap classifier
→ dedupe / cluster
→ only high-signal batch to LLM
→ cache result
```

不要：

```text
每条新内容都直接大模型总结
```

### 成本可视化

为了让共享 token 的理念变成用户可感知价值，应该显示：

- 本次复用公共摘要，节省多少 token。
- 该 collection 本周为社区节省多少 token。
- 该 source 的公共缓存命中率。
- 用户私有处理消耗了多少 token。
- 哪些私有源成本最高。
- 某个官方 digest 被多少用户或 Agent 复用。
- 某个 collection 产生了多少二次订阅和二次创作。

示例：

```text
This digest reused 18 public summaries and saved an estimated 42,000 tokens.
```

也可以显示更符合社区理念的指标：

```text
This collection powered 128 personal digests and 24 agent workflows this week.
```

这能表达：

```text
一次创建
多次复用
持续产生价值
```

### 滥用检测

需要监控：

- 高频匿名访问。
- 高频 Agent 轮询。
- 大量订阅后立即导出。
- 大量创建私有源。
- 大量触发刷新。
- 高频 webhook 失败重试。
- 低信用用户批量发布。
- 同 IP / ASN 批量注册。

异常处理：

- 降速。
- 要求登录。
- 要求验证邮箱 / passkey。
- 暂停 API key。
- 降低 trust level。
- 进入人工审核。
- block IP / ASN。

### 商业化与成本边界

可以考虑按能力分层，而不是简单按访问收费。

商业化不应围绕“平台替用户支付 token”展开。

更合理的是围绕：

- 可信源网络。
- 官方 digest。
- API / MCP / CLI 稳定访问。
- 团队协作。
- 历史检索。
- 高级 collection。
- 合规授权内容。
- 企业私有部署。

免费层：

- 订阅少量公共 collection。
- 读取公共 digest。
- 少量私有源。
- 低频 API。

个人付费层：

- 更多私有源。
- 更多个性化摘要。
- 更多 webhook。
- 更高 API rate limit。
- 更多历史保留。

团队层：

- 共享 team collection。
- 更高 token 配额。
- Webhook / API 集成。
- 私有 collection。
- 审计日志。

Agent / Developer 层：

- MCP / CLI / REST API 高配额。
- webhook。
- batch endpoints。
- signed request。
- usage dashboard。

核心原则：

```text
公共源共享降低边际成本
私有高成本能力由使用者 BYOK 或配额承担
Agent / API 访问必须计量
```

### 商业价值来源

OnlyFourBot 的商业价值不应建立在“倒卖 token”或“转卖未授权内容”上。

更稳妥的价值来源：

#### 1. 可信源网络

高质量 SourcePreset、SourceCollection、健康度、噪音率、信用评分，本身就是资产。

用户和 Agent 需要的不是更多 URL，而是：

```text
哪些源值得订阅
哪些源噪音低
哪些源已经被社区验证
哪些 collection 适合当前任务
```

#### 2. 官方摘要日报

官方可以发布：

- AI 日报。
- 金融政策日报。
- 技术 changelog 日报。
- 高价值论文速览。
- 重要页面 diff 摘要。

低需求用户可以直接消费这些公共产出。

#### 3. Agent / API 服务

高需求用户、开发者、小团队可能愿意为以下能力付费：

- 稳定 MCP。
- REST API。
- CLI。
- Webhook。
- Batch digest。
- 历史查询。
- 高配额。
- signed request。
- usage dashboard。

#### 4. 团队信息流

团队可以订阅共享源和 collection，并生成内部日报、竞品监控、技术雷达、政策雷达。

可付费能力：

- Team collection。
- 私有 collection。
- 成员权限。
- 审计日志。
- 团队 digest。
- 企业私有源。

#### 5. 授权内容合作

如果未来接入机构报告、研究分析、付费数据，应该通过授权合作，而不是购买后再分发。

可以探索：

- 与机构签 license。
- 只分发被授权摘要。
- 只提供购买入口和元信息。
- 对授权内容单独计费。
- 企业客户接入自己的内容权限。

## 高价值内容与版权边界

真正值得收费的内容可能包括：

- 机构报告。
- 研究分析。
- 高价值论文。
- 金融研报。
- 行业数据库。
- 专家评论。

但这些内容通常版权和许可最严格。

平台必须默认假设：

```text
购买访问权
不等于获得再分发权
```

也就是说，用户或官方购买了一份报告，并不自动拥有把报告分享给订阅用户的权利。

### 高风险行为

OnlyFourBot 不应允许：

- 上传购买的报告 PDF 给订阅用户下载。
- 转发报告全文。
- 大段摘录付费报告。
- 复制核心图表、表格、模型和数据。
- 把付费报告摘要到足以替代原文的程度。
- 用“订阅即可查看某机构付费报告精华”作为卖点。
- 批量抓取付费研报再包装成订阅内容。

这些行为可能侵犯：

- 复制权。
- 分发权。
- 改编权。
- 合同许可条款。
- 数据库或平台使用条款。

### 相对稳妥的行为

可以考虑：

- 分享报告元信息。
- 分享标题、机构、发布时间、原始链接。
- 分享是否值得阅读的评价。
- 分享用户自己的原创观点。
- 分享基于多个公开来源的交叉分析。
- 少量、必要、带来源的短引用。
- 引导用户到原始购买 / 阅读入口。

原则：

```text
帮助发现报告
不替代报告本身
```

### 内容权利字段

SourcePreset / Digest / ReportReference 应增加内容权利字段。

示例：

```json
{
  "content_rights": {
    "access_type": "paid_report",
    "redistribution_allowed": false,
    "summary_allowed": "limited_commentary_only",
    "quote_allowed": "short_excerpt",
    "source_link_required": true,
    "license_url": "https://example.com/terms",
    "risk_level": "high"
  }
}
```

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

### 合规商业化路径

更稳妥的商业化方向：

#### 1. 报告发现与索引

用户付费购买的是：

```text
哪些报告值得看
为什么值得看
在哪里购买或阅读
```

而不是购买报告内容本身。

#### 2. 原创分析

平台或社区基于公开来源、个人判断、多源交叉验证写原创分析。

注意：

```text
原创分析不能复刻付费报告的结构、表达和核心商业内容
```

#### 3. 授权合作

和报告机构、研究机构、媒体、数据库服务谈授权。

明确：

- 是否可摘要。
- 是否可引用。
- 是否可再分发。
- 是否可训练 / 缓存。
- 是否可展示给订阅用户。
- 收费分成。

#### 4. BYO Content

用户自己拥有访问权的报告，可以在 MajorRSS 本地或私有空间处理。

原则：

```text
用户自己的内容
用户自己的 key
用户自己的私有空间
不进入公共共享层
```

#### 5. 企业内部版本

企业使用自己的研报权限和内部模型处理。

OnlyFourBot / MajorRSS 提供：

- 工具。
- pipeline。
- 权限控制。
- 审计。
- 私有部署。

不拿企业内容进入公共库。

### 稳妥边界

```text
可以买报告学习
可以写自己的观点
可以告诉用户报告存在并链接原文
不能把报告内容当成订阅商品再分发
```

高价值内容的商业价值应来自：

```text
发现能力
筛选能力
原创分析
交叉验证
工作流工具
授权合作
企业私有部署
```

而不是：

```text
买一份报告
转述或摘要后卖给所有订阅用户
```

## 发布权限层级

建议 trust level：

```text
L0 new
L1 verified
L2 trusted
L3 maintainer
L4 admin
```

### L0 new

- 可以订阅。
- 可以创建私有源。
- 发布公共源需要审核。

### L1 verified

- 可发布低风险公开 RSS。
- collection 需要审核或延迟发布。

### L2 trusted

- 可自动发布多数公开源。
- 可维护 collection。
- 触发异常时回退审核。

### L3 maintainer

- 可维护官方 / 社区高质量 collection。
- 可处理举报。
- 可标记源 deprecated。

### L4 admin

- 平台治理。
- 全局 blocklist。
- 信用体系调整。

## MajorRSS 与 OnlyFourBot 的关系

MajorRSS：

- 本地桌面应用。
- 用户私有任务。
- 本地 AuthProfile。
- 私有抓取。
- 私有 prompt。
- 私有阅读状态。
- 用户自己的 Agent 处理入口。

OnlyFourBot：

- 公共源共享。
- 公共 collection。
- 公共摘要缓存。
- 官方摘要日报。
- 订阅网络。
- Agent / MCP / CLI / API 扩展。
- 信用体系和治理。
- 社区创建沉淀。

边界：

```text
私有凭证永远留在 MajorRSS
公开源元信息可以进入 OnlyFourBot
公共摘要只基于公开可信源
用户私有 overlay 不进入公共缓存
用户和 Agent 可以在公共源基础上继续创造自己的产出
```

## MVP 建议

### Phase 1：只允许 MajorRSS 发布

- MajorRSS 生成 AppInstance keypair。
- OnlyFourBot 注册公钥。
- SourcePreset 发布请求必须签名。
- 支持 pending / published / rejected。
- 支持基础 health check。

### Phase 2：用户订阅与 collection

- 支持订阅 SourcePreset。
- 支持订阅 SourceCollection。
- 支持订阅数统计。
- 支持用户反馈 useful / noisy / broken。

### Phase 3：信用体系

- User trust。
- Source trust。
- Collection trust。
- 基础举报和 quarantine。

### Phase 4：MCP / CLI / API

- 先开放 read-only。
- 支持 search / list / latest digest。
- 订阅能力需要 scope。
- 发布能力暂不开放给 Agent。

### Phase 5：共享 token 缓存

- 公共源公共抓取。
- 公共摘要缓存。
- 复用统计。
- token saved 可视化。

### Phase 6：社区创建与二次产出

- 用户发布 collection。
- 用户订阅 collection 后生成自己的 digest。
- Agent 订阅 collection 后生成自己的工作流产出。
- 官方 digest 作为默认公共视图。
- 展示 collection 被多少用户 / Agent 复用。
- 展示公共源产生了多少二次产出。

## 最终定位

OnlyFourBot 应该是：

```text
由 MajorRSS 客户端产生的可信关注源网络
支持用户和 Agent 订阅
通过信用体系防止污染
通过公共缓存减少重复 token 消耗
通过 MCP / CLI / API 成为可扩展的信息基础设施
让关注源和 AI 产出持续复用，而不是用完即丢
```
