# HK/US Insider Radar Playbook

Routing, the direction/type taxonomy, role weighting, netting rules, cluster detection, report skeleton, empty-data handling, and QA for `hk-us-insider-radar`. Read this before the first run in a session. The exact call contract for `get_stock_insider_trade` (HK) and `get_stock_insider_transaction` (US) still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| HK insider transactions | `get_stock_insider_trade` | `symbol` (e.g. `0004.HK`), `start_date`, `end_date` (by **`info_date`**), `fields` |
| US insider transactions | `get_stock_insider_transaction` | `symbol` (e.g. `AAPL`), `start_date`, `end_date` (by **`info_date`**), `fields` |
| HK price/valuation context (optional) | `get_stock_pv_indicator` | `symbol` |
| US price/valuation context (optional) | `get_stock_pv_metric` | `symbol` |

Market → method: **`.HK` → `get_stock_insider_trade`**, US tickers (e.g. `AAPL`) → **`get_stock_insider_transaction`**. Both share the same field schema below.

## 2. Field model (shared by HK & US)

| Field | Meaning | Use |
|---|---|---|
| `symbol` | 股票代码 | keying |
| `investor_name` | 内部人姓名/名称 | keying, cluster detection |
| `investor_type` | 投资者类型 | context |
| `info_date` | 消息/申报日期 | **date filter**, filing timeline |
| `insider_role` | 内部人身份（董事/高管/大股东…） | role weighting |
| `is_main_role` | 是否主要人物（多内部人时=1为主） | principal weighting |
| `transaction_date` | 交易发生日期 | trade timeline (vs filing lag) |
| `transaction_type` | 交易类型（Sale of shares / Purchase / Option…） | direction & type taxonomy |
| `acquisition_type` | 处置行为类型（Other / Open Market / Grant…） | type taxonomy |
| `adjusted_trade_shares` | 调整后交易股数（**有符号**：负=卖，正=买） | direction & scale |
| `reported_trade_shares` | 申报交易股数（有符号） | direction & scale |
| `trade_outstanding_ratio` | 交易股数占流通股比例 | scale vs float |
| `transaction_price` | 交易价格 | value = |shares|×price |
| `filing_currency_price` | 申报时货币价格 | context |
| `filing_type` | 申报文件类型 | provenance |
| `transaction_holding_type` | 交易持有方式（DIR 直接 / INDIR 间接） | direct vs indirect |
| `adjusted_sharehold` | 调整后（交易后）持有股数 | holding trajectory |
| `reported_sharehold` | 申报持有股数 | holding trajectory |
| `adjusted_indirect_sharehold` / `reported_indirect_sharehold` | 间接持有股数 | context |
| `currency` | 交易币种 | **never sum across currencies** |

Note: **there is no separate "direction" field** — infer it from the **sign** of `adjusted_trade_shares`/`reported_trade_shares` combined with `transaction_type`. Prefer `adjusted_trade_shares` (corporate-action adjusted); state which you used.

## 3. Direction & type taxonomy — classify every row

Bucket each transaction before netting:

- **Open-market buy** — positive shares + purchase-type text. **Strongest signal**, especially by a principal with cash.
- **Open-market sale** — negative shares + sale-type text with no plan/option marker.
- **Option exercise / award / grant** — `transaction_type`/`acquisition_type` marks an option/grant; treat as compensation mechanics, **not** a conviction buy.
- **Gift / inheritance / internal transfer** — non-economic transfer; exclude from directional net.
- **Scheduled / plan sale** — pre-arranged disposal; a weaker, routine sell.
- **Other / unclassifiable** — keep visible; do not force into a bucket.

The **headline net is open-market only** (buys − sales, by shares and by value). Report other buckets separately so a big option-exercise sale never masquerades as insider distribution — and never let an award inflate a "buy" signal.

## 4. Role weighting

