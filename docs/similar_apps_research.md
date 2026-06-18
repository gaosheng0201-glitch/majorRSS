# MajorRSS 同类型应用研究与产品差异

> 创建时间：2026-06-10
>
> 本文用于记录同类型开源项目、可借鉴能力、避免重复造轮子的边界，以及 MajorRSS / OnlyFouBot 的差异化方向。

## 结论

MajorRSS 不应该被定位成另一个传统 RSS Reader。

已有开源项目已经很好地覆盖了这些基础能力：

- RSS 阅读和订阅管理。
- RSSHub / RSS-Bridge 式站点转 RSS。
- 页面变化检测。
- 自动化 Agent 工作流。
- AI RSS 阅读器。

MajorRSS 更应该定位成：

```text
多源信息获取
→ 去重 / 降噪 / 变化检测
→ AI 判断重要性
→ 生成用户真正需要看的信息雷达
→ 支持用户之间共享关注源与处理结果，减少重复 token 消耗
```

核心差异不只是技术栈，而是产品理念：

1. 消除噪音。
2. 共享关注内容与共享 token 成本。

## 同类项目分层

### 1. RSS / Feed 基础设施

#### Miniflux

项目地址：

- https://github.com/miniflux/v2

定位：

- 极简、自托管 Feed Reader。
- Go + PostgreSQL。
- 后台调度更新 feed。
- 支持 RSS / Atom / JSON Feed。
- 支持全文搜索、Readability 抽取、CSS selector scraper、正则 include / exclude、cookies、proxy、custom user-agent。

值得学习：

- Feed polling 的工程纪律。
- ETag / Last-Modified / Cache-Control 等增量抓取策略。
- Postgres-first 的数据模型。
- 外部内容渲染前的安全清洗。
- 去 tracking 参数、移除 pixel tracker、media proxy 等隐私设计。

不适合直接照搬：

- 它仍然是阅读器，不是情报雷达。
- 它不会主动做跨源聚合、实体合并、AI 重要性判断。

对 MajorRSS 的启发：

```text
Feed 抓取层要学习 Miniflux
产品体验不能停留在 Miniflux
```

#### FreshRSS

项目地址：

- https://github.com/FreshRSS/FreshRSS

定位：

- 自托管 RSS 聚合器。
- 支持多用户、标签、API、CLI、WebSub、基础 XPath scraping、扩展系统。

值得学习：

- 多用户订阅管理。
- OPML 导入导出。
- API / CLI 能力。
- WebSub 推送。
- 扩展系统。

不适合直接照搬：

- PHP 技术栈不适合作为当前桌面应用主体。
- 产品仍偏传统 RSS 聚合。

对 MajorRSS 的启发：

```text
多用户订阅、OPML、API、扩展系统值得参考
但核心体验仍需围绕“雷达”和“降噪”重做
```

### 2. 站点转 RSS / 数据源路由

#### RSSHub

项目地址：

- https://github.com/DIYgod/RSSHub

定位：

- 将大量网站、社交平台、媒体源转换为 RSS。
- 中文生态覆盖强。
- 当前 MajorRSS 已经使用。

值得学习 / 继续使用：

- route 生态。
- 平台适配经验。
- 中文互联网源覆盖。
- RSSHub route 可以作为 MajorRSS 的低成本抓取入口。

局限：

- route 可用性依赖维护状态。
- 部分平台会封锁、反爬、改版。
- 默认不等于高质量信息。
- RSSHub 负责“取到”，不负责“判断是否值得看”。

对 MajorRSS 的定位：

```text
RSSHub 是数据源能力，不是产品核心
```

MajorRSS 应该把 RSSHub 放在 resolver / adapter 层，而不是让用户感知复杂 route。

#### RSS-Bridge

项目地址：

- https://github.com/RSS-Bridge/rss-bridge

定位：

- 给没有 RSS 的网站生成 feed。
- PHP Web 应用。
- 支持多种 Bridge。
- 有 `CssSelectorBridge`、`FeedMergeBridge`、`FeedReducerBridge`、`FilterBridge` 等。

值得学习：

- 用 CSS selector 构建 feed。
- feed 合并。
- feed 降噪。
- keyword include / exclude 过滤。
- route 缓存，避免频繁请求导致封禁。

局限：

