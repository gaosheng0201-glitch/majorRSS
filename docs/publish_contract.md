# 发布数据契约（PublishedDigest v0）

> 创建：2026-07-16
>
> 本文是**公开网站（分发页面）与本地重构管线之间的接口契约**。
> 两条线并行开发的兼容锚点：功能重构 session 最终让发布层产出这份 JSON；
> 站点 session 只消费这份 JSON。视觉设计随时可换，契约保持稳定。
>
> 上游依据：[vision_and_blueprint.md](vision_and_blueprint.md)（R7 发布层、发布合规策略、线索生命周期）、
> 现有模型 `db/models.py`（StoryThread / RadarAlert / IntelReport）、`services/radar_digest.py`。

## 1. 角色分工

```text
本地 MajorRSS（重构 session 的地盘）
  StoryThread / RadarAlert / IntelReport
  → 发布导出器（R7，未来实现）：选题 → PII 清洗 → 合规门 → 序列化
  → PublishedDigest JSON（本契约）
  → 静态站点生成 / 上传

公开网站（本 session 的地盘）
  只读 PublishedDigest JSON → 渲染分发页面 + generated RSS
```

站点**不直连数据库、不调 API、不感知本地模型细节**。契约就是全部耦合面。

## 2. 版本规则

- `contract_version` 采用 `MAJOR.MINOR`，当前 `0.1`。
- `0.x` 内只允许**加字段，不允许改名/删字段/改语义**（additive-only）。
- 站点渲染器必须**忽略未知字段**，缺可选字段时优雅降级。
- 破坏性变更升 MAJOR，站点按版本分支渲染。

## 3. 顶层结构

```json
{
  "contract_version": "0.1",
  "generated_at": "2026-07-16T02:00:00Z",
  "publisher": {
    "name": "majorflow",
    "instance_id": "author-main",
    "signature": null
  },
  "window": { "from": "2026-07-15T02:00:00Z", "to": "2026-07-16T02:00:00Z" },
  "topics": [ Topic ],
  "threads": [ Thread ],
  "stats": Stats | null
}
```

- `publisher.signature`：R7 接 Supabase 账号体系后放贡献者签名（追溯/归责，愿景 #6）；第一阶段可为 null。
- `stats`：可选，对应 `get_radar_stats()` 输出的子集，站点用一行安静文字展示"本期过滤 N 条噪音"（盲区 #8）。

## 4. Topic

对应本地 Tracker / Watch Target 的**公开投影**（名称可与本地不同，发布时可改写）。

```json
{
  "id": "ai-frontier",
  "title": "AI 前沿",
  "description": "模型发布、API 变更、基础设施动向",
  "language": "zh"
}
```

## 5. Thread（核心对象 = 一条线索）

```json
{
  "id": "thr_a41f9c",
  "topic_id": "ai-frontier",
  "title": "OpenAI 悄然更新 Realtime API 定价页",
  "lifecycle": "CORROBORATED",
  "fact_level": "verified",
  "importance": 4,
  "is_resonant": true,
  "distinct_source_count": 5,
  "first_seen_at": "2026-07-15T09:12:00Z",
  "last_update_at": "2026-07-16T01:30:00Z",
  "summary": {
    "text": "……（用自己的话写的摘要，永不含原文全文）",
    "language": "zh",
    "ai_generated": true,
    "method": "synthesized"
  },
  "increments": [
    {
      "at": "2026-07-16T01:30:00Z",
      "note": "官方 changelog 出现对应条目，线索升级为 CONFIRMED",
      "citation_indexes": [0]
    }
  ],
  "sources": [
    {
      "title": "OpenAI Pricing — Realtime API",
      "url": "https://…",
      "site": "openai.com",
      "kind": "first_party",
      "published_at": "2026-07-15T08:00:00Z",
      "quote": null
    }
  ],
  "provenance": {
    "pii_cleaned": true,
    "auth_content_excluded": true,
    "rights": "public_summary"
  }
}
```

### 字段语义与本地映射

| 契约字段 | 本地来源 | 说明 |
|---|---|---|
| `id` | `StoryThread.id` + instance 派生的稳定公开 id | 不直接暴露自增 int，hash(instance_id, thread_id) |
| `title` | `StoryThread.title` | |
| `lifecycle` | `StoryThread.lifecycle` | `LEAD` / `CORROBORATED` / `CONFIRMED`，站点必须原样标注（时效与置信分离原则） |
| `fact_level` | 派生（见下） | `observed` / `verified` / `disputed` / `low_confidence` |
| `importance` | `StoryThread.importance_score` | 1-5 |
| `is_resonant` / `distinct_source_count` | `StoryThread` 同名字段 | 佐证数可见（愿景 #4） |
| `summary` | `RadarAlert.summary` 或线索合成 | `method`: `synthesized`（LLM 带引用合成）/ `extractive`（置信不足只给原文关键句，盲区 #4 幻觉控制） |
| `increments` | 线索增量历史（RadarAlert 序列） | 站点渲染"发生了什么变化"而非"有多少新内容"（增量优先原则） |
| `sources` | 线索成员的 IntelReport/RawArticle | 按 `kind` 排序：first_party 置顶（一手来源追猎） |
| `sources[].kind` | 派生 | `first_party` / `media` / `social` / `generated_feed` |
| `sources[].quote` | 可选短引用 | ≤ 120 字（沿用 [security_and_sharing_boundary_plan.md](security_and_sharing_boundary_plan.md) 的 `quote_max_chars`），必须与 `url` 成对出现（发布合规：短引用+署名） |
| `provenance` | 发布导出器打标 | 见合规门 |

