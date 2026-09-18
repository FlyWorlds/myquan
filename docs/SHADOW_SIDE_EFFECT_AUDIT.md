# Shadow Side-Effect Audit

> 日期：2026-09-18  
> 范围：Paper runtime → Context Builder → ExitDecisionEngine → Exit Rules → Decision Trace → Shadow Compare  
> **Historical at Phase 3D：** 生产开关当时未打开（`USE_UNIFIED_EXIT_ENGINE=False`，`SHADOW_UNIFIED_EXIT_ENGINE=False`）  
> **Superseded by Primary Reversal：** `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`（Unified = Primary，Legacy = Shadow / fallback）  
> 本审计不改交易规则。审计结论仍适用于「Shadow 路径不得改成交」；不要把当时 False 读成当前配置。

分类：

| 标记 | 含义 |
|------|------|
| PURE | 无 I/O、无全局写入；只从入参算结果 |
| READ_ONLY | 可读入参 / 常量；不写 paper 状态 |
| MUTATING | 有写入。须注明写入对象是否隔离于 paper |
| UNKNOWN | 未能证明 |

---

## 1. 调用链（生产默认 Shadow OFF）

```text
paper_exit_decision
    │  snapshot kwargs                    READ_ONLY
    │  若 flags 全 False：不建 Unified Context
    ▼
_paper_exit_decision_legacy               PURE
    ▼
maybe_shadow_and_select
    │  flags False → 立即返回 legacy      READ_ONLY
    ▼
caller 用返回 dict 做成交 / 账本          （执行层，不在 Shadow 内）
```

Shadow OFF 时 Unified 路径不运行。

---

## 2. 调用链（仅当人工打开 Shadow）

```text
runtime scalars
    ▼
snapshot kwargs + DecisionContext         READ_ONLY  （Legacy 之前）
    ├──────────→ _paper_exit_decision_legacy     PURE → primary decision
    └──────────→ ExitDecisionEngine.evaluate     PURE → compare only
                      ▼
                 Shadow Compare / buffer         MUTATING（仅进程内 Shadow 缓冲）
```

Unified Context 必须在 Legacy 决策前从同一份 snapshot 建立。禁止：

```text
legacy() → 改仓/改止损/写账 → 再 build unified context
```

---

## 3. 逐函数

### Paper wrapper · `holdingStocks/index.py`

| 函数 | 标记 | 说明 |
|------|------|------|
| `paper_exit_decision` | READ_ONLY → 委托 | 只组 snapshot、调 legacy、可选 Shadow。本身不写 holdings / ledger / 文件。Shadow 异常时仍返回 legacy。 |
| `_paper_exit_decision_legacy` | PURE | 纯函数：入参标量 → 新 dict。不读全局仓位、不写账本、不发网络。 |

`paper_exit_decision` 的**调用方**（`settle_due_paper_stops` 等）会按返回值改仓。那是 paper execution，不是 Shadow。Shadow 不得成为那条写入链的一部分。

### Context / Compare · `strategy/exit_rules/shadow.py`

| 函数 | 标记 | 说明 |
|------|------|------|
| `build_exit_context_from_paper_kwargs` | PURE | 从 snapshot 建 `DecisionContext`。 |
| `compare_paper_vs_exit` | PURE | 比较两个决策，返回新 record。 |
| `classify_mismatch` | PURE | |
| `_legacy_action` / `_legacy_qty_ratio` | PURE | |
| `_is_rule_candidate_ctx` | PURE | |
| `_context_snapshot` / `_scalar_paper_kwargs` / `paper_kwargs_from_record` | PURE | 从 snapshot 重建标量 kwargs，不含行情 bars。 |
| `build_replayable_record` | PURE | mismatch/SELL 完整记录；不写文件。 |
| `_shadow_payload` | MUTATING | 会改 record 的 `log_level`/`sampled` 字段（仅该对象，非仓位）。 |
| `_record_shadow_metrics` | MUTATING | 只写进程内 `_SHADOW_METRICS`。candidate / winner 分列，不把 `last<=working_stop` 记成赢家 SELL。 |
| `_note_shadow_error` | MUTATING | 只写进程内 `_SHADOW_ERRORS` + `shadow_errors` 计数。 |
| `run_unified_exit` | PURE | 调 engine + 适配 dict。 |
| `maybe_shadow_and_select` | READ_ONLY + 条件 MUTATING | flags 全关：直接返回 legacy。Shadow 开：可写 `_SHADOW_BUFFER` / metrics / errors。**3D 当时** `use_unified` 默认 False，生产返回 legacy。当前 Primary Reversal 下 `use_unified=True` 返回 Unified，异常 failover 回 Legacy。 |
| `emit_shadow_record` | MUTATING | 追加进程内 `_SHADOW_BUFFER`（上限 5000）。**不写文件、不写 ledger、不 HTTP。** Hook 异常被吞掉。 |
| `set_shadow_hook` | MUTATING | 测试/观测注入。生产默认 `None`。 |
| `clear_shadow_buffer` / `get_shadow_buffer` / `get_shadow_errors` / `get_shadow_metrics` | MUTATING / READ_ONLY | 仅 Shadow 缓冲。 |
| 模块常量 `USE_*` / `SHADOW_*` | READ_ONLY 默认 | **Historical at 3D：** 本轮保持 False。 |