- 中文生态通常不如 RSSHub。
- 技术栈不适合作为当前主工程依赖。

对 MajorRSS 的启发：

```text
RSSHub 优先
RSS-Bridge 可作为补充源和设计参考
```

### 3. 页面变化检测 / Diff

#### changedetection.io

项目地址：

- https://github.com/dgtlmoon/changedetection.io

定位：

- 页面变化检测和通知工具。
- 支持 HTML、JSON、PDF。
- 支持 CSS selector、XPath、JSONPath、jq。
- 支持关键词触发、忽略文本、提取文本。
- 支持快速非 JS fetcher，也支持 WebDriver / Playwright / Chrome。
- 支持截图、代理、请求头、自定义方法、执行 JS。

这是 PAGE_DIFF 方向最值得学习的项目。

值得学习：

- Watch 的数据模型。
- selector-based diff。
- ignore text / remove text by selector。
- JSONPath / jq 对结构化 API 的 diff。
- Playwright fetcher 作为高阶 fallback。
- 按 watch 配置检查频率。
- 变化通知和快照保存。

对 MajorRSS 的启发：

```text
PAGE_DIFF 不应混在 Tracker 里
它应该是 Subscription / Monitor 的独立能力
```

MajorRSS 的页面 diff 应重点做：

- 正文区域识别。
- 广告、导航、推荐位、时间戳清洗。
- DOM 结构变化和文本变化分离。
- 只把有效变化送进 LLM。
- 对 API docs、公告页、政策页、价格页、GitHub release 页等场景做模板。

### 4. 自动化 Agent / 工作流

#### Huginn

项目地址：

- https://github.com/huginn/huginn

定位：

- 自托管自动化 Agent 平台。
- 类似自建版 IFTTT / Zapier。
- Agent 可以读取网页、监听事件、抓 RSS、监控关键词、调用 Webhook、发送通知。
- 支持 Twitter / Weibo / RSS / Bash / Slack 等集成。
- 支持 Agent 之间用事件图连接。

值得学习：

- Agent 事件流模型。
- source agent / transform agent / notify agent 分层。
- 可组合工作流。
- 自托管数据控制理念。
- 定时任务和事件传播。

不适合直接照搬：

- UI 和配置门槛高。
- 更适合工程用户，不适合普通信息消费用户。
- 用户需要理解 Agent 图，MajorRSS 不应该强迫用户理解这些。

对 MajorRSS 的启发：

```text
内部可以像 Huginn 一样有 pipeline / agent
外部 UI 应该是“创建关注任务”，而不是“搭建工作流图”
```

### 5. AI RSS Reader / 现代阅读器

#### Folo / RSSNext

项目地址：

- https://github.com/RSSNext/Folo

定位：

- AI RSS Reader。
- 支持 Web、iOS、Android、macOS、Windows、Linux。
- 强调 noise-free timeline。
- 支持 AI 翻译、摘要等能力。
- 关联 RSSHub 生态。

这是最接近 MajorRSS “现代信息消费体验”的同类项目。

值得学习：

- 跨平台桌面 / 移动布局。
- 时间线组织。
- AI 摘要和翻译体验。
- RSSHub 生态整合。
- 内容类型支持：文章、视频、图片、音频。
- 社区 / collection / shared list 方向。

需要注意：

- AGPL-3.0 许可证，不适合直接复制代码进闭源或不兼容项目。
- 它更偏 AI Reader，不是完整的信息探测管线。
- 它不等于“关键词全网探测 + 账号追踪 + 页面 diff + 授权抓取 + 共享 token 成本”。

对 MajorRSS 的启发：

```text
Folo 是体验和市场定位的重要参考
但 MajorRSS 应更强调任务化探测、降噪、共享 token 成本
```

## MajorRSS 的差异化

### 1. 消除噪音是第一原则

传统 RSS Reader 的问题：

- 把所有更新都推给用户。
- 用户需要自己判断哪些值得看。
- 订阅越多，噪音越大。
- AI 摘要如果直接作用在所有内容上，会放大 token 成本。

MajorRSS 的目标不是“抓更多”，而是“让用户少看无效内容”。

核心原则：

```text
先降噪
再送入 LLM
再生成报告
```

应优先在 LLM 之前完成：