- `insider_role` → tier: **principals** (董事/Director, CEO, CFO, 董事长, 大股东/10%+ holder) weigh more than peripheral officers or associated persons.
- `is_main_role=1` marks the principal when one filing lists several insiders — attribute the trade to them.
- State weighting as a **labelled convention** (e.g. "本报告以董事/CEO/CFO 的公开市场买入为高权重信号"); do not fabricate a role the field does not carry.

## 5. Netting & value rules

- **Value** = |trade shares| × `transaction_price`, in `currency`. Never sum HKD and USD together; report per currency (usually per market, so typically one currency per name).
- **Net open-market direction** over the window = Σ(open-market buy shares/value) − Σ(open-market sale shares/value), per name. Keep option/gift/plan buckets out of this net.
- **Holding trajectory** = read `adjusted_sharehold` across the window per insider: falling → reducing/exiting; rising → accumulating; to-zero → full exit.
- Prefer `adjusted_*` fields (corporate-action adjusted) over `reported_*`; note the choice.

## 6. Cluster detection

- **Cross-insider cluster** — ≥N distinct `investor_name` trading the **same direction** in the window (state N, e.g. ≥3). Cluster *buying by principals* is the notable case.
- **Repeat cluster** — one insider with ≥M transactions same direction (state M, e.g. ≥3), e.g. a director selling in tranches (like the docs' 0004.HK example: six sales working a position to zero).
- Report clusters with the insiders named and the direction; do not over-read a single transaction.

## 7. Report skeleton (8 sections)

```
# 港股/美股内部人交易雷达 · <范围> · <窗口>
## 1. 摘要              （范围、市场、窗口口径=info_date、去重内部人数/净方向、3–5 条要点）
## 2. 内部人交易总览    （笔数、内部人数、按币种的总交易额；方法与窗口）
## 3. 方向与类型分解    （公开市场买/卖 vs 期权/赠与/计划减持；公开市场净额=头条）
## 4. 身份加权          （董事/CEO/CFO/大股东 vs 边缘人；is_main_role 主要人物）
## 5. 聚集买入/卖出      （跨内部人聚集 / 单人多笔；点名 + 方向，标注 N/M 口径）
## 6. 持股变化          （adjusted_sharehold 轨迹：加仓/减仓/清仓）
## 7. 风险提示          （申报滞后、类型混同、克制措辞、非投资建议）
## 8. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 来源接口 | 查询窗口(info_date) | 返回笔数/内部人数 | 币种 | 采用股数字段(adjusted/reported) | 备注`。

## 8. Empty-data / failure handling

- If the insider method returns empty for the window, keep the headings and write `无数据（get_stock_insider_trade/transaction，<window>）`. No insider filings is itself a finding.
- If a name resolves to the wrong market (e.g. an `.HK` code passed to the US method), stop and re-route; state the correction.
- If `transaction_type`/`acquisition_type` is ambiguous, bucket it as **Other** and say so — do not force a buy/sell direction.
- If `currency` differs across rows for one name, split by currency; never net across currencies.
- If only `reported_*` (not `adjusted_*`) shares are populated, use reported and note the fallback.

## 9. QA checklist

- [ ] Market routed correctly: `.HK` → `get_stock_insider_trade`, US → `get_stock_insider_transaction`.
- [ ] Every transaction bucketed (open-market buy/sale / option / gift / plan / other); headline net is **open-market only**.
- [ ] Direction read from the **signed** share count **and** `transaction_type`, not from price or holdings alone.
- [ ] Filing lag stated: window is on `info_date`; `transaction_date` differs.
- [ ] Value stated per `currency`; no cross-currency sums.
- [ ] `insider_role` read verbatim; principals weighted; `is_main_role` used; no invented titles.
- [ ] Cluster thresholds N (cross-insider) and M (repeat) labelled as conventions.
- [ ] Holding trajectory read from `adjusted_sharehold`.
- [ ] Window / market / currency labelled; empty sections say `无数据` with method + window.
- [ ] Wording factual; no directional calls or trading instructions.
- [ ] Ends with the standard disclaimer.
