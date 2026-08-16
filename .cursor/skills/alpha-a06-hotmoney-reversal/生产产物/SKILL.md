---
name: alpha-a06-production
description: 当需要读取 A06 游资席位冷却反转与协同突破因子的生产结果时，使用此 skill。该 skill 只读取已生成的 Parquet，不在调用时拉取原始数据或重算因子。
tags: [quant, alpha, production, stock, lhb]
---

# A06 游资席位冷却反转与协同突破生产结果

## 适用场景

- 查询 A06 最新有效交易日结果。
- 交易 agent 使用 A06 辅助交易判断。

## 结果文件

- 文件路径：`数据库.parquet`
- 数据格式：Parquet
- 更新频率：每日收盘后
- 生成方式：生产任务使用已验收开发逻辑定时计算
- 数据版本：`pandadata-lhb-hotmoney-executable-open-a06-v1`

## 主键

- `trade_date`
- `factor_id`
- `ts_code`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 有效交易日期 |
| asset_type | string | 固定为 `stock` |
| ts_code | string | 股票代码 |
| factor_id | string | 固定为 `A06` |
| factor_name | string | 因子名称 |
| factor_value | float | 原始值，越大越强 |
| score | float | 每日横截面 0-100 评分 |
| rank | int | 每日横截面排名 |
| signal | string | `buy` / `watch` / `hold` |
| confidence | float | 0-1 置信度 |
| data_version | string | 数据版本 |
| update_time | string | 生成时间 |

## 读取规则

1. 直接读取 `数据库.parquet`。
2. 默认使用最新有效 `trade_date`；若不存在，可回退最近有效交易日，但必须说明数据日期。
3. 按 `trade_date`、`factor_id=A06`、`ts_code` 查询。
4. `watch` 只用于观察；`buy` 信号仍须执行 `t+1` 停牌/开盘涨停跳过规则。

## 禁止行为

- 不允许在 agent 调用时重新拉取原始行情或龙虎榜。
- 不允许在 agent 调用时重新计算因子。
- 不允许手工修改 `数据库.parquet`。
- 不允许使用旧因子编号、旧生产库或 `t+1 close` 偷价口径。

## 风险边界

- 信号稀疏，单票小仓位并限制组合总暴露。
- 新数据更新后发布验收失败时停止新增仓位。
