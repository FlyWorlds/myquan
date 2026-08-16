# Refinancing Monitor Playbook

Routing, stage/type/dilution definitions, dedup rules, report skeleton, empty-data handling, and QA for `refinancing-monitor`. Read this before the first run in a session. The exact call contract for `get_stock_private_placement` / `get_stock_allotment` still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| Private placements (market / name) | `get_stock_private_placement` | `symbol` (empty = whole market), `start_date`, `end_date`, `fields` |
| Rights issues (market / name) | `get_stock_allotment` | `symbol`, `start_date`, `end_date`, `fields` |
| Share base (for dilution) | `get_share_float` | `symbol` |
| Identity | `get_stock_detail` | `symbol` |
| Industry rollup | `get_stock_industry` / `get_industry_constituents` | `symbol` |
| Price context (discount / break-issue) | `get_stock_daily` | `symbol`, `start_date`, `end_date` |
| Unlock linkage (optional) | `get_restricted_list` | `symbol`, window |
| Window bounds | `get_last_trade_date`, `get_trade_cal` | per `pandadata-api` |

## 2. Field models

### 2.1 `get_stock_private_placement` (定向增发)

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `announcement_date` | code, info-release date | keying & timeline |
| `issue_type` | 发行类型 (非公开发行/竞价/定价…) | placement-type classification |
| `issue_status` | 发行进度/状态 | stage funnel, latest-stage |
| `issued_shares` | 发行股数 | **dilution numerator** |
| `issue_price` | 发行价 | discount / break-issue |
| `approval_date` | 证监会核准日 | stage date |
| `listed_date` | 上市日期 | executed / unlock anchor |

### 2.2 `get_stock_allotment` (配股)

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `announcement_date` | code, info-release date | keying & timeline |
| `planned_ratio` | 计划配股比例 | intended scale |
| `actual_ratio` | 实际配股比例 | **take-up** (gap vs planned) |
| `actual_shares` | 实际配售股数 | dilution numerator (executed) |
| `allotment_price` | 配股价 | discount |
| `record_date` | 股权登记日 | stage date |
| `ex_date` | 除权日 | executed anchor |

## 3. Dedup & stage rules

- Each interface returns **one row per event stage**. A single deal appears as 预案, then 过会, then 核准, then 实施完成. **Dedup to the deal** (by `symbol` + deal, keyed on the placement/allotment plan; when no plan id, group by `symbol` + overlapping announcement cluster + issue type) before counting.
- Report the **latest** stage per deal; keep the stage history for single-name timelines.
- Never double-count a deal across its stages in market-wide totals.
- Keep 定增 (`get_stock_private_placement`) and 配股 (`get_stock_allotment`) as **separate event streams**; report a split, then any combined view.

## 4. Stage funnel (issue_status)

Bucket distinct placement deals by latest status: 预案 → 股东大会通过 → 发审委/交易所通过 → 证监会核准 (`approval_date`) → 实施完成 (`listed_date`). State counts and shares. A high 预案 count is **intention**; raised capital is the 核准/实施完成 buckets. Never present a proposal as raised capital. Rights issues have their own progression (预案 → 核准 → 股权登记 `record_date` → 除权 `ex_date`).

## 5. Type classification

- **定增 vs 配股**: the two interfaces already separate them; always report the split.
- **Placement type** (`issue_type`): classify verbatim (非公开发行 / 竞价发行 / 定价发行 / 其他). Do not infer beyond the field text.
- If a field is None (common at 预案 stage — `issue_price`, `issued_shares`, `listed_date`), report the deal but mark the missing figure as 待披露; never fill a missing value.

## 6. Dilution & discount

- **Dilution**: `issued_shares` (定增) or `actual_shares` (配股) ÷ pre-event total shares from `get_share_float`, as 稀释比例 (%). State whether executed or 预案. Rank the leaders.
- **Discount**: `(market_close − issue_price) / market_close`. A positive value means the issue price is below market (discount to holders). Use the latest `get_stock_daily` close.
- **Break-issue (破发)**: for executed placements only, current close < `issue_price`. Report as "现价较发行价 低 X%（已破发）", a relative observation, not a call.
- **Take-up gap (配股)**: `actual_ratio` < `planned_ratio` signals under-subscription (认购不足) — flag it.

## 7. Report skeleton (9 sections)

```
# A股再融资监控 · <范围> · <窗口>
## 1. 摘要              （范围、窗口、快照日、去重后事件数、定增/配股拆分、3–5 条要点）
## 2. 再融资事件总览    （去重后事件、定增 vs 配股、新增预案数）
## 3. 进程漏斗          （预案/过会/核准/实施完成 各多少，标注预案≠已募资）
## 4. 折价与破发        （发行/配股价 vs 现价、已破发个股，get_stock_daily）
## 5. 稀释强度榜        （占总股本比例 Top，get_share_float，标注预案/已执行）
## 6. 认购缺口          （配股 planned vs actual，认购不足清单）
## 7. 行业分布          （哪些行业在集中再融资）
## 8. 风险提示          （克制措辞，非投资建议）
## 9. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 来源接口 | 查询窗口 | 返回行数(去重前/后) | 快照日/公告区间 | 备注`。

## 8. Empty-data / failure handling

- If a method returns empty for the window, keep the heading and write `无数据（<method>，<window>）`. No new refinancing is itself a finding.
- If a whole-market pull is heavy or times out, narrow the window and note it under 数据说明.
- If `issue_price` / `issued_shares` / total shares are None (common at 预案 stage), report the deal and mark the derived figure 待披露; never fabricate a dilution or discount number.
- If `get_share_float` is unavailable for a name, report the deal without a dilution ratio and note the missing base.

## 9. QA checklist

- [ ] 定增 and 配股 kept as separate streams; the split is reported.
- [ ] Deals deduplicated across stages before any market-wide count.
- [ ] Latest stage reported per deal; 预案 never presented as raised capital.
- [ ] Every capital figure labeled 预案 vs 实施完成.
- [ ] Dilution computed against a stated share base (`get_share_float`); missing base noted, not guessed.
- [ ] Discount / break-issue uses `get_stock_daily` and is stated as relative.
- [ ] Take-up gap flagged for under-subscribed rights issues.
- [ ] Window / snapshot date / announcement range labeled.
- [ ] Source-note table present; empty sections say `无数据` with method + window.
- [ ] Wording factual; no directional calls or trading instructions.
- [ ] Ends with the standard disclaimer.
