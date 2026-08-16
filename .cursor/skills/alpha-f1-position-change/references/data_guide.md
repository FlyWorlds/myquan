# 数据源与字段说明

## 数据来源

本因子使用 Panda data SDK 拉取期货持仓数据。

**正式 Alpha 开发必须使用 PandaAI data 数据拉取库或项目明确指定的数据源。** 不得使用来源不明、字段不稳定、个人临时整理的数据文件作为正式输入。

如不确定数据源、字段口径或权限配置，必须咨询项目工作人员后再开发。

## Panda data SDK 接口

本因子使用 `panda_data.get_future_netposi_rank` 获取期货持仓排名数据。

### 接口说明

- 函数名：`get_future_netposi_rank`
- 参数：
  - `start_date`: 开始日期（格式 YYYYMMDD）
  - `end_date`: 结束日期（格式 YYYYMMDD）
  - `underlying_symbol`: 标的代码列表，如 `["SR", "AP"]`
  - `max_rank`: 最大排名，示例使用 20（前20席位）
  - `type`: 持仓类型，`"long"` 或 `"short"`
- 返回字段：
  - `date`: 交易日期
  - `broker_name`: 期货公司名称
  - `net_position`: 净持仓量

## 环境变量

运行前设置：

```bash
set PANDA_DATA_USERNAME=你的账号
set PANDA_DATA_PASSWORD=你的密码
```

`panda-data` 要求 Python 3.10 以上。当前录屏环境可使用 Codex 自带 Python 3.12。

可选参数：

```bash
set PANDA_DATA_START_DATE=2026-01-01
set PANDA_DATA_END_DATE=2026-06-07
```

日期格式支持 `YYYY-MM-DD`，代码会自动转换为 Panda data 要求的 `YYYYMMDD` 格式。

## 字段口径

| 字段 | 口径 |
|---|---|
| date | Panda data `date` 字段，交易日期（格式 YYYYMMDD） |
| broker_name | Panda data `broker_name` 字段，期货公司名称 |
| net_position | Panda data `net_position` 字段，净持仓量 |
| position_type | 合并时添加：'long' 或 'short' |
| trade_date | 输出时转换为 YYYY-MM-DD 格式 |

## 因子计算

新算法逻辑（按品种独立计算）：

```text
# 1. 按品种、日期和持仓类型加总前20名持仓
long_total(symbol, date) = Σ 前20名多头持仓
short_total(symbol, date) = Σ 前20名空头持仓

# 2. 计算每个品种的多空变化率
long_change_rate = (long_total(today) - long_total(yesterday)) / |long_total(yesterday)|
short_change_rate = (short_total(today) - short_total(yesterday)) / |short_total(yesterday)|

# 3. 计算因子值
factor_value = long_change_rate - short_change_rate

# 4. 生成信号（每个品种独立）
signal = "buy"  当 long_change_rate >= 2% 或 short_change_rate <= -2% （多头优势）
signal = "sell" 当 long_change_rate <= -2% 或 short_change_rate >= 2% （空头优势）
signal = "hold" 其他情况

# 5. 输出格式
每个品种每天生成一条记录，支持多品种 Rank IC 计算
```

本因子只使用当前交易日及之前的持仓数据，不使用未来行情或数据。

## 清洗规则

- 多头和空头数据必须同时存在，否则抛出异常。
- 前一日持仓为 0 时，变化率设为 0。
- 第一日数据无前一日参考，不生成因子。
- 每日期生成一条记录，包含多空持仓总和和变化率。

## 正式接入提醒

正式任务中如果出现以下情况，必须先咨询项目工作人员，再进入开发：

- 期货合约代码格式或换月规则不明确
- 持仓数据口径（净持仓/ gross 持仓）不明确
- 交易日历（是否包含节假日/周末）不明确
- 期货公司排名范围（前5/前10/前20）不明确
- 数据权限或接口限制不清楚

## PandaAI data 接入说明

当正式接入 PandaAI data 数据拉取库时，需要确认：

1. **接口名称**：对应的数据拉取函数名
2. **参数格式**：日期格式、标的代码格式
3. **返回字段**：字段名称、数据类型、单位
4. **更新频率**：数据更新时间、延迟情况
5. **权限配置**：需要的账号权限、申请流程
6. **数据限制**：单次查询范围、频率限制

如上述任何信息不明确，请先咨询项目工作人员。
