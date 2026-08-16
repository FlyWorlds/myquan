---
name: global-macro-trend-strategy
description: "Turn an overseas commodity / macro / FX signal into a framework-neutral, backtestable research strategy - entry and exit rules, position sizing, risk limits, and a standalone backtest script. Use when a user wants to build and research-backtest an overseas trend or macro strategy from a signal, for research only, without live trading."
license: GPL-3.0-only
quantSkills:
  organization: https://github.com/quantskills
  organization_url: https://github.com/quantskills
  repository: quantskills/skill-global-macro-trend-strategy
  repository_url: https://github.com/quantskills/skill-global-macro-trend-strategy
  project_type: skill
  collection: global-macro-trend-strategy
  license: GPL-3.0
  category: trader-research            # trader-research / factor / data-api / replication / monitor / analyst / tooling
  tags: [strategy,backtest,overseas,trend,macro]                  # lowercase-hyphenated, 1-10 items
  platforms: [claude-code, codex, openclaw, cursor]        # claude-code / codex / openclaw / cursor / workbuddy
  language: zh-en
  status: draft                     # draft / active / stable / deprecated
  validation_level: listed          # listed / runnable / verified (community three-level scheme)
  maintainer_type: community        # official / community
  creator: abgyjaguo
  maintainer: abgyjaguo
  requires: []                      # dependent sibling skill-* / agent-* repository names
  summary_zh: "把海外商品/宏观/外汇信号做成框架无关、可回测的研究策略（规则+仓位+风控+回测脚本，仅研究）。"      # 8-120 chars
  summary_en: "Turn an overseas commodity/macro/FX signal into a framework-neutral, backtestable research strategy."      # 8-200 chars
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "请描述海外商品、宏观或外汇信号定义，并上传价格与 date,value 信号序列",
    "required": true
  },
  "fields": [
    {
      "key": "universe",
      "label": "标的池",
      "type": "text",
      "required": true,
      "placeholder": "如：CL=F, GC=F, ES=F, EURUSD=X"
    },
    {
      "key": "rebalance",
      "label": "再平衡频率",
      "type": "select",
      "default": "weekly",
      "options": [
        { "value": "daily", "label": "每日" },
        { "value": "weekly", "label": "每周" },
        { "value": "monthly", "label": "每月" }
      ]
    },
    {
      "key": "position_sizing",
      "label": "仓位方式",
      "type": "select",
      "default": "vol_target",
      "options": [
        { "value": "vol_target", "label": "波动率目标" },
        { "value": "fixed_fraction", "label": "固定比例" }
      ]
    },
    {
      "key": "focus",
      "label": "风险与假设",
      "type": "textarea",
      "placeholder": "补充手续费、滑点、最大权重、止损、回撤守门或样本外要求"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请将给定海外宏观、商品或外汇信号转化为标的池 {{universe}} 上框架无关、仅供研究的可回测策略，按 {{rebalance}} 频率再平衡并采用 {{position_sizing}} 仓位。{{#focus}}风险与假设要求：{{focus}}。{{/focus}}明确 t 时点信号到 t+1 成交、进出场、仓位、风险上限、成本与样本外约束，生成独立回测方案并解释 CAGR、Sharpe、回撤和换手，输出中文报告。"
}
```

# Global Macro Trend Strategy

把一个海外信号（商品期限结构、宏观利率/汇率、因子矿工产出，或用户自带的信号序列）落成一份
**框架无关、可回测、仅供研究**的策略：明确的进出场规则、仓位管理、风控上限，以及一段独立可跑的
回测脚本。本 skill **不下单、不接券商、不用实时行情**，只在公开历史日线上做研究回测。

数据只用**公开海外价格序列**（Yahoo Finance / stooq 的连续期货、外汇、指数），信号在 `t` 日生成、
`t+1` 开盘/收盘成交以规避前视。产出是"规则 + 仓位 + 风控 + 回测脚本 + 大白话结果说明"，不是交易指令。

## 与姊妹技能的区别（先读，避免选错）

| 技能 | 定位 | 差异 |
| --- | --- | --- |
| `ssquant-*` / `tbquant-strategy-builder` | 国内期货，绑定特定运行时（SSQuant/TBQuant） | 本 skill **框架无关、面向海外**，不生成运行时专用代码 |
| `signal-to-strategy` | 把 signal JSON 桥接进 ssquant 回测 | 本 skill 自带**独立 stdlib+pandas 回测**，不依赖 ssquant |
| `strategy-lab` | 通过 ssquant MCP 做策略闭环 | 本 skill 不连 MCP，产物是一段可离线跑的脚本 |
| 本 skill | **海外研究策略生成器** | 输入海外信号→输出规则化、可回测、仅研究的策略包 |

## 核心工作流（编号 6 步）

1. **界定信号与标的池（strategy contract）**——确认输入信号来源（`references/strategy-contract.md`）：
   是连续动量/期限结构/宏观打分，还是用户自带 `date,value` 序列；确认 universe（如 CL=F 原油、
   GC=F 黄金、ES=F 标普、EURUSD=X 欧元），采样频率（日线），以及 signal→position 的映射方向。
2. **定义进出场与再平衡**——把信号映射成目标仓位：趋势跟随可用 `sign(signal)` 或阈值带
   （进场 |z|>enter、出场 |z|<exit 的滞回，减少来回打脸）；声明再平衡频率（每日/每周）与
   `signal(t) → trade(t+1)` 的执行滞后，这是**规避前视**的硬约束。
3. **仓位管理（position sizing）**——二选一并写清参数：
   - 波动率目标（vol-target）：`weight = target_vol / realized_vol`，`realized_vol` 用过去 N 日
     收益年化，再乘以信号方向；
   - 固定比例（fixed-fraction）：每个方向暴露固定 `f`（如满仓 1.0 或半仓 0.5）。
4. **风控上限（risk limits）**——至少三道闸：单标的最大权重 `max_weight`、止损（价格较入场
   回撤 `stop_pct` 平仓）、回撤守门（组合 NAV 从峰值回撤超 `dd_guard` 时降杠杆或空仓）。
5. **写独立回测脚本并跑通**——调用 `scripts/backtest.py`：读入一个价格 CSV + 一列信号，按 `t+1`
   成交、计入手续费与滑点，输出 CAGR / Sharpe / 最大回撤 / 换手，以及权益曲线 CSV。脚本仅依赖
   标准库 + pandas，`pandas` 缺失时给出清晰报错（graceful degradation）。
6. **大白话结果解释 + 边界声明**——用非专业语言解释 CAGR/Sharpe/回撤/换手各代表什么、哪些是
   假设（成本、滑点、样本窗口）、为什么"历史好看≠未来能赚"，并给出 hold-out / 样本外的提醒。

## 输出契约（Output Contract）

产出以下四件，缺一不可：

- **`strategy_spec.md`**——策略契约：universe、信号定义、进出场规则、仓位公式、风控参数、
  再平衡与执行滞后，逐条可核对（模板见 `references/strategy-contract.md`）。
- **`scripts/backtest.py` 的一次运行结果**——`metrics.json`（CAGR/Sharpe/maxDD/turnover）+
  `equity_curve.csv`（date, nav, drawdown, position, ret_net）。
- **`results_explainer.md`**——大白话结果说明：指标含义、成本/滑点/窗口假设、过拟合与样本外提醒。
- **一段可人读的事实性小结**——不含任何"买/卖/加仓"指令，只描述规则在历史上的统计表现。

回测报告须能通过 `python scripts/validate_report.py results_explainer.md` 的结构与标签自检。

## 数据来源（Data Sources）

- **公开海外日线价格**：Yahoo Finance / stooq 的连续期货（如 `CL=F`、`GC=F`、`ES=F`）、
  外汇（`EURUSD=X`）、指数。使用者自行下载为 CSV（列含 `date, close`，可选 `open`）后喂给脚本。
- **信号来源（三选一）**：① 姊妹海外技能（商品期限结构、宏观利率汇率、因子矿工）产出的信号序列；
  ② 用户自带 `date,value` 信号 CSV；③ 脚本内置的示例趋势信号（收盘价均线交叉，仅用于跑通 demo）。
- **Pandadata（可选）**：若信号取自 Pandadata 海外接口，**不要臆造方法名**——把真实取数委托给
  `pandadata-api` skill，本 skill 只消费其返回的 `date,value` 序列。
- 本 skill **不附带任何行情数据**，也**不联网、不下单**；数据合法性与许可由使用者负责。

## References

- `references/strategy-contract.md` —— 策略契约模板：universe / 信号 / 进出场 / 仓位 / 风控字段逐项说明。
- `references/backtest-notes.md` —— 回测方法与坑：前视规避、成本/滑点、连续合约换月、样本外与过拟合。
- `references/source_boundary.md` —— 允许 / 不允许读取的数据边界。

## 跨工具适配

- OpenAI Codex / Assistants → `agents/openai.yaml`
- Cursor → `cursor-rule.mdc`（位于 agents/，由工作区 sync 生成）
- 无原生 skill 机制（Hermes / OpenClaw）→ `portable-loader.md`（位于 agents/，由 sync 生成）

## Boundaries（量化研究合规声明）

- **仅研究回测**：不产生实盘订单、不连接任何券商、不使用实时行情；产物是研究脚本与说明，不是交易系统。
- **数据来源**：公开海外日线（Yahoo/stooq）或用户自备信号；本 skill 不附带数据、不联网取数。
- **假设与参数**：`t+1` 成交、双边手续费 + 滑点（bps）、波动率目标 / 固定比例仓位、样本窗口等均为
  研究阶段的显式假设，须在产物中如实写明，不得隐藏。
- **已知限制**：连续合约换月与幸存者偏差可能高估收益；样本内过拟合风险；高换手时成本主导；
  单标的/少数标的的结果统计意义有限。**结果是示意性的，不是预测。**
- **风险边界**：输出的 CAGR/Sharpe/回撤等仅反映历史数据 + 假设条件下的统计表现，不代表未来。
- 研究与工作流工具，社区项目，非官方、未认证、未验证。
- **不构成任何投资建议 / does not constitute investment advice**。
