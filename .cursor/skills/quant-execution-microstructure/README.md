# Quant Execution Microstructure

本技能用于把已批准的组合交易转换为可执行、可观测、可评估成本的执行方案，覆盖订单设计、市场微观结构、成交模拟、交易成本分析、执行控制和交易后监控。

## 适用场景

适用于执行算法、VWAP/TWAP/POV 调度、订单类型、场所路由、限价逻辑、成交质量、滑点、市场冲击、队列位置、implementation shortfall 和执行监控。

目标权重构建与组合约束请使用 `quant-portfolio-risk`。信号发现、回测和统计验证请使用 `quant-research`。本技能默认把传入的目标和风险限制视为冻结输入。

## 文件结构

- `SKILL.md`：权威工作流、控制项、结果契约和参考资料路由。
- `README.en.md`：英文项目说明。
- `references/`：市场微观结构、执行模型和 TCA 指南。
- `scripts/`：执行订单验证工具。
- `agents/`：Codex、Cursor、Hermes 和 OpenClaw 适配入口。
- `CLAUDE.md`：Claude Code 适配入口。

## 默认边界

- 区分决策、到达、释放、确认、成交、撤单、拒单和对账事件，并使用可验证的时间戳。
- 分别报告价差、手续费、冲击、延迟、队列损失、不利选择、机会成本和残余风险。
- 未知队列位置或场所行为时，明确标记估计结果的置信边界，不伪造精确成交。
- 默认仅用于历史模拟、纸面交易和分析；未经明确授权不提交、撤销或修改实盘订单。
- 本项目不构成投资建议，不承诺收益，也不代表 QUANTSKILLS 官方认证或生产批准。

## 许可证与来源

本项目采用 GPL-3.0-only。上游组织为 QuantSkills，仓库为 `skill-quant-execution-microstructure`；最终收录、推荐和官方认可仍需维护者审核。