### fact_level 派生规则（发布导出器实现）

```text
CONFIRMED（一手来源在场）            → verified
CORROBORATED（≥N 独立来源，无冲突）   → verified
CORROBORATED（来源间说法冲突）        → disputed
LEAD（单源社交/论坛）                → observed
其他单源 / 低信来源                  → low_confidence
```

## 6. 合规门（导出器必须全过，站点信任其结果）

按蓝图「发布合规策略」+「共享与发布层」：

1. **摘要，永不全文**：`summary.text` 是转述，长度上限 500 中文字（`public_summary_max_chars`，沿用边界计划阈值）；原文只存在于用户本机。
2. **短引用受限**：`quote` ≤ 120 字、必须带 `url` 署名；不引用付费墙内容。
3. **PII 清洗**：出本机前过 `services/privacy.py`（地址/证件号/手机号/邮箱/精确坐标）；`provenance.pii_cleaned = true` 才允许发布。导出器若实现边界计划的 `privacy_level` 四级（none/personal/sensitive/blocked），可作为可选字段加入 `provenance`（additive），语义以边界计划为准：sensitive/blocked 不发布。
4. **授权内容不出本机**：cookie/登录态抓到的内容一律排除；`provenance.auth_content_excluded = true` 是硬门。
5. **溯源三件套**：每条 source 必须有 `title + url + published_at(或 first_seen)`——署名来源、原文链接、时间戳。
6. **AI 标注诚实**：`summary.ai_generated` 为 true 时站点显式标注"AI 归纳"；`method = extractive` 时站点只展示关键句+链接、不摆结论姿态。
7. 不转存图片（契约无图片字段即是执行）；takedown 通道在站点页脚。

## 7. 分发形态

> 谁在什么环境生成并推送这份 JSON（作者本机非 24h 在线的问题），见
> [official_feed_automation.md](official_feed_automation.md)。

同一份 JSON 驱动两个出口：

- **HTML 分发页面**：`site/`（线索流，内容优先）。
- **generated RSS**：每 topic 一条 feed + 全站 feed；item = thread 的最新增量，guid = `thread.id + last_update_at`。替代现有 [export_rss.py](../export_rss.py)（其 IntelReport 直出形态属于旧管线，R7 时淘汰）。

## 8. 与共享层的关系：三阶段演进路径

本契约是**分发出口**的契约，不是共享平台的全部。对照蓝图「信任模型分阶段」
与 [onlyfourbot_platform_design.md](onlyfourbot_platform_design.md)，演进如下——
**每一步只加维度，不改已有字段，站点渲染器全程复用**：

### Phase 1（现在）：官方分发源

- 单一 publisher = 作者实例；静态 JSON 直出，`signature` 为 null。
- 站点 = 官方雷达日报。无账号、无服务端、无投毒面（发布入口只有作者本机）。

### Phase 2（受邀发布）：多发布者频道

- 多份 PublishedDigest 并存，`publisher` 块开始携带真实身份：
  `signature`（AppInstance 私钥签名）+ Supabase 账号绑定（愿景 #6 追溯归责）。
- 站点新增**频道维度**：`/c/{publisher}` 或 `/t/{topic}` 聚合页 + 各自的 generated RSS；
  分发页面本身不变，只是从"一份 digest"变成"按频道选一份 digest"。
- 受邀制 = 信任白名单，仍不需要重型防投毒（蓝图明确留到开放投稿时）。

### Phase 3（共享索引）：先查再开火

- 这是**另一份契约**（服务端 API，非本文件）：客户端为某话题烧 token 前，
  先查 `GET /shared-index?topic=…&window=…` 是否已有足够新鲜的共享 digest；
  命中则拉取复用（零 token），未命中则本地生成、可选签名回推。
- 回推 payload 的主体就是本契约的 Thread 对象——所以 Phase 1 把 Thread 定扎实，
  Phase 3 的共享单元不需要重新发明。
- 开放投稿若启动，平台设计文档里的信用体系/审核流水线才进场；
  对本契约的影响仅限于给 Thread/publisher 增加 `trust` 类可选字段（additive）。

一句话分工：**本契约管"内容长什么样"，共享层管"谁能发、谁可信、怎么复用"**。
后者变化再大，内容形状不变，站点与导出器都不用返工。

## 9. 站点侧承诺（换皮不换骨）

- 渲染器只依赖本契约字段；视觉全部走 `site/assets/tokens.css` 的 CSS 变量，后续设计=改 token + 布局层，不动数据层。
- 样例数据 `site/data/digest.sample.js` 与契约同步维护，是两边并行开发期间的"活契约测试"。
