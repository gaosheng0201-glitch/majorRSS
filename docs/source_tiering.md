# 来源分层设计（Source Tiering）

> **实现状态（2026-08-13）**：§2「入口捕获」已全面落地——`SourceRoute.tier → RawArticle.source_tier`（迁移 0007）与账号盖章 `from_account`（迁移 0011）；一手地板扩至前沿实验室自有频道（迁移 0014 重盖历史行，组合型厂商博客刻意排除，理由见 `services/provenance.py` 头注）。本文其余部分保持设计意图定位。

> 定位：**跨域公共基建**（radar / feed / publish 共用），P1.1 融合门控是其第一个消费者
> 关联：[radar_quality_roadmap.md](radar_quality_roadmap.md)（P1.1 门控在此基础上实现）·
> [semantic_layer_audit.md](semantic_layer_audit.md)（一手来源 `_is_first_party` 已有）

## 0. 一句话

**Provenance（来源出身）是整个应用的地基，不是雷达专属、更不是某个门控的局部实现。** 在**入库那一刻**给每条情报盖一个"来源层级"章，一次采集、多处复用（聚类锚点 / 融合门控 / **feed 摘要门控** / 生命周期 / 评分 / 反馈 / 发布展示）。

**捕获现在做，权重应用留后。** 这条分界线是整份设计的关键——见 §2。

> **术语校准（作者 2026-07-23 截图确认）**：应用只有**一条 AI 融合管线**，配**两个显示 tab**——
> - **「AI 智能提炼情报」= feed 流 = 融合输出本身**（`IntelReport` 流）。它的摘要**就是融合 LLM 摘要**，所以「门控融合」与「门控 feed 摘要」是**同一件事、同一处**，不是两条管线。
> - **「原始订阅数据流」= `RawArticle` 直出**（无 AI）。
> - **`pure_rss` = 完全关 AI**，只剩原始订阅流。
>
> **为什么是公共基建**：
> - `ai_fusion`（开 AI，产出「智能提炼」feed）与 `pure_rss`（关 AI，仅「原始订阅数据流」）**共用同一条入库管线**（`scrape_single_tracker → SourceResolver → adapters → SourceNormalizer → RawArticle`），只在**入库之后**才分叉。盖章点放在这条共享管线上，`source_tier` **与 AI 开关无关**——三个显示面（智能提炼 feed / 原始订阅流 / pure_rss）都拿得到，零额外改动。
> - 分层**已经在被重复发明**：`services/semantic_ingest.py` 的 `_is_first_party()`（融合用）+ `services/publish_service.py` 的 `_source_kind()`（发布用，且反向 import 融合模块）——同一个"这条什么来路"的判断散在多处、都从 URL 硬猜。本设计是把这笔已欠的债收敛成一处采集。详见 §10。

---

## 1. 为什么它是地基，而不是 P1.1 的一部分

一个信号，多个下游消费者都在问同一个问题："这条我该多信？"——横跨采集、AI 融合、发布三处。

| 下游消费者 | 显示面 | 用来源层级做什么 | 时序 |
|---|---|---|---|
| **聚类** | 融合内部 | 一手源可当线程锚点（seed 质心），聚合项挂上去 | 现有 |
| **融合门控（P1.1）= 「AI 智能提炼」feed 的摘要闸** | AI feed | 高层（PRIMARY\|CURATED）一律融合成报告；聚合层（AGGREGATED）挣摘要（共振/多源），否则停在线索层（标题+来源） | 眼下 |
| **报告内「引用/未引用来源」列表挂 tier 徽标** | AI feed | 每个来源行显示来路——**即"要能看到从什么渠道来的"的落点**（与 P0.2 新标签同处 UI） | 眼下 |
| **「原始订阅数据流」+ pure_rss 显示来路** | 原始流 | 不融合，但每条显示 `source_tier` 作渠道标——**不开 AI 也有** | 眼下 |
| **生命周期** | 融合内部 | CONFIRMED 现在≈"有一手在场"——层级把这个隐式判断**显式化** | 现有 |
| **重要性评分（P2）** | AI feed | 一手确认的事件 > 只在聚合器出现的 | 后 |
| **反馈（P3）** | AI feed | 用户点赞/踩调**源**的信任——数值权重真正回本的地方 | 最后 |
| **发布展示** | publish | `feed.xml`/公开摘要按层级排序、决定谁上榜；替换现有 URL 派生的 `_source_kind` 的信任部分 | 后 |

