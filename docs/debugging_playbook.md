# 排查手册 —— 症状 → 去哪看（考古依据）

> 2026-09-24 起维护。目的：出了问题不用翻对话史,按症状直接找到对应的表、日志标记、脚本和当时的裁决。每条机制的"为什么这样做"在源文件头注释与 [radar_quality_roadmap.md](radar_quality_roadmap.md)（裁决/复盘按日期）、CHANGELOG.md（按批次）;本文只管"怎么查"。
>
> 约定：日志 `~/.majorss/logs/majorss.log`（本地时间 EDT,5MB×3 轮转）;数据库 `~/.majorss/major_rss.db`（`created_at` 等为 UTC,与日志差 4 小时）;**任何实验先 `cp` 一份副本再 `DATABASE_URL=sqlite:///<副本>`**,严禁对实库跑写脚本（例外：一次性修复,须逐线索小事务提交,见"教训"）。

## 0. 先看整体

```bash
curl -s http://127.0.0.1:8765/api/settings/health | head -c 300        # 后端/调度器心跳
sqlite3 ~/.majorss/major_rss.db "SELECT version_id FROM schemaversion ORDER BY version_id DESC LIMIT 1;"  # 迁移落到哪
grep "Semantic ingest:" ~/.majorss/logs/majorss.log | tail -3           # 每轮语义汇总(见 §2 字段)
grep -cE "Traceback| ERROR " ~/.majorss/logs/majorss.log
```

## 1. "这条新闻为什么没进 / 进晚了"

| 步骤 | 查什么 | 怎么查 |
|---|---|---|
| 抓到没有 | `rawarticle` | `SELECT id,tracker_id,source_tier,thread_id,created_at,url FROM rawarticle WHERE lower(title) LIKE '%关键词%'` |
| 源在不在 | 路由 | `SourceResolver(fetch_policy=...)._resolve_keyword_routes(...)`（别名路由 `gnews_alias_N`、后继探测,见 `source_resolver.py`）;预设路由 `preset_*`;`pipelineevent` 按 `route_id` 看 SUCCESS/FAILED/SKIPPED |
| 官方源漏了 | 第三方 feed 按路径过滤 | Fable 5.1 案例(公告不在 /news/ 下):解法=page_monitor 类建议源 → Subscription |
| 关键词太笼统 | gnews 100 条上限 | "gemini" 100 条里 2 条提 Gemini 4;具体别名各自成路由是为此 |
| X 通道 | nitter 410 | `pipelineevent` 里 `nitter_*` 全 FAIL/SKIP;无账号唯一路径=Grok relay(待 xAI key),一手=授权 agentic(待小号) |

## 2. "线索分错了 / 串目标 / 挂在错的目标下"

关系只有一张表：**`threadtarget(thread_id, tracker_id, source, llm_verdict, score)`**。

- `source`：`match`=确定性匹配器（`attribution.py`：官方域名 / 标题实体 / 正文≥2 且导语内）、`route`=聚合层条目经该目标关键词路由发现、`llm`=摘要模型点名、`model`=探针补漏
- `llm_verdict`：`NULL` 未判;`True` 参与;`False` **折叠不删**（摘要模型判同名撞车/被比较,或探针否决）
- `score`：探针概率（有启用探针时）

```sql
-- 某线索挂了哪些目标、谁判的
SELECT k.name, r.source, r.llm_verdict, r.score FROM threadtarget r JOIN tracker k ON k.id=r.tracker_id WHERE r.thread_id=<id>;
-- 探针状态
SELECT tracker_id, enabled, auc, n_pos, n_neg, add_threshold, veto_threshold, trained_at FROM targetmodel;
```

日志：`Semantic ingest: ... | probes +a -v`（本轮探针补/否决数）。规则在 `services/merge_policy.py`(合并) 与 `services/relation_model.py`(关系,阈值 add≥0.80 / veto≤0.20,校准依据在文件头)。

历史裁决：可见性集合(8/26,已废) → 透镜(9/1,已废) → **目标即查询**(9/17,现行,`targets_are_queries.md`) → 被比较≠参与(9/24) → **学出来的关系**(9/24)。旧列 `rawarticle.also_tracker_ids`、`storythread.tracker_ids` 已 DEPRECATED,零读写。

## 3. "同一件事出了两张卡 / 两条线索被错并"

