# 策略二·缠论因子研究报告

- 数据：CZSC可复现合成数据（24标的，仅用于流水线验证）
- 历史时点成分：否
- 规则：日线交易；30分钟只判断小转大一买/二买；日线二卖或三卖退出
- 成交：日线收盘信号，下一交易日开盘；A股T+1
- 搜索试验：22
- 接受因子：无（使用未排序基线）
- 试验状态：{"REJECTED": 21, "BASELINE": 1}

## 候选日志

| 因子 | 状态 | 原因 | 验证Sharpe | 验证主分 | 相关 |
|---|---|---|---|---|---|
| baseline_equal_weight | BASELINE | reference | 1.432 | 0.000 | 0.00 |
| xiaozhuan_confirm | REJECTED | discovery_score | 1.420 | 1.149 | 0.00 |
| oversold_in_turn | REJECTED | discovery_score | 1.599 | 1.052 | 0.00 |
| volume_confirm | REJECTED | discovery_score | 1.509 | 1.296 | 0.00 |
| liquidity | REJECTED | discovery_score | 1.596 | 1.168 | 0.00 |
| low_volatility | REJECTED | discovery_score | 1.601 | 1.033 | 0.00 |
| skip_momentum | REJECTED | discovery_score | 1.555 | 1.328 | 0.00 |
| reversal_5 | REJECTED | discovery_score | 1.456 | 1.115 | 0.00 |
| amihud_liquidity | REJECTED | discovery_score | 1.543 | 1.277 | 0.00 |
| range_quality | REJECTED | discovery_score | 1.450 | 1.090 | 0.00 |
| ma_extension | REJECTED | discovery_score | 1.467 | 1.023 | 0.00 |
| vol_compress | REJECTED | discovery_score | 1.810 | 1.276 | 0.00 |
| buy2_freshness | REJECTED | discovery_score | 1.585 | 1.192 | 0.00 |
| macd_align | REJECTED | discovery_score | 1.432 | 1.187 | 0.00 |
| zs_discount | REJECTED | discovery_score | 1.400 | 1.078 | 0.00 |
| down_bi_force | REJECTED | discovery_score | 1.526 | 1.252 | 0.00 |
| structure_efficiency | REJECTED | discovery_score | 1.807 | 1.343 | 0.00 |
| pivot_break_strength | REJECTED | discovery_score | 1.447 | 1.352 | 0.00 |
| divergence_proxy | REJECTED | discovery_score | 1.554 | 1.213 | 0.00 |
| risk_adjusted_reversal | REJECTED | discovery_score | 1.529 | 1.076 | 0.00 |
| range_position_20 | REJECTED | discovery_score | 1.615 | 1.350 | 0.00 |
| multi_freq_alignment | REJECTED | discovery_score | 1.433 | 1.227 | 0.00 |

## 冻结样本外结果

- 年化收益：-11.27%
- 成本后 Sharpe：-0.825
- 最大回撤：-36.83%
- 年化换手：41.14
- Bootstrap Sharpe 90%区间：[-2.902, 1.348]
- Deflated Sharpe 概率：0.000
- PBO估计：0.500
- 研究等级：reject

## 限制

- 本结果来自 CZSC 合成随机路径，只验证流水线；不能当成 A 股缠论选股绩效
- demo 跳过结构特征，bi_snr / bi_slope 记为 CRASH/missing_column
- 若成分股为当前截面而非历史时点成分，结论上限为探索性
- 未模拟盘口冲击和集合竞价排队
- 30分钟仅用于小转大买点，卖点与持仓管理在日线
- 历史回测不代表未来表现

本报告仅供量化研究与教育用途，不构成投资建议、自动交易指令或收益保证。