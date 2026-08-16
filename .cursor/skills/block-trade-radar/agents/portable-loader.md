# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named block-trade-radar at:
<BLOCK_TRADE_RADAR_SKILL_ROOT>

When the user asks for A-share block-trade monitoring, 大宗交易 scans, 折溢价率 (discount/premium) analysis, 机构专用接盘/出货 reads, block-trade amount or discount rankings, or a block-trade radar report:
1. Read <BLOCK_TRADE_RADAR_SKILL_ROOT>/SKILL.md.
2. For routing, the discount/premium formula and edge cases, direction/wash-print rules, aggregation rules, report format, empty-data handling, or QA, read <BLOCK_TRADE_RADAR_SKILL_ROOT>/references/block-trade-playbook.md.
3. Validate generated reports with <BLOCK_TRADE_RADAR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_block_trade and get_stock_daily parameters and fields before any real Pandadata call.
5. Compute 折溢价率 = price / 同日收盘价 − 1, always naming the get_stock_daily close basis; mark missing-close prints 待补.
6. Read direction from buyer/seller verbatim; treat 机构专用 as an anonymous seat (never name it); flag buyer==seller prints as 对倒 and exclude them from the directional net.
7. Aggregate prints per symbol+date before ranking; preserve source method names, query windows, trade dates, and missing-data notes. Do not invent prices, amounts, discounts, directions, credentials, or investment advice.
```
