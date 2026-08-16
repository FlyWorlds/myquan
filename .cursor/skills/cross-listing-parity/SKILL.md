---
name: cross-listing-parity
description: 监控 A/H 溢价、ADR 折溢价、跨市场配对 Parity 与汇率折算，输出异常与收敛观察报告. Use when the user asks for A/H 溢价, ADR 折溢价, 跨市场 parity, 港股/A股价差, 中概股 ADR parity, or 套利监控.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-cross-listing-parity
  repository_url: https://github.com/quantskills/skill-cross-listing-parity
  project_type: skill
  collection: cross-listing-parity
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - a-share
  - hk-stock
  - us-stock
  - cross-listing
  - parity
  - pandadata
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: draft
  validation_level: runnable
  maintainer_type: community
  summary_zh: 按数据日、汇率和股数比监控 A/H 与中概 ADR 跨市场折溢价。
  summary_en: A/H and China ADR cross-listing parity monitoring with explicit market dates, FX rates, and share ratios.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Cross Listing Parity

用于生成 A/H 溢价与中概 ADR 折溢价监控报告，重点说明数据日、汇率、股数比、映射表版本和异常变化。

## Scope And Positioning

- Unlike `hk-us-quote-scan`, which compares standalone HK/US securities on quotes, liquidity, and valuation, this skill only analyzes **explicitly mapped cross-listing pairs** after FX and share-ratio normalization.
- Unlike `hk-stock-dossier`, which performs broad due diligence on one Hong Kong company, this skill focuses on the same issuer's price parity across A/H/ADR venues.
- A spread is an observation, not an executable arbitrage signal. The skill does not model settlement, borrow availability, taxes, fees, capital controls, market-hour mismatch, or trade capacity.

## Workflow

1. 确定报告数据日。用户未指定时，使用已完成的最近交易日；跨 A/H/US 市场时分别记录 A 股、港股、美股的数据日，并用绝对日期写入报告。
2. 读取 `references/pandadata-map.md` 和 `references/parity-guide.md`，再读取 `references/pairs/a-h-pairs.csv` 与 `references/pairs/adr-pairs.csv`。用户提供自定义配对时，先校验 `ratio`、币种和对应市场字段。
3. 采集行情和基础信息：A 股用 `get_stock_daily` 与 `get_trade_list`，港股用 `get_hk_daily` 与 `get_hk_detail`，美股 ADR 用 `get_us_daily` 与 `get_us_detail`。所有 Pandadata 参数名以 `pandadata-api/references/api-docs.md` 为准，不猜测不存在的接口。
4. 获取或要求用户提供 USD/HKD/CNY 汇率。没有可验证汇率接口时，不自动抓取外部汇率；报告必须列明汇率来源、汇率日期和折算方向。HKD、USD、CNY 不做未折算合并。
5. 计算 A/H 溢价、ADR 折溢价、当日排行、缺口变化和异常扩张/收敛。历史分位只有在用户提供或本地已有滚动缓存时才输出；首版默认输出当日 snapshot，并在数据说明中标注历史分位需要累积。
6. 生成中文 Markdown 报告，至少包含摘要、A/H 溢价、ADR、异常/极值/收敛、数据说明和免责声明。写出后运行 `scripts/validate_report.py <report-path>`，修复缺失章节、数据来源、数据日、snapshot/T+1 标注或免责声明。

## Pandadata Reference

读 `references/pandadata-map.md` 规划接口、字段、参数和失败降级。该文件只做路由说明；真实方法名、参数名、字段名必须再以 `pandadata-api/references/api-docs.md` 为准。A 股清单使用 Pandadata 文档中存在的 `get_trade_list`。

## Report Rules

- 中文；绝对日期。
- T+1 / snapshot 声明。
- 拒绝下单指令与个性化投资建议。
- 失败降级 + 数据说明。

## Automation

默认关闭自动化。用户请求启用时，建议在 `Asia/Shanghai 21:00` 之后运行，以覆盖 A 股、港股和前一美股交易日 ADR 数据；任务应记录各市场实际数据日、汇率日期、映射表版本，并在缺少汇率或某一市场行情时生成降级报告而不是补写估算值。
