# Exit Coverage Qualification（Phase 3C+）

> 日期：2026-09-18  
> 对照：`_paper_exit_decision_legacy` ↔ `ExitDecisionEngine`  
> 行情：真实 1m OHLC（AKShare 缓存，约 2026-09-07～2026-09-17）  
> 持仓：Factor26 1m 回放生成，**不是**历史 paper ledger  
> 生产开关：**本轮未改变**（historical）

```text
USE_UNIFIED_EXIT_ENGINE = False
SHADOW_UNIFIED_EXIT_ENGINE = False
strategy → holdingStocks import 边 = 0（本轮未拆 index.py）
```

**Superseded by Primary Reversal：** `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`。下方 8,077/8,077 与 SELL 25/25 为当时 replay 事实，未改。

原则：One Decision Contract + Evidence = Safe Cutover。本轮补的是证据，不是架构。

---

## 1. 总表

| Rule | Synthetic | Historical cases (event corpus) | Production shadow | SELL | Partial SELL | Action | Price | Qty | Reason | Boundary | Collision | Remaining gaps |
| ---- | --------: | ------------------------------: | ----------------: | ---: | -----------: | ------ | ----- | --- | ------ | -------- | --------- | -------------- |
| T1_BLOCK | 2 fixture + 3 T+1 tests | 26 refs（raw BLOCK **1261** / would-SELL 4556） | 0 | 0 | 0 | ✓ | — | — | ✓ | ✓ hard last | ✓ vs 任意 SELL | 7360 里多数是空 HOLD |
| HOLD_LOCK | 1 fixture | 0（回放无锁仓） | 0 | — | — | ✓ | — | — | ✓ | — | — | 仅 synthetic |
| LIMIT_DOWN | 1 fixture | 0 | 0 | — | — | ✓ | — | — | ✓ | — | — | 仅 synthetic |
| NOT_SELLABLE | 1 fixture | 与 T+1 sellable=0 重叠 | 0 | — | — | ✓ | — | — | ✓ | — | — | 未单独出现非 T+1 |
| WAIT_AUCTION | 1 fixture | 0（signal_ok 恒 True） | 0 | — | — | ✓ | — | — | ✓ | — | — | 仅 synthetic |
| OPEN_PROTECT | 4 fixture + 3 boundary | 39 refs / **20 SELL** | 0 | 20 | 0 | 20/20 | 20/20 | 20/20 | 20/20 | ✓ | ✓ | 无 |
| PATH | 5 fixture | 15 refs / **5 SELL** | 0 | 5 | 含 2 | 5/5 | 5/5 | 5/5 | 5/5 | path_fill=0 | ✓ | 子类型样本不均 |
| PATH_HALF | 2 fixture | **2 SELL** | 0 | 2 | **2** | 2/2 | 2/2 | **2/2 @0.5** | 2/2 | — | ✓ vs full | 样本少但真实 |
| WORKING_STOP | 2 fixture + 3 boundary | 29 refs / 信号 1944 / **赢家 0** | 0 | **0** | 0 | 信号一致 | 赢家未验证 | 赢家未验证 | — | ✓ | ✓ 被 Open/PATH 吃掉 | **赢家历史缺口** |

全量 replay（未按规则过滤）：

```text
真实 1m evaluations     8,077
全量 Exact Match        8,077 / 8,077

Legacy SELL             25
Unified SELL            25
Legacy Partial SELL     2
Unified Partial SELL    2

SELL Action             25 / 25
SELL Price              25 / 25
SELL Quantity           25 / 25
SELL Reason             25 / 25

Mismatch                0
Unknown mismatch        0
Rule-order mismatch     0
```

---

## 2. 必须单独回答的问题

### Working Stop 找到多少历史案例？

- **信号**（`working_stop>0` 且 `last<=working_stop`）：**1944** 根 bar。
- 事件导向 corpus：**29**（`corpus/working_stop.json`）。
- 这些 bar 上发生 SELL：**14**，赢家全是 OPEN_PROTECT 或 PATH，**不是** WORKING_STOP。
- **WORKING_STOP 赢家 SELL：0**。
- 未改规则、未人工造价。原因是成交优先级 `open_protect > path > last`：本窗可卖时只要破 working_stop，更高优先级已经先触发。

### Half Position 找到多少历史案例？

- **2** 次真实 Partial SELL，两边 quantity_ratio 均为 **0.5**，Exact Match 2/2。
- `002636` 2026-09-11 09:39；`600967` 2026-09-14 09:32。
- Fixture 另有 2/2 synthetic。

### 是否存在任何 UNKNOWN mismatch？

**否。0。**

### 是否存在任何 rule-order mismatch？

**否。0。** Collision characterization 全部 Legacy winner == Unified winner（含 price / quantity / reason_code）。

### 是否存在任何 legacy-only rule？

**否。**

### 是否存在任何 unified-only rule？