- URL 去重。
- 标题相似度去重。
- 来源可信度判断。
- 时间窗口过滤。
- 关键词基础匹配。
- DOM 噪音清洗。
- 广告 / 推荐 / 导航去除。
- 同事件多来源合并。

LLM 的职责不是替代全部过滤，而是处理：

- 语义相关性。
- 事件重要性。
- 影响判断。
- 多源融合。
- 用户关注点解释。

### 2. 共享 token 是产品网络效应

MajorRSS / OnlyFouBot 的关键理念：

```text
同一个信息源、同一个事件、同一个页面变化
不应该被每个用户重复抓取、重复清洗、重复消耗 token
```

如果 100 个用户都关注 OpenAI API docs：

- 不应该 100 次抓取。
- 不应该 100 次 diff。
- 不应该 100 次 LLM 总结。

更合理的方式是：

```text
共享关注源
→ 公共抓取任务
→ 公共去重 / diff / 摘要结果
→ 用户只订阅自己关心的视图
```

这正是 OnlyFouBot 域名可以承载的方向：

- 用户分享自己关注的源。
- 其他用户可以订阅这些源集合。
- 热门源由系统统一抓取和处理。
- AI 结果可以缓存和复用。
- 用户只为个性化过滤、私有源、私有账号授权、私有总结偏好消耗额外 token。

### 3. OnlyFouBot 的可能定位

OnlyFouBot 可以不是一个普通 bot，而是：

```text
关注源共享网络
```

可能的核心对象：

- Shared Source：共享源，例如 OpenAI Blog、Anthropic News、某 GitHub repo releases。
- Shared Collection：共享关注包，例如“AI Infra Radar”、“Crypto Regulation Watch”、“Semiconductor Supply Chain”。
- Shared Digest：共享摘要，例如每日 AI 模型更新摘要。
- Shared Diff：共享页面变化，例如 OpenAI API docs 更新。
- Private Overlay：用户自己的关键词、阈值、提醒渠道、私有账号授权。

公共层：

```text
公开源抓取
公开页面 diff
公开 RSS / RSSHub route
公共摘要缓存
公共事件聚类
```

私有层：

```text
用户 cookie / AuthProfile
私有账号跟踪
私有关键词
私有 prompt
私有通知规则
私有阅读状态
```

这样可以避免把共享能力和敏感凭证混在一起。

## 和同类项目的差异矩阵

| 能力 | RSS Reader | RSSHub / RSS-Bridge | changedetection.io | Huginn | Folo | MajorRSS / OnlyFouBot |
|---|---|---|---|---|---|---|
| RSS 阅读 | 强 | 中 | 弱 | 中 | 强 | 中 |
| 站点转 RSS | 弱 | 强 | 弱 | 中 | 强依赖生态 | 强依赖生态 |
| 关键词探测 | 弱 | 中 | 中 | 强 | 中 | 强 |
| 账号追踪 | 弱 | 中 | 弱 | 中 | 中 | 强 |
| 页面 Diff | 弱 | 弱 | 强 | 中 | 弱 | 强 |
| Cookie 授权抓取 | 弱 | 部分 | 中 | 中 | 不确定 | 强，但应受控 |
| AI 摘要 | 弱 | 无 | 弱 | 可扩展 | 强 | 强 |
| 降噪优先 | 弱 | 弱 | 中 | 取决于配置 | 中 | 强 |
| 共享 token 成本 | 无 | 无 | 无 | 无 | 可能有社区源 | 核心差异 |
| 普通用户桌面体验 | 中 | 无 | 中 | 弱 | 强 | 目标为强 |

## 对当前 MajorRSS 重构的建议

### 不要重复造的轮子

1. 不要自己从零设计 RSS 协议处理。
   - 学 Miniflux。
   - 使用成熟 feedparser / HTTP cache / ETag / Last-Modified。

2. 不要自己从零设计页面 diff 全部能力。
   - 学 changedetection.io。
   - 优先做 selector、ignore、extract、snapshot、diff history。

3. 不要自己维护所有站点 route。
   - RSSHub 优先。
   - RSS-Bridge 补充。
   - 自写 adapter 只覆盖核心高价值站点。

4. 不要把 Agent 图暴露给普通用户。
   - 内部可以 pipeline 化。
   - UI 只暴露任务类型：RSS、关键词、账号、页面监控、混合模式。

