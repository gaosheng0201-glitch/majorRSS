# 工作交接与测试清单

> 最后更新：2026-07-06 · 分支 `feat/local-intelligence-radar`（领先 main 13 个提交，工作树干净）
>
> 这份文档用于：作者亲自测试已完成的工作后，再决定继续哪部分。开新会话时从这里接上即可。

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

## 已完成并提交（13 个提交，见 `git log main..HEAD`）
R1–R6 后端全部（获取运行时/账号守卫/语义层/线索/告警/portfolio），经 16 个发现的对抗审查加固；前端雷达阅读页+追赶+重点过滤+高关注+账号保护面板+portfolio 预览+通知投递；Fernet 加密；pytest 16 项；README 重写；macOS bundle targets 修复 + 打包/签名指南。详见 `docs/engineering_baseline.md`（2.9 节列了 16 个修复）。

## 真正剩余（多数卡在作者侧）
- **R7 共享层**（OnlyFourBot / 发布站 / 共享 token 索引）：需 Supabase 实例 + 域名
- **Tauri 签名更新插件实际接入**：需作者 `tauri signer generate` 生成密钥（步骤见 packaging_guide.md）
- **macOS 零警告分发 / Windows 代码签名**：需 Apple 开发者账号（$99/年）/ Authenticode 证书——**其余打包已就绪，见 packaging_guide.md**
- **11 平台 auth 真账号实测**（见 B）
- **页面 diff 并入统一 SourceItem**：蓝图故意延后到语义层稳定后
- **真 OS Keychain**（当前 Fernet+0600 文件已是真加密）：需 keyring 依赖决策

## 恢复工作的入口
下次继续时：读 `docs/vision_and_blueprint.md`（愿景+架构）+ 本文件 + `docs/engineering_baseline.md`（工程现状），git 在 `feat/local-intelligence-radar` 分支。
