# MajorRSS: Information Source Radar (全网信息监听雷达)

这是一个旨在聚合、过滤并提炼高价值 AI 行业信息的自动化监听工具。它将利用 RSSHub 将非标信息源（如 Twitter, TikTok, API 文档）转化为标准 RSS，通过后端定时抓取，并结合大语言模型（LLM）进行“去噪、事实核查与价值提炼”，最终分类输出为「前沿哨所」和「极客雷达」两大板块。

## User Review Required

> [!IMPORTANT]
> 技术栈已根据“最适合爬虫与AI应用”的原则敲定。如果您对以下技术选型没有异议，请批准该计划，我将立即开始执行（初始化工程并实现核心引擎）。

## Selected Tech Stack (已选定技术栈)

考虑到本项目需要进行高强度的网页抓取（包括应对反爬的无头浏览器）、与大模型频繁的结构化数据交互（Fact-Check）以及快速的数据可视化，**Python** 是目前该领域生态最完善的选择。

1. **核心语言**：`Python 3.10+` 
2. **抓取引擎 (Scraper)**：
   - 基础 RSS：`feedparser`
   - 动态/反爬虫文档 (Agentic Scraper)：`Playwright` (带 Stealth 插件的无头浏览器)
3. **AI 过滤与核查 (LLM Engine)**：
   - 使用内置模型（Gemini 3.1 Pro）进行长文本理解、去重和事实核查。
   - 配合 `Pydantic` 强制大模型输出结构化的 JSON 情报（分类、重要度评分、脱水摘要）。
4. **数据持久化 (Storage)**：
   - `SQLite`（本地零配置，非常适合独立的雷达工具。后期扩容可平滑迁移到 PostgreSQL）。
5. **后台调度 (Scheduler)**：
   - `APScheduler`（轻量级的后台定时任务，独立运行抓取循环）。
6. **可视化终端 (Frontend Dashboard)**：
   - `Streamlit`（能用极少代码快速构建极具科技感、支持图表和流式更新的 Data Dashboard，完美契合「情报雷达」的概念）。

## Proposed Architecture

系统初步设计分为 4 个核心模块：

### 1. Data Ingestion (数据摄取层)
- **RSSHub**：作为核心抓取引擎，将各种社交媒体和文档路由转换成标准 RSS/Atom feeds。
- **自定义 Scraper**：对于部分官方 API 文档（如缺少 RSS 的 Changelog 页面），编写定时轻量化爬虫监控 DOM/文本的 Diff 变化。
- **目标源配置矩阵**：
  - **大厂动态**：OpenAI, Anthropic 官方博客及 API Release Notes。
  - **算力基带**：Nvidia, AMD 官方 Newsroom / 开发者更新。
  - **开源舆情**：GitHub Trending (周期性快照), Reddit `r/LocalLLaMA`, HuggingFace Papers / Daily Trending。
  - **社交媒体**：指定的核心 AI X(Twitter) 博主, TikTok 关键词抓取。

### 1.5 混合分层抓取架构 (Hybrid Stratified Scraping Architecture)
> [!NOTE]
> 针对各种信息源的反爬虫强度不同，我们采取“降级与升维”相结合的混合抓取策略，以平衡**时间、算力成本与抓取成功率**。

1. **第一层：基础直连 (低成本，极速)**
   - **适用对象**：HuggingFace、大厂普通技术博客等原生支持 RSS 或无反爬墙的站点。
   - **技术手段**：使用 `feedparser` 或 `httpx` 直接请求解析。
2. **第二层：替代源与镜像降级 (中成本，稳定)**
   - **适用对象**：X (Twitter)、TikTok、Reddit 等封闭且强反爬的社交媒体。
   - **技术手段**：优先抓取开源镜像前端（如 Nitter、ProxiTok）或订阅 Telegram 上的搬运频道，绕过官方。若失效，可接入成熟的第三方 BaaS API (如 github-trending-api)。
