# Pandadata 映射

本文件只记录 `us-sector-rotation` 的数据路由。真实调用前必须回到 `skills/pandadata-api/references/api-docs.md` 核对方法名、参数名、字段名和返回字段。

## 调用原则

- 参数名使用 `symbol`，不要使用复数字段名。
- `symbol` 按 Pandadata 文档的单数字段理解；需要多成分时由调用侧分批或按接口可接受方式处理，不在报告中臆造参数。
- `fields` 只写文档中存在的字段。
- 行业分类以接口返回为准，不做 GICS 或供应商分类的二次映射。
- 币种统一按 USD 处理；不要把 USD、HKD、CNY 合并比较。

## 核心接口

### get_us_detail

用途：取得美股基础信息和行业字段，建立成分-行业映射。

入参：

- `symbol`: 股票代码，非必填。
- `fields`: 返回字段，非必填。
- `status`: 是否在市，`1` 在市，`0` 退市，`-1` 未知，非必填。

常用字段：

- `symbol`
- `name`
- `status`
- `exchange_name`
- `business_sector`
- `economic_sector`
- `industry_group`

降级：若行业字段缺失，将该成分列入“未分类”，并在报告“数据说明”中写明缺失比例。

### get_us_daily

用途：回填成分日线，计算近 1D、1W、1M、3M、YTD 收益。

入参：

- `start_date`: 开始日期，格式如 `20250702`，非必填。
- `end_date`: 结束日期，格式如 `20250702`，非必填。
- `symbol`: 股票代码，非必填。
- `fields`: 返回字段，非必填。

常用字段：

- `symbol`
- `date`
- `name`
- `close`
- `pre_close`
- `volume`
- `trade_status`

计算：

- 1D 收益优先用 `close / pre_close - 1`。
- 1W、1M、3M、YTD 收益用窗口起点有效收盘价到数据日收盘价计算。
- 行业表现取成分收益 median，同时记录有效成分数和缺失成分数。

降级：若某窗口起点缺数据，用可得的最近前序交易数据，并在“数据说明”中写明。

### get_stock_sector_median

用途：取得 Pandadata 提供的行业中位统计数据，作为美股行业估值和质量指标的主口径。

入参：

- `symbol`: 股票代码，非必填。
- `fields`: 返回字段，非必填。

常用字段：

- `symbol`
- `date`
- `industry_name`
- `imed_pe_ttm`
- `imed_pb_ttm`
- `imed_pcfo_ttm`
- `imed_ps_ttm`

使用规则：

- `industry_name` 是接口口径，不做重命名映射。
- `imed_pe_ttm`、`imed_pb_ttm` 是行业中位 PE/PB snapshot。没有滚动缓存时，只能写“snapshot”或“横截面分位”。
- 若 `date` 与报告数据日不同，估值章节必须标注 as-of 日期。

### get_stock_mktfin_metric

用途：可选。取得个股市场财务统计指标，用于横截面 PE/PB 后再做行业 median 聚合。

入参：

- `symbol`: 股票代码，非必填。
- `fields`: 返回字段，非必填。

常用字段：

- `symbol`
- `date`
- `period_end_date`
- `curr_pe_dil_excl_ttm`
- `curr_pe_basic_excl_ttm`
- `curr_pb`

使用规则：

- 优先使用同一 PE 口径，不能把多个 PE 口径混合聚合。
- `period_end_date` 属于财报截止日期，可能滞后于市场数据日；报告必须说明。
- 该接口是 snapshot 数据。没有自有滚动缓存时，不写“历史分位”。

## 失败降级

- `get_stock_sector_median` 不可用：估值章节保留，写“行业中位估值接口不可用”，可用 `get_stock_mktfin_metric` 做成分 snapshot 聚合。
- `get_stock_mktfin_metric` 不可用：估值章节只写 `get_stock_sector_median` 可得字段，或说明估值数据缺失。
- `get_us_daily` 不可用：不生成收益排名，只写数据失败说明。
- `get_us_detail` 不可用：无法建立行业映射，停止生成完整报告，返回缺失原因。
