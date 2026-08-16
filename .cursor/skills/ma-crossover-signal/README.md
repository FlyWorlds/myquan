# skill-ma-crossover-signal

**简体中文** | [English](README.en.md)

单标的均线交叉信号分析。给一个股票代码和快/慢均线周期，在**同一条清洗后的收盘序列**上计算快慢均线（SMA/EMA），并以 `(快线 − 慢线)` 的**变号**判定金叉/死叉，返回当前趋势状态、最近一次交叉（日期 + 距今 bar 数）、均线乖离与价格乖离率，自动按代码后缀路由 A股 / 港股 / 美股。仅输出信号事实与描述，不提供买卖指令。

<p align="center">
  <img alt="role" src="https://img.shields.io/badge/role-均线交叉信号-brightgreen">
  <img alt="output" src="https://img.shields.io/badge/output-金叉死叉·趋势·乖离率-blue">
  <img alt="market" src="https://img.shields.io/badge/market-A股·港股·美股-9cf">
  <img alt="data" src="https://img.shields.io/badge/data-panda__data·tqx__data-yellow">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-ma-crossover-signal` 是 QuantSkills 社区的单标的趋势信号 Skill。它只回答“这只票金叉了吗 / 还在上升趋势吗”这一类**单标的择时**问题，与做两标的关系的 `skill-pair-correlation`、做风险收益画像的 `skill-risk-return-metrics` 互补不重叠。

## 这个 Skill 解决什么问题

“茅台金叉了吗？”“现在还在上升趋势吗？”——这是最高频的单标的问题，但最朴素的答案（“快线在慢线上方”）会**掩盖交叉是新鲜的还是 40 根 bar 之前的陈旧信号**。

本 skill 把它变成可核对的结构化结果：

- 在同一条清洗收盘序列上算 MA5 / MA20（或自定义、可选 EMA），**用 `(快线 − 慢线)` 变号**检测交叉，因此返回的是**真实的最近一次交叉及其日期 + 距今 bar 数**，而不是“当前谁在上面”；
- 一并给出**趋势状态、均线乖离 `ma_gap`、价格乖离率 `price_bias`（乖离率）**，以及最近若干次交叉列表；
- 历史不足 `slow_period` 时 `state` / `last_cross` 优雅返回 `null`，不崩溃、不臆造。

## 计算口径

| 字段 | 含义 / 公式 |
|---|---|
| `state` | 最后一根 bar 上 `fast_ma ≥ slow_ma` 为 `bullish`，否则 `bearish` |
| `ma_gap_pct` | `(fast_ma − slow_ma) / slow_ma` |
| `price_bias_pct` | 乖离率 `(last_close − slow_ma) / slow_ma` |
| `last_cross.type` | `golden`（快线上穿慢线）/ `death`（快线下穿慢线） |
| `bars_ago` | 距该次交叉的交易 bar 数（0 = 最后一根 bar 才交叉） |
| `recent_signals` | 最多 `max_signals` 条最近交叉，按旧→新 |

`last_cross` 在窗口内无交叉（或历史 < `slow_period`）时为 `null`。这是**信号描述而非回测**：不含交易成本、滑点、仓位。

## 快速开始

```bash
# 依赖：pandas / numpy + panda_data(A股) / tqx_data(港美股)
python scripts/ma_crossover_signal.py 600519.SH --fast-period 5 --slow-period 20
python scripts/ma_crossover_signal.py AAPL.NB --ma-type ema --fast-period 10 --slow-period 50
```

作为平台 Skill 使用时，入口为 `scripts/ma_crossover_signal.py` 中的 `async def run(...) -> str`（Panda QuantFlow skill 契约）。缺少取数库时返回结构化 `Error: …` 字符串，而非抛异常。

## 示例输出

`600519.SH` MA5/MA20 示例（完整文件见 [`examples/output/`](./examples/output/)）：

```
最新收盘：1685.0    MA5 = 1690.2    MA20 = 1662.4
趋势状态：bullish    ma_gap = +1.67%    乖离率 = +1.36%
最近一次交叉：金叉 golden  20260512  距今 9 根 bar  收盘 1650.0
```

> 当前处于金叉后第 9 根 bar 的多头排列，乖离幅度不大，属“金叉初期、尚未过热”。
> 结构化 JSON 见 [`examples/output/ma_crossover_signal.json`](./examples/output/ma_crossover_signal.json)。
> 示例数值取自 SKILL.md 输出 schema，非实时行情。

## 数据从哪来

代码后缀决定市场路由（`market=auto` 时）：

- **A股** `.SH` / `.SZ` / `.BJ` 或裸 6 位数字 → `panda_data` 日线收盘；
- **港股** `.HK` → `tqx_data`；
- **美股** `.NB` / `.US` / `.NY` → `tqx_data`。

也可显式传 `--market cn|hk|us` 强制。取数由平台运行时注入，输出质量取决于上游数据可得性与正确性。

## 目录结构

```
skill-ma-crossover-signal/
├── SKILL.md                       # Agent 使用说明（核心）：用途、参数、输出 schema、定义、when-NOT-to-use
├── README.md                      # 本文件（简体中文，首段=平台简介）
├── README.en.md                   # 英文说明
├── LICENSE                        # GPLv3 许可证全文
├── quantskills.yaml               # QuantSkills 上游清单：provenance / 依赖 / license: GPL-3.0-only
├── agents/                        # 各 Agent 平台运行时入口（都回到同一份 SKILL.md）
│   ├── cursor-rule.mdc            #   Cursor 规则入口
│   ├── openai.yaml                #   OpenAI-style / OpenClaw 运行时清单（display_name / default_prompt）
│   └── portable-loader.md         #   Hermes / OpenClaw 便携加载器
├── scripts/
│   └── ma_crossover_signal.py     # 可执行：async def run(...) -> str + 独立 CLI；均线计算 + 交叉检测
└── references/
    └── example_output.md          # 输出字段逐项说明
