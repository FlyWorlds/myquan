# 数据源与字段说明

## 数据来源

本因子使用 Panda data SDK 拉取期货席位净持仓保证金数据。

正式 Alpha 开发必须使用 Panda data SDK 或项目明确指定的数据源。不得使用来源不明、字段不稳定、个人临时整理的数据文件作为正式输入。

## 环境变量

运行前设置：

```bash
export PANDA_DATA_USERNAME=你的账号
export PANDA_DATA_PASSWORD=你的密码
```

可选参数：

```bash
export PANDA_DATA_START_DATE=2025-01-01
export PANDA_DATA_END_DATE=2026-05-28
export PANDA_DATA_UNDERLYING=A,AG,AU,CU,RB,M,MA,SR,TA,Y
```

## 接口

### `panda_data.get_broker_netmarg`

用途：获取期货席位净持仓保证金。

入参：

- `start_date`: `YYYYMMDD`
- `end_date`: `YYYYMMDD`
- `broker`: 空字符串表示全部席位
- `underlying_symbol`: 期货品种代码列表

返回字段：

| 字段 | 口径 |
|---|---|
| date | 交易日期，`YYYYMMDD` |
| underlying_symbol | 期货品种代码 |
| broker | 席位名 |
| net_margin | 净持仓保证金额，正表示净多，负表示净空 |

### `panda_data.get_future_dominant`

用途（仅 backtest.py 使用）：获取每个品种每日主力合约，用于 Method A forward return 的合约映射。

### `panda_data.get_future_daily`

用途（仅 backtest.py 使用）：获取合约日线收盘价，用于计算 forward return。

## 因子计算

```text
# 1. 分母：全部席位 abs(net_margin) 之和
total_margin(t, u) = sum(abs(net_margin) for all brokers)
# total_margin = 0 的品种当日剔除

# 2. 多头集中度：净多席位按 net_margin 降序，取前5
bull_top5(t, u) = sum(net_margin for top5 brokers where net_margin > 0)
bull_ratio(t, u) = bull_top5 / total_margin

# 3. 空头集中度：净空席位按 abs(net_margin) 降序，取前5
bear_top5(t, u) = sum(abs(net_margin) for top5 brokers where net_margin < 0)
bear_ratio(t, u) = bear_top5 / total_margin

# 4. 合并原始权重
raw_weight(t, u) = bear_ratio - bull_ratio
# 正值代表空方集中度更高，负值代表多方集中度更高

# 5. Level 路径：raw_weight 的时序 Z-score（60 日滚动，min_periods=20）
zscore_level(t, u) = (raw_weight - rolling_mean(raw_weight, 60)) / rolling_std(raw_weight, 60)

# 6. Delta 路径：raw_weight 一阶差分的时序 Z-score（60 日滚动，min_periods=20）
delta_raw(t, u) = raw_weight(t) - raw_weight(t-1)
zscore_delta(t, u) = (delta_raw - rolling_mean(delta_raw, 60)) / rolling_std(delta_raw, 60)

# 7. 等权混合（两路同时有值才保留）
factor_value(t, u) = 0.5 * zscore_level + 0.5 * zscore_delta
```

## 信号规则

```text
bull_ratio > 0.6 AND factor_value > 0 AND rank ≤ ceil(n×0.9)  → buy
bear_ratio > 0.6 AND factor_value < 0 AND rank > n - ceil(n×0.1)  → sell
其余                                                              → hold
# BUY_QUANTILE = SELL_QUANTILE = 0.1；rank=1 为 factor_value 最大
```

## 清洗规则

- `date` 输出为 `YYYY-MM-DD`
- `underlying_symbol` 转大写后输出为 `symbol`
- `net_margin` 必须为数值
- 净多席位不足5家时取实际有的全部；净空侧同理
- `total_margin = 0` 的品种当日剔除

## 回测口径

Method A 使用同一合约收益：

```text
c_t = dominant(t, u)
forward_return(t, u) = close(t+1, c_t) / close(t, c_t) - 1
```

换月价差不计入收益；MVP 不显式建模手续费、滑点、保证金占用和换仓成本。
