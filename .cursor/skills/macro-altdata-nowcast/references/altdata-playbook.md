# Macro Alt-Data Nowcast Playbook

Routing, the mandatory code-resolution step, YoY/MoM & stat_type rules, the prosperity scoring convention, the report skeleton, empty-data handling, and QA for `macro-altdata-nowcast`. Read this before the first run in a session. The exact call contract for `get_macro_detail` and each `get_macro_*` still comes from the `pandadata-api` skill.

## 1. Category → method map (宏观特色数据)

| Category | Method | Sector |
|---|---|---|
| `EC` | `get_macro_ec` | 线上电商数据 |
| `MD` | `get_macro_md` | 医药数据 |
| `EH` | `get_macro_eh` | 能化数据 |
| `AD` | `get_macro_ad` | 汽车数据 |
| `HA` | `get_macro_ha` | 家电数据 |
| `OF` | `get_macro_of` | 线下商超数据 |
| `RB` | `get_macro_rb` | 招聘数据 |
| `RE` | `get_macro_re` | 房地产数据 |
| `ED` | `get_macro_ed` | 电子数据 |
| `EP` | `get_macro_ep` | 电新数据 |

Plus the resolver: **`get_macro_detail`** — 宏观指标列表 (indicator dictionary).

## 2. The mandatory code-resolution step (do this FIRST)

The 特色 series return only `symbol` (指标代码, e.g. `EC0252098`), `period_date`, `data_value`. A raw code is meaningless. So:

1. Call `get_macro_detail(category=<X>)` for each category in scope. It returns per code: `name`, `en_name`, `is_list`, `frequency`, `unit`, `stat_type`, `accuracy`, `region`, `importance`, `info_source`, `data_begin_date`, `data_end_date`, `is_update`, `api_name`.
2. Build a **code → {name, unit, frequency, stat_type, source, coverage}** dictionary. Keep it for the whole session.
3. When you pull `get_macro_<x>`, **join every row's `symbol` to this dictionary** before reporting. Never surface a code or `data_value` without its resolved name + unit + frequency.

Use `symbol=` on both `get_macro_detail` and `get_macro_<x>` to narrow to specific indicators when a category is large; `importance` helps pick the key ones.

## 3. `get_macro_<x>` field model

| Field | Meaning | Use |
|---|---|---|
| `symbol` | 指标代码 | **join key to the detail dictionary** |
| `period_date` | 数据期 | timeline, YoY/MoM alignment |
| `data_value` | 指标数值 | level (interpret via resolved unit + stat_type) |

## 4. YoY / MoM & `stat_type` rules

- Read `frequency` and `stat_type` from the detail row **before** any transform.
- **`stat_type` guards differencing**: if the series is already 同比 (YoY) or 累计同比, **do not** compute another YoY on it — read it as published. Only compute 同比/环比 on **level** series.
- **同比 (YoY)** = current period vs same period one year earlier (align by frequency: 52w back for weekly, 12m for monthly). **环比 (MoM/WoW)** = vs the immediately prior period of the same frequency.
- **Trend** over the last K periods (state K): rising / flat / falling; note the latest turning point if any.
- **Provisional tail**: the most recent 1–2 points may be revised; flag them.

## 5. Prosperity scoring convention (label it)

For a category-level read, combine its key indicators into a simple, **stated** convention, e.g.:

- Score each key indicator: 同比 up **and** 环比 up → +1 (heating); mixed → 0; both down → −1 (cooling).
- Category prosperity = mean of key-indicator scores → 回升 / 中性 / 走弱.
- **State the indicators used, the window, and the weighting.** This is a convention, not an official diffusion index — say so. Do not present it as a published prosperity index.

## 6. Lead/lag against official data (observation only)

- Where an alt series has an official counterpart (招聘数据 ↔ 官方就业; 地产高频 ↔ 官方地产投资/销售; 电商 ↔ 社零), place them side by side and note whether alt data **turned earlier**.
- State as a **relative observation**; do not claim causation or a guaranteed lead. For the official series, hand off to `macro-monitor`.

## 7. Report skeleton (7 sections)

```
# 宏观特色（另类）数据行业景气 Nowcast · <范围> · <窗口>
## 1. 摘要              （范围、涉及行业/指标数、窗口、口径=另类样本、3–5 条要点）
## 2. 指标字典          （get_macro_detail：代码→名称/单位/频率/来源/覆盖，本报告用到的关键指标）
## 3. 行业景气快照      （各行业关键指标最新值 + 同比/环比，注明 stat_type 是否已为同比）
## 4. 趋势与拐点        （近 K 期趋势、最新拐点，末端为暂定值）
## 5. 跨行业对比        （景气打分 + 排名，标注打分口径为约定）
## 6. 与官方数据的领先   （特色 vs 官方，或领先；仅作观察，移交 macro-monitor 看官方）
## 7. 数据说明          （表格见下）
```

数据说明表：`数据模块 | 类别 | 来源接口 | 指标代码→名称 | 频率 | stat_type | 查询窗口 | 数据期 | 来源(info_source) | 备注`。

Note: alt-data nowcast has **no 风险提示 as a market section** — instead the 数据说明 and 摘要 carry the alt-data/sample caveat, and the disclaimer closes the report.

## 8. Empty-data / failure handling

- If `get_macro_detail(category=X)` returns empty, stop for that category and write `无字典（get_macro_detail，category=X）`; do not pull the series blind.
- If a `get_macro_<x>` series is empty for the window, keep the heading and write `无数据（get_macro_<x>，<code>，<window>）`.
- If a code has no `stat_type`/`unit`, report it as-is and flag the ambiguity — do not guess a unit.
- If `is_update=否`/coverage ends before the window, note the series is stale; do not extrapolate.
- If the latest points look like an obvious data gap (zeros/nulls), exclude them from the trend and say so.

## 9. QA checklist

- [ ] `get_macro_detail` called first; every reported code resolved to name + unit + frequency.
- [ ] Category routed to the right `get_macro_<x>` method.
- [ ] `stat_type` respected — already-YoY series not double-differenced; YoY/MoM only on level series.
- [ ] Trend window K stated; provisional tail flagged.
- [ ] Prosperity scoring stated as a labelled convention (indicators, window, weighting), not a published index.
- [ ] Alt-data/sample caveat present (timely sample nowcasts, ≠ official statistic; source noted).
- [ ] Any lead/lag vs official framed as observation; official handed to `macro-monitor`.
- [ ] Frequency / window / data-period labelled; empty sections say `无数据` with method + code + window.
- [ ] Wording factual; no directional market calls or trading instructions.
- [ ] Ends with the standard disclaimer.
