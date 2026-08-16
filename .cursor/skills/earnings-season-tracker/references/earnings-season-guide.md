# Earnings Season Tracker Guide

Read this guide when generating or revising an earnings-season cross-sectional scan. Use it as a compact operating checklist, not as a replacement for the exact Pandadata API documentation. Confirm every method signature and field with the `pandadata-api` skill before calling.

## Default Scope

- View: whole A-share market, cross-sectional, for one earnings-disclosure window.
- Target period: the report period (`end_date`) under disclosure — e.g. annual `YYYY年报`, interim `YYYY中报`, quarterly `YYYYQn`. Infer from the run date if the user does not specify.
- Snapshot nature: forecasts, flash reports, and final reports accumulate through the season; a scan is a point-in-time snapshot. Always state the snapshot/as-of date.
- Output: Markdown report unless the user requests HTML, Word, PDF, or another deliverable.

## Earnings-Season Windows

| Window | Months | Deadline guide | Disclosures in scope |
|---|---|---|---|
| 年报业绩预告潮 | January | by Jan 31 | Annual performance forecasts (`get_fina_forecast`). |
| 年报 + 一季报季 | April | by Apr 30 | Annual reports + Q1 reports + audit opinions (`get_fina_reports`, `get_audit_opinion`, `get_fina_forecast`). |
| 中报季 | July–August | by Aug 31 | Interim forecasts and interim reports (`get_fina_forecast`, `get_fina_reports`). |
| 三季报季 | October | by Oct 31 | Q3 forecasts and Q3 reports (`get_fina_forecast`, `get_fina_reports`). |

Audit opinions are an annual-report-season concern; in non-annual windows, omit the audit section or note it as not applicable.

## API Routing

Before calling any method, use the `pandadata-api` skill to confirm exact parameters and return fields.

| Stage | Methods | Use |
|---|---|---|
| Calendar & universe | `get_last_trade_date`, `get_trade_cal`, `get_trade_list` | Resolve the as-of trading day, confirm the window is active, and obtain the tradable universe denominator for disclosure-progress ratios. |
| Forecast scan | `get_fina_forecast` | Pull market-wide forecasts for the target report period; bucket by forecast type and rank by change magnitude. |
| Flash reports | `get_fina_performance` | Track flash (快报) disclosures and compare against forecast or prior-period actual. |
| Quarterly reports | `get_fina_reports` | Track landed three-statement quarterly reports; compute realized growth and beat/miss versus forecast. |
| Audit opinions | `get_audit_opinion` | Annual season only: compile non-standard opinions. |
| Industry mapping | `get_industry_constituents`, `get_stock_industry`, `get_industry_detail` | Map names to industries and aggregate earnings signals to sector level. |

## Forecast-Type Buckets

Bucket each `get_fina_forecast` row by the forecast-type field exactly as the source assigns it; do not re-label. Typical A-share forecast types and how to read them:

| Type | Plain meaning | Read |
|---|---|---|
| 预增 | Profit up materially YoY | Positive; rank by upper/lower magnitude bounds. |
| 略增 | Profit up modestly YoY | Mildly positive. |
| 续盈 | Still profitable, roughly flat | Neutral-positive. |
| 扭亏 | Turned from loss to profit | Positive turnaround. |
| 减亏 | Loss narrowed YoY | Improving but still loss-making. |
| 略减 | Profit down modestly YoY | Mildly negative. |
| 预减 | Profit down materially YoY | Negative; rank downside. |
| 首亏 | First loss after profit | Negative reversal; high-attention. |
| 续亏 | Continued loss | Negative; high-attention. |
| 不确定 | Outcome uncertain | Flag separately; do not force into beat/miss. |

If the source provides a different label set or numeric bounds (e.g. forecast net-profit lower/upper or change-percent fields), report those verbatim and use the documented field for magnitude ranking. Never invent a bucket the source did not assign.

## Beat / Miss Rules

"Beat" (超预期) and "miss" (不及预期 / 暴雷) are derived judgments — always state the baseline and fields used.

