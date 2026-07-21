# site/ — OnlyFourBot 公开站

愿景 #1 的「作者公开网站」。已部署到 Cloudflare Pages（`onlyforbots.com`，Git 集成，
push `main` 自动部署）。两个页面，两类读者：

| 文件 | 路径 | 读者 | 作用 |
|---|---|---|---|
| [index.html](index.html) | `/` | 机器/开发者 + 冷访客（搜索/域名进来） | 介绍页：定位说明 + 接入方式（CLI/MCP/API，含规划中项） |
| [radar.html](radar.html) | `/radar` | 人类（应用链接直达） | 信息页：去噪线索流 |
| [llms.txt](llms.txt) | `/llms.txt` | LLM 爬虫 | 机器可读的站点说明；只列现能访问的 endpoint，规划中项归 planned |

介绍页是自包含的（内联 CSS，源自 [docs/onlyfourbot_site_concept.html](../docs/onlyfourbot_site_concept.html)）。
信息页与数据契约解耦，是并行开发的锚点。

## 信息页：与功能重构并行的方式

- 数据接口 = [docs/publish_contract.md](../docs/publish_contract.md)（PublishedDigest v0.1）。
- 只消费契约 JSON；[app.js](assets/app.js) 优先读 `data/digest.json`，读不到回退
  [data/digest.sample.js](data/digest.sample.js)（契约的活样例）。R7 发布导出器产出同构数据后自动切真数据。

## 换皮点（后续视觉设计从这里进）

- [assets/tokens.css](assets/tokens.css)：信息页的全部颜色/字体/间距变量，当前是刻意安静的占位设计。
- [assets/site.css](assets/site.css)：信息页布局结构。
- [assets/app.js](assets/app.js)：渲染逻辑，只认契约字段——设计怎么改都不用动数据层。
- 注：介绍页与信息页目前是两套独立视觉，待统一 design token（后续）。

## 本地预览

```sh
python3 -m http.server 4173 -d site   # / 介绍页，/radar 信息页
```

## 尚未接入（等 R7）

- generated RSS 出口（契约 §7，头部 RSS 链接目前是占位）。
- 真实 digest.json 的构建注入（生成端见 [docs/official_feed_automation.md](../docs/official_feed_automation.md)）。
- 介绍页里 CLI/MCP/API/订阅数字等规划中能力的真实实现。
