# 工作交接与测试清单

> 最后更新：2026-09-24 · 分支 `main`（公开仓库，直接推 main）
>
> 这份文档用于：作者亲自体验几天测试后，再决定继续哪部分。开新会话时从这里接上即可。
> 7-21 之后的全部改造（P0–P2 路线图执行、B1–B6 供给侧、P4 前置管线修复、呈现层三修、P6 雷达收口与时间诚实）见 CHANGELOG.md 与 `docs/radar_quality_roadmap.md`；工程现状见 `docs/engineering_baseline.md`。测试 58 项。
>
> **2026-09-28 收口**：第一类遗留全部清零——融合互斥锁与真增量重融、全后台预算刹车 + 每目标摘要上限（系统设置 / 目标开发者设置可改）、简报接地性（推断标〔分析〕）、编辑目标不再抹掉意图规划与授权、运行/试运行改后台任务（`GET /tasks/{id}`）、过期授权不再撞登录墙、HTML 清洗统一、macOS 退出清理整棵进程树、依赖补全;测试 129 项。**不做 / 下一期**的清单与理由见 [engineering_baseline.md](engineering_baseline.md) §3–§4。
>
> **2026-09-27 状态增补**：后台功耗治理——语义任务每轮从 ~5 分钟（常驻 100% CPU）降到 ~1 s，调度任务改低 QoS + CPU 预算告警，测试 115 项。新约束「托盘常驻 = 静默的资源预算」见 engineering_baseline §1；发烫排查见 debugging_playbook §7.5。向量改二进制存储待裁决（baseline §3.2）。
>
> **2026-09-24 状态增补**：测试 110 项;迁移 0001–0024。8/26 以来的大块：目标即查询（线索无主、`threadtarget` 关系表）、消防栓层级与盖章不变量、别名路由/后继探测/涌现关键词/接地词汇刷新（目标词表自动生长）、事后合并（`merge_policy.py` 唯一阈值声明）、引用 vs 佐证恢复、TrendScan 并入 alert_engine、学出来的关系（每目标探针）。**排查从 [debugging_playbook.md](debugging_playbook.md) 起**。仍等作者：xAI key 或小号（X 通道）、P8/P9 设计合同审阅、P5 暂放。
>
> **2026-08-13 状态增补**：agentic/浏览器管线已修复（打包版可用，dev 机需 `playwright install chromium` 一次）；交互式授权登录已验证到弹窗（B 节第一项半通），cookie 段等作者小号；雷达页已是唯一阅读面（AI 模式 提炼|线报 双 tab + 目标筛选，纯 RSS 模式 = 原始订阅流）。挂起等作者：浏览器打包粒度、P5 方案、授权实测。

## 怎么把它跑起来

```bash
# 后端（Python 3.10+）
source .venv/bin/activate
pip install -r requirements.txt          # 若首次：playwright install chromium
python backend/main.py                    # 127.0.0.1:8765

# 桌面端（另开一个终端）
cd desktop && npm install
npx tauri dev                             # 真机完整体验（含系统通知）
# 或只看前端：npm run dev → 浏览器开 localhost:5173（Tauri 专有功能会自动跳过）

# 公开分发站（R7）：先让后端生成 digest，再起静态站
curl -X POST http://127.0.0.1:8765/api/settings/publish   # 生成 site/data/digest.json + feed.xml
python3 -m http.server 4173 -d site                        # 浏览器开 localhost:4173
# 或让后端自动定时发布：设环境变量 PUBLISH_ENABLED=1（默认关，私人雷达不会误发布）

# 测试
pytest -q                                 # 58 项，~0.5s
```

配 API key / 选模型 / 切模式：应用内 **系统设置** 页（不需要 .env）。

## 请作者亲自测试的（"测试债"清单）

我在浏览器里验证过前端渲染、后端跑过单测与集成，但**以下需要真机 / 真实凭证 / 真实使用感受**才能确认：

### A. 真实模型接入后的行为（最关键）
- [ ] 配一个真实 Gemini key（或指向本地 Ollama：设 `LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL`），建一个你真关心的目标，跑几轮
- [ ] 确认**相关性门生效**：无 key 时噪音会漏进来（如关键词"ajax"会带进阿姆斯特丹足球队新闻，这是**预期行为**，见下方"已知预期"）；配 key 后应被过滤
- [ ] 确认 AI 摘要 / 每日简报 / 趋势用的是你选的 provider，token 记账在"计费与消耗审计"页可见
- [ ] 确认每日 token 预算刹车（设 `LLM_DAILY_TOKEN_BUDGET`）超额后停融合

### B. 授权账号（需要你的真实社媒登录）
- [ ] 逐个平台一键授权，看抓取是否真的用上登录态（`AUTH_PLATFORMS` 的 11 个平台定义**未经真账号实测**，是待验证脚手架）
  - 2026-08-05 进展：登录弹窗链路已通（浏览器修复后实测弹出）；作者决定等小号再走完 cookie 段（主号防封）。失败诊断已改为报告捕获到的 cookie 名/域（不含值）
