---
name: futures-roll-auditor
description: Use when a futures continuous series or backtest needs structural checks on selected contracts, roll dates, same-day contract price gaps, difference or ratio adjustment factors, and a reproducible roll ledger.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-futures-roll-auditor
  repository_url: https://github.com/quantskills/skill-futures-roll-auditor
  project_type: skill
  collection: futures-roll
  creator: adennng
  creator_url: https://github.com/adennng
  maintainer: adennng
  maintainer_url: https://github.com/adennng
quantSkills:
  project_type: skill
  category: tooling
  tags: [futures, continuous-contract, roll, back-adjustment, pandadata]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: [skill-pandadata-api]
  summary_zh: 审计期货连续合约的选择序列、换月事件、价差及差值/比例调整台账。
  summary_en: Audit futures contract selection, roll events, price gaps, and difference or ratio adjustment ledgers.
  license: GPL-3.0-only
---

# 期货连续合约换月审计

把输入研究制品当作需要验证的证据，而不是默认可信的结果。先冻结口径，再运行确定性检查，最后把“已证实的问题”和“缺失证据”分开报告。

## 核心工作流

1. 冻结主力/近月选择规则
2. 识别每次合约切换
3. 计算同日 roll gap 与差值/比例调整因子；不把价差自动等同于已实现展期成本
4. 区分研究连续价格与真实合约 PnL
5. 运行 `python scripts/audit_rolls.py --demo` 做离线烟雾测试；处理真实数据时用 `--input <csv> --out <report.json>`。
6. 按 `references/output-contract.md` 输出机器可读 JSON 和简洁中文结论。

## 输入契约

包含 date、front、back、selected、front_price、back_price 的逐日合约选择 CSV。
`date` 必须是 `YYYY-MM-DD` 格式的 ISO-8601 日历日期；脚本要求 `--demo` 与 `--input` 二选一。

字段名不一致时先显式建立映射，不要猜测。缺少关键字段时停止定量结论，并列出补数清单。

## 运行参数

- `--demo`：使用内置样例；与 `--input` 互斥且二者必须提供一个。
- `--input <csv>`：读取本地 CSV；与 `--demo` 互斥且二者必须提供一个。
- `--adjustment-method {none,difference,ratio}`：记录采用的调整方法，默认 `none`。
- `--out <json>`：可选输出路径；省略时把 JSON 写到标准输出。
- 同时提供 `--demo`、`--input`，或两者均未提供时，命令以参数错误码 2 退出。

## 输出契约

JSON 换月事件表、roll gap 和使用警告。

读取 `references/output-contract.md` 获取统一的证据等级、结论状态和报告字段。输出至少包含：输入规模、参数/假设、逐项发现、限制和下一步修复。

## 方法与证据

在修改阈值、公式或解释前读取 `references/methodology.md`。保留数据版本、时区、样本窗、随机种子和所有降级项，使另一位研究员可以复现结果。

## 数据源策略

- 用户已提供规范 CSV 时直接使用，不重复调用外部数据源。
- 缺少市场数据且任务落在 PandaData 覆盖范围时，先读取 `references/pandadata-integration.md`，再使用兄弟 Skill `pandadata-api` 查询：`get_future_detail`、`get_future_dominant`、`get_future_daily`、`get_future_daily_post`。
- 本 Skill 的分析脚本保持离线、确定性；PandaData 负责取数，字段标准化后再交给脚本，避免把认证、供应商响应和分析逻辑耦合。
- 主力映射只是供应商口径；若用户策略按成交量、持仓量或固定日换月，仍需提供自身 roll rule 并与主力映射分开报告。

## 与 QuantSkills 现有能力的边界

它审计连续序列构造；不重复商品期限结构观点研究，也不替代期货回测。

## 使用边界

- 只用于量化研究、数据质量和风险分析，不构成投资建议。
- 不把缺失证据写成“通过”，不把启发式异常写成已证实违规。
- 不自动下单，不修改原始数据；把修复结果写到新文件。
