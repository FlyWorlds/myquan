# Institutional Research Tracker Playbook

Routing, counting/breadth/type definitions, report skeleton, empty-data and field-sparsity handling, and QA for `institutional-research-tracker`. Read this before the first run in a session. The exact call contract for `get_investor_activity` still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | Method | Key params |
|---|---|---|
| Research activity (market / name) | `get_investor_activity` | `symbol` (empty = whole market), `start_date`, `end_date`, `fields` |
| Identity | `get_stock_detail` | `symbol` |
| Industry rollup | `get_stock_industry` / `get_industry_constituents` | `symbol` |
| Price cross-check (optional) | `get_stock_daily` | `symbol`, `start_date`, `end_date` |
| Window bounds | `get_last_trade_date`, `get_trade_cal` | per `pandadata-api` |

## 2. `get_investor_activity` field model

| Field | Meaning | Use |
|---|---|---|
| `symbol` | 股票代码 | keying, per-company counts |
| `date` | 公告发布日 | timeline, window filter |
| `institute` | 参与机构 (may be a name, a list, or None) | **breadth** (distinct count), type classification |
| `participant` | 参与人员 (often None) | attendee detail (do not require) |
| `investor_or_analyst_detail` | 与会人员详情 / type text | type classification |

**Field sparsity is expected.** The documented sample returns `participant=None`, `institute=None`, `investor_or_analyst_detail="境内投资者"`. Treat None as 未披露; never fabricate a name to fill a gap.

## 3. Counting rules

- **Heat (frequency)** = number of research **events** (rows) per `symbol` in the window. This is the primary ranking metric.
- **Breadth** = number of **distinct** `institute` values per `symbol`. Parse a delimited `institute` string conservatively (split on common separators); count None/empty as 未披露, not as an institution.
- Report frequency and breadth **side by side**; do not merge. Many visits by one house (high frequency, low breadth) differs from broad interest (high breadth).
- De-duplicate exact repeat rows (same `symbol` + `date` + `institute`) before counting, to avoid double-counting a re-published announcement.

## 4. Institution type classification (verbatim signals only)

| Class | Signal (verbatim in `institute` / `investor_or_analyst_detail`) |
|---|---|
| 公募基金 | 基金管理 / 基金公司 / 资产管理（公募） |
| 券商 / 卖方 | 证券 / 证券公司 / 研究所 |
| 保险 | 保险 / 养老 / 险资 |
| 私募 | 私募 / 投资管理 / 资本 / 投资合伙 |
| 外资 / QFII | 外资 / QFII / 境外 / 英文机构名（Capital / Asset Management…） |
| 其他 / 未披露 | none matches, or field is None |

Assign a type only on a matching source signal; ambiguous or None → 未披露.

## 5. Report skeleton (8 sections)

```
# A股机构调研热度监控 · <范围> · <窗口>
## 1. 摘要              （范围、窗口、快照日、事件数、被调研公司数、3–5 条要点）
## 2. 调研活动总览      （窗口内调研事件数、去重后、被调研公司数）
## 3. 调研热度榜        （按事件数 Top，标注频次≠广度）
## 4. 机构参与广度      （按 distinct institute Top，标注 None=未披露）
## 5. 机构类型分布      （公募/券商/保险/私募/外资/未披露 占比）
## 6. 行业调研分布      （哪些行业被集中调研，get_stock_industry）
## 7. 风险提示          （被调研=关注非背书，克制措辞，非投资建议）
## 8. 数据说明          （表格见下）
```

单票模式在第 2–3 章之间替换为「单票调研时间线」（日期·参与机构·类型，标注字段缺失）。

数据说明表：`数据模块 | 来源接口 | 查询窗口 | 返回行数(去重前/后) | 快照日/活动区间 | 字段缺失说明 | 备注`。

## 6. Empty-data / field-sparsity handling

- If `get_investor_activity` returns empty for the window, keep the headings and write `无数据（get_investor_activity，<window>）`. No research is itself a finding.
- If a whole-market pull is heavy or times out, narrow the window and note it under 数据说明.
- When `institute` / `participant` are None for many rows, state the sparsity rate (e.g. "N 行中 M 行机构未披露") and compute breadth on the disclosed subset only. Never impute a name or a type.
- Do not treat a generic "境内投资者" record as a named institution; it is a 未披露/泛化 entry.

## 7. QA checklist

- [ ] Frequency (event count) and breadth (distinct institutions) reported as separate metrics.
- [ ] Exact repeat rows de-duplicated before counting.
- [ ] Institution type classified from verbatim source text; ambiguous / None → 未披露; no fabricated names.
- [ ] Field sparsity (None `institute`/`participant`) surfaced with a rate, not hidden.
- [ ] Industry distribution rolled up via `get_stock_industry`.
- [ ] Window / snapshot date / activity range labeled.
- [ ] Source-note table present; empty sections say `无数据` with method + window.
- [ ] Being researched framed as attention, not a buy signal or endorsement; no directional calls.
- [ ] Any price overlay is descriptive only, with no causal claim.
- [ ] Ends with the standard disclaimer.
