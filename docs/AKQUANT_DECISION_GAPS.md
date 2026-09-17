# AKQUANT Decision Gaps（Phase 2 记录 · 不统一）

> 日期：2026-09-17  
> Phase 2 **不强行**把日线 AKQUANT 接入 ExitDecisionEngine。

---

## 路径对照

| 环境 | 卖出规则入口 | Context | Path 语义 | Price 语义 |
|------|--------------|---------|-----------|------------|
| Paper Watch | `paper_exit_decision` →（可选）`ExitDecisionEngine` | 持仓+行情标量 | 1m `path_dependent_pullback_hit` → path_* | open / path_fill / working_stop |
| ExitDecisionEngine | 同 paper 顺序 | `DecisionContext` | 消费 path_*，不重跑 1m | 同上 |
| Factor26Decision | `decide(MarketContext)` | 日线/快照 + meta.path_hit_stop | 无 path 则不卖 | levels.stop |
| 1m backtest | `eval_multi_tp_bar` / `replay_factor26_1m` | bar 序列 | 完整 path | bar 触达 fill |
| **AKQUANT daily** | `OpenBreak3Strategy` + `half_gain_stop_price` | 日线 OHLC | **无 1m path** | 日线 peak 半仓公式 / 开盘锚定 |

---

## 已知差距

1. 日线 AKQUANT **不跑** `eval_multi_tp_bar` 全优先级（阶梯半仓、T1 峰值回落、硬缺口模式等）。  
2. 无开盘保护编排（`overnight_open_protect` peak 兜底）。  
3. 无 `working_stop` last 分支。  
4. 与 Paper / ExitDecisionEngine **预期可不一致** —— 属简化回测，非 bug。

---

## Phase 3 再议

- 日线路径标注「简化」或改为 1m/`ExitDecisionEngine` 驱动  
- 在统一前保持本文件为差距真源  

---

*仅文档；未改 AKQUANT 行为。*
