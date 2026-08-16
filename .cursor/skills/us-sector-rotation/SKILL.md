---
name: us-sector-rotation
description: 生成美股 US sector rotation 行业/板块轮动报告，覆盖 sector median、成分聚合收益、PE/PB snapshot 估值与排名变化速度。Use when the user asks for US sector rotation, 美股行业轮动, 美股板块表现, or 美股行业估值对比.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-us-sector-rotation
  repository_url: https://github.com/quantskills/skill-us-sector-rotation
  project_type: skill
  collection: us-sector-rotation
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - us-stock
  - sector-rotation
  - valuation
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
  summary_zh: 基于 Pandadata 成分与行业字段生成美股行业收益、估值快照和排名变化报告。
  summary_en: US equity sector rotation reports covering constituent returns, valuation snapshots, and ranking changes from Pandadata.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# US Sector Rotation

用于生成美股行业/板块轮动报告，按 Pandadata 行业口径聚合成分收益、估值和排名变化。

## Scope And Positioning

- Unlike `overseas-equity-factor-miner`, which discovers and evaluates stock-level factors with IC/backtests, this skill applies a fixed descriptive workflow to **sector aggregates** and makes no factor-efficacy claim.
- Unlike `hk-us-quote-scan`, which compares named securities or baskets on quotes, liquidity, and valuation, this skill groups the US equity universe by source sector fields and measures **sector-level rotation**.
- It is a research and educational monitor, not an ETF/index substitute, portfolio-construction engine, or trading signal.

## Workflow

1. 明确报告数据日。若用户未指定日期，使用已完成的最近一个美股交易日；报告中写绝对日期，并说明美股日线、财务和估值数据可能存在 T+1 或 snapshot 滞后。
2. 读取 `references/pandadata-map.md`，只使用其中列出的 Pandadata 方法；真实调用前仍以 `pandadata-api` 的 `api-docs.md` 为准核对方法名、参数名和字段名。
3. 用 `get_us_detail` 获取在市美股成分和行业字段。行业分类以接口返回为准，优先保留 `business_sector`、`economic_sector`、`industry_group` 或接口可得的 sector 字段，不做 GICS 或其他二次映射。
4. 用 `get_us_daily` 回填成分近 1D、1W、1M、3M、YTD 收益，按行业做 median 聚合；只做成分聚合，不替换为 ETF、指数或自建指数。
5. 用 `get_stock_sector_median` 取得行业中位指标；需要横截面 PE/PB 时可用 `get_stock_mktfin_metric` 获取个股 snapshot，再按行业聚合。若没有自有滚动缓存，只能称 snapshot 分位或横截面分位，不能称历史分位。
6. 生成中文 Markdown 报告，包含摘要、行业/板块表现、估值、轮动、数据说明和末尾免责声明；保存后运行 `scripts/validate_report.py <report-path>`，修正缺项、数据日、来源说明和免责声明。

## Pandadata Reference

读 `references/pandadata-map.md` 规划数据调用、字段选择和失败降级。接口映射只是路由说明，真实参数和字段必须回到 `pandadata-api` 文档确认。

## Report Rules

- 中文；绝对日期。
- T+1 / snapshot 声明。
- 拒绝下单指令与个性化投资建议。
- 失败降级 + 数据说明。

## Automation

默认关闭。用户明确要求自动化时，建议在 `Asia/Shanghai 21:30` 之后运行，以覆盖美股收盘后的日线刷新窗口；任务应可重复执行，并在报告中写清数据日、生成时间、使用接口和缺失数据。
