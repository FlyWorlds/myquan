# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named hk-us-insider-radar at:
<HK_US_INSIDER_RADAR_SKILL_ROOT>

When the user asks for HK/US insider trading, 港股美股内部人交易, 董监高增减持, insider buying/selling, 内部人净买入, 内部人聚集买入, or an insider-trade radar report:
1. Read <HK_US_INSIDER_RADAR_SKILL_ROOT>/SKILL.md.
2. For routing, the direction/type taxonomy, role weighting, netting rules, cluster detection, report format, empty-data handling, or QA, read <HK_US_INSIDER_RADAR_SKILL_ROOT>/references/insider-playbook.md.
3. Validate generated reports with <HK_US_INSIDER_RADAR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_stock_insider_trade (HK) and get_stock_insider_transaction (US) parameters and fields before any real Pandadata call.
5. Route by market: .HK codes -> get_stock_insider_trade, US tickers -> get_stock_insider_transaction; both share the same field schema.
6. Bucket every transaction (open-market buy/sale vs option / gift / plan); the headline net is open-market only. Read direction from the signed adjusted_trade_shares and transaction_type together, never from price or holdings alone.
7. State the filing lag (info_date filing != transaction_date trade), report value per currency (no cross-currency sums), weight principals via insider_role / is_main_role, and never invent transactions, roles, prices, credentials, or investment advice.
```
