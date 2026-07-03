# MajorRSS / OnlyFourBot 安全与共享边界改造计划

> 创建时间：2026-06-22
>
> 目的：明确 MajorRSS 的本地授权能力与 OnlyFourBot 的公共共享能力边界，降低平台投诉、版权、隐私、凭证泄露和被误解为公共抓取代理的风险。

## 核心结论

MajorRSS 可以在用户本机处理用户有权访问的内容。

OnlyFourBot 只能共享公开来源的短摘要、来源元信息、内容指纹、source pack、source health 和公共 digest。

不能共享：

- Cookie。
- Authorization header。
- API key。
- 登录后页面原文。
- 付费报告正文。
- 用户私有 prompt。
- 用户私有过滤结果。
- 可替代原文阅读的长摘要。

推荐产品表述：

```text
MajorRSS 是本地优先的个人信息雷达。
OnlyFourBot 是公开可信来源和公共摘要的复用网络。
共享的是公开来源处理成果，不是私有权限、凭证或未授权内容。
```

## Phase 1：产品叙事与文案收敛

目标：把产品从“爬虫 / 绕过平台限制”的心智，调整为“本地授权阅读 + 公开来源摘要复用”。

需要移除或避免的表述：

```text
bypass anti-bot
绕过反爬
越权抓取
穿透
破解限制
批量抓取登录内容
```

推荐替代表述：

```text
本地授权阅读
用户本人可访问内容
仅本机处理
公开来源摘要
来源链接回流原站
公开可信来源复用
公共摘要缓存
```

需要同步修改的位置：

- README。
- AuthProfile 设置页。
- Tracker / Subscription 表单。
- UI 翻译文案。
- 开发者文档中关于 Playwright / Cookie 的描述。

建议明确写入产品说明：

```text
Cookie/AuthProfile 只用于用户本机授权阅读。
MajorRSS 不上传 Cookie，不共享登录后内容。
OnlyFourBot 只接收公开来源的短摘要、来源元信息和内容指纹。
```

## Phase 2：Source Rights Policy

目标：每个来源先分类，再决定能不能抓取、摘要、缓存和共享。

建议增加来源权利字段：

```text
access_type:
  official_feed
  public_web
  open_access
  third_party_generated
  generated_by_majorss
  login_required
  paid_report
  user_private_content
  unknown_rights

sharing_level:
  public_cache_allowed
  metadata_only
  local_only
  blocked

summary_level:
  public_short_summary
  limited_commentary
  private_summary_only
  no_summary
```

默认规则：

| access_type | sharing_level | summary_level | 说明 |
|---|---|---|---|
| official_feed | public_cache_allowed | public_short_summary | 官方 RSS / Atom，可进入公共短摘要缓存 |
| public_web | public_cache_allowed | public_short_summary | 公开网页，可短摘要并强制带来源链接 |
| open_access | public_cache_allowed | public_short_summary | 开放访问内容，可短摘要 |
| third_party_generated | public_cache_allowed | public_short_summary | 必须标注 unofficial / third-party generated |
| generated_by_majorss | public_cache_allowed | public_short_summary | 必须标注 generated_by_majorss，不伪装官方 RSS |
| login_required | local_only | private_summary_only | 登录态来源只能本地处理 |
| paid_report | metadata_only | limited_commentary | 默认只允许元信息和有限原创评论 |
| user_private_content | local_only | private_summary_only | 用户私有内容不能进入公共层 |
| unknown_rights | metadata_only | no_summary | 权利不明时默认不生成公共摘要 |

硬规则：

```text
requires_auth = true
→ local_only

auth_profile_id exists
→ local_only

access_type in [login_required, user_private_content]
→ 不允许发布到 OnlyFourBot

access_type in [paid_report, unknown_rights]
→ 不进入公共摘要缓存
```

## Phase 3：AuthProfile 本地硬隔离

目标：把“Cookie 只能本地”从设计约定变成代码硬规则。

当前正确方向：

- AuthProfile 登录在用户本机 Playwright 浏览器中完成。
- 数据库只保存 `storage_ref`。
- Windows 下使用 DPAPI 加密 storage state。
- 抓取时只在本地进程内读取和解密。

需要补强：

1. API 响应不要暴露 `storage_ref`。

```text
/auth/profiles/
→ 只返回 id、platform、display_name、status、last_checked_at、created_at
→ 不返回 storage_ref
```

2. 前端不显示 `storage_ref`。

3. 隐藏或移除 deprecated `cookie_string` 输入。

4. 所有带 `auth_profile_id` 的任务自动标记：

```text
access_type = login_required
sharing_level = local_only
summary_level = private_summary_only
```

5. 发布 payload 中如出现以下字段，直接拒绝：

```text
auth_profile_id
storage_ref
cookie_string
Cookie
Authorization
Set-Cookie
local file path
private prompt
```

## Phase 4：上传前信息脱敏层

目标：AI 摘要进入公共社区前，必须做隐私和敏感信息检查。

扫描阶段：

