# Pandadata Map

Use this map to plan港美股分红事件报告。真实调用前必须用 `pandadata-api/references/api-docs.md` 核对方法名、参数名和字段名。

## Core Methods

| 需求 | 港股方法 | 美股方法 | 说明 |
| --- | --- | --- | --- |
| 分红事件 | `get_stock_dividend_event` | `get_stock_dividend_activity` | 查询分红公告和执行事件。港股是 `event`，美股是 `activity`。 |
| 除息日价格 | `get_hk_daily` | `get_us_daily` | 取除息日或邻近交易日收盘价，用于收益率示意。 |
| 基础信息 | `get_hk_detail` | `get_us_detail` | 获取股票名称、行业、上市状态等基础资料；币种仍以分红事件字段为准。 |

## Parameters

| 方法 | 常用参数 | 注意事项 |
| --- | --- | --- |
| `get_stock_dividend_event` | `symbol`, `start_date`, `end_date`, `fields` | `symbol` 是单数字段名。日期格式按 Pandadata 文档使用 `YYYYMMDD`。 |
| `get_stock_dividend_activity` | `symbol`, `start_date`, `end_date`, `fields` | 美股使用 activity 方法，不要误调港股 event 方法。 |
| `get_hk_daily` | `symbol`, `start_date`, `end_date`, `fields` | 用于除息日价格和 TTM 收益率分母。 |
| `get_us_daily` | `symbol`, `start_date`, `end_date`, `fields` | 用于除息日价格和 TTM 收益率分母。 |
| `get_hk_detail` | `symbol`, `fields`, `status` | 用于名称、行业和上市状态。 |
| `get_us_detail` | `symbol`, `fields`, `status` | 用于名称、行业和上市状态。 |

## Event Fields

分红事件返回字段以 Pandadata 文档为准，常用字段包括：

| 字段 | 用途 |
| --- | --- |
| `publish_date` | 公告发布日期；报告中可列为公告日。 |
| `symbol` | 股票代码。 |
| `excute_date` | 事件执行日期；用于识别除息/执行日。字段名按文档拼写为 `excute_date`。 |
| `event_type` | 事件类型，例如 ExDividends。 |
| `number` | 每股现金金额。 |
| `currency` | 分红币种；必须按币种分池。 |
| `event` | 原始事件描述，用于识别特别股息、常规股息和口径备注。 |

## Degradation

1. 分红事件接口失败时，不生成排行数字；输出可用基础信息，并在“数据说明”写明缺失接口。
2. 行情接口失败时，可以保留事件日历和派息记录，但 TTM 股息率与 DRIP 示意必须标为不可计算。
3. 基础信息接口失败时，可以保留代码级表格，并在名称或行业处写“未取到”。
4. 字段不能区分特别股息和常规股息时，报告口径统一写为“所有现金分红”。
5. HKD/USD/CNY 等币种不得混合求和或合并排名。
