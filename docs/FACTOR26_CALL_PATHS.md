# 因子26 调用路径图（Phase 1C · 只分析不删改）

> 日期：2026-09-17  
> 范围：`pullback_wave_stop` / DecisionEngine / 盯盘纸面 / akquant 日线 / 1m 回测  
> 原则：**不删除旧实现**；标明规则真源 vs wrapper vs 重复编排

---

## 1. 结论摘要

| 角色 | 函数 / 模块 | 判定 |
|------|-------------|------|
| **规则真源（单 bar 卖出优先级）** | `strategy/pullback_wave_stop.py` → `eval_multi_tp_bar` | ✅ One Source of Truth（1m 触达内核） |
| **薄封装（Contract）** | `evaluate_pullback_wave_stop` → `FactorResult` | ✅ wrapper，算法未改 |
| **1m 序列编排** | `path_dependent_pullback_hit` → 循环调用 `eval_multi_tp_bar` | ✅ wrapper |
| **全日 1m 模拟** | `simulate_factor26_day_1m` / `replay_factor26_1m` | ✅ wrapper |
| **价位展示** | `working_stop_price` / `strategy_levels` / `strategy_signal` | ⚠️ 展示/信号；部分公式与卖出优先级共享子函数 |
| **盯盘纸面编排** | `holdingStocks/index.py` → `paper_exit_decision` + `_resolve_hit_stop_path_dependent` | ⚠️ **编排层**：开盘保护 + path + 现价；**不**直接调 DecisionEngine |
| **DecisionEngine** | `strategies/_factor26_decision.py` → `Factor26Decision.decide` | ⚠️ **另一编排**：默认靠 `meta.path_hit_stop`；无 1m 时**不**用全日 low 卖出 |
| **akquant 日线 Strategy** | `strategy/backtest.py` → `OpenBreak3Strategy` + `half_gain_stop_price` | ⚠️ **简化路径**：日线 OHLC + 半仓公式，**未**跑完整 `eval_multi_tp_bar` 优先级 |
| **1m 池回测** | `backtest/strategy1_pool_1m/run.py` | ✅ 直接 `eval_multi_tp_bar` / `replay_factor26_1m`（与真源对齐） |

**最高风险分叉**：同一套「因子26 卖出」，盯盘走 `paper_exit_decision`，回测 Decision 走 `Factor26Decision`，日线 akquant 再走 `half_gain_stop_price` —— 三套编排，内核仅部分共用。

---

## 2. 调用关系总图

```text
                    ┌─────────────────────────────────────┐
                    │  pullback_wave_stop.py              │
                    │  ★ eval_multi_tp_bar  (规则真源)     │
                    │  · half_gain_stop_price             │
                    │  · cost_hard_stop_px                │
                    │  · working_stop_price               │
                    │  · overnight_open_protect_px        │
                    └──────────────┬──────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
 path_dependent_pullback_hit   evaluate_pullback_wave_stop   strategy_levels /
 simulate_factor26_day_1m       → FactorResult                strategy_signal
 replay_factor26_1m
 first_session_exit_fill
         │                         │                         │
         └────────────┬────────────┘                         │
                      │                                      │
     ┌────────────────┼────────────────┐                     │
     ▼                ▼                ▼                     ▼
holdingStocks     1m backtest     Unit tests          Factor26Decision
index.py          strategy1_      test_pullback_*     levels_for()
                  pool_1m/run.py  test_factor26_*      decide()
     │
     ├─ _resolve_hit_stop_path_dependent  → path_dependent_pullback_hit
     ├─ paper_exit_decision               → overnight_open_protect_px
     │                                      + path_hit 入参
     │                                      + last vs working_stop
     └─ collect_rows / apply_exit_fill    → 纸面成交（不调 get_decision_engine）

另线：
  OpenBreak3Strategy.on_bar (akquant)
       → half_gain_stop_price / stop_trigger_price
       → order_target_percent / sell
       （不经过 eval_multi_tp_bar / paper_exit_decision / Factor26Decision）
```

---

## 3. 路径分册

### 3.1 规则真源：`eval_multi_tp_bar`

- **文件**：`strategy/pullback_wave_stop.py` ~L720
- **输入**：单根 1m OHLC、成本、peak、shares、tp_stage、can_sell、overnight_armed、vol20…
- **输出**：`{action: {kind, reason, fill_px, shares}|None, tp_marked, noted_px, peak_after, …}`
- **优先级**（文档与代码一致）：硬缺口 → T1 峰值回落 → 阶梯 15% → 中赚 → 硬保护 → 大赚半仓/回落
- **性质**：真正规则实现；其它路径应调用它，而非复制条件

### 3.2 Wrapper：`evaluate_pullback_wave_stop`

- **文件**：同模块 ~L2456（Phase 1B 新增）
- **行为**：映射 `DecisionContext` → `eval_multi_tp_bar` → `FactorResult`
- **性质**：Contract 入口；**零算法变更**

