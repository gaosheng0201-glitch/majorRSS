# P4.0 意图探索 — 实施设计（合同稿,待作者审）

> 2026-08-14 起草。上游依据：[radar_quality_roadmap.md](radar_quality_roadmap.md) P4.0 节（问题/产出表/分道规则/护栏,作者已裁决部分）+ [vision_and_blueprint.md](vision_and_blueprint.md) 3.1（架构链）/:87（时间语义）/:89（语言三原则）。
> 本文只补"怎么实现"。**产出表和护栏若与 roadmap 冲突,以 roadmap 为准。**

## 1. 目标形态（一句话）

用户输入一句自然语言 →（建目标时一次 LLM 调用）→ 结构化 **IntentPlan** → 用户确认/编辑 → 落为 Tracker(+扩展的 fetch_policy) → 运行时**零 token 确定性执行**全部路由。

## 2. IntentPlan schema（PortfolioPlan 的继任,治 Drift 3）

```python
class AliasSpec(BaseModel):
    text: str                 # "渐冻症" / "ALS" / "筋萎縮性側索硬化症"
    lang: str                 # BCP-47："zh" / "en" / "ja"
    regions: List[str] = []   # 该别名值得搜的地区版本：["CN"] / ["US","GB"]
    role: str = "name"        # name | person | org | product | ticker

class SourceSuggestion(BaseModel):
    kind: str                 # rss | account | subreddit | registry | page_monitor
    value: str                # URL / handle / 版块名 / 登记库查询
    platform: str = ""        # twitter / reddit / …（kind=account/subreddit 时）
    reason: str               # 为什么建议（可解释>自动化）
    verified: bool = False    # 存在性校验结果（护栏：模型会编造）

class IntentPlan(BaseModel):
    lane: str                 # "radar" | "monitor"（分道判断,P4.0 核心新增）
    lane_reason: str
    entities: List[AliasSpec]           # 语言无关实体画像（替代 List[str]）
    official_domains: List[str] = []    # 该目标自己的官方域名 → per-target 一手判定
                                        # （provenance.py 地板注释里欠的那笔）
    selected_collections: List[str]     # 预设集合（沿用）
    suggested_sources: List[SourceSuggestion] = []   # 集合外的补充（P4.1 雏形）
    keep_keywords: List[str]
    ignore_keywords: List[str]
    warmup_days: int = 7               # 预热回填窗（愿景:87,快话题7/慢话题90）
    fetch_interval_minutes: int = 30
    narration_lang: str                # 输入语言 → 只定叙述语言（三原则①）
    rationale: str
```

存储：`Tracker.fetch_policy`(JSON) 增加 `intent_plan` 键整体存放；`entities` 兼容旧读法（继续同步写 `keep_keywords`/`source_scope`,旧运行时字段一个不删——绞杀者演进,不迁表）。

## 3. 运行时消费（决策已在规划期,这里只执行）

- `SourceResolver` 读 `intent_plan`：
  - 每个 `AliasSpec` → 按其 `lang/regions` 生成对应 gnews 版本路由（**取代**运行时 `gnews_locale_params` 字形猜测;无 plan 时旧启发式作兜底,已降级为 fallback 的裁决落地）
  - `kind=account` → 现有 `_twitter_account_routes`/平台链,自动 `is_account=True`
  - `kind=subreddit` → reddit 版块 RSS 路由（受 host_politeness 管辖）
  - `kind=page_monitor` → 建 Subscription（监控道）而不是 tracker 路由
- `official_domains` → 注入 per-target 一手判定：`tier_for_url` 增加可选 `extra_first_party` 参数,normalizer 从 tracker 的 plan 里取。**全局地板不动**（Cloudflare 教训:组合博客的 PRIMARY 只对拥有它的目标成立）。

## 4. UI 流（Discovery 页改造,三步不变但语义变）

1. 输入框只收一句话（现有"主题"框升级;高级字段折叠为"手动模式",纯 RSS/无 key 用户的现有表单**原样保留**——地板不动）
2. 展示 IntentPlan 预览："我理解你想追的是…,雷达道,将监听这些源（含理由）,别名覆盖 zh/en/ja"——**可编辑,确认才落库**
3. 落库后走现有 plan-preview 的解释展示

## 5. 兜底与降级（纯 RSS 地板）

- 无生成模型：跳过 LLM,走现有确定性规划（关键词重叠+实体词典）,`lane` 默认 radar,UI 提示"接入模型可自动分道/扩别名"
- LLM 返回不合 schema：一次重试后回落确定性路径（沿用 planner 现有模式）
- 存在性校验:`suggested_sources` 逐条 HEAD/GET(超时 5s,不过校验的标 `verified=False` 且默认不勾选)

## 6. 验证计划（做完什么算过）

- 单测：schema 往返、lane 判断边界例（roadmap 里的三个例句）、alias→路由派生、official_domains 不污染全局地板、无 key 兜底
- 实测（对照 7/29 的实证）：`gemini` 意图不再招星座（ignore 自动含 horoscope）;`渐冻症` 产出 zh+en+ja 别名并生成对应版本路由;监控例句正确走 Subscription
- 成本：每次建目标 1-2 次 LLM 调用,记账 `action_type=IntentPlan`

## 7. 分期（可独立合入的三刀）

1. ✅ **P4.0a schema+分道**（2026-08-20 落地,真实 LLM 边界例三过,66 测试）：IntentPlan/lane 判断+UI 预览确认（不动 resolver,`entities` 仍降维成关键词用）——独立可用
2. ✅ **P4.0b 路由派生**（2026-08-20 落地）：resolver 消费 AliasSpec（`gnews_edition_params(lang, region)` 显式版本路由,取代字形猜测——猜测保留为无 plan 的兜底,7-29 降级裁决就此彻底落地）+ `official_domains` per-target 一手判定（`tier_for_url(extra_first_party=…)`,营销路径守卫仍生效,全局地板不动）+ ingest 的 CONFIRMED 改读入库盖章（消灭又一处消费期重推导）。实测:「帮我盯大谷翔平的动向」不提语言 → 6 条路由横跨 JP:ja/US/CA:en/CN:zh-Hans/TW:zh-Hant/HK:zh-Hant。账号建议消费归 c 刀
3. **P4.0c 建议源**（=P4.1 雏形）：suggested_sources + 存在性校验

## 8. 留给作者的三个决策点

1. **重规划时机**：只在建目标时跑一次,还是提供"重新规划"按钮（改意图后重跑）？建议:手动按钮,不自动周期（成本可见、行为可预期）。
2. **分道判断的落点**：monitor 道判定后直接建 Subscription,还是提示用户"这更像监控,去订阅管理建"？建议:直接建,但确认页明示"这将建为页面监控"。
3. **Grok x_search 是否进 P4.0c**：计费已查证（$5/1000 次调用 + token 费,一次规划 1–2 美分,不是障碍）;**真约束是无独立 endpoint**——只能在 Grok 补全内由模型触发,接入即引入 xAI provider 分支。建议:c 刀基线用现有 provider 建议 + 存在性校验,Grok 作可选增强建议器(有 xAI key 才启用),首版不做。
