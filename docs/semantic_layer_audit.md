# 语义/嵌入层审计与收口计划

> 创建：2026-07-23 · **状态：设计 TODO，多数项未实现**
>
> 本文汇总 2026-07-23 调查发现的语义/嵌入层缺陷、**根因**、以及分层收口计划。
> 触发：作者测试打包应用时发现"关键词目标全是 Google News""同一事件重复推送""计费不准"。
> 相关：`services/llm_provider.py`、`services/semantic.py`、`services/semantic_ingest.py`、
> `desktop/src/pages/Billing.tsx`、`docs/vision_and_blueprint.md`（R3 设计）、
> `docs/engineering_baseline.md`（R3 落地记录）、`docs/investigator_redesign.md`。

## 0. 根因：为什么这一层这么多缺陷

**设计文档把该设计的都设计对了**（见下各条引用），但**实现只用 stub/兜底 embedder 验证，真实嵌入路径从打包第一天就死于一个 404 的模型名**，导致整个语义层从未在真实数据上运行过——直到本次会话修好才暴露全部下游问题。

- `engineering_baseline.md` R3 记录原话："**注入 stub embedder 端到端验证**：3 篇同事件→1 条 CORROBORATED 线索"——聚类只用桩验证过。
- 默认嵌入模型 `text-embedding-004` 返回 **404（停服）**，`run_semantic_ingest` 每 5 分钟抛异常 → **0 embedding / 0 聚类 / 0 去重 / 0 线索 / 0 告警**，所有打包版本里语义层 100% 死。
- 于是：聚类质量（坍缩/过度合并）、嵌入计费、模型配置——**全都没经过真实运行的检验**。

一句话：**这是"用 mock 通过了单测、却从未与真实依赖做集成测试"的经典案例，而真实依赖从第一天就是坏的，把整层的问题一起藏了起来。**

本次会话已修的前置：`text-embedding-004` → `gemini-embedding-001`（语义层首次真正运转）；生成模型 `gemini-3-flash-preview` → `gemini-3.6-flash`；Gemini 客户端 GC bug。**以下是修完这些后暴露的、尚未处理的问题。**

## 1. 计费与 token 记账（高 · 代码修复）

### 1.1 计费公式结构性错误
`Billing.tsx` 当前：
```js
if (model.includes('flash')) flashTokens += total_tokens
else if (model.includes('pro'))  proTokens += total_tokens
estCost = (flashTokens/1e6)*0.15 + (proTokens/1e6)*2.5
```
- **混合单价 × total_tokens**：真实计费 = `输入token×输入价 + 输出token×输出价`，输出通常 4–8× 输入价。数据已分 prompt/completion，却被揉成总数乘单一费率 → 根上不准。
- **硬编码 `0.15/flash、2.5/pro`**：gemini-2.5 时代价，gemini-3.6-flash 不是这个价（具体值查官方 pricing，勿臆造）。
- **粗暴按名字分桶**：2.5-flash 与 3.6-flash 同价；embedding 模型名无 flash/pro → 落空 → 计 $0。

正解：后端维护 `{model: {input_price, output_price}}` 价格表（可随官方更新），按 prompt/completion 分别计价；前端只展示。

### 1.2 Embedding 完全没记账（预算刹车失效）
`GeminiProvider.embed()` **不取 `usage_metadata`、不调 `_record_usage`** → embedding token 从未进 `TokenUsage`。后果：
- 计费页 embedding 成本恒为 0；
- **每日预算刹车 `LLM_DAILY_TOKEN_BUDGET` 不数 embedding** → 可能悄悄超支；
- 每次抓取给新文章 embed 是持续真实支出，目前完全隐形。

正解：`embed()` 捕获 usage 并 `_record_usage(provider, "Embedding", usage)`；计费表纳入 embedding 单价。

## 2. 向量模型黑盒、无用户配置（中 · 前端+后端 · 违背愿景）

- 设计意图：`vision_and_blueprint.md:145-147` "Provider 抽象 generate+embed；后端 Gemini/OpenAI 兼容（覆盖 Ollama/LM Studio/vLLM）；**embedding 优先本地（隐私+免费）**"。
- 实际：`Settings.tsx` 只有 **API Key（Gemini）+ 语言 + 模式**。**没有** `LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL / LLM_EMBED_MODEL` 的 UI，全 env-only，打包用户改不到。
- 后果：用户**无法选嵌入/生成模型、无法指向本地模型**；provider 抽象"造了引擎没接方向盘"。