└── examples/
    └── output/                    # 示例输出（数值取自 SKILL.md schema）
        ├── ma_crossover_signal.json   #   结构化 JSON 示例
        └── ma_crossover_signal.txt    #   人类可读摘要 + 解读 + 免责
```

## 运行时入口

本 Skill 支持 Claude Code、Codex、Cursor、Hermes 和 OpenClaw。Claude Code、Codex 与原生 Skill 运行时直接加载 `SKILL.md`；Cursor 使用 `agents/cursor-rule.mdc`；Hermes / OpenClaw 在无法原生发现 Skill 时使用 `agents/portable-loader.md`（`agents/openai.yaml` 提供 OpenClaw 展示信息）。所有入口最终都回到同一份 `SKILL.md` 与同一个脚本，不维护平行业务逻辑。

## 与社区其他 skill 的分工

- **本 skill**：单标的趋势 / 金叉死叉 —— **看一只票的择时信号**；
- `skill-pair-correlation`：两标的相关性 / 对冲 beta / 价差 —— **看两只票的关系**；
- `skill-risk-return-metrics`：单标的夏普 / 回撤 / 卡玛 —— **看一只票的风险收益**；
- RSI / MACD / KDJ 指标序列或完整策略 P&L 回测 → 交给对应的指标 / 回测 skill。

## 免责声明

- **仅供研究与教育用途。** 输出为信息性研究，**不构成投资建议，不承诺任何收益**。
- **数据来源：** A股经 `panda_data`、港美股经 `tqx_data`（平台提供），输出质量取决于上游数据可得性与正确性。
- **假设与局限：** 均线基于日线收盘，交叉为 `(快线 − 慢线)` 变号；这是**信号描述而非回测**，未计交易成本 / 滑点 / 仓位，金叉死叉不等于买卖建议；历史不足 `slow_period` 时 `last_cross` 为 `null`。
- **风险边界：** 请勿作为实盘进出场唯一依据，独立验证并注意市场风险。

## License

GPL-3.0-only。本 skill 为 QuantSkills 社区原创，均线与交叉检测为量化通用做法。许可证全文见 [`LICENSE`](./LICENSE)。
