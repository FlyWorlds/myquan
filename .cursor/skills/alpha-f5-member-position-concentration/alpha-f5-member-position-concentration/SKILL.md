---
name: alpha-f5-member-position-concentration
description: Use when developing, computing or validating the F5 commodity futures member-position concentration factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, development, future]
---

# 会员持仓集中度 Alpha

## 适用场景

- 当用户需要计算期货会员持仓集中度因子时
- 当用户需要验证前5大净多/净空席位集中度信号是否有效时
- 当用户需要生成商品期货横截面 `buy` / `sell` / `hold` 候选信号时

## 因子逻辑

- 核心假设：前5大净多（或净空）席位持仓保证金占全市场超过60%时，主力方向高度一致，价格跟随主力运动。
- 多头集中度：`bull_ratio = sum(top5 net_margin by 净多) / sum(abs(net_margin) all brokers)`
- 空头集中度：`bear_ratio = sum(abs(top5 net_margin by 净空)) / sum(abs(net_margin) all brokers)`
- 原始权重：`raw_weight = bear_ratio - bull_ratio`（正值代表空方更集中，负值代表多方更集中）
- Level 路径：对 `raw_weight` 做 60日滚动 Z-score → `zscore_level`，`min_periods=20`
- Delta 路径：对 `raw_weight` 做一阶差分后再做 60日滚动 Z-score → `zscore_delta`，`min_periods=20`
- 混合：`factor_value = 0.5 × zscore_level + 0.5 × zscore_delta`（两路同时有值才保留，等权）
- 信号门槛：`bull_ratio > 0.6 AND factor_value > 0 AND rank ≤ 前90%` → buy；`bear_ratio > 0.6 AND factor_value < 0 AND rank ≥ 后10%` → sell（`BUY_QUANTILE=SELL_QUANTILE=0.1`）
- 排序方向：`factor_value` 越大越好（横截面降序排名，rank=1 为最高）

## 输入数据

因子计算必须使用 Panda data SDK，不读取本地表格作为正式输入。

| 字段 | 说明 | 来源 |
|---|---|---|
| date | 交易日期 | `panda_data.get_broker_netmarg` |
| underlying_symbol | 期货品种代码 | `panda_data.get_broker_netmarg` |
| broker | 席位名 | `panda_data.get_broker_netmarg` |
| net_margin | 净持仓保证金，正为净多，负为净空 | `panda_data.get_broker_netmarg` |

## 输出结果

| 字段 | 说明 |
|---|---|
| trade_date | `YYYY-MM-DD` 交易日 |
| asset_type | 固定为 `future` |
| symbol | 期货品种代码 |
| factor_id | 固定为 `F5` |
| factor_name | 固定为 `会员持仓集中度` |
| factor_value | Level Z-score 与 Delta Z-score 的等权混合值（各60日滚动），不限制在 [-1, 1] |
| score | 当日横截面百分位评分，范围 `[0, 100]` |
| rank | 当日横截面整数排名，`1` 为最优 |
| signal | `buy` / `sell` / `hold` |
| confidence | `score / 100` |
| data_version | 固定为 `real-v2` |
| update_time | ISO8601 生成时间 |

## 因子评价标准

Alpha 任务需要同时报告因子预测能力和策略层表现。

| 分类 | 指标 | 方向 | 说明 |
|---|---|---|---|
| Factor Predictive Power | `IC` | 越高越好 | 因子值与下一期收益的 Pearson 相关 |
| Factor Predictive Power | `ICIR` | 越高越好 | IC 均值 / IC 标准差 |
| Factor Predictive Power | `Rank IC` | 越高越好 | 因子排名与下一期收益排名的 Spearman 相关 |
| Factor Predictive Power | `Rank ICIR` | 越高越好 | Rank IC 均值 / Rank IC 标准差 |
| Strategy Performance | `IR(SHR*)` | 越高越好 | 多空组合收益的信息比率/年化 Sharpe 近似 |
| Strategy Performance | `CR` | 越高越好 | 累计收益 / 最大回撤绝对值 |
| Strategy Performance | `ARR(%)` | 越高越好 | 年化收益率 |
| Strategy Performance | `MDD(%)` | 越低越好 | 最大回撤 |

硬性要求：

- 不允许未来函数：因子在 `t` 日形成时，只能使用 `t` 日及以前可获得的席位净持仓。
- 回测收益使用 Method A：`t` 日主力同一合约的 `t+1 close / t close - 1`，换月价差不计入收益。
- MVP 不计手续费、滑点、保证金占用和换仓成本。

## 使用方式

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

运行前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD`。可选设置 `PANDA_DATA_START_DATE`、`PANDA_DATA_END_DATE` 和 `PANDA_DATA_UNDERLYING`。

## Agent 执行规则

1. 先运行 `scripts/factor.py`，确认 Panda data 返回真实席位净持仓，且因子结果非空。
2. 再运行 `scripts/validate.py`，确认无未来函数、字段完整、取值范围合法、信号枚举合法、样本外切片可用。
3. 最后运行 `scripts/backtest.py`，输出两组指标：
   - **研究口径**：`IC`/`ICIR`/`IC_p`/`Rank IC`/`Rank ICIR`/`Bootstrap IC 95% CI`/多周期 IC 衰减（1D/2D/3D/5D/10D/20D）/`ARR(%)`/`MDD(%)`/`CR`/`分层收益`/`多空收益`/`换手率`/`换月次数`/`成本敏感性`（0/0.05%/0.15%/0.30% 四档）。
   - **可交易口径**：`tradeable_ARR(%)`/`tradeable_IR`（data_lag=1 日，换月成本 5bps，交易成本 5bps）。
4. 如果任一步失败，必须报告失败命令、错误信息和数据日期，不得进入生产。

## 成功标准

- `factor.py` 输出非空，包含 12 个必需字段，`factor_id=F5`，`data_version=real-v2`。
- `validate.py` 输出验证通过信息。
- `backtest.py` 输出研究口径和可交易口径两组指标，包含多周期 IC 衰减（1D-20D）、Bootstrap IC 95% CI、成本四档分析和可交易 ARR/IR。
- 数据来源为 Panda data SDK，不读取本地文件作为正式输入。

## 边界

本 skill 仅用于研究和验证，不构成投资建议，不承诺收益，不代表任何平台或组织的官方背书。不得记录、提交或传播 Panda data 凭据。

## 验收要求

- 不允许未来函数。
- 必须有样本外验证。
- 必须有回测指标。
- 必须使用 PandaAI data 或项目指定数据源实现。
- 不通过验证不得进入生产。

## 依赖

- Python 3.10+
- panda-data
- pandas
- scipy
- pyarrow 或 fastparquet

## 与生产产物的关系

开发产物用于计算、验证和回测；生产产物用于读取已生成结果。在生产查询时应使用 `alpha-f5-member-position-concentration-production`，不要临时重算因子。