正解：Settings 增"模型与后端"区——provider 下拉（Gemini / OpenAI 兼容 / 本地）、base_url、生成模型、嵌入模型；后端 `/settings` 落到 config。

## 3. Embedding 本地化（可行，且是设计首选）

- **代码已支持**：`OpenAICompatibleProvider.embed()` 调 `{base_url}/embeddings`（OpenAI 嵌入 API），Ollama/LM Studio/vLLM 均暴露。`LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL=http://localhost:11434/v1` + `LLM_EMBED_MODEL=nomic-embed-text` 即全本地嵌入。
- **仅差 UI（见 §2）** + 一份"推荐本地嵌入模型"说明（多语言要求见 §5，愿景 #6 硬性）。

## 4. 向量坍缩 / 各向异性（高 · 设计级 · 当时未设计）

- 设计缺口：`semantic.py` **只做 L2 归一化，无去均值/白化/各向异性校正**。R3 的"诚实局限"只提兜底哈希 embedder 弱，**未预见真实 embedding 的坍缩**——因为真实 embedding 从没跑过。
- 实测症状（2026-07-23，库内真实向量）：gemini-embedding-001 各向异性明显，任意两条 AI 新闻余弦 0.60–0.86，**同事件 0.755–0.783 与不同事件 0.60–0.861 分布严重重叠**；加 `task_type=SEMANTIC_SIMILARITY/CLUSTERING` 实测仍切不开（间隔≈0 或负）。→ 阈值 `THREAD=0.62` 造成**过度合并**（"Tesla 更新"一条线索塞 44 篇不同事件）。
- 结论：**单靠余弦阈值无法聚类同实体短新闻事件**。正解两条叠加：
  1. **各向异性校正**：语料去均值（corpus mean-centering）或 all-but-the-top 白化后再算余弦；
  2. **LLM 事件签名聚类**（见 `docs/investigator_redesign.md` 同类思路）：LLM 抽"动作+主体+时间"事件键，按事件键聚类，而非纯向量。
- 止血选项（未做，需作者决策）：`THREAD` 阈值提到 ~0.88 退化为"只近似去重、宁可欠合并"（愿景本就说"欠合并安全、错合并危险"），并清空重跑聚类。代价：同事件不同措辞不再归并（可接受）。

## 5. 跨语言 / 多语言归并（愿景硬性要求，需随嵌入选型验证）

- `vision_and_blueprint.md:186`（盲区 #6）："**embedding 模型必须多语言**，同一事件的中英文报道归同一线索，否则去重承诺破产"——R3 选型硬性要求。
- 现状：从没用真实多语言数据验证过（stub 验证）。换嵌入模型（本地或 gemini-embedding-2）时必须重测中英文同事件是否归并。

## 6. 嵌入模型版本（低 · 评估项）

- 本次设为 `gemini-embedding-001`（稳定、已验证 3072 维可用）。
- Google 已更新到 **Gemini Embedding 2**（`gemini-embedding-2` / `gemini-embedding-2-preview` 在 `models.list` 可见）。可能坍缩更轻、分离更好，**值得评估**；但较新（preview/价格待确认），不建议即换，评估后再定。

## 收口优先级

| 项 | 严重度 | 性质 | 依赖 |
|---|---|---|---|
| §1 计费公式 + embedding 记账 | 高（钱不准 + 预算刹车失效） | 代码 | 官方价格表 |
| §4 向量坍缩 + 事件聚类 | 高（核心"事件线索"前提） | 设计级 | 决策：止血阈值 or LLM 事件键 |
| §2/§3 模型配置 UI + 本地嵌入 | 中（违背 BYOK/本地愿景） | 前端+后端 | — |
| §5 多语言归并验证 | 中（去重承诺） | 测试 | 随 §3/§6 选型 |
| §6 Gemini Embedding 2 评估 | 低 | 评估 | — |

**建议顺序**：先 §1（钱和预算是硬伤、纯代码）→ §4 止血（提阈值让测试体验正常）→ §2/§3（放开模型配置，兑现本地愿景）→ §4 正解（LLM 事件键，与 investigator 重设计合流）→ §5/§6 随选型验证。
