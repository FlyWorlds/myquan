# Exit 规则顺序（真源：`paper_exit_decision`）

> 日期：2026-09-17  
> 来源：`holdingStocks/index.py` → `paper_exit_decision`（约 L4750–4927）  
> **ExitDecisionEngine 必须遵守本顺序；禁止擅自重排。**

---

## 1. 总览

纸面卖出判定分三阶段：

```text
A. 输入校验与触达信号计算
B. 展示命中但不可成交的拦截（show-only）
C. 可成交时的优先级（谁先触发谁成交）
```

---

## 2. 详细顺序（与代码一致）

| 序号 | 阶段 | 条件 / 动作 | paper 字段 |
|------|------|-------------|------------|
| 00 | 校验 | `qty <= 0` → 空结果（不成交、不展示） | `empty` |
| 01 | 信号 | 算 `protect`：`resolve_peak_for_open` + `overnight_open_protect_px` | — |
| 02 | 信号 | `open_hit` = 今开 ≤ protect | — |
| 03 | 信号 | `last_hit` = last ≤ working_stop | — |
| 04 | 信号 | `path_ok` = path_hit ∧ path_fill_px>0 | — |
| 05 | T+1 收窄 | 若 `t1_today`：清零 `open_hit`；`last_hit`/`path_ok` 仅允许硬保护触达 | — |
| 06 | 展示 | `hit_show` = open_hit ∨ last_hit ∨ path_ok；否则 empty | `hit_show` |
| 07 | 拦截 | `t1_today` → 只展示，不成交 | `reason=t1` |
| 08 | 拦截 | `hold_locked` → 只展示 | `hold_lock` |
| 09 | 拦截 | `stop_locked` → 只展示 | `limit_down` |
| 10 | 拦截 | `sellable <= 0` → 只展示 | `not_sellable` |
| 11 | 拦截 | `not signal_ok` → 只展示 | `wait_auction` |
| 12 | **成交优先 1** | `open_hit` → 全仓卖，价=今开 | `kind=open_protect` |
| 13 | **成交优先 2** | `path_ok` → 半仓或全仓，价=path_fill | `kind=path` |
| 14 | **成交优先 3** | 否则（必有 last_hit）→ 全仓卖，价=working_stop | `kind=last` |

---

## 3. 映射到 ExitDecisionEngine / ReasonCode

| 序号 | Engine 步骤 | ReasonCode |
|------|-------------|------------|
| 00 | qty 校验 | `NONE` |
| 01–06 | 信号预计算（含 T+1 收窄） | — |
| 07 | T+1 block | `T1_BLOCK` |
| 08 | hold lock | `HOLD_LOCK` |
| 09 | limit down | `LIMIT_DOWN` |
| 10 | not sellable | `NOT_SELLABLE` |
| 11 | wait auction | `WAIT_AUCTION` |
| 12 | `evaluate_overnight_open_protect` | `OPEN_PROTECT` |
| 13 | path（Factor26 1m 结果入参） | `PATH` / `FACTOR_26` |
| 14 | `evaluate_working_stop` | `WORKING_STOP` |

说明：

- **Factor26 数学**仍在 `eval_multi_tp_bar`；盯盘路径把结果以 `path_*` 喂入编排层。  
- Engine 的 path 分支消费 `path_hit` / `path_fill_px` / `path_action_kind`，不在此重跑 1m。  
- `quantity_ratio`：path 半仓 → `0.5`；其余全仓 → `1.0`。
- **`rule_id` = `ReasonCode.value`**（`ExitDecision.rule_id` 只是 property，不另存字段）。PATH 的 Factor26 子类型用 `path_stop_kind` / `quantity_ratio` 区分。
- 覆盖与资格：[`EXIT_COVERAGE_MATRIX.md`](EXIT_COVERAGE_MATRIX.md) · [`EXIT_COVERAGE_QUALIFICATION.md`](EXIT_COVERAGE_QUALIFICATION.md)

---

## 4. 刻意不在此引擎内的事项

| 事项 | 原因 |
|------|------|
| 改持仓 / 账本 | 执行层 |
| 拉行情 | Market |
| 调用 `get_decision_engine()` 买入逻辑 | 本文件仅 EXIT |
| 改 `eval_multi_tp_bar` | Factor 真源 |

---

*文档与 `strategy/exit_rules/engine.py` 同步维护。*
