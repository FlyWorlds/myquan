---
name: alpha-f8-family-main-divergence-production
description: Use when reading the local F8 commodity futures broker-position divergence factor parquet output without recomputing the factor.
license: GPL-3.0-only
tags: [quant, alpha, production, future]
---

# F8 家人主力分歧生产因子

本 skill 读取同目录下的 `database.parquet`。不得在生产查询中临时调用 Panda data 重算因子。

## Schema

| Field | Type | Description |
|---|---|---|
| trade_date | string | `YYYY-MM-DD` |
| asset_type | string | fixed `future` |
| symbol | string | futures underlying symbol |
| factor_id | string | fixed `F8` |
| factor_name | string | fixed `家人主力分歧` |
| factor_value | float | cross-section percentile rank mapped to [-1, 1] |
| score | float | `[0, 100]` |
| rank | int | `1` is best |
| signal | string | `buy` / `sell` / `hold` |
| confidence | float | `score / 100` |
| data_version | string | fixed `real-v1` |
| update_time | string | ISO8601 |

## 信号解释

- `buy`: 当日横截面排名前10%（`rank ≤ ceil(n × 0.1)`），主力与家人分歧最强、主力方向一致，跟随主力方向做多。
- `sell`: 当日横截面排名后10%（`rank > n - ceil(n × 0.1)`），家人与主力分歧方向相反且主力一致，跟随主力方向做空。
- `hold`: 分歧信号不在触发区间。

## 禁止行为

- 不允许在 agent 调用时重新拉取原始行情。
- 不允许在 agent 调用时重新计算因子。
- 不允许手工修改 Parquet 结果。
- 不允许将结果表述为投资建议、收益承诺或官方背书。
