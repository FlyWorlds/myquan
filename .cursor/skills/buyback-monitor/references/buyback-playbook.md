# Buyback Monitor Playbook

Routing, stage/purpose/intensity definitions, dedup rules, report skeleton, empty-data handling, and QA for `buyback-monitor`. Read this before the first run in a session. The exact call contract for `get_repurchase` still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| Buyback events (market / name) | `get_repurchase` | `symbol` (empty = whole market), `start_date`, `end_date`, `fields` |
| Identity | `get_stock_detail` | `symbol` |
| Industry rollup | `get_stock_industry` / `get_industry_constituents` | `symbol` |
| Price context | `get_stock_daily` | `symbol`, `start_date`, `end_date` |
| Window bounds | `get_last_trade_date`, `get_trade_cal` | per `pandadata-api` |

## 2. `get_repurchase` field model

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `date`, `announcement_dt` | code, event date, announcement timestamp | keying & timeline |
| `procedure` | 事件进程 (预案/决案/实施/完成/注销…) | stage funnel, latest-stage |
| `purpose` | 回购目的 (long text) | purpose classification |
| `write_off_date` | 回购注销公告日 | cancellation flag |
| `buy_back_mode` | 回购方式 (集中竞价/协议回购…) | execution mode |
| `share_type` | 股份类别 (流通A股…) | context |
| `buy_back_percent` | 占总股本比例 | **primary intensity** |
| `buy_back_value` | 回购总金额 (元) | absolute executed/announced amount |
| `value_floor` / `value_ceiling` | 拟回购资金总额下限/上限 (元) | **planned range** (not spent) |
| `buy_back_volume` | 回购股数 (股) | share count |
| `volume_floor` / `volume_ceiling` | 回购数量下限/上限 | planned share range |
| `buy_back_price` | 回购价格 | executed price |
| `price_floor` / `price_ceiling` | 回购价格下限/上限 | announced band |
| `buy_back_start_date` / `buy_back_end_date` | 回购期限起止 | window |
| `maturity_desc`, `seller`, `currency` | 说明/被回购方/币种 | context |

## 3. Dedup & stage rules

- `get_repurchase` returns **one row per stage per event**. A single buyback appears as 预案, then 决案, then 实施, etc. **Dedup to the event** (by `symbol` + buyback plan; when no plan id, group by `symbol` + overlapping `buy_back_start_date`/`buy_back_end_date` and purpose) before counting events.
- Report the **latest** `procedure` per event as its current stage; keep the stage history for single-name timelines.
- Never double-count an event across its stages in market-wide totals.

## 4. Stage funnel (procedure)

Bucket distinct events by latest stage: 预案 → 决案/股东大会通过 → 实施中 → 完成/届满 → 注销。State counts and shares. A high 预案 count is **intention**; executed capital return is the 实施/完成 buckets. Never present a proposal as executed spend.

## 5. Purpose classification

Classify from `purpose` text + `write_off_date` + `buy_back_mode`, verbatim signals:

| Class | Signal | Note |
|---|---|---|
| 注销式回购 | `write_off_date` present, or purpose has 注销 / 减少注册资本 | permanent share reduction, most accretive |
| 股权激励 / 员工持股 | purpose has 股权激励 / 员工持股计划 | shares may be re-issued |
| 市值管理 / 维护价值 | purpose has 维护公司价值 / 股东权益 | — |
| 未分类 | none of the above clearly matches | do **not** guess |

Do not assert 注销 without `write_off_date` or an explicit cancellation purpose.

## 6. Intensity & price-band

- **Intensity**: rank by `buy_back_percent` (占总股本比例) first; report `buy_back_value` / planned range for absolute scale. State whether the amount is 预案 range or executed.
- **Price-band vs market**: compare `price_ceiling` / `buy_back_price` to the latest `get_stock_daily` close. Report as "价格上限较现价 高/低 X%"; a relative observation, not a call.

## 7. Report skeleton (8 sections)

```
# A股回购监控 · <范围> · <窗口>
## 1. 摘要              （范围、窗口、快照日、去重后事件数、3–5 条要点）
## 2. 回购事件总览      （去重后事件、新增预案数）
## 3. 进程漏斗          （预案/决案/实施/完成/注销 各多少，标注预案≠已执行）
## 4. 回购目的分类      （注销/激励/市值管理/未分类 占比）
## 5. 回购强度榜        （占总股本比例 & 金额 Top，标注预案范围/已执行）
## 6. 价格区间对比      （价格区间 vs 现价，get_stock_daily）
## 7. 风险提示          （克制措辞，非投资建议）
## 8. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 来源接口 | 查询窗口 | 返回行数(去重前/后) | 快照日/公告区间 | 备注`。

## 8. Empty-data / failure handling

- If `get_repurchase` returns empty for the window, keep the headings and write `无数据（get_repurchase，<window>）`. No new buybacks is itself a finding.
- If a whole-market pull is heavy or times out, narrow the window and note it under 数据说明.
- If `buy_back_percent` or amount is None for an event (common at 预案 stage), report the planned range and mark the executed figure as 待披露; never fill a missing value.

## 9. QA checklist

- [ ] Events deduplicated across procedure stages before any market-wide count.
- [ ] Latest `procedure` reported per event; 预案 never presented as executed spend.
- [ ] Every amount labeled 预案范围 (`value_floor`/`value_ceiling`) vs 已执行 (`buy_back_value`).
- [ ] Purpose classified from source signals; `注销` only with `write_off_date`/explicit purpose; ambiguous → 未分类.
- [ ] Intensity ranked on `buy_back_percent` with absolute scale beside it.
- [ ] Price-band comparison uses `get_stock_daily` and is stated as relative.
- [ ] Window / snapshot date / announcement range labeled.
- [ ] Source-note table present; empty sections say `无数据` with method + window.
- [ ] Wording factual; no directional calls or trading instructions.
- [ ] Ends with the standard disclaimer.