- [ ] 观察 **系统设置 → 授权账号保护** 面板：熔断/预算/利用率是否合理
- [ ] 故意让某平台 cookie 过期，确认抓取撞登录墙后账号被标 Expired

### C. 真机桌面体验
- [ ] `npx tauri dev` 跑起来，整体 UX 感受（雷达阅读页是否舒适、信息是否够看）
- [ ] **系统通知投递**（只有真机 tauri 能测）：高关注目标出现证实/共振时是否弹系统通知、且每条只弹一次
- [ ] 窗口/托盘/关闭到托盘行为

### D. 升级路径（重要，我只在脚本里验证过）
- [ ] 用一个**有旧数据的库**启动一次，确认 migration 0006 自动补上新列、不崩（我实测过预升级库，但你的真实库值得再确认一次）
- [ ] 旧的 base64 加密的 config.dat / cookie 文件能否被新 Fernet 逻辑正常读出（迁移兼容）

## 已知预期行为（别误报为 bug）
- **无 API key 时噪音多**：相关性门只在配了真实 embedder 时启用（兜底词袋 embedder 不做过滤，是防误杀的安全设计）。默认体验依赖你接模型。
- **兜底 embedder 跨语言/改写聚类弱**：无 key 时同一事件可能拆成多条细线索（"欠合并"，安全方向）；真实 embedder 会合并。
- **无 key 时日志有 "No generation model configured" traceback**：这是融合的优雅降级，已被捕获，不是崩溃。
- **雷达页 `in` 属性 React 警告**：预先存在（来自 Mantine 某组件），非本次改动引入，无害。

### E. 公开分发站（R7 Phase 1，新完成）
- [ ] 建几个真实目标、跑一阵有内容后，`POST /settings/publish` → 开 `localhost:4173` 看公开站
- [ ] 确认合规门：摘要非全文、每条来源可点到源头、页脚有下架邮箱；**授权（登录态）平台来源的线索不出现在站上**（保守按域名排除，见下方预期行为）
- [ ] 无 key 时摘要走抽取式、标注"置信不足"；配 key 后应是 AI 合成摘要
- [ ] generated RSS：`localhost:4173/data/feed.xml`

## 已知预期行为（补充）
- **公开站授权内容排除偏保守**：Phase 1 按"来源域名匹配 AUTH_PLATFORMS 即整条线索不发布"实现（安全优先，会连带排除该平台的公开内容）。后续可加 per-article 授权标记精细化。
- **公开站 digest 是运行产物**：`site/data/digest.json` / `feed.xml` 已 gitignore，由 `POST /settings/publish` 或 `PUBLISH_ENABLED=1` 定时任务生成；仓库里只有样例 `digest.sample.js`。

## 已完成并提交（见 `git log`）
R1–R6 后端全部（获取运行时/账号守卫/语义层/线索/告警/portfolio），经 16 个发现的对抗审查加固；前端雷达阅读页+追赶+重点过滤+高关注+账号保护面板+portfolio 预览+通知投递；Fernet 加密；README 重写；macOS bundle targets 修复 + 打包/签名指南。**2026-07-21 收尾**：R7 Phase 1 发布导出器（services/publish_service.py，合规门全过 → PublishedDigest v0.1 → 公开站接真实数据 + generated RSS，scheduler publish_digest 任务 + POST /settings/publish）；pytest 扩到 24 项（含发布合规门/语义流程）。详见 `docs/engineering_baseline.md`、`docs/publish_contract.md`（数据契约）、`docs/official_feed_automation.md`（官方源自动化三形态）。

## 收口时的状态（2026-09-28）
没有未完成的承诺项。收口时逐项定过性、写明理由的两张清单都在 [engineering_baseline.md](engineering_baseline.md)：
- **§3.1 挂起的裁决（不做，除非作者重启）**：浏览器分发、P5 编辑价值门、向量二进制存储、授权真账号实测 / X 通道、改名 MajoSleuth + 域名、签名与分发、官方源无人值守托管、系统钥匙串。
- **§4 下一期候选（有设计、无实现）**：P7a 订阅频道、P9 监控判读、P8 云端分体、P7b 共享索引、R7 Phase 2/3、情报溯源重设计、页面 diff 并入 SourceItem、P3.1 反馈闭环（最后做）。
上面的「测试债」A–E 仍是只有作者能做的真机/真账号验证。

## 恢复工作的入口
项目已收口。若重启：先读 [engineering_baseline.md](engineering_baseline.md)（现状 + §3 挂起裁决 + §4 下一期候选）→ 选定的那一项的设计合同（`cloud_split_design.md` / `monitor_diff_design.md` / `publish_contract.md` §8 / `investigator_redesign.md`）→ [radar_quality_roadmap.md](radar_quality_roadmap.md)（裁决史）。症状排查从 [debugging_playbook.md](debugging_playbook.md) 起。git 在 `main`（公开仓库；backend-bundle/.env/.enckey/config.dat 已 gitignore，严禁入库）。数据库测试一律 `DATABASE_URL` 指向副本。
