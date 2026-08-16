# 🧩 Global Macro Trend Strategy

**简体中文** | [English](README.en.md)

> 把一个海外信号（商品期限结构 / 宏观利率汇率 / 因子矿工产出 / 用户自带序列）落成一份**框架无关、
> 可回测、仅供研究**的策略：规则 + 仓位 + 风控 + 一段独立可跑的回测脚本。**不下单、不接券商、不用实时行情。**

![type](https://img.shields.io/badge/type-skill-blue)
![category](https://img.shields.io/badge/category-trader--research-green)
![license](https://img.shields.io/badge/license-GPLv3-blue)

## 📖 这是什么

一个**海外研究策略生成器**。你给它一个信号和一段公开海外日线价格，它帮你把想法落成可复核的东西：

- **输入**：公开海外价格 CSV（Yahoo Finance / stooq 的连续期货、外汇、指数，列含 `date, close`），
  加一个信号——姊妹海外技能的产出、用户自带的 `date,value` 序列，或脚本内置的均线交叉示例。
- **处理**：界定策略契约（标的池 / 信号→仓位映射 / 进出场 / 再平衡）→ 仓位管理（波动率目标或固定比例）
  → 风控上限（单标的权重 / 止损 / 回撤守门）→ 用 `scripts/backtest.py` 按 `t+1` 成交、计入成本滑点跑回测。
- **产出**：策略契约 `strategy_spec.md`、回测指标 `metrics.json` + 权益曲线 `equity_curve.csv`、
  大白话结果说明 `results_explainer.md`（可被 `scripts/validate_report.py` 结构自检）。

**与姊妹技能的区别**：`ssquant-*` / `tbquant-strategy-builder` 面向国内期货、绑定特定运行时；
`signal-to-strategy` 把 signal JSON 桥接进 ssquant 回测；`strategy-lab` 走 ssquant MCP。
本 skill **框架无关、面向海外、自带离线 stdlib+pandas 回测**，产物是一段能独立跑的研究脚本，不是实盘系统。

## 🚀 快速开始

```bash
cp -r skill-global-macro-trend-strategy ~/.claude/skills/global-macro-trend-strategy
```

自带一个不依赖任何数据文件的 demo（合成随机游走价格 + 内置均线信号），装完即可跑通：

```bash
python skill-global-macro-trend-strategy/scripts/backtest.py --demo --zscore --enter 0.5 --exit 0.2
```

真实用法（自备价格 CSV + 信号 CSV）：

```bash
python scripts/backtest.py --prices CL=F.csv --signal my_signal.csv --sizing vol_target --fee-bps 2 --slip-bps 1
```

触发示例 prompt：

```text
用商品期限结构信号在原油(CL=F)上做一个趋势跟随的研究回测，波动率目标仓位，报告 CAGR/Sharpe/回撤
把我这列宏观打分信号落成框架无关的可回测策略，加止损和回撤守门，仅研究不要下单
```

## 📦 目录结构

```text
skill-global-macro-trend-strategy/
├── SKILL.md                        # 运行时入口：6 步工作流 + 输出契约 + 边界
├── README.md / README.en.md        # 中文优先 / English
├── LICENSE                         # GPLv3
├── agents/
│   └── openai.yaml                 # OpenAI/Codex 适配（cursor-rule.mdc、portable-loader.md 由工作区 sync 生成）
├── references/
│   ├── strategy-contract.md        # 策略契约模板（标的/信号/进出场/仓位/风控字段）
│   ├── backtest-notes.md           # 回测方法与坑：前视/成本/换月/过拟合/优雅降级
│   └── source_boundary.md          # 数据读取边界
└── scripts/
    ├── backtest.py                 # 独立回测（stdlib+pandas，含 --demo，可跑通）
    └── validate_report.py          # 结果说明结构自检（stdlib，坏报告非零退出）
```

## 🖼 产物说明

本仓库**不提交任何回测产物或行情数据**，运行结果默认保存在使用者本地（`backtest_out/` 下的
`metrics.json`、`equity_curve.csv`）。输入 / 输出关系如下：

| 产物 | 谁用 | 如何生成 | 数据基础 | 风险提示 |
| --- | --- | --- | --- | --- |
| `strategy_spec.md` | 人读 / 复核 | 按 `references/strategy-contract.md` 填 | 用户信号 + 公开价格 | 参数为研究假设 |
| `metrics.json` / `equity_curve.csv` | 人读 / 脚本 | `scripts/backtest.py` | 公开日线 + 信号 | 示意性历史统计，非预测 |
| `results_explainer.md` | 人读 | 大白话解释 + `validate_report.py` 自检 | 上述回测 | 不构成投资建议 |

## 🔌 运行时兼容

以 `SKILL.md` 为统一入口，可在 **Claude Code、Codex、Cursor、Hermes、OpenClaw** 等运行时加载；
`agents/openai.yaml` 提供 OpenAI/Codex 适配，`cursor-rule.mdc` 与 `portable-loader.md` 由工作区 sync 生成。

## 🗃 数据来源与依赖

- **公开海外日线价格**：Yahoo Finance / stooq 的连续期货（`CL=F`、`GC=F`、`ES=F` 等）、外汇（`EURUSD=X`）、
  指数；使用者自行下载为 CSV，数据合法性与许可由使用者负责。
- **信号**：姊妹海外技能产出 / 用户自带 `date,value` / 内置均线示例。
- **Pandadata（可选）**：若信号取自 Pandadata 海外接口，**不臆造方法名**，把取数委托给 `pandadata-api` skill。
- **依赖**：Python 3 + pandas（缺失时脚本给出安装提示并非零退出）。

## ⚠️ 限制与风险边界

- **仅研究回测**：不产生实盘订单、不连接券商、不使用实时行情。
- **前视规避**：信号 `t` 日生成、`t+1` 成交，脚本以 `shift(1)` 强制滞后。
- **已知限制**：连续合约换月与幸存者偏差可能高估收益；样本内过拟合风险；高换手时成本主导；
  单标的/少数标的统计意义有限。**结果是示意性的，不是预测。**
- **需人工确认**：任何据此的交易决策由使用者自行判断与承担；外部写入/下单不在本 skill 范围内。

## 📜 免责声明

本仓库仅作量化研究与方法论层面的整理，为社区项目，非官方、未认证、未验证、未经维护者审阅；
不隶属任何被研究对象，不承诺任何收益，输出的 CAGR/Sharpe/回撤等仅反映历史数据 + 假设条件下的统计表现，**不构成任何投资建议**。

## 🧑‍🔧 维护者

Created or maintained by `abgyjaguo`.

## 📜 License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## 🐼 PandaAI / QUANTSKILLS 社群

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI 社群二维码" width="220">
  <br>
  <sub>扫码加入 PandaAI 社群，交流 QUANTSKILLS 技能、Agent 工作流与量化研究实践。</sub>
</div>
