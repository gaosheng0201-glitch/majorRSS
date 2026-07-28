# 早期信号源（B2′）— 比新闻更早的痕迹

> 2026-07-28 实测可用。**本文档只提供数据（URL + 配置），不引入任何新代码机制**——按架构裁决，新增领域永远是往预设库/监控里加 URL，不是加 adapter。

## 原理

模型发布、功能上线、产品动向在被人类讨论之前，通常已经在**机器可读的痕迹**里出现了：API 的模型列表冒出新 ID、SDK 里先落地模型常量、文档 changelog 先提交、未发布功能先出现在已发版的 App 里。**推文和新闻是这条时间线的终点，不是起点。**

这个规律**与领域无关**——每个领域都有自己的先导痕迹：

| 领域 | 早期痕迹 |
|---|---|
| AI 模型 | 模型列表 API、SDK releases、未发布功能实测 |
| 罕见病 | ClinicalTrials.gov 新试验注册、FDA 审批库 |
| 独立影展 | FilmFreeway 报名开放、影展官网 |
| 公司追踪 | SEC EDGAR 备案、招聘页变化 |
| 安全 | CVE/NVD |

哪些 URL 适合某个话题，由 **P4.1 发现引擎**回答；本文档是 AI 域的种子。

## 两条通道，按源的形态分（架构裁决：雷达与监控永不合并）

### 雷达道（离散条目的 feed → 进聚类/门控/摘要）

已随预设库落地，见 `docs/source_presets.seed.json` 的 **`ai_early_signals`** 集合：

| 源 | URL | 说明 |
|---|---|---|
| TestingCatalog 泄露 | `https://www.testingcatalog.com/tag/leak/rss/` | 未发布功能的实测发现，**通常早于官方公告数天**。实测 15 条，当日头条即「Anthropic preparing for potential Claude Opus 5 rollout」 |
| TestingCatalog 全量 | `https://www.testingcatalog.com/rss/` | 同上，全量（噪声略高） |
| SDK releases ×5 | 已在库（openai-python/node、anthropic-sdk、mcp-python/ts） | 模型常量常在公告前落进代码 |

建目标时在 `source_scope` 勾选 `ai_early_signals` 即可。

### 监控道（会变的文档 → diff → 直接通知）

**这类不该进雷达管线**：它们是用户指定的确切对象，变化本身即事件，注意力是预先授予的——走雷达会被门控当单源 lead 拦下（架构裁决）。在「订阅监控」里手动添加：

| 目标 | URL | 实测 | 建议配置 |
|---|---|---|---|
| OpenRouter 模型表 | `https://openrouter.ai/api/v1/models` | 200 / 585KB | 各实验室常以匿名代号提前数天~数周挂上生产模型（Polaris Alpha→GPT-5.1、Sherlock Alpha→Grok 4.1）。**当前最早的信号源** |
| models.dev | `https://models.dev/api.json` | 200 / 3.2MB / 173 家 | 能抓到"根本没人发推"的发布 |

⚠️ **尺寸提醒（实测）**：这两个端点分别 585KB / 3.2MB，整页 diff 会产生大量噪声文本（每次价格、上下文长度的微调都算变化）。建议：
- 先只加 **OpenRouter**（较小、信号最密）；
- 观察几天噪声量，必要时用 `diff_policy` 的 `extract_selector` 收窄，或降低轮询频率；
- models.dev 体量大、更新慢，可作为可选补充。

> 若日后噪声证明不可接受，正确的解法仍是**配置**（收窄抽取范围/频率），不是新写一个 JSON diff adapter——那条路已被架构裁决否决。

## 与新鲜度断言（B1）的关系

B1 让"200 但内容陈旧/持续空返回"的源被判 FAILED 而非"安静"。这对早期信号源尤其重要：**一个悄悄停更的泄露源会让你以为"最近没爆料"**，而真相是通道断了。B1 会把它标红。
