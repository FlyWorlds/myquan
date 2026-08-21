# 策略二·缠论因子研究报告

- 数据：CZSC可复现合成数据（36标的，仅用于流水线验证）
- 历史时点成分：否
- 规则：一买候选，二买确认开仓，三买增强，二卖或三卖退出
- 成交：30分钟收盘信号，下一根30分钟开盘；A股T+1
- 搜索试验：14
- 接受因子：无（使用未排序基线）
- 试验状态：{"REJECTED": 11, "CRASH": 2, "BASELINE": 1}

## 候选日志

| 因子 | 状态 | 原因 | 验证Sharpe | 验证主分 | 相关 |
|---|---|---|---|---|---|
| baseline_equal_weight | BASELINE | reference | 0.631 | 0.000 | 0.00 |
| buy1_freshness | REJECTED | discovery_score | 0.641 | 0.253 | 0.00 |
| buy2_freshness | REJECTED | discovery_score | 0.636 | 0.516 | 0.00 |
| buy3_freshness | REJECTED | discovery_score | 0.631 | 0.451 | 0.00 |
| bi_snr | CRASH | missing_column | nan | nan | nan |
| bi_slope | CRASH | missing_column | nan | nan | nan |
| structure_efficiency | REJECTED | discovery_score | 0.631 | 0.380 | 0.00 |
| pivot_break_strength | REJECTED | discovery_score | 0.631 | 0.380 | 0.00 |
| divergence_proxy | REJECTED | discovery_score | 0.630 | 0.426 | 0.00 |
| risk_adjusted_reversal | REJECTED | discovery_score | 0.636 | 0.250 | 0.00 |
| multi_freq_alignment | REJECTED | discovery_score | 0.630 | 0.416 | 0.00 |
| range_position_40 | REJECTED | discovery_score | 0.641 | 0.439 | 0.00 |
| volatility_40 | REJECTED | discovery_score | 0.634 | 0.373 | 0.00 |
| turnover_log | REJECTED | discovery_score | 0.641 | 0.495 | 0.00 |

## 冻结样本外结果

- 年化收益：-14.88%
- 成本后 Sharpe：-0.846
- 最大回撤：-55.93%
- 年化换手：141.26
- Bootstrap Sharpe 90%区间：[-1.910, 0.423]
- Deflated Sharpe 概率：0.000
- PBO估计：0.333
- 研究等级：reject

## 限制

- 本结果来自 CZSC 合成随机路径，只验证流水线；不能当成 A 股缠论选股绩效
- demo 跳过结构特征，bi_snr / bi_slope 记为 CRASH/missing_column
- 若成分股为当前截面而非历史时点成分，结论上限为探索性
- 未模拟盘口冲击和集合竞价排队
- 历史回测不代表未来表现

本报告仅供量化研究与教育用途，不构成投资建议、自动交易指令或收益保证。