---
name: chinese-business-topic-curator
description: 从纯中文权威、财经及实体经营信源中抓取并筛选金融、企业经营、零售和餐饮热点，为企业主与实体门店老板生成每日选题。只用于选题，不负责撰写正文。
---

# 中文企业经营热点选题

运行 `python scripts/scrape_aihot.py`，从 `resources/content_curator_sources.json` 配置的中文 RSS 抓取候选内容。

## 硬性边界

- 不得抓取、配置或推荐英文信息源。
- 不得使用 RSSHub 等第三方拼接 RSS；只使用官网明确公布且能够解析标题、链接和时间的 RSS。
- 只做选题筛选，不撰写文章、脚本或口播稿。
- 默认不调用 OpenRouter 或其他模型 API。

## 筛选标准

本地规则按时效、企业主相关度、正文完整度和来源权重排序，优先保留以下方向：

- 企业贷款、融资、利率、税务、现金流和经营风险。
- 消费、零售、餐饮、门店、支付、加盟和供应链。
- 会直接影响企业主决策的政策、宏观数据与行业变化。

结果写入 `topics/<时间戳>/aihot_selected.json` 和 `index.html`。
