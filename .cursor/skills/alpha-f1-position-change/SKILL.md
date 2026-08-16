---
name: alpha-f1-position-change
description: 当需要开发、计算、验证期货前20席位持仓突变因子时，使用此 skill。支持多空持仓优势分析、主力调仓方向判断。
tags: [quant, alpha, development, future]
---

# 期货前20席位持仓突变 Alpha

## 适用场景

- 当用户需要分析期货前20席位持仓突变时
- 当用户需要计算基于主力调仓行为的 Alpha 因子时
- 当用户需要验证期货持仓类因子的完整交付流程时

## 因子逻辑

- 核心假设：将前20名持仓按品种加总，每个品种独立计算。当某品种多头增加2%以上或空头减少2%以上时，判定为该品种多头优势；当多头减少2%以上或空头增加2%以上时，判定为该品种空头优势。
- 计算公式：
  - 每个品种前20名多头总和 = Σ(多头持仓)
  - 每个品种前20名空头总和 = Σ(空头持仓)
  - 多头变化率 = (今日多头总和 - 昨日多头总和) / abs(昨日多头总和)
  - 空头变化率 = (今日空头总和 - 昨日空头总和) / abs(昨日空头总和)
  - factor_value = 多头变化率 - 空头变化率
  - signal = "buy"  当 多头变化率 >= 2% 或 空头变化率 <= -2%
  - signal = "sell" 当 多头变化率 <= -2% 或 空头变化率 >= 2%
  - signal = "hold" 其他情况
- 排序方向：因子值越大表示多头优势越强
- 适用市场：支持 panda_data `get_future_netposi_rank` 的所有期货品种
- 输出格式：每个品种每天生成一条记录，支持多品种 Rank IC 计算

## 输入数据

本示例使用 Panda data SDK 拉取期货持仓数据。正式开发时，因子计算必须使用 PandaAI data 数据拉取库或项目指定数据源获取数据。

| 字段 | 说明 | 来源 |
|---|---|---|
| date | 交易日期 | get_future_netposi_rank |
| broker_name | 期货公司名称 | get_future_netposi_rank |
| net_position | 净持仓量 | get_future_netposi_rank |
| position_type | 持仓类型(long/short) | 合并时添加 |

## 输入契约

调用 `load_position_data` / `panda_data.get_future_netposi_rank` 时的字段契约：

- **underlying_symbol 格式**：品种代码（如 `"AP"`、`"AU"`），不含合约月份（`"AP801"` 错）、不含交易所后缀（`"AP.CZC"` 错）
- **大小写**：必须大写（`"ap"` 不会工作）
- **数据类型**：列表（`["AP", "AU"]`）；分批调用上限 `BATCH_SIZE = 8`，超出自动分批
- **错误处理**：panda_data 静默跳过无效代码，返回空 DataFrame；本 skill 因 `combined_df.empty` 抛 `ValueError("未获取到期货持仓数据...")`
- **接口返回字段契约**：必须包含 `underlying_symbol`、`date`、`broker_name`、`net_position` 三列。如接口字段名为 `symbol` / `code` / `instrument_id`，`validate_input` 会自动映射为 `underlying_symbol`，但会打印 `[INFO]` 警告
- **调试模式**：设置环境变量 `PANDA_DATA_DEBUG=1` 后，首次成功 API 调用会打印接口返回字段名与前 3 行示例，便于排查契约不匹配问题

## 输出结果

每日期生成一条记录，包含以下字段：

| 字段 | 说明 |
|---|---|
| trade_date | 交易日期（YYYY-MM-DD 格式） |
| asset_type | 资产类型（future） |
| symbol | 标的代码 |
| factor_value | 因子原始值（多头变化率 - 空头变化率） |
| score | (0, 100) 标准化评分（z-score 经 logistic 映射，公式 `100/(1+exp(-z))`）；当日品种数 < 5 时降级为 NaN |
| rank | 横截面排名 |
| signal | 交易信号：`buy`（多头优势）/ `sell`（空头优势）/ `hold` |
| confidence | \|z-score\|，当日因子值偏离横截面均值的标准差倍数；当日品种数 < 5 时降级为 NaN |
| long_total | 当前多头总持仓 |
| short_total | 当前空头总持仓 |
| prev_long_total | 前一日多头总持仓 |
| prev_short_total | 前一日空头总持仓 |
| long_change_rate | 多头变化率 |
| short_change_rate | 空头变化率 |
| long_broker_count | 参与多头计算的期货公司数 |
| short_broker_count | 参与空头计算的期货公司数 |

## 因子评价标准

Alpha 任务需要同时报告因子预测能力和策略层表现，不能只给单一收益结果。

| 分类 | 指标 | 方向 | 说明 |
|---|---|---|---|
| Signal Statistics | 信号频率 | 合理范围 | buy/sell 信号占比，过高可能过拟合 |
| Signal Statistics | 多头优势天数 | 参考指标 | 多头变化率 >= 2% 的天数 |
| Signal Statistics | 空头优势天数 | 参考指标 | 空头变化率 >= 2% 的天数 |
| Broker Coverage | 活跃期货公司数 | 越多越好 | 参与计算的期货公司数量 |

