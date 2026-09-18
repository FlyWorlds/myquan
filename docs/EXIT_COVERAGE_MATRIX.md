# Exit Coverage Matrix

> Phase 3C+ · 2026-09-18  
> 代码真源：`docs/EXIT_RULE_ORDER.md` · `ExitDecisionEngine` · `_paper_exit_decision_legacy` · `ReasonCode`  
> `rule_id` = `ExitDecision.reason_code.value`（未新增并行字段）  
> 扫描器：`python backtest/exit_decision_replay/scan_rules.py --write`

**Historical at Phase 3C+：** Production Shadow 未开。  
**Superseded by Primary Reversal：** `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`。

证据等级必须分开：**Synthetic** / **Historical** / **Production Shadow**。  
本表 Historical 来自 2026-09-07～2026-09-17 真实 1m、Factor26 回放生成持仓，**8077** 次 evaluation。下表 Production Shadow 列为当时未开（0），不是当前 runtime。

### Evidence Tier

| Tier | 定义 | 本轮不得做的事 |
| ---- | ---- | -------------- |
| **A** | 真实 historical **或** production **winner** | 不要为了升档人工制造 historical winner |
| **B** | 真实 **candidate** + 被更高优先级规则覆盖 + synthetic winner + collision/boundary 已验证 | candidate 不得记成 winner |
| **C** | 只有 synthetic evidence | 可以保留，须标明 |

| Rule | Tier | 依据 |
| ---- | ---- | ---- |
| OPEN_PROTECT | **A** | historical winner SELL **20** |
| PATH | **A** | historical winner SELL **5**（含 2 Partial） |
| PATH_HALF | **A** | historical winner Partial **2** |
| T1_BLOCK | **A** | historical winner BLOCK **1261**（不成交） |
| WORKING_STOP | **B** | historical candidate **1944** / winner **0**；被 OPEN_PROTECT / PATH 覆盖；synthetic + boundary + collision PASS |
| HIT_SHOW_FALSE / QTY_EMPTY | **A** | 大量真实 HOLD evaluation |
| NOT_SELLABLE | **B** | 与 T+1 sellable=0 重叠，非独立 historical winner |
| HOLD_LOCK | **C** | synthetic only |
| LIMIT_DOWN | **C** | synthetic only |
| WAIT_AUCTION | **C** | synthetic only |
| PATH_LADDER_FULL_15 / PATH_PEAK_PULLBACK | **C** | 本窗 0 historical；仅因子层 / synthetic |

---

## 1. 可能改变仓位或拦截成交的路径

| Rule | Effect | Legacy | Unified | Fixture | Replay | Hist SELL / Partial | Price | Qty | Reason | Notes |
| ---- | ------ | ------ | ------- | ------- | ------ | -------------------: | ----- | --- | ------ | ----- |
| QTY_EMPTY | HOLD | ✓ | ✓ | ✓ | ✓ | — | — | — | — | qty≤0 空结果 |
| HIT_SHOW_FALSE | HOLD | ✓ | ✓ | ✓ | ✓ | — | — | — | — | 大量 T+1 evaluation 落在这里，不是 T1_BLOCK |
| T1_BLOCK | BLOCK_SELL | ✓ | ✓ | ✓ | ✓ | 0 SELL；**1261** 次真正 BLOCK | — | — | ✓ | 前置：T+1 收窄后仍 hit_show |
| HOLD_LOCK | BLOCK_SELL | ✓ | ✓ | ✓ | ✗ | 历史不可得（回放未设 hold_locked） | — | — | — | Synthetic only |
| LIMIT_DOWN | BLOCK_SELL | ✓ | ✓ | ✓ | ✗ | 历史不可得（回放未设 stop_locked） | — | — | — | Synthetic only |
| NOT_SELLABLE | BLOCK_SELL | ✓ | ✓ | ✓ | ✓/? | T+1 时 sellable=0 与 T1 重叠 | — | — | — | Replay 用 T+1 表达不可卖 |
| WAIT_AUCTION | BLOCK_SELL | ✓ | ✓ | ✓ | ✗ | 历史不可得（signal_ok 恒 True） | — | — | — | Synthetic only |
| OPEN_PROTECT | SELL | ✓ | ✓ | ✓ | ✓ | **20** / 0 | ✓ 20/20 | ✓ | ✓ | 成交优先 1 |
| PATH | SELL / PARTIAL | ✓ | ✓ | ✓ | ✓ | **5** SELL（含 2 Partial） | ✓ 5/5 | ✓ | ✓ | Factor26 1m；`factor_id=factor26` |
| WORKING_STOP | SELL | ✓ | ✓ | ✓ | 信号 ✓ / 赢家 ✗ | **0 winner SELL** | 未作为赢家验证 | 未作为赢家验证 | — | **Tier B**；见 §3 |

PATH 子类型（仍是 `reason_code=PATH`）：