3. **第三层：智能体浏览器 (Agentic Scraper) (高成本，降维打击)**
   - **适用对象**：OpenAI/Anthropic 等带有强 Cloudflare 保护的 API 页面，或需要复杂交互（如展开加载）的无 RSS 动态网站。
   - **技术手段**：拉起带 Stealth 插件的 `Playwright` 无头浏览器模拟真人渲染，获取页面文本快照，直接交由 Gemini 3.1 Pro 大模型进行“阅读理解”提取。免疫 CSS DOM 变更与基础人机验证。

### 2. Processing & Fact-Checking (处理与提炼层 - AI Workflow)
- **Cron Job / 轮询服务**：每隔一定时间（如 1 小时）拉取所有配置的 Feeds。
- **LLM Filter Pipeline**：
  - **初筛去重**：对比历史数据，去除重复或极度相似的资讯。
  - **深度核查与总结**：将正文或相关推文上下文输入 LLM（带 System Prompt）。
    - *前沿哨所模式*：提取对行业工作流的真实影响，抛弃营销话术。
    - *极客雷达模式*：总结社区共识与争议，提取高赞/高关注工具链接。

### 3. Storage (持久化层)
- **数据库 (如 Supabase/PostgreSQL)**：
  - `sources` (信息源配置表)
  - `raw_articles` (原始抓取记录表，防止重复处理)
  - `intel_reports` (LLM 处理后的提炼情报表，分栏目归档)

### 4. Delivery (分发与展现层)
- **Web UI**：双列瀑布流或 Dashboard 视图，直观展示两类雷达情报。
- **RSS/API 输出**：将处理后的高质量情报重新生成标准 RSS，供您的 Inoreader/Feedly 订阅，实现**“闭环体验”**。

### 5. Open Source Decentralized Network (开源与分布式共享网络)
作为开源项目，MajorRSS 客户端将支持“一键共享”功能，允许社区用户将自己本地抓取、提炼的高质量情报 Push 到您的中央网站（中心化专属域名）。
- **专属输出格式 (MajorRSS-Sync Protocol)**：定义一套标准化的 JSON Schema，包含 `source_url`, `original_html_hash`, `llm_summary`, `category`, `client_signature` 等字段，规范化不同客户端的数据结构。
- **防投毒与 AI 审查机制 (Anti-Poisoning & Auditing)**：
  为了防止恶意节点或“水军”向您的中央网站投递垃圾广告、钓鱼链接或虚假 AI 新闻，中央服务器必须建立以下防御体系：
  1. **中央 AI 二次审查 (Fact-Checking the Checkers)**：**绝对必要。** 用户上传的内容入库前，必须流经中央服务器的 LLM 安全围栏（Safety Guardrail）。用一个成本较低的小模型（如 Gemini Flash）进行 `[SPAM]`, `[MALICIOUS_LINK]`, `[VALID_NEWS]` 分类判定，剔除“夹带私货”的内容。
  2. **源头白名单约束 (Source Whitelisting)**：中心节点只接受由高权威域名（如 `github.com`, `huggingface.co`, `arxiv.org`, 知名大V的 `x.com`）产生的新闻。如果在 Payload 里发现跳转赌博或营销号的 URL，直接阻断。
  3. **基于签名的信誉系统 (Reputation System)**：使用者需在客户端绑定自己的账户（如 GitHub OAuth 颁发的 Token）。根据其历史贡献的“有效情报率”积累 `Trust Score`。高信誉节点提交的信息可“秒批”上榜，新节点必须进入隔离区接受严苛的 AI+人工抽检。

## Verification Plan

### Automated Tests
- 验证针对不同类型源（GitHub, Reddit, 普通 RSS）的抓取解析逻辑是否正常。
- 验证 LLM Prompt 在面对典型营销文案时的“脱水去噪”能力。

### Manual Verification
- 手动添加几个高频更新的测试源，运行完整 Pipeline，验证生成的“情报”是否符合您的严格审核标准。
