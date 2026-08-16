# PandaData 数据契约

## 来源

严格使用 PandaData。凭证来自环境变量或 `~/.pandadata/pandadata.env`，不得进入输出。

## 状态

- `ok`：接口返回记录且必要字段齐全；
- `empty`：调用成功但无记录；
- `error`：调用或字段错误；
- `unsupported`：SDK/服务端不支持。

`empty/error/unsupported` 不填零、不当中性，报告保留章节并显示 N/A 与原因。

## 接口矩阵

- 企业：`get_stock_detail`、`get_stock_industry`、`get_fina_reports`、`get_fina_performance`、`get_fina_forecast`、`get_audit_opinion`；
- 估值：A股使用 `get_factor`（`pe_ratio_ttm`、`pe_ratio_lyr`、`pb_ratio_lf`、`pb_ratio_ttm`、`pb_ratio_lyr`、`market_cap`），指数基准使用 `get_index_indicator`；`get_stock_mktfin_indicator` 属于 SDK 的港股 reader，不用于 .SH/.SZ；
- 市场：`get_trade_cal`、`get_index_daily`、`get_index_weights`、`get_margin`、`get_hsgt_hold`、`get_lhb_detail`、`get_fund_etf_cr_net`。

## 时间规则

所有信息必须在 `as_of` 当日已可知。财务数据同时检查报告期和公告/披露日期；已公告但未来发生的事件可以作为“已知催化/风险”，不能当作已实现结果。历史股票池使用截止日前最新成分快照，不使用当前成分股回填历史。

## 代理限制

公司业绩预告不等于卖方一致预期；北向持仓不是实时资金流；成交额不是主力净流入；ETF 净申赎不是国家队入场证明；估值分位不是市场完整共识。
