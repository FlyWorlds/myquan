---
name: hk-us-insider-radar
description: Scan and read HK/US company insider (董监高/内部人) trading activity with the
  Pandadata get_stock_insider_trade (港股) and get_stock_insider_transaction (美股) interfaces —
  separating open-market buys from sales, option-exercise and gift-type dispositions, weighting
  by insider role (董事/高管/大股东) and is_main_role, netting shares and value over a window,
  flagging cluster buying/selling and post-trade holding changes, and ranking names by net insider
  direction — for one name or a watchlist. Use when the user asks for 港股美股内部人交易, 董监高增减持,
  insider buying/sell, 内部人交易信号, 内部人净买入, 内部人聚集买入, or an HK/US insider-trade radar report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-hk-us-insider-radar
  repository_url: https://github.com/quantskills/skill-hk-us-insider-radar
  project_type: skill
  collection: hk-us-insider-radar
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - hk-stock
  - us-stock
  - insider-trading
  - corporate-insider
  - ownership-signal
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
  summary_zh: 港股/美股内部人（董监高/大股东）交易信号雷达：区分公开市场买入与卖出、期权行权/赠与等处置类型，按内部人身份与主要人物标记加权，窗口内净额（股数/金额）聚合，标记聚集买入/卖出与持股变化，按净内部人方向排榜，支持单票或自选清单与定时运行。
  summary_en: An HK/US insider-trading radar that reads get_stock_insider_trade (HK) and
    get_stock_insider_transaction (US), separates open-market buys from sales and option/gift
    dispositions, weights by insider role and is_main_role, nets shares and value over a window,
    flags cluster buying/selling and holding changes, and ranks names by net insider direction.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "请输入港股或美股代码/自选股列表，并说明希望关注的内部人交易问题",
    "required": true
  },
  "fields": [
    {
      "key": "symbol",
      "label": "单只股票代码",
      "type": "text",
      "placeholder": "例如：00700.HK 或 AAPL.US；批量代码可写在任务中"
    },
    {
      "key": "market",
      "label": "市场",
      "type": "select",
      "default": "HK",
      "options": [
        { "value": "HK", "label": "港股" },
        { "value": "US", "label": "美股" }
      ]
    },
    {
      "key": "horizon",
      "label": "回看窗口",
      "type": "select",
      "default": "90",
      "options": [
        { "value": "30", "label": "近 30 天" },
        { "value": "90", "label": "近 90 天" },
        { "value": "180", "label": "近 180 天" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}扫描 {{market}} 市场{{#symbol}}股票 {{symbol}}{{/symbol}} 近 {{horizon}} 天的内部人交易，严格区分公开市场买卖、期权行权、赠与继承及其他处置，结合有符号股数、交易金额、内部人角色、主要人物标记、申报滞后和交易后持股识别聚集买卖并排序；所有数值标注币种、来源方法和日期，不提供交易指令，输出中文报告。"
}
```

# HK/US Insider Radar

Use this skill to **scan and read insider (内部人 / 董监高 / 大股东) trading activity for HK and US listed companies**: for one name or a watchlist over a window, read every insider transaction, **separate open-market buys from sales** and from non-market dispositions (期权行权, 赠与, 继承), weight by **insider role** (董事/高管/大股东) and the `is_main_role` flag, net **shares and value** over the window, flag **cluster buying/selling** and post-trade **holding changes**, and rank names by net insider direction. Prefer Pandadata as the data source, keep every figure traceable to `get_stock_insider_trade` (HK) or `get_stock_insider_transaction` (US) plus a filing/transaction date, and never invent transactions, prices, roles, or share counts.

## Scope And Positioning (read first to avoid overlap)

This skill is the **HK/US insider-trading** view. It is deliberately distinct from its siblings:

- Unlike `hk-us-quote-scan` (HK/US price-volume and valuation snapshot via `get_stock_pv_indicator` / `get_stock_pv_metric`): this skill reads **who inside the company is buying or selling their own shares**, not the market quote. Use `hk-us-quote-scan` for valuation/price context; use this for the insider signal.
- Unlike `hk-us-consensus-radar` (sell-side **analyst** consensus and recommendation): insiders are **company officers/directors/large holders**, not the street. Insider action is a different, often contrarian, signal.
- Unlike A-share `event-risk-alert` / 减持 monitoring (A-share shareholder reduction filings): this skill covers **HK and US** insiders through the Pandadata HK/US endpoints, which carry per-transaction role, type, price, and post-trade holdings — a different data model.
- Unlike `a-share-stock-dossier` (single-name A-share due diligence): this skill is an HK/US insider scan, not a company dossier and not A-share.

## Insider Trade Model (read before analysis)

`get_stock_insider_trade` (HK) and `get_stock_insider_transaction` (US) share the **same field schema** and return **one row per insider transaction**, keyed by `symbol` + `investor_name` + `transaction_date` (a single filing may span several rows, and a single day may carry several transactions).

- **Direction is in `transaction_type` + share sign, not a separate field.** `adjusted_trade_shares` / `reported_trade_shares` are **signed** — negative = 卖出/减持, positive = 买入/增持 (see the `Sale of shares` / `-100000.0` pattern in the docs). Read direction from the sign **and** the `transaction_type` text; do not assume.
- **Not every transaction is an open-market trade.** `transaction_type` / `acquisition_type` distinguish open-market buys/sales from **期权行权 (option exercise), 赠与/继承 (gift/inheritance), 计划内处置**, and internal transfers. A cash open-market **buy** is the strongest signal; an option-exercise or scheduled sale is weaker and must be labelled as such — never lump them into one "net".
- **Role & main-person weighting.** `insider_role` (董事/CEO/CFO/大股东/etc.) and `is_main_role=1` (the principal insider when several are named in one filing) tell you *who* traded. A CEO/CFO open-market buy weighs more than a peripheral holder's. Read the role text verbatim; do not infer a title the field does not state.
- **Value.** `transaction_price` × trade shares ≈ transaction value (state the currency from `currency`; HK=HKD, US=USD, etc.). `trade_outstanding_ratio` sizes the trade against 流通股. `adjusted_sharehold` / `reported_sharehold` are the **post-trade holdings** — use them to see whether an insider is exiting or scaling in.
- **Dates.** `info_date` is the **message/filing date** and is the **date filter** for the query; `transaction_date` is when the trade happened. They differ (HK/US insiders file after the fact) — always state which you are using, and note the filing lag.

## Workflow

1. Resolve the target: a single ticker's insider timeline, or a watchlist scan over a window. Confirm market (HK vs US → different method) and the date window (default a recent trailing window, e.g. last ~90 days by `info_date`).
2. Read `references/insider-playbook.md` before the first run in a session. Use it for the routing table, the direction/type taxonomy, role weighting, netting rules, cluster detection, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_stock_insider_trade` / `get_stock_insider_transaction` sections in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Insider transactions: `get_stock_insider_trade` for HK symbols, `get_stock_insider_transaction` for US symbols, over the `info_date` window (per-name, or looped over a watchlist).
   - Price/valuation context (optional): `get_stock_pv_indicator` (HK) / `get_stock_pv_metric` (US) to place trades against the current quote — hand valuation depth to `hk-us-quote-scan`.
5. Per transaction: classify by `transaction_type`/`acquisition_type` into **open-market buy / open-market sale / option-exercise / gift-inheritance / other**; read the signed share count and role. Net **open-market** buys vs sales by shares and by value over the window, keeping non-market dispositions separate. Detect **clusters** (≥N distinct insiders, or ≥M transactions by one insider, in the window — state N, M). Rank names by net open-market insider direction. Track post-trade holdings for scale-in vs exit.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/insider/<scope>-<date>.md` (e.g. `reports/insider/watchlist-20260707.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, a missing type-taxonomy note, missing filing-lag caveat, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 内部人交易总览 | `get_stock_insider_trade` / `get_stock_insider_transaction` | Transactions, distinct insiders, and total value in the window. |
| 方向与类型分解 | same (`transaction_type`, `acquisition_type`, signed shares) | Open-market buy vs sale vs option/gift split; net open-market direction. |
| 身份加权 | same (`insider_role`, `is_main_role`) | Whether principals (董事/CEO/CFO) or peripheral holders are trading. |
| 聚集买入/卖出 | same (per-name aggregation) | Cluster buys/sells across insiders or repeated by one insider. |
| 持股变化 | same (`adjusted_sharehold`, `reported_sharehold`) | Scale-in vs exit; post-trade holdings trajectory. |
| 价格情景（可选） | `get_stock_pv_indicator` / `get_stock_pv_metric` | Where the trades sit vs the current quote. |

## Analysis Modes

- **Single-name timeline**: one ticker's insider transactions — each dated, typed, signed, role-tagged, with running post-trade holdings and a net open-market read.
- **Watchlist scan**: loop the watchlist, net each name's open-market insider direction, then rank net buyers and net sellers; surface clusters and principal-insider trades.
- **Direction read**: **open-market cluster buying by principals** (multiple 董事/高管 buying with cash) is the strongest insider signal; scheduled/plan sales and option-exercise-then-sell are weaker and routine. State these as **relative observations**, not signals to act.
- **Holding-trajectory read**: use `adjusted_sharehold` to tell an insider *reducing* from one *building* a position; a shrinking-to-zero holding is an exit, a rising one is accumulation.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always separate transaction types.** Never merge open-market buys with option exercises, gifts, or scheduled sales into a single net. Present the **open-market net** as the headline and list other types separately.
- **Read direction from the signed share count and `transaction_type` together.** Do not infer buy/sell from price or holdings alone.
- **State the filing lag.** `info_date` (filing) ≠ `transaction_date` (trade). Say which date bounds your window and note that HK/US insiders report after the fact.
- Read `insider_role` verbatim; weight principals higher but do not invent a title. `is_main_role=1` marks the principal in a multi-insider filing.
- State the **currency** for every value (from `currency`); do not sum across currencies.
- Separate facts (raw shares, price, role, type, holdings), derived metrics (net buy/sell, value, cluster flags, ranks), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "净买入/净卖出", "聚集买入", "可能提示内部人增持意愿" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated insider radar over a watchlist, create a task that runs on a chosen cadence (e.g. daily or weekly) to pull new filings by `info_date`. Make it idempotent: if `reports/insider/<scope>-<date>.md` exists, regenerate and overwrite. Note that HK/US filing windows differ from A-share; use the message-date window, not a trading-calendar assumption.

## Resource Guide

- `references/insider-playbook.md`: routing table, the direction/type taxonomy, role weighting, netting rules, cluster detection, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, the type-taxonomy note, the filing-lag caveat, currency/window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_stock_insider_trade` / `get_stock_insider_transaction`, a filing/transaction date, the window, and the currency.
- Open-market buys/sales are netted **separately** from option-exercise, gift, and scheduled dispositions — the headline net is open-market only.
- Direction is read from the signed share count **and** `transaction_type`, never assumed.
- The `info_date` vs `transaction_date` distinction (filing lag) is stated.
- Insider role is read verbatim; principals are weighted but never invented.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