- **Forecast-implied direction**: rank 预增/扭亏/略增 as upside and 预减/首亏/续亏/略减 as downside, using the forecast change-magnitude field for ordering. This is direction, not yet a beat/miss.
- **Flash vs. forecast**: when `get_fina_performance` lands, compare the flash net profit/revenue against the prior `get_fina_forecast` band. Above the upper bound → beat; below the lower bound → miss.
- **Report vs. forecast / prior period**: when `get_fina_reports` lands, compare realized figures against the forecast band or the same period last year. State which baseline was used.
- **Magnitude ranking**: build a 超预期榜 (largest positive surprises / largest 预增 magnitudes) and an 暴雷榜 (largest 首亏/续亏/预减 magnitudes or biggest misses). Always show the change figure and its baseline in the table.
- **Caliber discipline**: compare the same report period and the same single-quarter vs. cumulative (累计) caliber. Do not compare a cumulative figure against a single-quarter band.

## Industry Aggregation Method

1. For each disclosed name, resolve its industry via `get_stock_industry`, or intersect `get_industry_constituents` per industry with the disclosed set. State the taxonomy used (the field returned by `get_industry_detail`).
2. Per industry, count disclosed names by forecast type, and compute the share of positive (预增/扭亏/略增) vs. negative (预减/首亏/续亏) types — this is the industry's earnings prosperity spread.
3. Rank industries by positive share, by count of beats, or by count of 首亏/暴雷, and present a "行业业绩景气分布" table.
4. Cross-check with `macro-monitor`: where a sector shows clustered earnings beats here, note whether it corroborates that sector's top-down prosperity reading, and call out divergences explicitly (e.g. "行业财报集体超预期，但宏观景气度走弱，需关注背离").

## Report Skeleton

Use this chapter order unless the user asks for a custom structure:

1. `摘要`: 3–6 bullets — disclosure progress, dominant forecast-type tilt, standout beats and blow-ups, hottest/coldest industries, audit-opinion flags (annual season), and snapshot date.
2. `披露进度概览`: disclosed counts by channel (forecast / flash / final report) versus the `get_trade_list` universe, with the as-of date.
3. `业绩预告类型分布`: count and share per forecast type, plus a change-magnitude leaderboard.
4. `超预期 / 暴雷个股榜`: top upside-surprise names and top blow-up names, each with type, change figure, baseline, and source method.
5. `行业业绩景气分布`: per-industry positive/negative type spread and ranking; note any `macro-monitor` corroboration or divergence.
6. `审计非标清单（年报季）`: every non-standard audit-opinion name with the opinion type verbatim; in non-annual windows, mark "本期不适用".
7. `风险提示`: factual, structural cautions; no directional or trading language.
8. `数据说明`: method-by-method source table — `数据模块 | 来源接口 | 查询窗口 | 返回行数 | 报告期/数据日 | 备注`, plus caliber notes and any degraded/missing data.

## Suggested Tables

Forecast-type distribution:

| 预告类型 | 家数 | 占已披露比例 | 备注 |
| --- | ---: | ---: | --- |

Beat / blow-up leaderboard:

| 排名 | 股票 | 预告类型 | 变动幅度 | 比较基准 | 行业 | 报告期 | 来源接口 |
| ---: | --- | --- | ---: | --- | --- | --- | --- |

Industry earnings prosperity:

| 行业 | 已披露家数 | 正面占比 | 负面占比 | 首亏/暴雷家数 | 景气倾向 | 来源接口 |
| --- | ---: | ---: | ---: | ---: | --- | --- |

Audit non-standard list (annual season):

| 股票 | 审计意见类型 | 报告期 | 来源接口 | 备注 |
| --- | --- | --- | --- | --- |

## Empty-Data And Degradation Handling

- If a full-market `get_fina_forecast` scan is too slow or unavailable, keep the calendar/progress section and report what could be fetched, noting the skipped interface and reason under `数据说明`.
- If industry mapping is incomplete for some names, aggregate only the mapped subset and state the unmapped count rather than dropping it silently.
- In non-annual windows, mark the audit section "本期不适用" instead of forcing it.
- For any section with no returned rows, keep the heading and write "无数据" with the method name and queried window.

## Final QA Checklist

- Target report period (`end_date`) and disclosure window are stated.
- Snapshot / as-of date appears, and the snapshot nature of the scan is noted.
- Disclosure-progress ratios cite the universe denominator (`get_trade_list`).
- Forecast types are reported as the source assigns them; no re-labeling.
- Beat/miss claims state their baseline and fields.
- Single-quarter vs. cumulative caliber is labeled and never mixed.
- Industry aggregation states its taxonomy; `macro-monitor` cross-check noted where relevant.
- Empty data is disclosed rather than hidden.
- Every section carries a source method and report period.
- Final disclaimer is present exactly as required by `SKILL.md`.
