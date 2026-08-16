# skill-alpha-f1-position-change

**简体中文** | [English](README.en.md)

> 期货前 20 席位持仓突变 Alpha 因子：从 PandaAI 期货持仓数据计算多空突变信号，输出可验证的因子表、回测指标与 HTML 可视化报告。

<p align="center">
  <img alt="libraries" src="https://img.shields.io/badge/libraries-Futures%20Top20%20Position-blue">
  <img alt="factor" src="https://img.shields.io/badge/factor-F1-brightgreen">
  <img alt="type" src="https://img.shields.io/badge/type-alpha--development-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-PandaAI-9cf">
  <img alt="status" src="https://img.shields.io/badge/status-active-brightgreen">
  <img alt="validation" src="https://img.shields.io/badge/validation-L2%20contract--checked-success">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-alpha-f1-position-change` 是一个期货持仓突变因子 Skill，用于计算前 20 席位多空持仓突变因子值，并完成验证、回测与离线复现。

这个 Skill 适合用于：

- 期货前 20 席位多空持仓突变因子的开发与批量计算
- 主力合约持仓数据的因子矩阵构建（SHFE / INE / DCE / CZCE / GFEX / CFFEX 全市场 61 个品种）
- 因子值验证、契约检查、IC 稳定性回测的完整工作流
- Claude Code 对话中触发确定性因子计算与回测

本 Skill 通过 `panda_data` SDK 拉取真实持仓与价格数据，输出因子表、回测指标（IC/ICIR/分层收益/Calmar）、HTML 可视化报告以及离线 fixture，便于 CI 集成。

## 仓库内容

| 文件 | 说明 |
|---|---|
| `SKILL.md` | Skill 契约文档（Agent 内部使用） |
| `scripts/factor.py` | 因子计算入口（持仓 → 因子表） |
| `scripts/validate.py` | 因子验证（契约检查 + IC 稳定性 + 离线模式） |
| `scripts/backtest.py` | 回测评估（真实价格收益 IC/ICIR） |
| `scripts/backtest_report_data.py` | 回测时序数据包装层（HTML 报告数据源） |
| `scripts/report.py` | HTML 报告生成入口（matplotlib 静态图） |
| `scripts/save_fixture.py` | 一次性生成离线测试 fixture |
| `scripts/fixtures/` | 离线测试数据（Parquet 格式） |
| `requirements.txt` | Python 依赖清单 |
| `references/data_guide.md` | PandaAI 数据接口参考 |
| `LICENSE` | GPLv3 协议 |
| `README.md` / `README.en.md` | 中英文 README |

## 目录结构

```text
skill-alpha-f1-position-change/
├── SKILL.md
├── README.md
├── README.en.md
├── LICENSE
├── requirements.txt
├── references/
│   └── data_guide.md
├── scripts/
│   ├── factor.py                  # 因子计算（含 load_position_data / load_price_data）
│   ├── validate.py                # 验证（含 check_factor_contract 11 条契约）
│   ├── backtest.py                # 回测（严格口径 forward_return）
│   ├── backtest_report_data.py    # 回测时序数据包装层（保留 curve / daily_ic / drawdown）
│   ├── report.py                  # HTML 报告生成入口（matplotlib + base64）
│   ├── save_fixture.py            # 离线 fixture 生成
│   └── fixtures/                  # 离线测试数据（首次运行后生成）
│       ├── sample_positions.parquet
│       └── sample_prices.parquet
└── reports/                       # 报告产物（.gitignored）
    ├── backtest_result.json       # 中间数据（含全部时序）
    └── report.html                # 最终 HTML 报告（self-contained）
```

## 数据要求

调用 `panda_data.get_future_netposi_rank` 与 `get_future_daily` 的输入契约：

| 字段 | 类型 | 说明 |
|---|---|---|
| `underlying_symbol` | str | 品种代码（如 `"AP"`），不含合约月份、不含交易所后缀 |
| `date` | str | 交易日期 YYYYMMDD 格式 |
| `broker_name` | str | 期货公司名称 |
| `net_position` | int | 净持仓量 |
| `position_type` | str | 持仓类型：`long` 或 `short` |

输入契约细则：

- **underlying_symbol 格式**：品种代码（`"AP"`、`"AU"`），不是合约代码（`"AP801"`）
- **大小写**：必须大写
- **错误处理**：panda_data 静默跳过无效代码，返回空 DataFrame；本 Skill 因 `combined_df.empty` 抛 `ValueError`
- **接口字段契约**：必须返回 `underlying_symbol` 字段；如返回 `symbol` / `code` / `instrument_id`，`validate_input` 会自动别名映射并打印 `[INFO]` 警告

## 快速开始

### 环境准备

```bash
export PANDA_DATA_USERNAME=your_username
export PANDA_DATA_PASSWORD=your_password