> **要点**：「AI 智能提炼」feed = 融合输出本身，所以"融合门控"与"feed 摘要门控"是**同一个消费者**（同一处闸），不是两件事。`source_tier` 入库即盖章、与 AI 开关无关，故连关掉 AI 的 `pure_rss` 原始流也能显示来路。publish 的 `feed.xml` 摘要则**复用融合合成的 alert.summary**。

### 决定性论据：有些层级**只有入库时才知道**

- `news.google.com` 这种能从域名反推，事后补也行。
- 但"这条来自**被追踪账号**管线" vs "来自**用户加的 portfolio 预设**" vs "来自 gnews 关键词搜索"——**光看最终文章 URL 分不清**（追踪账号经 RssHub 出来，域名可能和普通 RSS 撞；预设 RSS 和直给 URL 域名也可能一样）。

这个信息**只有 `SourceResolver` 在决定怎么抓的时候知道**。不在那一刻盖章，出身就**永久丢失**，以后 P2/P3 想用也补不回来。这一条基本把"现在就做捕获"钉死了。

---

## 2. 捕获 vs 应用（整份设计的分界线）

把"来源分层"拆成两半，**只有第一半现在做**：

### ① 捕获（provenance capture）—— 现在做
入库时给每条盖来源层级章。**无损、便宜、无下游语义争议**——不管哪个阶段怎么用，"这条来自哪个渠道"是客观事实。

### ①′ 执行状态（2026-09-06 架构收口）：消费期零推导

"捕获在入口、消费只施权重"从原则变成了结构约束：
- **盖章无 NULL**：迁移 0020 把 1,256 条盖章前的旧行一次性按当年的兜底规则盖上（一手地板 → primary，否则 aggregated），此后 `source_tier` 恒有值，所有消费点的"NULL 就看 URL"兜底代码**全部删除**（`semantic_ingest` 出生/加入两处、`publish_service` 的来源种类改读盖章）。
- **生命周期一处决定**：`services/lifecycle.py::lifecycle_for(member_tiers, distinct_sources, current)`——出生、成员加入、盖章升级、迁移纠错全部调用它；运行中只升不降，纠错只在迁移里发生。此前规则内联在四处并已漂移（出生看 URL 地板、加入看盖章 → 150 条聚合层单条出生即"已证实"）。
- **目标一处定义**：`services/target_profile.py::TargetProfile`——相关性门的 embedding 锚点、跨目标匹配器、摘要模型的目标简报，三个消费者读同一个对象的三个视图；此前三处各自从 Tracker 字段拼装，摘要模型那份干脆缺失（把 Claude 证的定理读成叫 Claude 的人）。

### ② 应用（weight application）—— 现在不做
"每个阶段该多信任某一层"。这一半**有语义分歧**（聚类要的是"能否当锚点"，评分要的是"加权"，门控要的是"高层是否在场"，不是同一个标量），而且**需要反馈信号才能调准**。

**反模式警告**：现在就把层级数值化（`PRIMARY=1.0 / CURATED=0.6 / AGGREGATED=0.2`）并让各阶段按这个权重加权，等于**在没有信号的时候凭空编权重**——正好违背路线图的排序铁律："评分/反馈最后做，别在脏基准上叠加"。捕获是采集事实，应用是下判断；先把事实采干净，判断留到有数据。

今天融合门控只需把层级当**布尔**用（"有没有高层成员"），不需要任何数值。

---

## 3. 三层枚举

序数枚举，**从高到低**：