| Rule | Effect | Fixture | Historical | Notes |
| ---- | ------ | ------- | ---------- | ----- |
| PATH_HALF | PARTIAL_SELL 0.5 | ✓ 2/2 | **2 SELL**（002636、600967） | `ladder_half_10` / `action_kind=half` |
| PATH_HALF_GAIN | SELL | ✓ | 含于 5 次 PATH SELL | Factor26 `half_gain` |
| PATH_VOL_GIVEBACK | SELL | ✓ | 本窗未单列 | Factor26 `vol_giveback` |
| PATH_HARD_FROM_COST | SELL | ✓ | 本窗未单列 | 硬保护走 PATH，不是独立 engine 规则 |
| PATH_HARD_GAP | SELL | ✓/? | 本窗未单列 | `hard_open_dump`；`ReasonCode.HARD_GAP` 未被 Engine 使用 |
| PATH_LADDER_FULL_15 | SELL | ✗ 仅因子层 | 本窗 0 | 低频 |
| PATH_PEAK_PULLBACK | SELL | ✗ 仅因子层 | 本窗 0 | 低频 |
| PATH_T1_PEAK_TRAIL | SELL/BLOCK | ✗ | T+1 下不成交 | 触及后仍受 T1_BLOCK |

---

## 2. 未使用的 ReasonCode（不是独立成交规则）

| Code | 说明 |
| ---- | ---- |
| FACTOR_26 | Engine 用 PATH + `factor_id=factor26` |
| HARD_GAP | 因子26 path 子类型，不进 ExitDecisionEngine 独立分支 |
| UNKNOWN | `paper_reason_to_code` 回退 |

**Legacy-only rule：无。Unified-only rule：无。**

---

## 3. Working Stop 覆盖缺口（P0）

扫描条件（**未改规则、未人工改价**）：

```text
working_stop > 0 AND last <= working_stop
AND qty>0（含 T+1 / 不可卖等前置状态一并记录）
```

| 口径 | 数量 | 证据等级 |
| ---- | ---: | -------- |
| 原始信号 bar | 1944 | Historical |
| 事件导向 corpus | 29 | Historical |
| 其中 SELL（赢家不是 WORKING_STOP） | 14 | Historical collision |
| **WORKING_STOP 赢家 SELL** | **0** | 本窗历史不可得 |
| Synthetic fixture SELL | 2 | Synthetic |
| Boundary last−tick / = / +tick | 3 | Synthetic |
| Production shadow | 0 | 未开 |

本窗凡 `last<=working_stop` 且可卖，更高优先级的 **OPEN_PROTECT 或 PATH** 先成交。T+1 日则 BLOCK 或空 HOLD。这是规则顺序的结果，不是漏扫。

---

## 4. T+1 不要被 7360 迷惑

| 口径 | 数量 |
| ---- | ---: |
| T+1 evaluation（买入日不可卖） | 7360 |
| T+1 且前置信号 would-SELL | 4556 |
| 其中 would Open Protect | 3863 |
| 其中 would Working Stop | 1930 |
| 其中 would Factor26 | 含于 path 15 |
| **真正 T1_BLOCK**（收窄后仍 hit_show） | **1261** |
| 其余 | 空 HOLD（T+1 清掉 open_hit 后不再 hit_show） |

Characterization：`T+1 + Open Protect would SELL` / `T+1 + Working Stop would SELL` / `T+1 + Factor26 would SELL` 均与 Legacy HOLD/BLOCK 一致。

---

## 5. Half Position / Partial SELL

| 口径 | Legacy | Unified | Exact |
| ---- | -----: | ------: | ----- |
| Partial SELL | 2 | 2 | 2/2 |
| quantity_ratio | 0.5 | 0.5 | ✓ |
| Fixture | 2/2 | 2/2 | ✓ |

历史案例：`002636` 2026-09-11 09:39；`600967` 2026-09-14 09:32。见 `corpus/half_position.json`。

---

## 6. Collision / Boundary

| 组合 | Characterization | Historical 同刻信号 |
| ---- | ---------------- | ------------------- |
| Open Protect + Working Stop | PASS（Open 赢） | 1249 |
| Working Stop + Factor26 | PASS（PATH 赢） | 11 |
| Open Protect + Factor26 | PASS（Open 赢） | 10 |
| T+1 + 任意 SELL | PASS（HOLD/BLOCK） | 见 §4 |
| Half + Open Protect | PASS（Open 全仓） | Synthetic |
| Half + Working Stop | PASS（PATH 半仓） | Synthetic |

Boundary（比较符保持 `<= + 1e-12`，未改）：

- Working Stop：`last = stop − tick / stop / stop + tick`
- Open Protect：`open = protect − tick / protect / protect + tick`
- T+1 hard last：同样三档
- PATH：`path_hit ∧ path_fill_px=0` 不是 path_ok

---

## 7. Coverage Gate（Cutover 前）

| Gate | 状态 |
| ---- | ---- |
| 已知 Exit Rule fixture coverage | **YES** |
| Position-changing historical coverage | OPEN_PROTECT YES；PATH YES；PATH_HALF YES；**WORKING_STOP 赢家本窗不可得**（已标明） |
| 已有 historical SELL Action/Price/Qty/Reason | **25/25 = 100%** |
| Rule collision characterization | **PASS** |
| Boundary characterization | **PASS** |
| Unknown mismatch | **0** |
| Production shadow | **当时未开**（historical：`SHADOW_UNIFIED_EXIT_ENGINE=False`） |

**Historical 结论（Phase 3C+ 当时）：尚未进入 Paper Unified Cutover。**  
当时：`USE_UNIFIED_EXIT_ENGINE=False` · `SHADOW_UNIFIED_EXIT_ENGINE=False` · 未删 `_paper_exit_decision_legacy` · 未拆 `holdingStocks/index.py`。

**Superseded by Primary Reversal：** `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`（Unified = Primary，Legacy = Shadow / fallback）。未删 `_paper_exit_decision_legacy`。

研究用途，非投资建议。
