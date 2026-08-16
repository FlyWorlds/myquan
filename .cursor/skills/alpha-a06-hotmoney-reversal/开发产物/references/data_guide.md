# A06 数据源与清洗口径

## 正式数据源

正式输入仅使用 PandaData：

| 接口 | 频率 | 用途 |
|---|---|---|
| `get_lhb_detail(..., side="buy")` | 龙虎榜披露日 | 买方席位、排名、买卖金额 |
| `get_trade_cal(..., is_trading_day=1)` | 日频 | 有效交易日校验 |
| `get_market_data(..., type="stock")` | 日频 | 行情、成交额、涨跌停价和交易状态 |

真实运行通过环境变量 `PANDA_DATA_USERNAME`、`PANDA_DATA_PASSWORD` 鉴权。接口超限时，龙虎榜按 31 天、行情按 90 天和股票批次自动分段拉取。

## 字段与价格口径

- 龙虎榜：`symbol/date/type/side/rank/agency/b_value/s_value/reason`。
- 行情：`open/close/high/low/volume/amount/pre_close/limit_up/limit_down/trade_status`。
- 使用 PandaData 返回的同口径原始价格，不混用其他复权序列；持有期仅为次日开盘至后日收盘。
- 固定 Parquet 是 PandaData 原始接口快照，只用于可复现验收，不属于个人手工数据。

## 因子已知性

信号日 `t` 只使用 `t` 日收盘后已知的龙虎榜与行情。生产结果不写入未来收益。未来行情仅在 `backtest.py` 中计算评估收益。

```text
factor_value =
    (-z(net_buy_to_amount) - z(ret_5d) - z(ret_10d)) / 3
    + 0.25 * watch
    + 3.00 * buy
```

严格 `buy`：净买入占成交额当日前 10%，重复席位至少 1 个，同日有效买方席位至少 3 个，位置为高位但涨幅和成交热度不过热。

## 可成交回测

```text
entry = open[t+1]
exit = close[t+2]
跳过 entry_open >= entry_limit_up * 0.999
跳过停牌、缺失价格或无有效涨停价
net_return = exit / entry - 1 - round_trip_cost
```

标准成本 `0.003`，压力成本 `0.005`，极端信息性压力成本 `0.010`。

## 清洗与缺失处理

- 只保留买方前五席位。
- 剔除机构、股通和主要外资席位。
- 买入金额不低于 500 万元，净买入比例不低于 0.55。
- 同股票、日期、席位重复记录聚合。
- 停牌、无有效开盘价、无有效涨停价或无退出价的样本不可成交。
- 因子生产日期必须属于 PandaData 交易日历。
