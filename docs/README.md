# 文档索引

| 文档 | 说明 |
|------|------|
| [`READ.md`](../READ.md) | 项目总览、安装、运行命令、**策略/因子摘要表** |
| [`GLOBAL_STRATEGY_OVERVIEW.md`](GLOBAL_STRATEGY_OVERVIEW.md) | **全局量化交易策略说明手册**（多策略、时序管线、买卖规则、出场风控） |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **架构与技术栈报告**（分层、盯盘拓扑、栈清单） |
| [`TODO.MD`](../TODO.MD) | 任务优先级、锁定项 |
| [`STRATEGY.md`](STRATEGY.md) | 策略一及已实现策略说明 |
| [`STRATEGY35.md`](STRATEGY35.md) | **策略三十五 多维空仓避险策略**（大盘择时、广度水位监控、为什么需要空仓诊断） |
| [`STRATEGY36.md`](STRATEGY36.md) | **策略三十六 科技成长空仓避险策略**（创业板/科创板/深成指生命线、科技池专属广度、高Beta资产熔断避险） |
| [`FACTOR13.md`](FACTOR13.md) | 因子13 质量带 + 熊市盾牌（锁定） |
| [`FACTOR14.md`](FACTOR14.md) | 因子14 题材共振（策略八） |
| [`FACTOR16.md`](FACTOR16.md) | 因子16 概念龙头评分 |
| [`FACTOR17.md`](FACTOR17.md) | 因子17 缠论笔盈亏比（原策略七） |
| [`FACTOR18.md`](FACTOR18.md) | 因子18 低开跌停情绪（策略十二择时） |
| [`FACTOR19.md`](FACTOR19.md) | 因子19 低开反包（旧假设，未过关） |
| [`FACTOR20.md`](FACTOR20.md) | 因子20 跌停次日开板（已否决） |
| [`FACTOR21.md`](FACTOR21.md) | 因子21 涨停次日低开（策略十二，OOS 未过关） |
| [`FACTOR35.md`](FACTOR35.md) | **因子35 多维复合空仓避险因子**（指数MA60破位+全市场广度溃败，样本外回撤降至-18.5%） |
| [`strategy/README.md`](../strategy/README.md) | 因子/策略注册表、CLI |
| [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) | **2026-09-13 策略十六/因子26 项目审查**（现行默认；含工作止损/费用/信号） |
| [`EXIT_RULE_ORDER.md`](EXIT_RULE_ORDER.md) | Paper 卖出规则顺序（ExitDecisionEngine 真源） |
| [`EXIT_COVERAGE_MATRIX.md`](EXIT_COVERAGE_MATRIX.md) | Phase 3C+ 退出路径覆盖矩阵 |
| [`EXIT_COVERAGE_QUALIFICATION.md`](EXIT_COVERAGE_QUALIFICATION.md) | Phase 3C+ 覆盖资格（historical；当时未切 Unified） |
| [`SHADOW_SIDE_EFFECT_AUDIT.md`](SHADOW_SIDE_EFFECT_AUDIT.md) | Phase 3D Unified-as-Shadow 只读副作用审计（historical） |
| [`SHADOW_VALIDATION_REPORT.md`](SHADOW_VALIDATION_REPORT.md) | Phase 3D 就绪快照（historical 全 0）；当前已 Primary Reversal |
| [`DECISION_PARITY_PHASE3_REPLAY.md`](DECISION_PARITY_PHASE3_REPLAY.md) | Phase 3A～3C 真实 1m parity 基线 |
| [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md) | 2026-08 凯盛 OpenBreak（因子1）底稿 |

改代码时同步更新：`.cursor/rules/docs-sync.mdc`
