# 目标即查询 —— 目标不是容器，是对全局线索池的查询（2026-09-17 落地）

> 作者 2026-09-09："是不是有更简单有效的解法？这应该不是一个复杂的难题。"——是。此前三周的跨目标缺陷（串目标、抓到算谁的、官博在别的目标下不可见、垃圾地板按抓取者画像打分、摘要站在抓取者立场判"与监测目标无关"）是**同一个缺陷**：内容被"抓到它的目标"拥有。每次修复都加了一个补偿机制（`also_tracker_ids` → `tracker_ids` 透镜 → 按 owner 的融合轮次 → 透镜简报）。本次用一个关系替换它们。

## 模型（三句话）

1. 所有源 → **一个全局文章池**（文章只带出处盖章：tier / from_account）→ **全局线索** → 每条线索**摘要一次**，中立地写"发生了什么"。
2. 目标 = 对线索池的一个**查询**（画像：实体 / 官方域名 / 排除词，`services/target_profile.py`）。
3. "这条线索和目标 X 有没有关系"是一个**独立、对称**的问题，答案存在 `ThreadTarget(thread_id, tracker_id, source, llm_verdict)`。

## 关系从哪来（`services/thread_targets.py`）

| source | 含义 |
|---|---|
| `match` | 确定性匹配器（`attribution`）对**全部**目标一视同仁地判：官方域名命中 / 标题实体 / 正文≥2 实体 / ignore 否决。没有"抓取者特例"。 |
| `route` | **聚合层**条目能入库，是因为它通过了发现它的目标的关键词路由和 keep_keywords——搜索引擎已经把它匹配给了该目标。curated/primary 路由的"发现"不构成关系（DeepMind 的帖子经 openAI 目标的集合抓到，与 openAI 无关）。 |
| `llm` | 摘要模型点名、但匹配器漏掉的目标（补充）。 |
| `llm_verdict` | 摘要模型对"是否真的参与事件"的独立判定：`None` 未判 / `True` / `False`（同名撞车）。**False 只折叠，不删除**——模型会错。 |

`RawArticle.tracker_id` 保留为"经谁发现"（诊断 + 入口过滤的上下文），**任何地方都不再把它读作归属**。

## 由此消失的东西

`RawArticle.also_tracker_ids`、`StoryThread.tracker_ids`、`Storyline.tracker_ids`（列保留、标 DEPRECATED、零读写）；normalizer 的入库可见性盖章；语义层的 `_also_ids` / `_thread_lens`；融合的按目标轮次（`process_tracker_fusion` 循环）、`_lens_profile` / `_target_profile`；摘要提示词里的相关性规则；API 的 `_stored_lens` / 成员可见性并集。

## 由此新增的规则

- **一个目标都不涉及的线索不花钱**（此前"抓取者拥有"掩盖了这条）：迁移实测 18,567 条线索里 1,830 条无人关心。
- 融合**按线索走一遍**（`process_pending_threads`），一条线索无论几个目标关心都只摘要一次。
- 摘要提示词只写事件；"涉及哪些目标"是结构化输出 `concerned_targets`，写回关系表的 `llm_verdict`。用户指令（prompt_override）只在线索恰好涉及一个目标时生效。
- 高关注 = 线索涉及的**任一**目标是高关注。板块 / 告警行 / 发布 topic 需要单一目标时取 `primary_target_id`（未被否决的最小 id）——只是标签，不是立场。

## 呈现

`/threads` 返回 `relevant_tracker_ids`（verdict ≠ False）与 `irrelevant_tracker_ids`（verdict = False）。目标筛选下两者都列出，后者进"模型判为无关/重复（可能误判，展开核对）"折叠区；"全部"视图不受影响。

## 迁移 0022

对全部线索按同一对称规则从成员重建关系（确定性，无 LLM，实库副本 24 秒：21,966 条关系 / 3,641 条线索涉及 ≥2 目标）。**不读旧透镜列**——它们带着本次要消除的"赛跑归属"。对照：WeatherNext 线索旧透镜 `[gemini, grok, openAI]` → 新关系 `gemini`；SDLC 手册 → `claude`。

## 已知边界

- `llm_verdict` 会错：实测"Claude's Theorem"论文被判为同名撞车（文本里确实没有任何 AI 线索）。架构的回答是让错判**代价小且可见**（折叠在一个目标筛选下，摘要不受污染，"全部"照常显示）；纠错入口归 P3.1 反馈。
- 匹配器靠实体画像，画像缺词就漏配——重规划（P4.0c）与 `rebuild_recent` 维护任务会把新画像补到近 30 天线索上。
