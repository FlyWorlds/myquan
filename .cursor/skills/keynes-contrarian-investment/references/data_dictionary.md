# 数据字典

| 对象 | 常见字段 | 时间语义 | 说明 |
|---|---|---|---|
| 行情 | `symbol/date/close/amount` | 交易日 | 价格与成交行为，不等于基本面 |
| 财务 | `revenue/net_profit/operating_cash_flow` | 报告期+公告日 | 计算趋势与现金转换 |
| 预告 | `forecast/profit_change` | 公告日+预计期间 | 公司披露，不是分析师一致预期 |
| 估值因子 | `pe_ratio_ttm/pe_ratio_lyr/pb_ratio_lf/pb_ratio_ttm/market_cap` | 交易日 | 通过 `get_factor` 获取；负 PE 无效，历史分位是定价代理 |
| 融资 | `margin` | 交易日/披露日 | 杠杆和流动性代理 |
| 北向 | `holding_ratio/shares_num` | 报告期快照 | 滞后持仓代理，不是实时流量 |
| ETF | `net_inflow/shares_change` | 交易日 | 申赎/风险偏好代理 |

状态应标记为 `ok/derived/proxy/empty/error/unsupported`。每个衍生字段保存公式、源字段和日期。
