# HK/US Consensus Radar Playbook

Routing, metric definitions, market-split and suffix notes, report skeleton, empty-data handling, and QA for `hk-us-consensus-radar`. Read this before the first run in a session. The exact call contract for every method still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | HK method | US method | Key params |
|---|---|---|---|
| Rating & target-price consensus | `get_stock_recommendation_consensus` | `get_stock_recommendation_estimate` | `symbol`, `fields` |
| Long-term growth / 1y target price | `get_stock_ncycl_consensus` | `get_stock_ncycl_estimate` | `symbol`, `fields`; `indicator` in {`LTGROWTH`,`TP`} |
| Current-price anchor (upside) | `get_hk_daily` | `get_us_daily` | `symbol`, `start_date`, `end_date` |

Empty `symbol` list returns the whole market's consensus (heavy). Never call the HK method for a US ticker or vice versa.

## 2. Market-split & suffix notes

- **Same schema, different method** per market. HK → `..._consensus`; US → `..._estimate`. Choose by market, not by preference.
- **Time-window suffixes**: rating and target-price fields commonly exist as base + `_week` / `_month` / `_6month` variants (e.g. `buy_num`, `buy_num_week`; `high`, `high_week`; `std`, `std_6month`). The delta base−suffix (or suffixA−suffixB) is the **revision**. Confirm which suffixes exist for each field in `pandadata-api`; if a suffix is absent, do not fabricate a revision — report base only.
- `ncycl` `indicator` values: `LTGROWTH` = 未来 3–5 年长期成长预期(%); `TP` = 未来 1 年目标价(currency). Filter by `indicator`; do not blend the two.

## 3. Metric definitions (all derived — label them)

- **Rating counts** (facts): `strong_buy_num`, `buy_num`, `hold`, `sell_num`, `strong_sell_num`, `no_opinion_num`, `recommendations_num`.
- **Buy share** = `(strong_buy_num + buy_num) / recommendations_num`. **Sell share** = `(sell_num + strong_sell_num) / recommendations_num`. State the denominator (whether `no_opinion_num` is included).
- **Net rating** = buy share − sell share, or a signed score if you weight strong/normal differently — state the weighting scheme explicitly.
- **Target-price upside** = `consensus_TP / current_price − 1`. State: which TP (recommendation `mean`/`median`, or ncycl `TP` mean) and the current-price **date and source** (`get_hk_daily`/`get_us_daily` close). Same currency on both sides — never divide a USD target by an HKD price.
- **Coverage depth** = `recommendations_num` / `estimates_num` (ratings) and `estimates_num` / `included_estimates_num` (ncycl). Report it beside every consensus stat.
- **Dispersion** = `std` and/or the `high`−`low` band relative to `mean`. Wider band = weaker consensus.
- **Revision** = base−suffix (or `_week` vs `_month`) delta for a rating count or target price. State the two windows.

## 4. Report skeleton (8 sections)

```
# 港美股一致预期雷达 · <市场> · <范围> · <数据日>
## 1. 摘要              （范围、市场、货币、数据日、3–5 条要点）
## 2. 评级分布          （强买/买/持有/卖/强卖计数、买入占比、净评级）
## 3. 目标价与上行空间  （一致目标价 + 相对现价上行空间，注明现价日期与口径）
## 4. 长期成长预期      （LTGROWTH 均值/中位/分歧）
## 5. 覆盖广度与分歧    （覆盖分析师数、std、高低带）
## 6. 一致预期变化      （周/月评级迁移与目标价修正）
## 7. 风险提示          （克制措辞，非投资建议）
## 8. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 市场 | 来源接口 | 查询标的/窗口 | 返回行数 | 数据日 | 备注`。

## 5. Empty-data / failure handling

- Many small caps and recent listings have **no analyst coverage**. If a consensus method returns empty or `recommendations_num`/`estimates_num` is 0/None, keep the heading and write `无覆盖 / 无数据（<method>，<symbol>）`. A thin or absent consensus is itself a finding.
- If a `_week`/`_month` suffix field is missing, report the base value only and note "无区间修正数据"; do not invent a revision.
- If the current-price anchor is unavailable, report the target price in absolute terms and state that upside could not be computed — never assume a price.
- If a whole-market pull is too slow, narrow to the requested basket and note it under 数据说明.

## 6. QA checklist

- [ ] Correct method family used per market (HK `_consensus`, US `_estimate`).
- [ ] Every target price labeled with market and currency; no HK/US mixing without a market column.
- [ ] Every upside states TP source (mean/median) and current-price date/source; same currency both sides.
- [ ] Coverage depth (`recommendations_num`/`estimates_num`) reported beside consensus stats; thin coverage flagged.
- [ ] `LTGROWTH` and `TP` not blended.
- [ ] Revisions state the two windows compared; no fabricated revision when suffix absent.
- [ ] Empty/no-coverage sections say so with method + symbol, not omitted.
- [ ] Consensus framed as analyst opinion snapshot, not price forecast or company guidance.
- [ ] Ends with the standard disclaimer.
