# PandaData 数据契约

> 本文档分为 SDK 静态能力与当前账号实测结果。静态存在不等于服务端可用；以 `--probe-only` 结果为准。

## 认证

只读取：

- `PANDA_USERNAME`
- `PANDA_PASSWORD`
- `~/.pandadata/pandadata.env`

凭证不得进入 JSON、Markdown、日志和异常文本。

## 使用接口

| 模块 | 方法 | 关键字段/用途 | 2026-07-31 实测 |
|---|---|---|---|
| 交易日 | `get_trade_cal` | `nature_date/is_trade` | 可用 |
| 全市场日线 | `get_stock_daily` | symbol/date/OHLC/pre_close/volume/amount | 可用 |
| 当日日线 | `get_stock_rt_daily` | 只探测，不与完整日线混用 | 可用 |
| 指数成分股 | `get_index_weights` | 沪深300/中证500/中证1000历史成分股快照 | 可用 |
| 宽基指数 | `get_index_daily` | 宽基 OHLC/volume/amount | 可用 |
| 融资 | `get_margin` | margin_balance/buy_on_margin_value/margin_repayment | 可用；cash/stock 重复记录需去重 |
| 北向持仓 | `get_hsgt_hold` | `date/symbol/shares_num/holding_ratio/adjusted_holding_ratio` | 可用；按季度快照返回，需按股票传参并使用宽窗口 |
| 龙虎榜 | `get_lhb_detail` | agency/b_value/s_value | 可用 |
| 国家队持仓 | `get_top_holders` | holder_name/end_date/hold_percent_float | 可用 |
| ETF 净申赎 | `get_fund_etf_cr_net` | net_inflow/net_redemption/shares_change | 可用 |
| ETF 行情 | `get_fund_daily` | OHLC/volume/amount | 可用 |
| 股票基本信息 | `get_stock_detail` | 名称、上市状态 | 可用 |
| 行业归属 | `get_stock_industry` | 单股参数 `stock_symbol`, `level=L1` | 可用 |

## 调用结果状态

每个调用统一返回：

- `ok`：有数据且满足最低字段要求；
- `empty`：调用成功但无记录；
- `error`：鉴权、服务端、参数或网络错误；
- `unsupported`：SDK 不存在或已知未上线。

每项溯源记录：方法、窗口、参数摘要、行数、列名、最新日期、状态和无敏感信息的错误摘要。

## 时间边界

- `--as-of` 是硬截止日期。
- 指数股票池使用 `get_index_weights` 在 `as_of` 及之前的最新快照，不使用当前成分替代历史成分。
- 历史日扫描只调用 `start_date <= date <= as_of` 的接口。
- 默认分析日使用最近完整交易日；盘中不将 `get_stock_rt_daily` 与收盘数据拼接。
- 股东持仓按报告期记录，并标注披露滞后，不当作实时流量。

## 实测命令

```bash
python3.11 scripts/oversold_rebound.py --probe-only \
  --out-json /tmp/oversold_rebound_probe.json \
  --out-md /tmp/oversold_rebound_probe.md
```

2026-07-31 实测 11 个接口中 8 个对单一探测标的返回记录；北向与龙虎榜对该标的为空，但全市场接口可返回记录。ETF 净申赎和 ETF 行情接口均可用。脚本不会把凭证写入探测结果。
