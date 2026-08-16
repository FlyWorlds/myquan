# Holder Structure Scan Playbook

Routing, the three-interface field model, concentration/trend definitions, caliber (flow vs total) rules, report skeleton, empty-data handling, and QA for `holder-structure-scan`. Read this before the first run in a session. The exact call contract for the three interfaces still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| Holder count & 户均持股 trend | `get_holder_count` | `symbol`, `start_date`, `end_date`, `fields` |
| Top-holder concentration | `get_top_holders` | `symbol`, `start_date`, `end_date`, `stock_type` (`flow`/`total`), `start_rank`, `end_rank`, `market`, `fields` |
| Share float / free float | `get_share_float` | `symbol`, `start_date`, `end_date`, `fields` |
| Identity | `get_stock_detail` | `symbol` |
| Industry rollup | `get_stock_industry` | `symbol` |
| Window bounds | `get_last_trade_date`, `get_trade_cal` | per `pandadata-api` |

## 2. Field models

**`get_holder_count`**

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `date`, `end_date` | code, 公告日期, 截止日期 | key on `end_date` (the period it refers to) |
| `holders` / `a_holders` | 股东户数 / A股股东户数 | **primary count** |
| `avg_holders` / `avg_a_holders` | 户均持股数 | concentration proxy (↑ = concentrating) |
| `avg_circulation_holders` | 无限售A股户均持股 | free-float-account concentration |

**`get_top_holders`** (one row per ranked holder)

| Field | Meaning | Use |
|---|---|---|
| `date`, `end_date`, `rank` | 发布日, 截止日, 排名 | keying, period |
| `stock_type` | `flow` (流通口径) / `total` (总股本口径) | **caliber — never mix** |
| `hold_percent_float` | 占流通A股比例(%) | concentration under 流通口径 |
| `hold_percent_total` | 占股比例(%) | concentration under 总股本口径 |
| `holder_name`, `holder_kind`, `holder_attr`, `holder_type` | 股东名称/性质/属性/类别 | identify 控股/国资/机构 vs free-float |
| `pledge`, `freeze` | 质押/冻结涉及股数 | risk flag among top holders |

**`get_share_float`**

| Field | Meaning | Use |
|---|---|---|
| `symbol`, `date` | code, 发布日 | keying |
| `circulation_a` | 流通A股 | denominator context |
| `free_circulation` | 自由流通股本 | **free-float numerator** |
| `non_circulation_a` | 非流通A股 | locked context |
| `total` / `total_a` | 总股本 / A股总股本 | denominators |

## 3. Concentration & trend definitions

- **Holder-count trend**: 户数环比 = (本期 `holders` − 上期) / 上期. 户数↓ = accounts leaving (often retail exiting / chips concentrating). Pair with 户均持股 (`avg_holders`) — ↑ confirms concentration.
- **Top-N concentration ratio**: Σ `hold_percent_*` for `rank` 1..N (default N=10) in a single **caliber**. Track its change across periods.
- **Free-float share**: `free_circulation / total` (or `/ total_a`). State the denominator. Small free float ⇒ higher price sensitivity to the same flow.
- **Concentration-direction read** (combine, don't rely on one signal):
  - 集中: 户数↓ AND 户均持股↑ AND top-N占比↑ across consecutive periods.
  - 分散: the reverse.
  - 稳定/混合: signals disagree — say so rather than forcing a verdict.
- **Locked vs tradable**: if the top ratio is dominated by a 控股股东/国资/limited-sale block (`holder_kind`/`holder_attr` + limited-sale context), label it **锁定型集中** — it is not free-floating tradable concentration.

## 4. Caliber (flow vs total) rules

- Pick **one** `stock_type` per comparison and label it (流通口径 = `flow`/`hold_percent_float`; 总股本口径 = `total`/`hold_percent_total`).
- Never sum a `flow` ratio for one period against a `total` ratio for another. If both are shown, present them as two clearly labeled columns.
- 户数-based concentration and 占比-based concentration are different lenses; report both, don't conflate.

## 5. Report skeleton (8 sections)

```
# A股股东结构与筹码集中度 · <范围> · <回溯期>
## 1. 摘要              （范围、回溯期数、最新披露日、集中/分散结论、3–5 条要点；标注披露频率与滞后）
## 2. 股东户数趋势      （户数环比、户均持股趋势，按 end_date 对齐）
## 3. 前十大集中度      （top-N 合计占比，明确 流通/总股本 口径，环比变化）
## 4. 自由流通占比      （free_circulation/total，标注分母；对价格敏感度的含义）
## 5. 筹码集中方向      （集中/分散/稳定；锁定型 vs 可流通型集中区分）
## 6. 大股东质押/冻结    （top holders 的 pledge/freeze 风险标记）
## 7. 风险提示          （克制措辞，非投资建议；披露滞后提醒）
## 8. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 来源接口 | 查询窗口 | 披露期/截止日 | 口径(流通/总股本) | 返回行数 | 备注`。

## 6. Empty-data / failure handling

- If any interface returns empty for the window, keep the heading and write `无数据（<method>，<window>）`. Some names disclose 户数 infrequently — absence is a finding, not an error.
- If only one or two periods are available, state that a trend cannot be confirmed from a single snapshot; report the level and flag the limitation.
- If `get_top_holders` returns fewer than N ranks, use the ranks available and state N_actual.
- If a period's `end_date` differs across the three interfaces, align by nearest period and note the mismatch — do not silently pair mismatched periods.

## 7. QA checklist

- [ ] Top-holder concentration carries its caliber (流通/总股本) and no cross-caliber mixing.
- [ ] 户数 & 户均持股 trend read across periods, keyed on `end_date`.
- [ ] Free-float share stated with its denominator; price-sensitivity implication noted.
- [ ] Concentration-direction verdict combines 户数/户均/占比, not a single signal.
- [ ] Locked (控股/国资/限售) concentration distinguished from free-float concentration.
- [ ] Pledge/freeze among top holders surfaced as a risk flag.
- [ ] Disclosure frequency & lag caveat stated; single-snapshot limitation noted where relevant.
- [ ] Period / disclosure dates labeled throughout.
- [ ] Source-note table present; empty sections say `无数据` with method + window.
- [ ] Wording factual; no directional calls; ends with the standard disclaimer.
