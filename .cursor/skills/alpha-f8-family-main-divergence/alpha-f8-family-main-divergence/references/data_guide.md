# F8 Data Guide

## Required Panda Data

| Data | Interface | Required Fields |
|---|---|---|
| Broker net margin | `panda_data.get_broker_netmarg` | `date`, `underlying_symbol`, `broker`, `net_margin` |
| Dominant contract | `panda_data.get_future_dominant` | `date`, `underlying_symbol`, `symbol` |
| Futures daily | `panda_data.get_future_daily` | `date`, `symbol`, `close`, `open_interest` |
| Futures detail | `panda_data.get_future_detail` | `symbol`, `underlying_symbol`, `start_delivery_date` |

## Environment Variables

- `PANDA_DATA_USERNAME`: required.
- `PANDA_DATA_PASSWORD`: required.
- `PANDA_DATA_START_DATE`: optional, default `2024-01-01`.
- `PANDA_DATA_END_DATE`: optional, default `2026-05-28`.
- `PANDA_DATA_UNDERLYING`: optional comma-separated symbols; unset or `all` means all available symbols.

## Broker Semantics

- `net_margin > 0`: net long margin.
- `net_margin < 0`: net short margin.
- Missing family brokers are treated as zero family net exposure.
- Missing major brokers make `major_total=0`; that row is excluded from the factor cross-section.

## 因子计算

```text
# 1. 有效分母（加回家人内部对冲量）
family_internal_hedge(t, u) = min(family_bull, family_bear) × 2
denom(t, u) = total_abs_margin + family_internal_hedge

# 2. 持仓比例
family_ratio(t, u) = family_net / denom
major_ratio(t, u) = major_net / denom

# 3. 主力一致性
consistency(t, u) = max(major_bull, major_bear) / (major_bull + major_bear)
consistency_strength(t, u) = clip(2 × consistency - 1, 0, 1)

# 4. 原始权重（主力领先 - 家人跟随，按一致性加权）
raw_weight(t, u) = (major_ratio - family_ratio) × consistency_strength

# 5. 因子值（横截面百分位映射到 [-1, 1]，非时序）
factor_value(t, u) = rank_pct(raw_weight, 当日全品种) × 2 - 1
```

## 信号规则

```text
rank ≤ ceil(n × 0.1)          → buy   # 前10%，BUY_QUANTILE=0.1
rank > n - ceil(n × 0.1)      → sell  # 后10%，SELL_QUANTILE=0.1
其余                            → hold
# rank=1 为 factor_value 最高；major_total=0 的品种当日排除
```

## 清洗规则

- `date` 输出为 `YYYY-MM-DD`
- `underlying_symbol` 转大写后输出为 `symbol`
- `net_margin` 必须为数值
- `total_abs_margin = 0` 的品种当日剔除
- `major_total = 0` 的品种当日剔除（无法计算一致性）
