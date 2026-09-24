# PRODUCTION_EXIT_ORCHESTRATION_CONTRACT

> **日期**：2026-09-24  
> **真源**：`holdingStocks/index.py` → `paper_exit_decision` → `_paper_exit_decision_legacy`  
> **性质**：从生产代码抽出的退出编排合同（非臆造）  
> **约束**：本 Phase 不改 Factor26 参数 / PRIORITY_ENVELOPE / Realtime 粒度

---

## 0. 入口

| 符号 | 角色 |
|------|------|
| `paper_exit_decision` | 对外入口；默认返回 legacy 结果（统一引擎默认关） |
| `_paper_exit_decision_legacy` | **成交语义真源** |
| `_open_protect_hit_ts` | open_protect 的 `triggered_at`（仅 open_bell / kind=open_protect → 09:30） |

观测优先级常量（与代码一致）：

`FACTOR26_OBSERVATION_PRIORITY_REALTIME = ("open_protect", "path", "last")`

---

## 1. 控制流（确定性）

```text
输入校验 qty>0
  → 计算 protect / open_hit / last_hit / path_ok / open_bell
  → 若 t1_today：强制削弱为「仅硬保护」语义（见 §3）
  → hit_show = open_hit ∨ last_hit ∨ path_ok
  → 若 ¬hit_show → empty（hit=False）
  → 闸门（short-circuit，hit 仍 False，仅 reason）：
        t1_today → reason=t1
        hold_locked → hold_lock
        stop_locked → limit_down
        sellable≤0 → not_sellable
        ¬signal_ok → wait_auction
  → 竞争（命中即 return，short-circuit）：
        open_hit → kind=open_protect, fill=open_px, action=full
        path_ok  → kind=path, fill=path_fill_px, …
        else     → kind=last, fill=working_stop, action=full
```

**三者竞争优先级：open_protect > path > last。**  
任一命中后 **short-circuit**，不再评估后续腿。

---

## 2. 各层资格（eligible）

### 2.1 open_protect（`open_hit`）

**资格**（非 T+1 时）：

- `open_px > 0`
- `protect > 0`，其中 `protect = overnight_open_protect_px(...)`
- `open_px ≤ protect`

**peak_for_open 输入规则**（代码内）：

- 调用方应传隔夜冻结峰值；兜底：高开且 `peak≥open` → 回退 `max(cost, prev_close)`；低开保留 raw peak

**T+1**：`open_hit` **强制 False**（买入日不做开盘保护卖出）。

**是否改状态**：本函数不写 holdings；成交由 `apply_exit_fill` 完成。

**exit_kind**：`"open_protect"`  
**triggered_at**：`_open_protect_hit_ts(..., open_bell=True | exit_kind=open_protect)` → **session 09:30:00**  
**禁止**：用 `fill≈open` 反推时刻（`_open_protect_hit_ts` 已 `del fill_px, open_px`）。

---

### 2.2 path（`path_ok`）

**资格**（非 T+1）：

- 调用方传入 `path_hit=True` **且** `path_fill_px > 0`

**T+1 收紧**：

- 另需：`path_fill ≤ hard` 且 `last ≤ hard×1.003`（硬保护附近才允许 path 展示/结算）

**输入**：`path_hit`, `path_fill_px`, `path_action_kind`, `path_stop_kind`（由 1m `path_dependent` / `eval_multi_tp_bar` 上游供给；**本函数不重算 Factor26**）

**exit_kind**：`"path"`；`stop_kind` 透传上游；半仓由 `is_half_stop_kind`  
**triggered_at**：上游 1m `touch_ts` / 真实事件时间；**禁止**价格反推开盘铃。

---

### 2.3 last

**资格**（非 T+1）：

- `working_stop > 0` 且 `last > 0` 且 `last ≤ working_stop`

**T+1**：仅当 `last ≤ cost_hard_stop`（硬保护）。

**输入**：`last`（实时 quote）、`working_stop`（`working_stop_price`）

**exit_kind**：`"last"`；`action_kind=full`；`fill_px=working_stop`  
**triggered_at**：决策时 quote 事件时间（扫描/快刷时刻）。

---

## 3. T+1 / 闸门对资格的影响

| 条件 | 对 hit 的影响 |
|------|----------------|
| `t1_today` | 清除 open；last/path 仅硬保护语义；**闸门 reason=t1 且 hit=False**（只展示） |
| `hold_locked` / `stop_locked` / `sellable≤0` / `¬signal_ok` | `hit_show` 可为 True，但 **hit=False**，reason 分别为 hold_lock / limit_down / not_sellable / wait_auction |

即：闸门在竞争选择 **之前**；过闸门后才选 open/path/last。

---

## 4. 与 BT-1m 的边界

| | Realtime 编排 | BT-1m |
|--|---------------|-------|
| open_protect | 生产腿；今开 vs overnight protect | 映射为 bar 内 `hard_from_cost` / gap 等（**非同一观测名**） |
| path | 1m 上游 + 本函数选 path | `eval_multi_tp_bar` + PRIORITY_ENVELOPE |
| last | 秒级 quote | **无**独立 last 腿 |

Cross 比较：允许 `RESOLUTION_DIFFERENCE`；要求 `decision_at ∈ BT bar`（粒度兼容），**不要求**秒级相等。  
open_protect 时间语义例外：必须合法开盘窗，禁止 11:00 fill≈open → OPEN_PROTECT。

---

## 5. 三层竞争矩阵（期望）

`eligible` 指过闸门后的 open_hit / path_ok / last_hit：

| O | P | L | selected |
|---|---|---|----------|
| 0 | 0 | 0 | （无 hit；或仅 hit_show 被闸门挡住） |
| 1 | 0 | 0 | open_protect |
| 0 | 1 | 0 | path |
| 0 | 0 | 1 | last |
| 1 | 1 | 0 | open_protect |
| 1 | 0 | 1 | open_protect |
| 0 | 1 | 1 | path |
| 1 | 1 | 1 | open_protect |

---

## 6. Gate 4

`FULL_EXIT_ORCHESTRATION`：上表 + OP/PATH/LAST 场景 + RealtimeFullExitRunner（调用生产 `paper_exit_decision`）必须 PASS。
