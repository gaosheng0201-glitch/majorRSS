# site/ — OnlyFourBot 公开站 · 分发页面

这是愿景 #1 的「作者公开网站」里**分发去噪信息的页面**（不是营销主页——那个概念稿在
[docs/onlyfourbot_site_concept.html](../docs/onlyfourbot_site_concept.html)，两者定位不同）。

## 与功能重构并行的方式

- 数据接口 = [docs/publish_contract.md](../docs/publish_contract.md)（PublishedDigest v0.1）。
- 本页面只消费契约 JSON；重构 session 的 R7 发布导出器最终产出同构数据。
- 并行期间用 [data/digest.sample.js](data/digest.sample.js) 驱动，它是契约的活样例，两边都以它对表。

## 换皮点（后续视觉设计从这里进）

- [assets/tokens.css](assets/tokens.css)：全部颜色/字体/间距变量，当前是刻意安静的占位设计。
- [assets/site.css](assets/site.css)：布局结构。
- [assets/app.js](assets/app.js)：渲染逻辑，只认契约字段——设计怎么改都不用动数据层。

## 本地预览

```sh
python3 -m http.server 4173 -d site
# open http://localhost:4173
```

## 尚未接入（等 R7）

- generated RSS 出口（契约 §7，头部 RSS 链接目前是占位）。
- 真实 digest.json 的构建注入与部署流水线。
- 「关于」页。
