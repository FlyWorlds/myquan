# Pandadata Map

本文件用于规划 `cross-listing-parity` 的 Pandadata 调用。真实方法名、参数名和字段名必须以 `skills/pandadata-api/references/api-docs.md` 为准。

## 已验证方法

| 需求 | Preferred method | 关键参数 | 主要字段 | 说明 |
| --- | --- | --- | --- | --- |
| A 股日线 | `get_stock_daily` | `symbol`, `start_date`, `end_date`, `fields` | `date`, `symbol`, `name`, `close`, `pre_close`, `volume`, `amount`, `trade_status` | A/H 折算中的 A 股收盘价来源。 |
| A 股交易清单 | `get_trade_list` | `date`, `exchange` | `symbol`, `date` | 用于校验 A 股代码是否在指定日期可交易；Pandadata 文档未提供其他 A 股清单方法。 |
| 港股日线 | `get_hk_daily` | `symbol`, `start_date`, `end_date`, `fields` | `date`, `symbol`, `name`, `close`, `pre_close`, `volume`, `trade_status` | A/H 折算中的 H 股收盘价来源。 |
| 美股日线 | `get_us_daily` | `symbol`, `start_date`, `end_date`, `fields` | `date`, `symbol`, `name`, `close`, `pre_close`, `volume`, `trade_status` | 中概 ADR 折溢价来源。 |
| 港股基础信息 | `get_hk_detail` | `symbol`, `fields`, `status` | `symbol`, `name`, `cn_name`, `status`, `isin_code`, `trading_code`, `listed_date` | 用于校验港股代码、名称、上市状态。 |
| 美股基础信息 | `get_us_detail` | `symbol`, `fields`, `status` | `symbol`, `original_symbol`, `name`, `status`, `isin_code`, `exchange_name`, `listed_date` | 用于校验 ADR 代码、名称、上市状态。 |

## 调用顺序

1. 读取 `references/pairs/a-h-pairs.csv` 与 `references/pairs/adr-pairs.csv`，取出待监控代码和 `ratio`。
2. 用 `get_trade_list(date=数据日)` 校验 A 股代码在数据日是否可交易。
3. 用 `get_hk_detail(symbol=港股代码列表, status=1)` 与 `get_us_detail(symbol=ADR代码列表, status=1)` 校验港股和美股标的状态。
4. 分别调用 `get_stock_daily`、`get_hk_daily`、`get_us_daily` 获取同一报告窗口内的收盘价。
5. 使用用户提供或已验证来源的 USD/HKD/CNY 汇率做折算。没有汇率时只列原币行情，不计算折溢价。

## 计算口径

A/H 溢价的基础口径：

```text
A/H 溢价 = A股价格(CNY) / (H股价格(HKD) * HKD/CNY * ratio) - 1
```

ADR 折溢价的基础口径：

```text
ADR 折溢价 = ADR价格(USD) / (原生市场价格 * 原生币种兑USD折算 * ratio) - 1
```

实际报告必须写明使用的汇率方向。例如 `HKD/CNY` 表示 1 HKD 折合多少 CNY。不要混用 `CNY/HKD`。

## 失败降级

当某一接口不可用或返回空值：

1. 保留已取得市场的原币价格和数据日。
2. 不用前值填补缺失市场价格。
3. 不计算缺失配对的折溢价。
4. 在 `数据说明` 写明缺失接口、缺失标的、影响范围和是否降级为 snapshot。

## 汇率

本 skill 不内置可验证的 Pandadata 汇率方法。若用户环境确认存在宏观或外汇接口，使用前必须在 `pandadata-api/references/api-docs.md` 中验证方法名、参数名和字段名；否则要求用户提供 USD/HKD/CNY 汇率、来源和日期。
