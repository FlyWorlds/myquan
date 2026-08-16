# Dividend Yield Scan Playbook

Routing, yield/continuity/cash-vs-送转 definitions, the `round_lot` pitfall, report skeleton, empty-data handling, and QA for `dividend-yield-scan`. Read this before the first run in a session. The exact call contract for the dividend methods still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| Cash dividends (yield + continuity) | `get_stock_cash_dividend` | `symbol`, `start_date`, `end_date`, `fields` |
| Dividend form (cash vs 送转) | `get_stock_dividend` | `symbol`, `start_date`, `end_date` |
| Total amount + stage | `get_stock_dividend_amount` | `symbol`, `start_date`, `end_date` |
| Split / 送转 context | `get_stock_split` | `symbol`, `start_date`, `end_date` |
| Price (for yield) | `get_stock_daily` | `symbol`, `start_date`, `end_date` |
| Basket definition | `get_index_weights` / `get_industry_constituents` | index / industry |
| Identity | `get_stock_detail` | `symbol` |
| Industry rollup | `get_stock_industry` | `symbol` |
| Payout (optional) | `get_fina_performance` / `get_fina_reports` | `symbol` (net profit) |
| Window bounds | `get_last_trade_date`, `get_trade_cal` | per `pandadata-api` |

## 2. Field models

### 2.1 `get_stock_cash_dividend`

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `announcement_date` | code, announce date | keying |
| `div_cash_gross` | 税前每股现金分红 **per `round_lot`** | **yield numerator (÷ round_lot)** |
| `round_lot` | 分红基准单位 (typically 10) | **divide `div_cash_gross` by this** |
| `record_date` | 股权登记日 | timeline |
| `ex_date` | 除权除息日 | trailing window filter, ex-date calendar |
| `payment_date` | 派息日 | timeline |
| `meeting_date`, `quarter` | 股东大会日 / 财报期 | context |

### 2.2 `get_stock_dividend`

`div_type`: `cash` (only cash) · `transferred share` (转增) · `bonus share` (送股) · `cash and share` / `cash and transferred share` (兼有). Fields: `announcement_date`, `effective_date`, `ex_date`. **送转 is not cash.**

### 2.3 `get_stock_dividend_amount`

`total_div_amount` (分红总额) · `event_stage` (预案 / 方案实施 …) · `quarter`. Note the **same amount may appear at both 预案 and 方案实施** — label the stage; a proposal is not paid.

### 2.4 `get_stock_split`

`split_factor_pre` / `split_factor_post` / `cum_adj_factor` / `ex_date` — context for 送转/拆分 adjustments to per-share figures across time.

## 3. The `round_lot` pitfall (read this)

`div_cash_gross` is **per `round_lot`** (usually 10 shares), not per single share. **Per-share cash = `div_cash_gross` / `round_lot`.** Example: `div_cash_gross=6.0`, `round_lot=10` → 0.6 元/股. Forgetting this inflates yield 10×. Always divide, and always state it in the report.

## 4. Derived metrics

- **Trailing DPS** = Σ (per-share cash) over cash dividends with `ex_date` in the trailing window (default 12 months). Use only cash (`div_cash_gross`); exclude 送转.
- **Dividend yield** = trailing DPS ÷ latest close (`get_stock_daily`). State window + price date.
- **Continuity streak** = number of consecutive years (by `ex_date` year or `quarter`) with a cash dividend. A long streak signals payout stability.
- **Cash-vs-送转 share** = share of dividend events that are cash vs 送转 (from `get_stock_dividend.div_type`).
- **Payout ratio (optional)** = `total_div_amount` ÷ net profit (from fina). Mark optional and derived; skip cleanly if fina is unavailable.

## 5. Report skeleton (9 sections)

```
# A股高股息与分红质量 · <范围> · <窗口>
## 1. 摘要              （范围、扫描窗口、股息率滚动窗口、价格日、口径一句话、3–5 条要点）
## 2. 分红事件总览      （范围内分红事件、现金 vs 送转 占比）
## 3. 股息率榜          （滚动股息率 Top，标注 每股=div_cash_gross/round_lot、价格日、仅现金）
## 4. 连续分红与稳定性  （连续分红年数、稳定性）
## 5. 现金分红 vs 送转  （哪些"分红"是真现金、哪些是送转）
## 6. 除权除息日历      （未来 ex_date 排期）
## 7. 分红率（可选）    （total_div_amount / 净利润，标注可选/派生）
## 8. 行业分布          （哪些行业派现最多）
## 9. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 来源接口 | 查询窗口 | 滚动窗口/价格日 | 返回行数 | 备注`。

## 6. Empty-data / failure handling

- If a dividend method returns empty for the window, keep the heading and write `无数据（<method>，<window>）`. No dividend is itself a finding (a name may simply not pay).
- If `get_stock_daily` has no close for the price date, use the latest available close and state the date; never compute a yield without a dated price.
- If `round_lot` is missing, do **not** guess 10 — flag the name and skip its yield rather than risk a 10× error.
- If fina/net-profit is unavailable, omit payout for that name and note it; do not fabricate a payout ratio.

## 7. QA checklist

- [ ] Per-share cash computed as `div_cash_gross` / `round_lot`; the divisor is stated in the report.
- [ ] Every yield states trailing window, price date, and "cash only, 送转 excluded".
- [ ] Cash dividends and 送转 separated; 送转 never counted as cash return.
- [ ] `get_stock_dividend_amount` stages (预案 vs 实施) labeled; proposed ≠ paid.
- [ ] Continuity computed from multi-year cash history and stated as a streak.
- [ ] Ex-dividend calendar lists upcoming `ex_date` only, framed as a schedule.
- [ ] Payout ratio marked optional/derived; skipped cleanly when fina missing.
- [ ] Scan window / trailing window / price date labeled.
- [ ] Source-note table present; empty sections say `无数据` with method + window.
- [ ] Yield framed as backward-looking, not a forecast; no directional calls.
- [ ] Ends with the standard disclaimer.
