# Shadow Validation Report

> Phase 3D · Production Shadow Readiness  
> 日期：2026-09-18  
> 对照：`_paper_exit_decision_legacy`（当时 Primary）↔ `ExitDecisionEngine`（只读观察）  
> 研究用途，非投资建议。

**Historical state at Phase 3D（本文件原始快照）：**

```text
Legacy Primary + Unified Shadow 尚未打开
USE_UNIFIED_EXIT_ENGINE = False
SHADOW_UNIFIED_EXIT_ENGINE = False
Production Shadow Enabled: NO
```

**Superseded by Primary Reversal（当前生产，勿把下方零表当现况）：**

```text
USE_UNIFIED_EXIT_ENGINE = True
SHADOW_UNIFIED_EXIT_ENGINE = True
Unified = Primary
Legacy = Shadow / fallback
```

后续历史生产 evidence（Legacy Primary + Unified Shadow，另一次会话）：3538/3538 exact，183/183 SELL，0 errors。  
Unified Primary Runtime Gate：PASS。本文件不补写新的 live 计数。

人工打开 `SHADOW_UNIFIED_EXIT_ENGINE=True` 之前（3D 当时）：只读副作用审计、失败隔离测试、mismatch replay 已具备。  
下方 §1 零表是 **Shadow 仍关闭时** 的就绪快照，不是当前 runtime。

---

## 1. 生产 Shadow 计数（Phase 3D 原始快照 · 当时未开）

| 指标 | 值 |
| ---- | -: |
| Evaluations | 0 |
| Exact match | 0 |
| Mismatch | 0 |
| Shadow error | 0 |
| legacy SELL | 0 |
| unified SELL | 0 |
| SELL exact match | 0 |
| Partial SELL | 0 |

对应进程内计数器（Shadow ON 后才增加）：

```text
shadow_evaluations
shadow_exact_matches
shadow_mismatches
shadow_errors
legacy_sell
unified_sell
sell_exact_match
partial_sell
candidate_by_reason.*
winner_by_reason.*
```

---

## 2. Candidate / Winner（历史基线，非生产 Shadow）

历史 replay 窗 2026-09-07～2026-09-17，**8077** evaluation，**不是** production shadow。

| Rule | candidate | winner |
| ---- | --------: | -----: |
| OPEN_PROTECT | ≥20（SELL 赢家 20） | **20** |
| PATH | 5 SELL（含 2 Partial） | **5** |
| WORKING_STOP | **1944** 信号 / 29 事件 corpus | **0** |
| T1_BLOCK | would-SELL 4556 | **1261** BLOCK |

不要把 `last <= working_stop` 统计成 Working Stop SELL。

---

## 3. Evidence Tier

见 [`EXIT_COVERAGE_MATRIX.md`](EXIT_COVERAGE_MATRIX.md) § Evidence Tier。

| Tier | 本轮 |
| ---- | ---- |
| A | OPEN_PROTECT、PATH、PATH_HALF、T1_BLOCK、大量真实 HOLD |
| B | **WORKING_STOP**（candidate>0，winner=0，synthetic/boundary/collision PASS） |
| C | HOLD_LOCK、LIMIT_DOWN、WAIT_AUCTION |

---

## 4. 开启后更新清单

打开 `SHADOW_UNIFIED_EXIT_ENGINE=True` 后持续填写：

```text
evaluations
exact match
mismatch
shadow errors

legacy SELL
unified SELL
SELL parity

partial SELL parity

candidate distribution
winner distribution

Tier A/B/C coverage
```

Mismatch 用 `python backtest/exit_decision_replay/replay_mismatch.py path.json` 复现，再固化为 regression fixture。

---

## 5. 开关与范围

- **Historical at 3D：** Legacy 是当时 Primary。  
- **Current：** Unified = Primary；Legacy = Shadow / fallback。  
- 未删 `_paper_exit_decision_legacy`。  
- 未接 AKQUANT，未改 Factor26 / Open Protect / Working Stop / Rule Order。  
- `strategy → holdingStocks` 生产 import = 0。