- 入库仲裁：日志 `Arbiter split (sim=…)`、`Arbiter rescue`、`Storyline link`;**预算耗尽/调用出错=不并**（9/9 裁决）
- 事后合并：日志 `Merge (sim=…): thread B → A`、`Merge pass: N pairs judged, M merged, L storyline links`;判定记忆 **`threadpairverdict(thread_a, thread_b, verdict, similarity)`**——同一对不会重复问
- 阈值：`services/merge_policy.py`（入库 floor 0.05 / 置信 0.80 / top-3 / 300 次;事后 ≥0.70 / 48h / 20 对）
- 错并复查脚本（9/9 用过）：对"重摘要且有 14 天后加入成员"的线索逐成员问仲裁——写在 CHANGELOG 9/9 条;**必须按线索逐条提交**（长事务曾和应用抢锁）

```sql
SELECT * FROM threadpairverdict WHERE thread_a=<id> OR thread_b=<id>;
SELECT id, member_count, (SELECT COUNT(*) FROM rawarticle WHERE thread_id=storythread.id) real FROM storythread WHERE id=<id>;  -- 计数与实际不符=合并遗留,重算
```

## 4. "为什么没提炼 / 为什么被判无关 / 摘要花钱在哪"

- 门控日志（`processor`）：`Thread N concerns no target`（无目标不花钱）、`gated — no summary (原因)`、`no material increment`、`Fused thread N: [VALID_NEWS] score`、`cross-tracker duplicate`
- 生命周期唯一规则 `services/lifecycle.py`（primary 盖章→CONFIRMED;≥2 出版方→CORROBORATED;只升不降）;盖章唯一入口 `provenance.tier_for_url`（消费期零推导,NULL=0）
- 消防栓源恒为 AGGREGATED（`provenance.is_firehose_url`,arXiv/HN 首页/GitHub trending）——曾占融合支出 3/4
- 摘要中立、"涉及目标"是独立字段 `concerned_targets`（`llm/processor.py`）;判 NOISE 的在提炼面折叠"模型判为无关（可核对）"
- 引用 vs 佐证：`storythread.cited_article_ids`;卡片两组

```sql
SELECT action_type, COUNT(*), SUM(total_tokens) FROM tokenusage WHERE created_at >= date('now','-1 day') GROUP BY 1 ORDER BY 3 DESC;  -- 今天钱花在哪
```

不变量（应恒为 0）：
```sql
SELECT COUNT(*) FROM storythread t WHERE lifecycle='CONFIRMED' AND NOT EXISTS (SELECT 1 FROM rawarticle a WHERE a.thread_id=t.id AND a.source_tier='primary');
SELECT COUNT(*) FROM rawarticle WHERE source_tier IS NULL;
SELECT COUNT(*) FROM rawarticle WHERE url LIKE '%arxiv.org%' AND source_tier IN ('primary','curated');
```

## 5. "词表 / 别名 / 建议源"

- 目标的一切在 `tracker.fetch_policy`(JSON)：`entities`（别名,派生搜索路由与匹配）、`intent_plan.official_domains`、`intent_plan.suggested_sources[].selected`
- 自动增长：`Vocab refresh: 'X' learned [...]; suggested [...]`（`vocab_refresh.py`,模型读线报标题,数据裁决,core 自动/context 建议）;`Emergent term auto-added as alias`（版本短语,`emergent_sources.py`）;`Emergent sources: scanned…`
- 建议区：`emergentsource(kind=account|domain|term, status=pending|accepted|dismissed)`;雷达页顶部一行
- 规划器世界知识过期（它把 Gemini 的下一代说成 2.5/3）——所以"什么在路上"只从数据学;replan 别名只增不删

## 6. "告警 / 趋势"

`alert_engine.evaluate_alerts`（共振/高关注）+ `evaluate_entity_spikes`（原 TrendScan,9/24 并入：≥3 线索、每实体每日一次、每轮 ≤3）;日志 `Entity spike: 'X' across N threads`;表 `radaralert` / `trendalert`。

## 7. 仲裁模型评估

`scripts/bench_arbiter.py`（任意 provider,标注对,并线正确率/故事线召回/token/延迟）;当前 gemini-3.8-flash + `thinking_level="low"`（9 对×2:17/18,177 token/次）。

## 7.5 "Mac 发烫 / sidecar 占满一个核"

