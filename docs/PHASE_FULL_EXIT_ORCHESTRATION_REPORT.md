# PHASE — FULL EXIT ORCHESTRATION PARITY 报告

> **日期**：2026-09-24  
> **合同**：[`PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md`](PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md)  
> **回归**：`python holdingStocks/run_regression_tests.py` → **71 OK**

---

## 1. Production Exit Contract

真源：`_paper_exit_decision_legacy` / `paper_exit_decision`。

优先级（过闸门后 short-circuit）：**open_protect > path > last**。

闸门先于竞争：`t1` / `hold_lock` / `limit_down` / `not_sellable` / `wait_auction` → `hit=False`。

`triggered_at`：open_protect → 仅 09:30；path/last → 真实事件时间；**禁止 fill≈open 反推**。

---

## 2–5. 测试覆盖

| 组 | 结果 |
|----|------|
| OP1–OP4 open_protect | PASS |
| PATH1–PATH3（含 Cross RESOLUTION 证据） | PASS |
| LAST1–LAST3 | PASS |
| 8 路 O/P/L 竞争矩阵 | PASS |
| RealtimeFullExitRunner（生产 `paper_exit_decision`） | PASS |
| `TEMPORAL_GRANULARITY_COMPATIBLE` | PASS |

---

## 6–7. Synthetic Cross / Historical Replay

- Synthetic Cross（`use_full_exit=True`）：歧义例可归 **RESOLUTION_DIFFERENCE** 且带 first-divergence evidence。  
- Historical Replay：**INSUFFICIENT_REPLAY_DATA**（`trades*.jsonl` 无 `exit_kind`/quote 事件流；**禁止**按成交结果反造行情）。凯盛 PATH@09:58 由 Gate1 temporal 用例锁定。

---

## 8–11. 分类统计（Gate 套件内）

| 项 | N |
|----|---|
| TEMPORAL_VIOLATIONS | **0** |
| UNEXPLAINED STRATEGY DIFFERENCES | **0** |
| RESOLUTION（允许，须证据） | ≥0（PATH1 场景可产生） |

Classifier 升级字段：`first_divergence_at` / `rt_state_before` / `bt_state_before` / `rt_decision` / `bt_decision` / `intrabar_ambiguous` / `classification_reason`。

---

## 12. Regression

**71** tests OK（含 Gate1–4）。

---

## 最终判定

| 项 | 结果 |
|----|------|
| **REALTIME ENGINE** | **PASS** |
| **BT-1M CONTRACT** | **PASS** |
| **FULL EXIT ORCHESTRATION** | **PASS** |
| **CROSS-RESOLUTION COMPARABILITY** | **PARTIAL**（全链编排已覆盖；历史 replay 数据不足；Capital/Fee 未做） |
| **TEMPORAL VIOLATIONS** | **0** |
| **UNEXPLAINED STRATEGY DIFFERENCES** | **0** |

---

## Pure Core 启动条件

`FULL_EXIT_ORCHESTRATION=PASS` 且 temporal/unexplained=0 → **允许进入** SHARED PURE CORE EXTRACTION（下阶段）。  
必须以现有 Golden/Cross 为 characterization；**禁止改测试迁就重构**。

## 未做（按计划）

Factor26 参数 / PRIORITY_ENVELOPE / Realtime 降 1m / AQ live trailing / Capital / Fee / Pure Core 抽取。
