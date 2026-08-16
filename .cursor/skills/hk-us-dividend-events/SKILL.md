---
name: hk-us-dividend-events
description: 港美股分红事件监控与 Dividend calendar/DRIP 再投资示意，覆盖 ex-dividend、TTM yield、currency 分池、T+1 snapshot 与 Pandadata 外盘 dividend_event/activity. Use when the user asks for 港股或美股分红日程、除息日、派息记录、高股息榜、Dividend calendar、ex-dividend events, DRIP illustration.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-hk-us-dividend-events
  repository_url: https://github.com/quantskills/skill-hk-us-dividend-events
  project_type: skill
  collection: hk-us-dividend-events
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - hk-stock
  - us-stock
  - dividend
  - event-calendar
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
  summary_zh: 港美股除息日历、近期派息、分币种 TTM 股息率与 DRIP 算术示意。
  summary_en: HK and US ex-dividend calendars, recent payouts, currency-bucketed TTM yields, and simplified DRIP illustrations.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# 港美股分红事件
用于生成港股和美股分红事件日历、近期派息复盘、TTM 股息率排行和 DRIP 再投资简化示意。

## Scope And Positioning

- Unlike `dividend-yield-scan`, which ranks **A-share** dividend yield and continuity, this skill covers **Hong Kong and US dividend events**, currency buckets, ex-dividend dates, and DRIP arithmetic.
- Unlike a broad corporate calendar, this skill is dividend-specific: it reconciles payout dates, trailing cash distributions, yield denominators, and event-level caveats rather than mixing earnings and other corporate actions.
- Unlike `hk-stock-dossier`, which performs broad single-company due diligence, this skill produces a dividend-event calendar or cross-sectional payout report for HK/US names.

## Workflow

1. 明确市场、股票池、日期窗口和输出口径。用户未指定窗口时，默认生成未来 30 日即将除息、过去 12 个月 TTM 派息统计，并使用绝对日期。
2. 读取 `references/pandadata-map.md`，再用 `pandadata-api/references/api-docs.md` 确认方法名、参数名和字段名；不要猜测 Pandadata 签名。
3. 按市场取数：港股使用 `get_stock_dividend_event`、`get_hk_daily`、`get_hk_detail`；美股使用 `get_stock_dividend_activity`、`get_us_daily`、`get_us_detail`。
4. 清洗分红事件：以 `excute_date` 识别除息/执行日期，以 `publish_date` 标注公告日期，以 `number` 和 `currency` 计算现金分红；币种按 HKD/USD/CNY 等分池，不做混算。
5. 生成报告章节：摘要、即将除息、近期派息、高股息/Yield 榜、DRIP 示意、数据说明。TTM 只累加过去 12 个月现金分红，不做简单外推。
6. 写出 Markdown 后运行 `scripts/validate_report.py <report-path>`。修复缺失章节、数据来源、数据日、T+1/snapshot 和免责说明后再交付。

## Pandadata Reference

读 `references/pandadata-map.md` 规划接口、字段、降级路径和港/美镜像差异。详细报告口径读 `references/dividend-guide.md`。真实调用前必须回到 `pandadata-api/references/api-docs.md` 核对方法名、参数名、字段名。

## Report Rules

- 中文；绝对日期。
- T+1 / snapshot 声明。
- 拒绝下单指令与个性化投资建议。
- 失败降级 + 数据说明。
- 分红金额、收盘价和 TTM 股息率按币种分别列示；HKD/USD/CNY 不合并。
- DRIP 只做示意，明确未考虑税、费、最小买入单位和汇兑。
- 特别股息和常规股息按字段区分；接口不能区分时，口径统一写为“所有现金分红”。

## Automation

默认关闭。用户请求自动化时，建议设置 `Asia/Shanghai 07:00` 每日任务，生成未来 7-30 日除息日程。任务应幂等：同一日期窗口和股票池的报告已存在时，可按用户要求覆盖或另存；任何接口失败都要在“数据说明”记录。