### MajorRSS 应该重点做的轮子

1. Source Resolver
   - 把用户输入转成具体抓取路线。
   - 支持 route test。
   - 支持 fallback。
   - 支持 public route 和 private auth route 分离。

2. Noise Filter
   - LLM 前过滤。
   - 同源去重。
   - 跨源事件聚类。
   - 低价值内容压制。

3. Shared Token Cache
   - 相同 URL / 内容 fingerprint / diff fingerprint 只处理一次。
   - LLM 结果按 prompt version、model、language、user intent 缓存。
   - 公共源公共处理，私有源私有处理。

4. Shared Collection
   - 用户可以发布关注包。
   - 其他用户可以订阅关注包。
   - 关注包有源列表、默认关键词、默认过滤策略、摘要模板。

5. Trust / Quality Layer
   - 共享源需要健康度。
   - route 成功率。
   - 噪音率。
   - 最近更新时间。
   - token 节省估算。

## 产品形态建议

### 桌面端 MajorRSS

负责：

- 用户自己的任务管理。
- 本地授权凭证。
- 私有数据源。
- 本地阅读和审计。
- 个人雷达面板。

不负责：

- 大规模公共源重复抓取。
- 大规模共享摘要计算。

### OnlyFouBot / 云端共享层

负责：

- 共享关注源。
- 共享 collection。
- 公共抓取和公共摘要缓存。
- 热门源统一处理。
- 用户互相订阅。
- 降低重复 token 消耗。

不负责：

- 保存用户私有 cookie。
- 未经授权抓私有账号。
- 替用户执行高风险浏览器操作。

## 后续可验证问题

1. 用户是否愿意订阅别人整理的关注包？
2. 一个共享源的 AI 摘要能否满足不同用户？
3. 共享摘要需要多少个版本？
   - 中文 / 英文。
   - 简报 / 详细。
   - 技术 / 投资 / 产品视角。
4. 哪些内容必须私有处理？
   - cookie 授权内容。
   - 私人账号关注。
   - 用户私有关键词。
5. token 节省如何量化展示？
   - 本次复用公共摘要，节省 X tokens。
   - 该 collection 本周为社区节省 X tokens。

## 阶段性方向

### Phase 1：不要偏离当前重构

- 修复当前 pipeline 的安全和可用性问题。
- 移除 legacy 明文 cookie 表单。
- 修复 AuthProfile 登录超时。
- 修复 fallback 空结果不继续的问题。
- 完善 PAGE_DIFF 与 Tracker 分离。

### Phase 2：引入共享源模型

- 增加 `shared_source` / `shared_collection` 概念。
- 本地任务可以引用共享源。
- 相同 URL / RSS feed / RSSHub route 统一 fingerprint。
- 同 fingerprint 的抓取结果可复用。

### Phase 3：OnlyFouBot 作为共享层

- 用户发布关注包。
- 用户订阅关注包。
- 公共源公共抓取。
- 公共摘要缓存。
- 私有配置叠加。

### Phase 4：token 成本可视化

- 显示每次复用节省的 token。
- 显示 collection 的公共处理价值。
- 让用户理解“共享关注”带来的收益。

## 最终定位

MajorRSS / OnlyFouBot 不应只是：

```text
RSS Reader + AI Summary
```

而应是：

```text
面向关注目标的信息雷达
通过共享关注源和共享 AI 结果
减少噪音
减少重复 token 消耗
让用户直接抵达真正关心的信息
```

更进一步，OnlyFouBot 的长期价值不只是节省 token。

它应该体现一种社区创建理念：

```text
关注源、collection、摘要、日报、diff、Agent 处理结果
都不应该用完即丢
而应该在可信边界内继续被订阅、复用、扩展
```

因此它更准确的定位是：

```text
面向人和 Agent 的可信关注源网络
```

官方可以发布默认摘要日报，服务低需求用户。

高需求用户和 Agent 可以订阅同一组源，再用自己的模型、prompt、MCP、CLI、API 做个性化日报、研究和工作流。

这和传统 RSS Reader、AI 摘要工具、页面监控工具的差异在于：

```text
传统工具通常只完成一次消费
OnlyFouBot 希望让一次创建持续产生复利
```