# 可选：控制数据区间
export PANDA_DATA_START_DATE=2026-01-01
export PANDA_DATA_END_DATE=2026-03-31
```

### 四步运行

```bash
cd scripts/

# 1. 因子计算
python factor.py
# 输出：因子表（trade_date, symbol, factor_value, score, signal, confidence, ...）

# 2. 因子验证
python validate.py
# 输出：契约检查（11 条断言）+ IC 稳定性 + score 分布

# 3. 回测评估
python backtest.py
# 输出：IC, ICIR, Rank IC, Rank ICIR, 分层收益, Calmar, MDD, 换手率

# 4. HTML 报告生成
python report.py
# 输出：reports/report.html（self-contained，含 4 张图 base64 内嵌）
```

### 离线模式（CI 友好）

```bash
# 1. 一次性生成 fixture（需联网 + 凭证）
python save_fixture.py
# 生成 scripts/fixtures/sample_positions.parquet + sample_prices.parquet

# 2. 后续验证无需联网
export PANDA_DATA_OFFLINE=1
python validate.py

# 3. 离线生成 HTML 报告（无需凭证，自动用浏览器打开）
python report.py --offline --open
```

`check_factor_contract`（11 条契约断言）始终离线可跑，不依赖任何 fixture。

离线模式下若本地未装 `panda_data` SDK，`report.py` 会自动注入 stub 模块绕过 `factor.py` 顶层 import；pyarrow 19 与旧版 parquet 不兼容时自动 fallback 到 `fastparquet`。

## 输入配置

| 环境变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `PANDA_DATA_USERNAME` | ✓ | — | PandaAI 账号 |
| `PANDA_DATA_PASSWORD` | ✓ | — | PandaAI 密码 |
| `PANDA_DATA_START_DATE` | — | 当前日期往前 90 天 | 起始日期（YYYY-MM-DD） |
| `PANDA_DATA_END_DATE` | — | 当前日期 | 结束日期（YYYY-MM-DD） |
| `PANDA_DATA_OFFLINE` | — | `0` | `1` 时启用离线模式，从 fixture 加载 |
| `PANDA_DATA_DEBUG` | — | `0` | `1` 时首次 API 调用打印 schema 探针 |

## 信号生成规则

因子值公式：

```
factor_value = long_change_rate - short_change_rate
```

其中：

```
long_change_rate  = (今日多头总和 - 昨日多头总和) / |昨日多头总和|
short_change_rate = (今日空头总和 - 昨日空头总和) / |昨日空头总和|
```

信号阈值 `CHANGE_THRESHOLD = 0.02`（2%）：

| 信号 | 触发条件 |
|---|---|
| `buy` | 多头变化率 ≥ 2% 或 空头变化率 ≤ -2% |
| `sell` | 多头变化率 ≤ -2% 或 空头变化率 ≥ 2% |
| `hold` | 其它 |

评分公式（z-score + logistic squash）：

```
z = (factor_value - 横截面均值) / (横截面 σ)
score = 100 / (1 + exp(-z))      # 范围 (0, 100) 开区间
confidence = |z|                  # 偏离横截面均值的标准差倍数
```

当日品种数 N<5 时降级：`score = NaN`，`signal = hold`。

## 输出文件

`factor.py` 输出的因子表字段：

| 字段 | 说明 |
|---|---|
| `trade_date` | 交易日期（YYYY-MM-DD） |
| `asset_type` | 资产类型（固定为 `future`） |
| `symbol` | 品种代码 |
| `factor_id` | 因子编号（固定为 `F1`） |
| `factor_name` | 因子名称（"期货前20席位持仓突变"） |
| `factor_value` | 因子原始值（多头变化率 - 空头变化率） |
| `score` | (0, 100) 标准化评分（z-score 经 logistic 映射） |
| `rank` | 横截面排名 |
| `signal` | 交易信号：`buy` / `sell` / `hold` |
| `confidence` | `|z-score|`，偏离横截面均值的标准差倍数 |
| `long_total` / `short_total` | 当日前 20 多空持仓总和 |
| `prev_long_total` / `prev_short_total` | 前一日多空持仓总和 |
| `long_change_rate` / `short_change_rate` | 多空变化率 |
| `long_broker_count` / `short_broker_count` | 参与计算的期货公司数 |
| `data_version` | 数据版本（`real-v1`） |
| `update_time` | 数据最新日期 + A股收盘时间 15:30（ISO 8601） |

## HTML 回测报告

`scripts/report.py` 把回测结果渲染成 self-contained 单 HTML 文件（base64 内嵌图表，离线可看），默认输出到 `reports/report.html`，同目录还有中间产物 `reports/backtest_result.json`。

### 报告内容

| 区块 | 说明 |
|---|---|
| 摘要卡片 | 8 个核心指标：IC / ICIR / Rank IC / Rank ICIR / IR(SHR*) / CR / ARR / MDD |
| 样本统计 | 样本数、买入/卖出/持仓信号数、换手率 |
| 分层收益对比 | Low 组 vs High 组平均收益及价差 |
| 累计收益率与回撤 | 双子图：上为累计收益曲线，下为回撤填充 |
| 每日 IC 时序 | Pearson IC 与 Rank IC 双线对比 |
| 信号时间分布 | 按交易日堆叠的 buy/sell/hold 计数柱状图 |
| Top 20 品种信号分布 | 水平堆叠条形图，按信号总数排序 |
| Top 20 品种明细表 | 品种 / Buy / Sell / Hold / 总计 |
| 评估口径 | 严格口径 `forward_return = close_{t+1}/open_{t+1} - 1` 说明 |

### CLI 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--offline` | False | 强制离线模式（用 fixtures，无需凭证） |
| `--json-path` | `reports/backtest_result.json` | 中间 JSON 输出路径 |
| `--html-path` | `reports/report.html` | 最终 HTML 输出路径 |
| `--dpi` | 100 | 图表 DPI（控制 PNG 体积） |
| `--open` | False | 生成后自动用默认浏览器打开 |

