# 页面监控 diff 语义层 —— 程序管"变没变"，LLM 管"变的是什么"（合同稿，2026-09-03，待作者审）

> 作者原话："程序只负责监控变化，发现变化后用 LLM 轻量过一下变化具体是什么，比如模型更新、价格调整，这样用户能知晓个大概，也能避免页面广告之类的干扰触发 diff 但用户想了解的信息其实没有变化。"

## 1. 现状（`worker_subscription.py`）

HTML → 清洗（可选 extract/ignore 选择器）→ sha256 → 变了就 `difflib.unified_diff` → `SubscriptionUpdate(diff_text)` → 可选 `ignore_keywords` 过滤 → 通知。**全确定性，无语义**：广告位/日期/推荐位/计数器一动就是一次"变化"；真变了也只给 +/- 行。

## 2. 设计：两段式，LLM 只在第二段、只在变化时

```text
确定性检测（现状，不动）──变了──▶ 轻量判读（新增，一次短调用）──▶ 通知 / 静默记录
```

**判读输入**：diff 的 +/- 行（裁到 ~1,500 字，去掉纯空白/纯数字行）+ 这条监控的**意图**（订阅名 + 来源目标的意图句/实体/官方域名，若由 P4.0c 物化则天然有）。
**判读输出（结构化，固定集合）**：

```json
{"material": true, "category": "model_update", "summary": "新增 Gemini 3.8 Flash 定价：$0.75/M 输入", "confidence": 0.9}
```

`category ∈ {model_update, price_change, availability, policy_terms, docs_change, announcement, other, noise}`；`noise` = 广告/推荐位/时间戳/计数器/布局。

**行为**：`material=false` → **不通知**，但更新照常入库、可在订阅管理里查（静默不等于丢弃）；`material=true` → 通知带类别与一句话（"价格调整：…"），比"页面变了"有用得多。

## 3. 护栏（沿用雷达层的三条原则）

1. **LLM 不覆盖事实**：变没变仍由 hash 决定；LLM 只决定"通不通知"和"贴什么标签"。diff 原文永远保留。
2. **成本封顶**：只在 hash 变化时调用一次，输入短；走现有每日预算刹车；连续判为 noise 的监控可自动降频（可选）。
3. **地板不动**：无 key（纯 RSS 模式）退回现状——每次变化都通知，只是没有判读；用户也可按订阅关闭判读。
4. **分类集合固定**、不让模型自由发挥；`confidence < 0.5` 视为 material（宁多勿漏）。

## 4. 数据与呈现

- `SubscriptionUpdate` 增 `category`、`is_material`；`llm_summary` 已有字段直接用。
- 通知只推 material；订阅管理列表按 material 高亮，noise 折叠；类别做筛选 chip。
- 与雷达的关系：**监控道保持独立**（变化即事件，不进聚类）。可选后续：`announcement/model_update` 类的 material 更新在雷达页顶部作一行提醒（复用涌现源那行的形态）。

## 5. 验收（用真实监控）

- `anthropic.com/news` 列表页监控：新公告出现 → material / `announcement` / 一句话含标题；页面推荐位或页脚变动 → `noise`，不通知。
- Vercel/Google 定价页：价格数字变化 → `price_change`；促销横幅变化 → `noise`。
- 成本：一周内判读调用数 ≤ 变化次数；每次 < 1k tokens。

## 6. 分期

| 刀 | 内容 | 量 |
|---|---|---|
| M0 | 判读函数 + 字段 + 通知门（material 才推）+ 无 key 兜底 | 半天 |
| M1 | 订阅管理 UI：类别/一句话/noise 折叠/按订阅开关 | 半天 |
| M2 | 连续 noise 自动降频（可选）· 雷达页顶部 material 提醒（可选） | 半天 |

## 7. 决策点

1. 类别集合是否够（要不要 `security_advisory`、`api_deprecation`）？
2. material 更新要不要也进雷达提炼面（我建议不进，保持"变化即事件"的语义纯粹）。