硬性要求：

- 不允许未来函数：因子在 `t` 日形成时，只能使用 `t` 日及以前可获得的数据。
- 不允许偷价：策略评估不得假设用 `t` 日收盘后才知道的信号，在同一个 `t` 日收盘价成交。
- 成交时点：信号 `t` 日收盘后产生 → `t+1` 日开盘成交 → `t+1` 日收盘平仓（严格口径）。
- 收益数据源：`forward_return` 必须来自 `panda_data.get_future_daily` 主力合约真实价格，不允许使用持仓差分 proxy。
- forward_return 必须从 `t+1` 日开始取，不允许与因子共用 `t` 日数据（避免持仓自相关伪 IC）。
- 期货持仓数据通常在收盘后发布，正式策略应考虑数据发布延迟和实际可交易性。

## 使用方式

Agent 使用本 skill 时，应在 `开发产物` 目录下执行命令，优先按下面顺序运行：

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
python scripts/report.py
```

第四步 `report.py` 生成 HTML 回测报告（`reports/report.html`），含 4 张图、8 张指标卡片、Top 20 品种表，self-contained 单文件可离线查看。

运行前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 环境变量。
可选设置 `PANDA_DATA_START_DATE` 和 `PANDA_DATA_END_DATE` 控制样本区间。

### 离线验证模式（CI 友好）

为支持 CI/无网络场景下的可复现验证，提供 fixture 离线模式：

```bash
# 1. 一次性生成 fixture（需联网 + 凭证）
python scripts/save_fixture.py
# 生成 scripts/fixtures/sample_positions.parquet + sample_prices.parquet

# 2. 后续验证无需联网
export PANDA_DATA_OFFLINE=1
python scripts/validate.py
```

- `PANDA_DATA_OFFLINE=1`：从 `fixtures/` 加载固定数据，跳过联网调用
- fixture 入 git，保证 bug 报告时可复现
- 若仅生成 positions fixture（无 prices fixture），`check_ic_stability` 自动跳过，其它 check 全部正常
- `check_factor_contract`（10 条契约断言）始终离线可跑，不依赖任何 fixture

### HTML 报告生成（CI 友好）

```bash
# 离线模式生成 HTML 报告（无需凭证）
python scripts/report.py --offline
# 输出：reports/report.html + reports/backtest_result.json

# 自动用浏览器打开
python scripts/report.py --offline --open
```

- 离线模式下若本地未装 `panda_data` SDK，会自动注入 stub 模块绕过 `factor.py` 顶层 import
- pyarrow 19 与旧版 parquet 不兼容时，自动 fallback 到 `fastparquet` 引擎
- `--dpi` 控制 PNG 体积（默认 100），`--html-path` / `--json-path` 自定义输出路径

## Agent 执行规则

1. 先运行 `scripts/factor.py`，确认 Panda data 能返回持仓数据，且因子结果非空。
2. 再运行 `scripts/validate.py`，确认字段完整、时间顺序正确、无未来函数问题。
3. 接着运行 `scripts/backtest.py`，输出信号统计、IC/ICIR、分层收益等回测指标。
4. 最后运行 `scripts/report.py`，生成 HTML 回测报告（含 4 图 + 8 指标卡 + Top 20 品种表）。
5. 如果任一步失败，必须报告失败命令、错误信息和数据日期，不得直接进入生产。

## 成功标准

- `factor.py` 能输出包含 `factor_value`、`score`、`rank`、`signal` 的结果。
- `validate.py` 输出验证通过信息（含样本外 IC 稳定性检验）。
- `backtest.py` 至少输出 IC、ICIR、信号频率、样本数。
- `report.py` 能生成包含 4 张图、8 张指标卡片、Top 20 品种表的 self-contained HTML 报告。
- IC、ICIR 必须基于 `get_future_daily` 返回的真实价格收益，严禁使用持仓 proxy 计算伪 IC。
- 回测输出必须说明收益评估口径（严格口径 `forward_return = close_{t+1}/open_{t+1} - 1`），避免未来函数和偷价。
- 结果中的 `data_version` 应为真实数据版本，例如 `real-v1`。

## 与生产产物的关系

开发产物用于计算、验证和回测；生产产物用于读取已生成结果。Agent 在开发验证时可以运行本 skill 的脚本，但在生产查询时应使用 `alpha-f1-position-change-production`，不要临时重算因子。

## 验收要求

- 不允许未来函数。
- 必须有样本外验证。
- 必须有回测指标。
- 正式任务必须使用 PandaAI data 或项目指定数据源实现。
- 不通过验证不得进入生产。

## 依赖

- Python 3.10+
- panda-data
- pandas
- numpy
- matplotlib（HTML 报告生成，`scripts/report.py`）
- fastparquet（pyarrow 19 与旧版 parquet 文件不兼容时的 fallback 引擎）