### 示例

```bash
# 离线模式（最常用）
python scripts/report.py --offline --open

# 自定义输出路径
python scripts/report.py --offline --html-path reports/custom.html

# 减小 HTML 体积（适合邮件附件）
python scripts/report.py --offline --dpi 80
```

报告章节内的图表标签全英文（避免 matplotlib 中文字体跨平台问题），HTML 文字部分中文。单个 HTML 约 250KB（dpi=100）。

## 运行大样本时的建议

- **API 分批**：单次 API 调用 ≤ 8 个品种（`BATCH_SIZE = 8`），避免服务器超限
- **网络重试**：单批返回空时跳过，全部批空才报错
- **离线 fixture**：CI 中用 `PANDA_DATA_OFFLINE=1`，从 `fixtures/sample_*.parquet` 加载
- **DEBUG 探针**：`PANDA_DATA_DEBUG=1` 时首次 API 调用打印接口返回字段名与前 3 行示例

## 验证口径

### forward_return 严格口径

```
forward_return_t = close_{t+1} / open_{t+1} - 1
```

信号 t 日收盘后产生 → t+1 日开盘价成交 → t+1 日收盘价平仓。**避免未来函数和偷价**。

### IC 稳定性检验

样本前后半段 IC 同号且 `|IC| > 0.02`（行业经验下限）。

### 因子契约 11 条断言

`check_factor_contract` 覆盖：

1. 关键列存在（防御纯多头品种 KeyError）
2. `rank` 整数类型
3. `rank` 与 `factor_value` 单调对应（按日）
4. `factor_value == long_change_rate - short_change_rate` 数学等价
5. `long_total` / `short_total` 非负
6. `change_rate` 范围 `[-1, +∞)`
7. `factor_id` 全等于 `"F1"`
8. `data_version` 全等于 `"real-v1"`
9. `trade_date` 格式 YYYY-MM-DD
10. `update_time` 格式 ISO 8601
11. `signal` 子集检查

## 项目状态与风险边界

### 已完成（截至 2026-07）

14 轮修复记录：

| 轮次 | 主题 |
|---|---|
| 1 | IC 自相关 / 回测无价格 / alpha 0 证据 / 阈值不一致 |
| 2 | score/confidence 标准化偏置 |
| 3 | pandas FutureWarning |
| 4 | API 分批拉取（BATCH_SIZE=8） |
| 5 | symbols 全市场扩展（73 个） |
| 6-7 | 删除 11 个低流动性品种（剩 61 个） |
| 8 | underlying_symbol 输入契约 + 别名映射 + DEBUG 探针 |
| 9 | validate 离线模式 + 11 条契约检查 + fixture |
| 10 | 纯多头品种 KeyError 防御 |
| 11 | `_load_fixture_or_network` 联网 prices 加载 |
| 12 | `update_time` 动态推导（数据最新日期 + 15:30） |
| 13 | HTML 回测报告生成（`backtest_report_data.py` + `report.py` + matplotlib） |

### 已知未覆盖

- **CFFEX 国债因子语义**：金融期货持仓结构与商品不同，因子有效性待实际验证
- **GFEX 后缀运行时验证**：`SI/LC/PS_DOMINANT.GFE` 格式未经 API 实测，可能需改为 `GFEX`
- **PS 多晶硅历史数据短**：2024-12-13 上市，因子统计可能不稳定

### 边界

本 Skill 不做的事：

- 不调用 LLM
- 不读取非 PandaAI 的 API key
- 不提供交易建议
- 不进行样本外 walk-forward 优化（仅前后半段 IC 稳定性）

## License

[GPL-3.0](LICENSE) © 2026 PandaTest