```
PRIMARY      一手：主体自己的官方渠道
             — 厂商域名 / gov / edu / arxiv / github（复用现有 _is_first_party）
             — 被追踪本人的官方账号（当账号即主体时）
CURATED      精选：用户主动加的二手
             — portfolio 预设（分析师博客、订阅的 newsroom、非主体的追踪账号）
             — 用户直给的 RSS / 网页 URL
AGGREGATED   聚合：关键词消防栓
             — Google News / Reddit search / Hacker News search
```

- **PRIMARY / CURATED = 高权重类**（opt-in 即信号，永不被渠道门过滤）。
- **AGGREGATED = 低权重类**（量大、来源杂，必须挣摘要）。
- 枚举是**可扩展**的那部分——以后要细分（如 `PRIMARY_SUBJECT` vs `PRIMARY_VENDOR`）只加枚举值，不动地基。

> 为什么是序数而不是现在就上数值：序数够今天的门控用（布尔化），且**前向兼容**——将来一张 `tier → base_weight` 映射就能升级成数值，反馈信号来了再让 per-source 权重在 base 上浮动。见 §7。

---

## 4. 唯一盖章点：`SourceResolver`

resolver 是**唯一同时知道"抓取意图渠道"**的地方（`services/source_resolver.py`）。每个 `_resolve_*` 方法在造 `SourceRoute` 时顺手盖章：

| resolver 方法 | 生成的 route_id | 盖的 tier | 依据 |
|---|---|---|---|
| `_resolve_keyword_routes` | `gnews_N` / `hn_N` / `reddit_N` | **AGGREGATED** | 关键词元搜索，恒为消防栓 |
| `_resolve_account_routes` | `nitter`/`rsshub`/`agentic_<plat>_N` | **CURATED** | opt-in 追踪账号 |
| `_append_portfolio_routes` | `preset_N` | `_is_first_party(url)` → **PRIMARY**，否则 **CURATED** | 用户主动加的预设 |
| `_resolve_rss_routes` | `rss_feed_N`/`agentic_snapshot_N`/`rss_alternate_N` | `_is_first_party(url)` → **PRIMARY**，否则 **CURATED** | 用户直给 URL |

要点：
- **AGGREGATED 恒定**。gnews 抓的文章 URL 恒为 `news.google.com` 重定向，不会因为偶然指向 openai 就升级——关键词搜索的"杂"是它的本质。
- **PRIMARY 升级用现成的 `_is_first_party`**（`services/semantic_ingest.py:83`，已识别 gov/edu/arxiv/github/厂商域名）。把它抽到共享位置（如 `services/provenance.py`）供 resolver 和 semantic 共用，避免两份名单漂移。
- 账号路由默认 CURATED，不强判 PRIMARY——"被追踪的人是否就是报道主体"难可靠判定，留给枚举将来细分，宁可保守。

---

## 5. 数据流（盖章 → 落库 → 门控）

沿现有管线一路透传，改动都是"加一个字段"，无结构性重构：

```
SourceResolver._resolve_*          →  SourceRoute.tier            [新字段, dataclass]
   ↓ adapter.fetch(route)
RssAdapter/RssHubAdapter/Agentic   →  SourceItem.tier = route.tier [新字段, 抄一行]
   ↓ normalizer.normalize_and_save
SourceNormalizer                   →  RawArticle.source_tier       [新列 + migration]
   ↓
融合门控 / 聚类 / 评分 / 开发者模式  →  读 RawArticle.source_tier
```

**Migration**：`RawArticle.source_tier` 设为 **nullable**。
- 旧行 = `NULL` = 出身未知 → 门控按 **AGGREGATED 保守处理**（未知出身要挣摘要，不白给）。
- 新行由 resolver 盖章，恒有值。

---

## 6. 今天怎么用（P1.1 融合门控）

门控只把层级当**布尔**读，零数值：

```
线索（thread）级规则：
  含任一 PRIMARY|CURATED 成员      → 融合（opt-in 即信号）
  纯 AGGREGATED                    → 挣摘要：is_resonant 或 distinct_source_count ≥ N
  tracker.is_high_attention        → 一律融合（用户标了高关注）
  未过门                           → 不烧 LLM，雷达照常显示标题+来源+生命周期
```