Shadow 局部可变状态：

```text
_SHADOW_BUFFER      进程内存，非 paper ledger
_SHADOW_ERRORS      进程内存
_HOLD_SAMPLE_SEQ    抽样计数
_SHADOW_METRICS     计数器（Shadow ON 才写）
_SHADOW_HOOK        默认 None
_ENGINE             无状态编排器单例
```

这些在 Shadow OFF 时不被写入（`maybe_shadow_and_select` 早退）。

### Engine / Rules

| 函数 | 标记 | 说明 |
|------|------|------|
| `ExitDecisionEngine.evaluate` | PURE | 只读 `DecisionContext`，返回 `ExitDecision` + trace。 |
| `_annotate_candidates` | PURE | 只往本次 trace 追加 candidate/winner/superseded_by。 |
| `exit_decision_to_paper_dict` | PURE | |
| `evaluate_overnight_open_protect` | PURE | 委托 `overnight_open_protect_px`（价位公式）。 |
| `resolve_peak_for_open_protect` | PURE | |
| `evaluate_working_stop` | PURE | `last <= working_stop` 判定。 |
| `cost_hard_stop_px` | PURE | 买点硬保护价。 |
| `is_half_stop_kind` | PURE | |
| `overnight_open_protect_px` | PURE | 因子26 价位；无 I/O。 |

`strategy/exit_rules/` **禁止 import holdingStocks**。不经过 Market / Broker / AKQUANT。

---

## 4. 明确不存在的副作用

Shadow 调用链中**未发现**：

| 检查项 | 结果 |
|--------|------|
| position mutation | 无 |
| holding mutation | 无 |
| working_stop mutation | 无（只读 ctx.working_stop） |
| ledger write | 无 |
| database write | 无 |
| HTTP request | 无 |
| WebSocket emit | 无 |
| file mutation | 无（paper Shadow 只写内存缓冲。`replay_mismatch.py --out` 是离线工具，不在盯盘路径） |
| AKQUANT action | 无 |
| cache mutation（行情缓存） | 无 |

---

## 5. 发现的 MUTATING（隔离范围）

| 位置 | 写入对象 | 是否影响 paper |
|------|----------|----------------|
| `_SHADOW_BUFFER.append` | 进程内比较日志 | 否 |
| `_SHADOW_ERRORS.append` | 进程内错误日志 | 否 |
| `_SHADOW_METRICS` | 进程内计数 | 否 |
| `_HOLD_SAMPLE_SEQ` | 抽样计数 | 否 |
| `_shadow_payload` 改 record 字段 | 比较对象 | 否 |
| `set_shadow_hook` | 可选回调 | **若人工注入危险 hook，hook 本身可能有副作用**；生产未设置。`emit` 已吞掉 hook 异常。 |

**无 UNKNOWN。** Hook 在默认 `None` 下不执行。

---

## 6. 结论

- Shadow OFF：与引入 Shadow 之前的 Legacy 行为一致。  
- **Historical at 3D Shadow ON：** Legacy 仍是 Primary；Unified 只读观察。  
- **Current（Primary Reversal）：** Unified = Primary；Legacy = Shadow / fallback。  
- 已将 Unified Context 固定在 Legacy 决策之前的 snapshot 上。  
- Shadow / Engine / Compare / 日志异常不得改变当时返回的 Primary 决策（3D 为 legacy；当前为 Unified，failover 才回 Legacy）。  

**Historical：** 当时具备人工打开 `SHADOW_UNIFIED_EXIT_ENGINE=True` 的安全前提（只读、失败隔离）。**本轮（3D）不打开。** 后续已打开 Shadow 并完成 Primary Reversal。

研究用途，非投资建议。
