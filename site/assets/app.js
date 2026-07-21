/* 分发页面渲染器。
   只依赖 docs/publish_contract.md 定义的 PublishedDigest 契约字段；
   未知字段一律忽略，可选字段缺失时降级。视觉不在这里，全在 CSS。 */
(function () {
  "use strict";

  var digest = window.__OFB_DIGEST__;
  var streamEl = document.getElementById("stream");
  if (!digest || !Array.isArray(digest.threads)) {
    streamEl.innerHTML = '<p class="empty">暂无内容。</p>';
    return;
  }

  /* ---- 契约枚举 → 展示文案（与 UI 语言绑定，不进契约） ---- */
  var LIFECYCLE = {
    LEAD:         { label: "线报 · 未证实", cls: "lead" },
    CORROBORATED: { label: "多源佐证",      cls: "corroborated" },
    CONFIRMED:    { label: "一手证实",      cls: "confirmed" }
  };
  var FACT_LEVEL = {
    disputed:       "来源之间存在分歧",
    low_confidence: "单一来源 · 可信度不足",
    observed:       null,   // LEAD 徽章已表达，不重复
    verified:       null    // 默认状态不加话
  };
  var SOURCE_KIND = {
    first_party:    { label: "一手", cls: "first-party" },
    media:          { label: "媒体", cls: "" },
    social:         { label: "社交", cls: "" },
    generated_feed: { label: "生成源", cls: "" }
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtTime(iso, withDate) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var opts = withDate
      ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" };
    return d.toLocaleString("zh-CN", opts);
  }

  /* ---- 头部：期号 + 安静的统计行 ---- */
  var editionEl = document.getElementById("edition");
  if (digest.window && digest.window.to) {
    var to = new Date(digest.window.to);
    editionEl.innerHTML =
      '截至 <time datetime="' + esc(digest.window.to) + '">' +
      to.toLocaleString("zh-CN", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }) +
      "</time>";
  }

  var statsEl = document.getElementById("stats");
  var st = digest.stats;
  if (st) {
    statsEl.textContent =
      "过去 " + (st.window_hours || 24) + " 小时：摄入 " + st.ingested +
      " 条，过滤噪音 " + st.noise_filtered + " 条，归并重复 " + st.duplicates_merged +
      " 条，沉淀为 " + st.events_tracked + " 条线索。";
  }

  /* ---- 话题过滤 ---- */
  var topics = digest.topics || [];
  var topicTitle = {};
  topics.forEach(function (t) { topicTitle[t.id] = t.title; });

  var nav = document.getElementById("topic-nav");
  var active = "all";

  function renderNav() {
    var items = [{ id: "all", title: "全部" }].concat(topics);
    nav.innerHTML = items.map(function (t) {
      return '<button aria-pressed="' + (active === t.id) + '" data-topic="' + esc(t.id) + '">' + esc(t.title) + "</button>";
    }).join("");
  }

  nav.addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-topic]");
    if (!btn) return;
    active = btn.getAttribute("data-topic");
    renderNav();
    renderStream();
  });

  /* ---- 线索流 ---- */
  function sortedSources(sources) {
    var order = { first_party: 0, media: 1, generated_feed: 2, social: 3 };
    return (sources || []).slice().sort(function (a, b) {
      return (order[a.kind] != null ? order[a.kind] : 9) - (order[b.kind] != null ? order[b.kind] : 9);
    });
  }

  function renderThread(th) {
    var lc = LIFECYCLE[th.lifecycle] || { label: th.lifecycle, cls: "corroborated" };
    var meta = ['<span class="badge ' + lc.cls + '">' + esc(lc.label) + "</span>"];

    var factNote = FACT_LEVEL[th.fact_level];
    if (th.fact_level === "disputed") {
      meta.push('<span class="badge disputed">' + esc(factNote) + "</span>");
    } else if (factNote) {
      meta.push("<span>" + esc(factNote) + "</span>");
    }

    if (th.is_resonant) meta.push('<span class="resonant-mark">共振中</span>');
    if (th.distinct_source_count > 1) meta.push("<span>" + th.distinct_source_count + " 个独立来源</span>");
    if (topicTitle[th.topic_id]) meta.push("<span>" + esc(topicTitle[th.topic_id]) + "</span>");
    meta.push('<span><time datetime="' + esc(th.last_update_at) + '">' + fmtTime(th.last_update_at, true) + " 更新</time></span>");

    var html = '<article class="thread" data-topic="' + esc(th.topic_id) + '">';
    html += '<div class="thread-meta">' + meta.join("") + "</div>";
    html += "<h2>" + esc(th.title) + "</h2>";

    if (th.summary && th.summary.text) {
      html += '<p class="thread-summary">' + esc(th.summary.text) + "</p>";
      var notes = [];
      if (th.summary.ai_generated) notes.push("AI 归纳，结论以下方来源为准");
      if (th.summary.method === "extractive") notes.push("置信不足：仅呈现来源关键句，不作结论");
      if (notes.length) html += '<p class="summary-note">' + esc(notes.join(" · ")) + "</p>";
    }

    /* 短引用（契约：≤90 字，必须署名带链接） */
    sortedSources(th.sources).forEach(function (s) {
      if (s.quote) {
        html += '<blockquote class="quote">“' + esc(s.quote) + '”<br><cite>—— <a href="' + esc(s.url) +
          '" rel="noopener" target="_blank">' + esc(s.site || s.title) + "</a></cite></blockquote>";
      }
    });

    var incs = th.increments || [];
    if (incs.length) {
      html += '<ul class="increments">' + incs.map(function (inc) {
        return "<li><time datetime=\"" + esc(inc.at) + "\">" + fmtTime(inc.at, true) + "</time>" + esc(inc.note) + "</li>";
      }).join("") + "</ul>";
    }

    var srcs = sortedSources(th.sources);
    if (srcs.length) {
      var firstParty = srcs.filter(function (s) { return s.kind === "first_party"; }).length;
      var label = srcs.length + " 个来源" + (firstParty ? " · 含 " + firstParty + " 个一手来源" : "");
      html += '<details class="sources"><summary>' + esc(label) + "</summary><ol>" +
        srcs.map(function (s) {
          var kind = SOURCE_KIND[s.kind] || { label: s.kind || "", cls: "" };
          return '<li><span class="source-kind ' + kind.cls + '">' + esc(kind.label) + "</span>" +
            '<a href="' + esc(s.url) + '" rel="noopener" target="_blank">' + esc(s.title) + "</a>" +
            '<time datetime="' + esc(s.published_at) + '">' + fmtTime(s.published_at, true) + "</time></li>";
        }).join("") + "</ol></details>";
    }

    html += "</article>";
    return html;
  }

  function renderStream() {
    var threads = digest.threads.filter(function (th) {
      return active === "all" || th.topic_id === active;
    });
    // 排序：共振优先，其次重要度，其次最新更新
    threads.sort(function (a, b) {
      if (!!b.is_resonant - !!a.is_resonant) return (!!b.is_resonant) - (!!a.is_resonant);
      if ((b.importance || 0) !== (a.importance || 0)) return (b.importance || 0) - (a.importance || 0);
      return String(b.last_update_at).localeCompare(String(a.last_update_at));
    });
    streamEl.innerHTML = threads.length
      ? threads.map(renderThread).join("")
      : '<p class="empty">这个话题暂时没有新线索。</p>';
  }

  renderNav();
  renderStream();
})();
