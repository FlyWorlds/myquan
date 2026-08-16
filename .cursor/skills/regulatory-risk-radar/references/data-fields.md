# 数据字段映射 (data-fields)

各 Pandadata 接口的关键返回字段 → 风险语义映射。字段以实测 gateway 返回为准。

## get_stock_shareholder_change（股东增减持计划）
| 字段 | 含义 | 用途 |
|---|---|---|
| direction | 变动方向（减持/增持） | 仅"减持"计入风险 |
| ratio_up_limit | 占总股本比例上限(%) | 规模因子 |
| shareholder_type | 股东/高管/实际控制人 | 类型修正 |
| progress | 进度（预披露/实施中/已完成） | 证据展示 |
| info_date | 公告日期 | 时间邻近因子 |
| trigger_price / trigger_days | 触发价/连续天数 | 条件式减持证据 |

## get_restricted_list（限售解禁）
| relieve_date | 解禁日期 | 前瞻窗口 + 邻近加权 |
| relieve_shares | 解除限售股数 | 规模 |
| shareholder_type | 股东类型 | 证据 |
| relieve_reason | 解禁原因 | 证据 |

## get_stock_pledge（股权质押）
| acc_pledge_total_ratio | 累计质押占总股本(%) | 规模因子（核心） |
| pledge_ratio | 本次质押占其持股(%) | 辅助 |
| publish_date | 公告日期 | 时间因子 |

## get_stock_equity_placard（举牌）
| total_share_ratio | 占总股本比例(%) | 规模 |
| shareholder_name | 举牌方 | 证据 |
| info_date | 公告日期 | 时间因子 |

## get_top_holders（前十大股东）
| freeze | 股权冻结涉及股数 | >0 触发冻结风险 |
| pledge | 股权质押涉及股数 | 辅助交叉验证 |
| holder_name | 股东名 | 证据 |

## get_stock_daily（日线，st=True）
| trade_status | 停牌标记（0=正常） | !=0 触发停牌 |
| name | 含 ST/*ST | 触发 ST 风险 |

## 注意
- 网关模式（data_mode=gateway）返回行数受套餐配额限制；大股票池需按 symbol 分批。
- 举牌/质押部分接口为全市场返回，需按 symbol 过滤后入池。
- 日期统一 YYYYMMDD。