`ps -o %cpu,rss,time -p $(pgrep -f backend-sidecar)` → `sample <pid> 5`（原生栈里 `scan_once_unicode`/`PyFloat_FromString` = 在解析向量 JSON,`cosine` 纯 Python 循环不会出现在原生栈但会占满 `_PyEval`）;日志 `~/.majorss/logs/majorss.log` 里 `semantic_clustering` 的 Running→executed 间隔 ≥5 分钟或出现 `maximum number of running instances` = 这一轮跑满了整个间隔,等于一直在跑。9/25 实测:3.3 万条嵌入 × 3072 维,每轮 ~5 分钟(全量解析嵌入求均值 ×2、每篇对 1.16 万线索纯 Python 余弦、合并轮 160 万对),常驻 100% CPU / 6 GB。现在:语料均值是增量累加(累加和持久化在 `<数据目录>/cache/corpus_mean.npz`,探针均值在训练时存为 `probe_mean.npy`,均可随时删除、下次自动重建)、线索质心按内容哈希缓存、近邻与全对用 numpy 矩阵,无新文章时合并轮直接跳过;热轮 ~1 s。定时任务跑在 macOS `utility` QoS(日维护 `background`,只用能效核),用户触发的任务保持默认;任务线程 CPU 超过间隔 20% 会记 `Job X used Ns CPU … (budget 20%)` 警告——看到它就是回归了。9/27 打包版实测:空转轮 1–2 s,有 9 篇新文章的一轮 69 s 墙钟(几乎全是 25 次仲裁调用的网络等待),维护后 5 分钟均值 8.8% CPU、空闲时 0%,RSS ~450–650 MB。正常的短时尖峰只有两类:启动后第一次有新文章时加载 30 天线索池(~6 s),以及每日维护(启动 15 分钟后首跑,~4.5 min,background QoS)。

## 7.6 收口后新增机制的排查入口（2026-09-28）

| 症状 | 看哪里 |
|---|---|
| 摘要/入库/告警突然停了 | 日志 `Daily LLM token budget exhausted (用量/上限): <阶段> paused until 00:00 UTC`（`services/llm_budget.py`,每阶段每天记一次）；单个目标停：`'<名>' reached its daily token cap` / `summary deferred`。上限在系统设置 → 模型配置（全局）与目标开发者设置（每目标） |
| 「运行并追踪 / 试运行 / 立即检查」转圈或报错 | 前端轮询 `GET /api/tasks/{id}`；表 `taskrequest` 里 `job_type LIKE 'USER_%'`（status/error/payload.result）。重启会把进行中的用户任务收成 FAILED「Interrupted」 |
| 文章抓到了但雷达里没有 | `GET /api/settings/db-status` 的 `pipeline_health`（两项都应为 0,非 0 设置页有橙色提示）；日志 `failed to embed 3x in a row; parked until next launch` = 该文章本进程内搁置 |
| 某账号源每轮都 SKIPPED | trace 事件 error=`auth:expired` = 目标绑定的授权已过期,重新授权即恢复（公开页面会改走匿名抓取,不会撞登录墙） |
| 打开电脑没看到离开期间的重要消息 | 雷达页顶部「你离开期间」卡片 = `GET /api/intelligence/away?since=`（告警 + 离开后新出现的已证实/共振事件,只含与目标相关的,最多 8 条）；前端 localStorage `radar_last_active_at`（最后一次窗口在前台且聚焦）/ `radar_away_since`（回来时冻结,点「知道了」清除）；离开 < 15 分钟不算离开；菜单栏图标旁数字 = 同一份列表的条数（Tauri 命令 `set_tray_badge`）。**不会**为此阻止睡眠——睡眠期间只能醒后补抓 |
| 新型号发布被并进了上一代的老线索 | 相似度 ≥0.80 且标题近乎相同（转载）才免仲裁;模板相同型号不同 → 仲裁。日志里该文章若无 `Arbiter` 行且进了老线索,查 `dedup.is_near_duplicate(新标题, 线索标题)` |
| 同一线索被摘要两次 / 摘要突然「重写」 | 不应再发生（`pipeline_lock.py`）；重融日志带 `update of previous summary` = 走的是「旧摘要 + 新成员」更新模式 |

## 8. 教训（别再踩）

- 对实库跑长事务脚本会与应用抢锁（9/9 丢了 95 条 token 记账）→ 逐条提交
- 探针负例只用"对手线索"会让中等分数失去意义（VS Code 发布说明被 0.4 补给三目标）→ 必须含背景负例 + 门槛钉死
- 同主题的多语言目标会被严格分类器当成不同实体 → 提示词明写"语言变体一视同仁"
- 文件里残留旧函数定义会静默覆盖新版（`refresh_all` 9/22）→ 改完 grep 一次 `^def 名字`
- 日志行被 `cut` 截断后再解读会误判（把 13908 看成 1390）
- 随库增长的每轮全量扫描（全表读 + 纯 Python 向量运算）会悄悄变成常驻负载 → 每轮只处理增量,向量运算走 numpy