```text
抓取后 / 入库前
LLM 输入前
OnlyFourBot 发布前
```

检测范围：

- 手机号。
- 邮箱。
- 身份证 / 护照。
- 银行卡 / 金融账户。
- 地址。
- 精确位置。
- 医疗健康信息。
- 未成年人信息。
- 私信 / 聊天记录。
- 账号后台信息。
- Cookie / token / API key。
- Authorization header。
- 用户私有标签。
- 用户私有 prompt。
- 本地文件路径。

建议输出：

```text
privacy_level:
  none
  personal
  sensitive
  blocked
```

处理规则：

| privacy_level | 处理方式 |
|---|---|
| none | 可进入公共发布流程 |
| personal | 脱敏后才可进入公共发布流程 |
| sensitive | 默认 metadata_only，不进入公共摘要缓存 |
| blocked | 不上传，只保留本地 |

示例：

```text
邮箱、手机号
→ 可以替换为 [REDACTED_EMAIL] / [REDACTED_PHONE]

Cookie、token、Authorization
→ 必须阻断上传

私信、登录后页面、医疗金融敏感数据
→ local_only 或 blocked
```

## Phase 5：公共摘要格式限制

目标：避免公共摘要被平台或版权方认定为原文替代品。

OnlyFourBot 可接受的公共摘要结构：

```text
title
source_url
published_at
source_id
content_fingerprint
summary_bullets: 3-5 条短要点
trust_label
risk_label
```

限制：

- 不上传全文。
- 不上传原始 HTML。
- 不上传长段摘录。
- 不复制图表、表格、研报核心模型。
- 不复刻文章结构。
- 摘要必须带来源链接。
- 摘要必须鼓励用户回到原站阅读全文。
- 对媒体、研报、付费内容只允许 `metadata_only` 或 `limited_commentary`。

建议阈值：

```text
public_summary_max_chars = 300-500 中文字
quote_max_chars = 120 中文字
must_include_source_link = true
```

公共摘要应该是：

```text
帮助发现内容
帮助判断是否值得阅读
帮助快速理解公开事实
```

不应该是：

```text
替代原文阅读
复刻付费内容
复制核心表达
提供未授权内容再分发
```

## Phase 6：OnlyFourBot 发布闸门

目标：OnlyFourBot 不是任意 URL 抓取 API，而是受治理的公共源网络。

发布流程：

```text
用户在 MajorRSS 创建来源
→ 用户显式点击发布
→ 客户端剥离私有字段
→ Source Rights Policy 判断
→ Privacy Filter 扫描
→ 摘要替代性检查
→ 客户端签名
→ OnlyFourBot 服务端复查
→ pending / experimental / listed / verified / rejected
```

拒绝规则：

```text
requires_auth = true
auth_profile_id exists
access_type = login_required
access_type = user_private_content
access_type = paid_report 且无授权
privacy_level = sensitive
privacy_level = blocked
summary too long
missing source link
payload contains cookie/token/header
```

状态建议：

```text
private
pending
experimental
listed
verified
quarantined
rejected
blocked
deprecated
```

普通用户或 Agent 不应拥有：

```text
POST /fetch?url=任意URL
POST /summarize?url=任意URL
POST /refresh-source-now 高频调用
```

替代方式：

```text
提交 SourcePreset
→ 审核 / health check
→ 进入调度
→ 结果缓存
→ fan-out 给订阅者
```

## Phase 7：测试与审计

目标：防止后续代码改动破坏本地 / 公共边界。

必须测试：

1. AuthProfile API 不返回 Cookie。
2. AuthProfile API 不返回 `storage_ref`。
3. 带 `auth_profile_id` 的来源无法发布到 OnlyFourBot。
4. 登录态来源无法进入 public cache。
5. 发布 payload 中出现 cookie/token/header 会被拒绝。
6. 公共摘要上传前会脱敏手机号、邮箱、token。
7. `paid_report` 默认不能生成公共摘要。
8. `unknown_rights` 默认不能生成公共摘要。
9. `user_private_content` 只能 local_only。
10. public digest 可以追踪来源 URL、source_id、fingerprint。
11. 删除或下架 source 后，相关公共摘要缓存可以撤回或 quarantine。

审计记录建议：

```text
source_id
publisher_user_id
app_instance_id
signature
access_type
sharing_level
summary_level
privacy_level
content_fingerprint
created_at
review_status
review_reason
```

## 推荐落地顺序

1. 修改 README / UI / 翻译文案，降低外部误解风险。
2. 增加 Source Rights Policy，作为共享前核心闸门。
3. 收紧 AuthProfile API 输出，隐藏 `storage_ref`。
4. 移除 raw `cookie_string` 输入路径。
5. 增加 Privacy Filter。
6. 增加公共摘要长度和结构限制。
7. 实现 OnlyFourBot 发布闸门。
8. 增加测试和审计日志。

## 一句话边界

```text
MajorRSS 可以本地处理用户授权内容；
OnlyFourBot 只能共享公开来源的短摘要、元信息、fingerprint 和 source pack。
```