这**天然涵盖**原来的 CONFIRMED 门控（一手在场 = PRIMARY 在场），且更便宜——层级入库即知，不必等线索统计跑完。细化见 [radar_quality_roadmap.md](radar_quality_roadmap.md) P1.1 附录。

---

## 7. 前向兼容（留给 P2/P3 的钩子，现在只留接口不实现）

- **P2 评分**：加一张 `tier → base_weight` 只读映射，评分把它作为一个特征。序数→数值的升级点。
- **P3 反馈**：用户点赞/踩累积成 per-source 信任偏移，叠在 base_weight 上——**学习出来的**权重，而非编的。这才是数值权重回本的地方，也是它必须等到最后的原因（要先有信号）。
- 枚举细分：`PRIMARY_SUBJECT` / `PRIMARY_VENDOR` 等，只加值不动地基。

---

## 8. 明确不做（防过度设计）

- ❌ 现在就给层级配数值权重、让各阶段按权重加权
- ❌ per-source 覆盖表 / 手动权重 UI
- ❌ 学习/衰减权重（P3 之前无信号可学）
- ❌ 账号是否为"报道主体"的强判定

做这些 = 在脏基准上叠判断。**先把出身采干净（§2①），判断留到有数据。**

---

## 9. 落地清单（最小改动，P1.1 前置）

1. `services/provenance.py`：抽出共享的 `_is_first_party` + `Tier` 枚举（`PRIMARY`/`CURATED`/`AGGREGATED`）。
2. `SourceRoute` 加 `tier` 字段；各 `_resolve_*` 按 §4 表盖章。
3. `SourceItem` 加 `tier`；三个 adapter 各抄一行 `tier=route.tier`。
4. `RawArticle` 加 `source_tier` 列（nullable）+ migration。
5. `SourceNormalizer.normalize_and_save` 写 `source_tier`。
6. 开发者模式：每条情报显示 `source_tier`（呼应"要能看到从什么渠道来"）。
7. （P1.1）融合门控读 `source_tier`，按 §6 布尔化。

第 1–6 步是**纯捕获**、无行为变化、可独立验证；第 7 步才改融合行为。可分两次提交，先把地基铺稳再改门控。

---

## 10. 两个正交 facet + 与现有分类的统一

系统里"给源分类"其实是**两个正交问题**，别揉成一个枚举：

| facet | 回答 | 取值 | 怎么来 | 谁消费 |
|---|---|---|---|---|
| **trust tier**（本设计新增） | 该多信？ | `PRIMARY / CURATED / AGGREGATED` | **路由派生**（入库盖章，无损） | 融合门控 · feed 摘要门控 · 评分 · 反馈 |
| **outlet kind**（`publish_service._source_kind` 已有） | 什么类型媒体？ | `first_party / media / social / generated_feed` | URL 域名派生（展示够用） | 发布展示排序 · 公开摘要上榜 |

**为什么 trust 必须路由派生、不能像 outlet kind 那样从 URL 猜**：
同一篇文章 URL，经"用户订阅的 TechCrunch RSS"进来是 `CURATED`，经 gnews 关键词搜到是 `AGGREGATED`——**最终 URL 一样，信任不一样，只有路由知道**。这正是 URL 派生补不回来、必须入库盖章的那部分（呼应 §1 的"决定性论据"）。outlet kind 是媒体**类型**，本就是域名的属性，URL 派生够用，保留现状即可。

**现有碎片的收敛路径**（都是 URL 派生、各判各的，本设计逐步消化）：
- `services/semantic_ingest.py:83` `_is_first_party()` —— 抽到 `services/provenance.py`，成为 trust tier 判 `PRIMARY` 的共享依据（§4/§9-1）。
- `services/publish_service.py:69` `_source_kind()` —— 保留其 outlet-kind 职责，但把 `first_party` 分支改为**读 `RawArticle.source_tier == PRIMARY`**，去掉那次反向 `import _is_first_party`。两个 facet 各归其位，不再互相依赖雷达内部实现。

净结果：**一处入库盖章（trust），一处 URL 派生（outlet kind），互不重叠、互不重造**——这才是"公共基建"的落点，而不是又加一套平行分类。