**否。** `ReasonCode.FACTOR_26` / `HARD_GAP` 是未使用枚举，不是 Unified 多出来的成交路径。

### 哪些规则仍只有 synthetic evidence？

- **WORKING_STOP 作为赢家成交**（历史只有信号与 collision，没有赢家 SELL）
- HOLD_LOCK
- LIMIT_DOWN
- WAIT_AUCTION
- PATH 低频子类型：`ladder_full_15` / `peak_pullback` / `hard_open_dump`（本窗未单列）

---

## 3. 四维比较口径

每次 evaluation / fixture / collision / boundary：

```text
legacy.action          == unified.action
legacy.price           == unified.price          # 绝对误差 ≤ 1e-6（沿用项目现口径）
legacy.quantity_ratio  == unified.quantity_ratio
legacy.reason_code     == unified.reason_code    # = rule_id
```

未引入新的 rounding semantics。

`rule_id` 复用 `reason_code`：

```text
Decision
├── action
├── price
├── quantity_ratio
├── rule_id        # property → reason_code.value
├── reason_code
├── factor_id
└── trace
```

---

## 4. Coverage Gate

| Gate | 结果 |
| ---- | ---- |
| 所有已知 Exit Rule fixture coverage | YES |
| 所有 Position-changing Rule historical coverage | OPEN_PROTECT / PATH / PATH_HALF = YES；WORKING_STOP 赢家 = **本窗不可得（已标明）** |
| 已有 historical SELL 四维 100% | YES 25/25 |
| Rule collision characterization | PASS |
| Boundary characterization | PASS |
| Unknown mismatch | 0 |

**Historical（Phase 3C+ 当时）：不进入 Phase 3D Paper Unified Cutover。**

下一步若要积累 WORKING_STOP 赢家 / 锁仓 / 竞价拦截，当时只能：

1. 更长历史或其它持仓来源再 `find_cases --rule WORKING_STOP`
2. 或由人工打开 `SHADOW_UNIFIED_EXIT_ENGINE=True`（当时约束：**Cursor 不得自行打开**）

Shadow 代码已准备：一致 HOLD 抽样最小日志；SELL / mismatch / rule candidate 全量 compare；mismatch 含 symbol、timestamp、两边 decision、context snapshot、rule、trace、working_stop、path、position、config_version。当时 Unified 仍不成交。后续已打开 Shadow 并完成 Primary Reversal。

---

## 5. 产物与复现

| 产物 | 路径 |
| ---- | ---- |
| Coverage Matrix | `docs/EXIT_COVERAGE_MATRIX.md` |
| 本报告 | `docs/EXIT_COVERAGE_QUALIFICATION.md` |
| Corpus | `backtest/exit_decision_replay/corpus/*.json` |
| Replay 汇总 | `backtest/exit_decision_replay/replay_summary.json` |
| 规则扫描 | `python backtest/exit_decision_replay/scan_rules.py --write` |
| 找案例 | `python backtest/exit_decision_replay/find_cases.py --rule WORKING_STOP` |
| 定向 replay | `python backtest/exit_decision_replay/run.py --rule PATH --symbol 002636` |
| Collision / boundary | `python -m unittest strategy.test_exit_characterization -v` |

Corpus 只存 `symbol / date / timestamp / source / expected rule` 及少量诊断字段，行情仍从原 1m 缓存加载。

```bash
python backtest/exit_decision_replay/find_cases.py --rule ALL --days 10 --source ak --write-corpus
python backtest/exit_decision_replay/run.py --days 10 --source ak
python backtest/exit_decision_replay/run.py --rule WORKING_STOP --days 10 --source ak
python -m unittest strategy.test_exit_characterization strategy.test_exit_fixture_parity backtest.exit_decision_replay.test_run -v
```

---

## 6. 本轮未做（刻意 STOP · historical Phase 3C+）

- 当时未设 `USE_UNIFIED_EXIT_ENGINE=True`
- 未删除 `_paper_exit_decision_legacy`
- 未开始 AKQUANT migration
- 未继续拆 `holdingStocks/index.py`
- 当时未打开生产 Shadow

**Superseded：** 当前生产已是 Unified Primary + Legacy Shadow。不要删 `_paper_exit_decision_legacy`。

---

## 7. Evidence Tier（3D 标注，未改规则）

详见 [`EXIT_COVERAGE_MATRIX.md`](EXIT_COVERAGE_MATRIX.md) Evidence Tier。

- **Tier A**：OPEN_PROTECT / PATH / PATH_HALF / T1_BLOCK 真实 winner  
- **Tier B**：WORKING_STOP（historical candidate > 0，winner = 0）  
- **Tier C**：HOLD_LOCK / LIMIT_DOWN / WAIT_AUCTION  

生产 Shadow 计数见 [`SHADOW_VALIDATION_REPORT.md`](SHADOW_VALIDATION_REPORT.md)（3D 原始快照全 0；当前已 Primary Reversal）。