### 3.3 Wrapper：`path_dependent_pullback_hit`

- **文件**：同模块 ~L937
- **行为**：按 1m 时间顺序抬 peak，每根调用 `eval_multi_tp_bar`
- **性质**：序列编排；禁止「全日 low vs 抬高后卖价」捷径（文档已强调）

### 3.4 Wrapper：`simulate_factor26_day_1m` / `replay_factor26_1m` / `first_session_exit_fill`

- **行为**：日级买卖模拟 / 回放 / 第一次触达价
- **调用方**：`holdingStocks/index.py`（已平仓价）、`backtest/strategy1_pool_1m/run.py`、测试

### 3.5 盯盘：`paper_exit_decision`（编排，非第二套内核）

- **文件**：`holdingStocks/index.py` ~L4750
- **职责**：
  1. `overnight_open_protect_px` → 开盘保护（竞价核）
  2. 入参 `path_hit` / `path_fill_px`（由 `_resolve_hit_stop_path_dependent` → `path_dependent_pullback_hit` 预先算好）
  3. 5s 现价 vs `working_stop`
  4. T+1 / 锁仓 / 跌停 → 只展示不平仓
- **重复判断？**：
  - **不**重写 `eval_multi_tp_bar` 优先级
  - **有**额外业务：开盘保护峰值是否含今日、买入日只记硬保护、半仓价与开盘保护混用禁令
- **参数转换**：行情/持仓 dict → 上述标量；与 `MarketContext` **字段不对齐**

### 3.6 DecisionEngine：`Factor26Decision.decide`

- **文件**：`strategy/strategies/_factor26_decision.py`
- **卖出**：仅当 `ctx.meta.path_hit_stop` 为真才 `Decision.sell`；否则有仓 HOLD  
  （注释明确：无 1m 时不用全日 low，避免同 bar 次序误判；**盯盘不走本引擎**）
- **买入**：levels + path_hit_buy / 日线 high≥买点
- **与 paper 差异**：
  - 无开盘保护独立分支（依赖 path / levels）
  - 卖出价用 levels 的 `stop_px`，未必等于 path `fill_px`
  - 可叠因子22 再买

### 3.7 AKQUANT 日线：`OpenBreak3Strategy`

- **文件**：`strategy/backtest.py`
- **卖出**：`stop_anchor=="day_high"` 时用 `half_gain_stop_price(peak, cost)`；否则开盘锚定止损
- **重复？**：**是简化子集** — 使用真源的**子公式**，但缺少完整多层优先级（阶梯半仓、T1 峰值回落 2.5%、硬缺口模式等）
- **性质**：历史日线回测路径；与 1m 生产路径**预期可不一致**

### 3.8 1m 池回测：`backtest/strategy1_pool_1m/run.py`

- **直接** `eval_multi_tp_bar` / `replay_factor26_1m`
- **与真源对齐度最高**（相对日线 akquant）

---

## 4. 行为差异矩阵（分析结论，未改规则）

| 场景 | eval_multi_tp_bar | paper_exit_decision | Factor26Decision | OpenBreak3 日线 |
|------|-------------------|---------------------|------------------|-----------------|
| 1m 顺序触达中赚/阶梯 | ✅ | ✅（经 path 入参） | ✅（需 meta.path_hit_stop） | ❌ 简化 |
| 低开硬保护立刻卖 | ✅ | ✅（overnight_open_protect） | ⚠️ 依赖 path/levels | ⚠️ 不同 |
| 开盘保护「峰值含今日」黑猫规则 | 子函数 overnight_* | ✅ 编排层特有兜底 | ❌ | ❌ |
| T+1 只展示不成交 | can_sell=False | ✅ t1_today | ✅ t_plus_one → HOLD | 引擎 T+1 |
| 因子22 止损后再买 | ❌ | 盯盘另枝 | ✅ | ❌ |
| 无 1m 仅日线 high/low | N/A | 禁止用全日 low | path_stop=False 不卖 | 用日线 bar |

---

## 5. 哪些不要删（Phase 1）

- `paper_exit_decision` — 仍是盯盘生产口径；待 parity + feature flag
- `Factor26Decision` — 回测/研究 Decision 入口
- `OpenBreak3Strategy` 内 `half_gain_stop_price` — 日线历史路径；统一需单独里程碑
- `eval_multi_tp_bar` — **永久真源**

---

## 6. 建议收敛顺序（供 Phase 2，本文件不执行）

1. 盯盘 path 结果写入统一 `FactorResult`（已有 wrapper）
2. `paper_exit_decision` 仅保留「开盘保护 / T+1 / 锁仓」编排，卖出触达只消费 FactorResult
3. `Factor26Decision` 卖出改为消费同一 FactorResult（含 fill_px）
4. 日线 akquant：标注为「简化回测」，或长期改为 1m/`eval_multi_tp_bar` 驱动

---

*Phase 1C 完成：只分析，未删除旧实现。*
