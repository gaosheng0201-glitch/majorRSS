// PublishedDigest v0.1 样例数据 —— 与 docs/publish_contract.md 同步维护。
// 并行开发期间这是"活契约"：重构 session 的发布导出器最终产出同构 JSON。
// 生产环境由构建步骤注入真实 digest.json，本文件仅供原型与设计验证。
window.__OFB_DIGEST__ = {
  contract_version: "0.1",
  generated_at: "2026-07-16T02:00:00Z",
  publisher: { name: "majorflow", instance_id: "author-main", signature: null },
  window: { from: "2026-07-15T02:00:00Z", to: "2026-07-16T02:00:00Z" },
  topics: [
    { id: "ai-frontier", title: "AI 前沿", description: "模型发布、API 变更、基础设施动向", language: "zh" },
    { id: "supply-chain", title: "供应链线报", description: "硬件与代工厂的早期信号", language: "zh" },
    { id: "dev-tools", title: "开发者工具", description: "文档与 changelog 监测", language: "zh" }
  ],
  threads: [
    {
      id: "thr_a41f9c",
      topic_id: "ai-frontier",
      title: "OpenAI 调整 Realtime API 定价，音频输入价格下调约 40%",
      lifecycle: "CONFIRMED",
      fact_level: "verified",
      importance: 4,
      is_resonant: true,
      distinct_source_count: 5,
      first_seen_at: "2026-07-15T09:12:00Z",
      last_update_at: "2026-07-16T01:30:00Z",
      summary: {
        text: "定价页在无公告的情况下先行变更，数小时后官方 changelog 补充了正式条目。音频输入 token 单价下调约四成，文本部分不变。多名开发者确认新价格已在账单中生效。",
        language: "zh",
        ai_generated: true,
        method: "synthesized"
      },
      increments: [
        { at: "2026-07-16T01:30:00Z", note: "官方 changelog 出现对应条目，线索升级为「证实」", citation_indexes: [0] },
        { at: "2026-07-15T14:02:00Z", note: "两家媒体跟进报道，与页面 diff 相互印证", citation_indexes: [2, 3] },
        { at: "2026-07-15T09:12:00Z", note: "页面 diff 监测捕获定价表变更（首次发现）", citation_indexes: [1] }
      ],
      sources: [
        { title: "OpenAI Changelog — Realtime API pricing update", url: "https://platform.openai.com/docs/changelog", site: "openai.com", kind: "first_party", published_at: "2026-07-16T01:10:00Z", quote: null },
        { title: "OpenAI Pricing 页面 diff（监测快照）", url: "https://openai.com/api/pricing/", site: "openai.com", kind: "first_party", published_at: "2026-07-15T09:12:00Z", quote: null },
        { title: "OpenAI quietly cuts Realtime audio pricing", url: "https://example-tech-media.com/openai-realtime-pricing", site: "example-tech-media.com", kind: "media", published_at: "2026-07-15T13:40:00Z", quote: null },
        { title: "Realtime API 价格变动实测", url: "https://example-dev-blog.dev/realtime-price", site: "example-dev-blog.dev", kind: "media", published_at: "2026-07-15T14:02:00Z", quote: null },
        { title: "开发者社区讨论串", url: "https://news.ycombinator.com/item?id=00000000", site: "news.ycombinator.com", kind: "social", published_at: "2026-07-15T10:05:00Z", quote: null }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    },
    {
      id: "thr_b8d201",
      topic_id: "supply-chain",
      title: "线报：某代工厂流出疑似下一代旗舰机中框，散热结构明显加大",
      lifecycle: "LEAD",
      fact_level: "observed",
      importance: 3,
      is_resonant: false,
      distinct_source_count: 1,
      first_seen_at: "2026-07-15T22:47:00Z",
      last_update_at: "2026-07-15T22:47:00Z",
      summary: {
        text: "单一社交来源声称拍到新机中框，称散热腔体积明显大于现款。无第二来源佐证，图片真伪未验证。",
        language: "zh",
        ai_generated: false,
        method: "extractive"
      },
      increments: [
        { at: "2026-07-15T22:47:00Z", note: "首次出现，等待独立来源佐证", citation_indexes: [0] }
      ],
      sources: [
        { title: "供应链爆料账号帖子（日语）", url: "https://x.com/example_leaker/status/000000", site: "x.com", kind: "social", published_at: "2026-07-15T22:30:00Z", quote: "放熱構造は現行モデルより明らかに大きい" }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    },
    {
      id: "thr_c3e77a",
      topic_id: "ai-frontier",
      title: "多家媒体报道某开源模型基准成绩，但复现结果存在分歧",
      lifecycle: "CORROBORATED",
      fact_level: "disputed",
      importance: 3,
      is_resonant: false,
      distinct_source_count: 3,
      first_seen_at: "2026-07-14T08:00:00Z",
      last_update_at: "2026-07-15T19:20:00Z",
      summary: {
        text: "官方技术报告给出的基准分数与两个独立复现结果不一致：一方基本复现，另一方在相同配置下低约 6 个百分点。分歧点疑似在评测采样参数。结论待更多复现。",
        language: "zh",
        ai_generated: true,
        method: "synthesized"
      },
      increments: [
        { at: "2026-07-15T19:20:00Z", note: "第二个独立复现结果发布，与首个复现冲突，线索标记为「有分歧」", citation_indexes: [2] }
      ],
      sources: [
        { title: "模型技术报告（官方）", url: "https://example-lab.ai/tech-report", site: "example-lab.ai", kind: "first_party", published_at: "2026-07-14T07:30:00Z", quote: null },
        { title: "独立复现 A：结果基本一致", url: "https://example-eval.org/repro-a", site: "example-eval.org", kind: "media", published_at: "2026-07-15T02:10:00Z", quote: null },
        { title: "独立复现 B：低约 6 个百分点", url: "https://example-bench.dev/repro-b", site: "example-bench.dev", kind: "media", published_at: "2026-07-15T19:00:00Z", quote: null }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    },
    {
      id: "thr_d90b12",
      topic_id: "dev-tools",
      title: "Anthropic API 文档新增批量请求速率说明",
      lifecycle: "CONFIRMED",
      fact_level: "verified",
      importance: 2,
      is_resonant: false,
      distinct_source_count: 1,
      first_seen_at: "2026-07-15T06:00:00Z",
      last_update_at: "2026-07-15T06:00:00Z",
      summary: {
        text: "文档 diff：速率限制页新增批量请求（batch）独立配额说明一节，未见价格变化。",
        language: "zh",
        ai_generated: true,
        method: "synthesized"
      },
      increments: [
        { at: "2026-07-15T06:00:00Z", note: "changelog 监测捕获文档新增段落", citation_indexes: [0] }
      ],
      sources: [
        { title: "Anthropic Docs — Rate limits（页面 diff）", url: "https://docs.anthropic.com/en/api/rate-limits", site: "docs.anthropic.com", kind: "first_party", published_at: "2026-07-15T06:00:00Z", quote: null }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    },
    {
      id: "thr_e5518f",
      topic_id: "supply-chain",
      title: "两家日媒证实某存储大厂 Q3 调价，与上周社交线报吻合",
      lifecycle: "CORROBORATED",
      fact_level: "verified",
      importance: 4,
      is_resonant: true,
      distinct_source_count: 4,
      first_seen_at: "2026-07-10T11:00:00Z",
      last_update_at: "2026-07-15T16:45:00Z",
      summary: {
        text: "上周仅有单一社交来源的调价传闻，本周被两家日本财经媒体独立证实，幅度与线报一致（约 8–10%）。官方公告尚未发布，线索保持「多源佐证」。",
        language: "zh",
        ai_generated: true,
        method: "synthesized"
      },
      increments: [
        { at: "2026-07-15T16:45:00Z", note: "第二家媒体独立报道，共振信号触发（5 天内 1 源 → 4 源）", citation_indexes: [1, 2] }
      ],
      sources: [
        { title: "最初的社交线报（已归档）", url: "https://x.com/example_supply/status/000001", site: "x.com", kind: "social", published_at: "2026-07-10T10:30:00Z", quote: null },
        { title: "日経系媒体报道", url: "https://example-nikkei.com/storage-price", site: "example-nikkei.com", kind: "media", published_at: "2026-07-15T08:00:00Z", quote: null },
        { title: "第二家财经媒体跟进", url: "https://example-biz.jp/q3-nand", site: "example-biz.jp", kind: "media", published_at: "2026-07-15T16:20:00Z", quote: null },
        { title: "渠道商价格表变动讨论", url: "https://example-forum.com/thread/8812", site: "example-forum.com", kind: "social", published_at: "2026-07-14T13:00:00Z", quote: null }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    },
    {
      id: "thr_f207cc",
      topic_id: "ai-frontier",
      title: "传某云厂商将推出推理专用实例，仅一家二线媒体报道",
      lifecycle: "LEAD",
      fact_level: "low_confidence",
      importance: 2,
      is_resonant: false,
      distinct_source_count: 1,
      first_seen_at: "2026-07-15T12:00:00Z",
      last_update_at: "2026-07-15T12:00:00Z",
      summary: {
        text: "单一媒体来源，未引用具名信源，官方渠道无对应信号。仅供留意，不作结论。",
        language: "zh",
        ai_generated: false,
        method: "extractive"
      },
      increments: [
        { at: "2026-07-15T12:00:00Z", note: "首次出现", citation_indexes: [0] }
      ],
      sources: [
        { title: "二线媒体独家报道", url: "https://example-rumor-media.com/inference-instance", site: "example-rumor-media.com", kind: "media", published_at: "2026-07-15T11:30:00Z", quote: null }
      ],
      provenance: { pii_cleaned: true, auth_content_excluded: true, rights: "public_summary" }
    }
  ],
  stats: {
    window_hours: 24,
    ingested: 412,
    noise_filtered: 358,
    duplicates_merged: 31,
    events_tracked: 6
  }
};
