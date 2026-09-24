# PHASE LOCK CONTRACT — 完成报告

> **日期**：2026-09-24  
> **合同**：[`TRADING_ENGINE_CONTRACT.md`](TRADING_ENGINE_CONTRACT.md)  
> **回归**：`python holdingStocks/run_regression_tests.py` → **56 OK**（pin 前后一致）

---

## 交付清单

| # | 产物 | 状态 |
|---|------|------|
| 1 | `docs/TRADING_ENGINE_CONTRACT.md` | ✅ |
| 2 | `FACTOR26_EXIT_PRIORITY_1M` + 观测层表 | ✅ 常量 + `test_factor26_exit_priority.py` |
| 3 | `CURRENT_INTRABAR_POLICY=PRIORITY_ENVELOPE` | ✅ 正式锁定 |
| 4 | Realtime Golden（Gate1 temporal+HWM） | ✅ PASS |
| 5 | BT-1m Golden（priority + characterization + ambiguity meta） | ✅ PASS |
| 6 | Cross Harness `strategy/cross_resolution.py` | ✅ |
| 7 | HWM Boundary Parity 单测 | ✅ |
| 8 | Stop Formula Parity 单测 | ✅ |
| 9 | State（overnight / tp_stage 透传；编排全量对拍另列 gap） | ⚠️ PARTIAL |
| 10 | Intrabar Ambiguity 审计字段 | ✅（不改成交） |
| 11 | Resolution Difference + 证据 | ✅ 例：先 106 后 102 → RESOLUTION |
| 12 | Strategy Difference（无证据滥用） | ✅ 单调用例禁 RESOLUTION |
| 13 | Temporal Violation | **0** |
| 14 | AKQuant pin `0.3.21→0.3.22` | ✅ requirements；回归无变化 |
| 15 | 剩余 gaps | 见下 |

---

## PRIORITY_ENVELOPE（摘要）

同 bar：high/low 同时可读；**禁止** O-H-L-C 假路径；冲突由 Factor26 优先级表决定；标记 `intrabar_ambiguous` + `resolved_by=PRIORITY_ENVELOPE`。

## FACTOR26_EXIT_PRIORITY_1M（摘要）

`hard_open_dump` → `hard_from_cost_gap` → `t1_peak_trail` → `ladder_full_15` → mid(`half_gain`/`vol_giveback`) → `hard_from_cost` → `ladder_half_10` → `peak_pullback_clear`

Realtime 观测层：`open_protect` → `path` → `last`

---

## Cross Harness 示例

**歧义分钟**（104→106→102，cost=100）：

- Realtime：last 腿 `vol_giveback` @103.35，`peak=106`  
- BT-1m：包络 `half_gain` @102.0，`intrabar_ambiguous=true`  
- 分类：`RESOLUTION_DIFFERENCE`（有证据）

**单调两分钟**：`MATCH × 2`；无 RESOLUTION 滥用。

---

## 最终判定

| 项 | 结果 |
|----|------|
| **REALTIME ENGINE** | **PASS** |
| **BT-1M STRATEGY CONTRACT** | **PASS** |
| **CROSS-RESOLUTION STRATEGY PARITY** | **PARTIAL**（Harness+分类已通；全状态机/path/open_protect 对拍未齐；Capital/Fee 未做） |
| **TEMPORAL VIOLATIONS** | **0** |
| **UNEXPLAINED STRATEGY DIFFERENCES** | **0**（Gate 套件内） |

---

## 剩余 gaps（不阻塞本 Phase）

1. Realtime 全链 `paper_exit_decision`（open_protect/path）未进 Cross mini-engine（仅 last 腿）  
2. Capital V2 / Fee / PnL → 另 PHASE  
3. BT-Daily 仍 research-only  
4. 生产 path 腿与 BT 竞价 K 过滤对齐（已知编排债）  
5. Cross 中 RT/BT 同退出但 reason 不同时归 RESOLUTION（有歧义证据）；若未来要拆 `OBSERVATION_LEG_DIFFERENCE` 可再细分  

**未做**：降级 Realtime 粒度；改 Factor26 参数；改 PRIORITY_ENVELOPE 成交逻辑；接 AQ live trailing。
