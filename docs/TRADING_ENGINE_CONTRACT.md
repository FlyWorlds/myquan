# Trading Engine Contract（正式锁定）

> **日期**：2026-09-24  
> **Phase**：LOCK REALTIME / BT-1M CONTRACT  
> **关联**：[`REALTIME_1M_ARCHITECTURE.md`](REALTIME_1M_ARCHITECTURE.md)、[`PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md`](PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md)

---

## 0. 钉死原则

| 层 | 定义 |
|----|------|
| **PRODUCTION** | **REALTIME FIRST** — 每个有效 quote/trade 可推进策略状态；**绝不**等 1m bar close |
| **BACKTEST（正式验证）** | **BT-1m + PRIORITY_ENVELOPE** |
| **SHARED** | Factor26 **Strategy Semantics**（参数、优先级、HWM 数值语义、T+1、overnight、exit kind） |
| **允许** | `RESOLUTION_DIFFERENCE`（须有 intrabar / 顺序丢失证据） |
| **禁止** | `TEMPORAL_VIOLATION`；无法解释的 `STRATEGY_DIFFERENCE`；为对齐降级 Realtime；在 OHLC 伪造 tick 时刻 |

**不在本 Phase**：Capital V2 / Fee / PnL 对等（已知 FAIL，另开 PHASE）。

**不讨论**：Paper 改接 AKQuant live trailing。

---

## 1. Realtime Engine

```text
QuoteHub (trade/quote)
    → temporal_integrity   (quote_at ≤ decision_at)
    → HWM / peak_high_at   (raise_position_peak_high；dayHigh ≠ HWM)
    → working_stop_price
    → paper_exit_decision  (open_protect → path → last)
    → Paper execution
```

- 观测优先级：`FACTOR26_OBSERVATION_PRIORITY_REALTIME = (open_protect, path, last)`
- **禁止** Realtime 使用 `PRIORITY_ENVELOPE`
- **禁止** 延迟 HWM 到 bar close

---

## 2. BT-1m Engine

```text
1m OHLC
    → PRIORITY_ENVELOPE
    → eval_multi_tp_bar
    → strategy decision (+ audit: resolution / intrabar_ambiguous)
    → AKQuant accounting / execution（可选）
```

- `CURRENT_INTRABAR_POLICY = "PRIORITY_ENVELOPE"`
- BT **不拥有**真实 tick 顺序；`decision_at` 可为 bar 边界，**禁止**伪造 high@15s / low@45s

---

## 3. BT-Daily

仅 **RESEARCH BACKTEST**。  
不得用于证明 Factor26 production semantic parity。

---

## 4. PRIORITY_ENVELOPE（正式定义）

同一 1m bar：

- `high` 证明该分钟触及过上方价格  
- `low` 证明该分钟触及过下方价格  
- OHLC **不能**证明 high/low 真实先后  

因此：

- **禁止**人为重放 `O→H→L→C` 或 `O→L→H→C` 冒充真实路径  
- 使用 **PRICE ENVELOPE + FACTOR26 PRIORITY** 解决同 bar 多条件竞争  

同 bar 若同时「创新高 / 阶梯上破」与「下行触达」：

- 标记 `intrabar_ambiguous = true`  
- `resolved_by = PRIORITY_ENVELOPE`  
- **不是** `TEMPORAL_VIOLATION`

审计字段（不改成交逻辑）：

| 字段 | 含义 |
|------|------|
| `resolution` | `"1m"` |
| `intrabar_ambiguous` | bool |
| `resolution_policy` | `"PRIORITY_ENVELOPE"` |
| `resolved_by` | 歧义时 = 政策名 |
| `intrabar_flags` | new_high / upside_hits / downside_hits |

---

## 5. FACTOR26_EXIT_PRIORITY_1M

与 `eval_multi_tp_bar` **控制流一致**（代码真源；常量见 `strategy/pullback_wave_stop.py`）：

| 序 | reason / 标签 | 说明 |
|----|---------------|------|
| 0a | `hard_open_dump` | research `open_dump` 模式 |
| 0b | `hard_from_cost_gap` | 低开已破硬保护 → immediate（返回 reason 仍为 `hard_from_cost`） |
| 1 | `t1_peak_trail` | overnight_armed 且未 live_ok |
| 2 | `ladder_full_15` | high 上破 15% |
| 3 | `half_gain` / `vol_giveback` | 中赚；同 bar 价高者先触 |
| 4 | `hard_from_cost` | 盘中硬保护 |
| 5 | `ladder_half_10` | 10% 半仓（**优先于**同 bar `peak_pullback_clear`） |
| 6 | `peak_pullback_clear` | ≥10% 后峰值回落清仓 |

单测：`strategy/test_factor26_exit_priority.py`。

---

## 6. Cross-Resolution Harness

模块：`strategy/cross_resolution.py`  
测试：`strategy/test_cross_resolution_harness.py`

```text
synthetic ticks  ──┬──► Realtime mini-engine (last 腿)
                   └──► aggregate_1m ──► BT-1m (eval_multi_tp_bar)
                              └── compare + classify
```

**必须**同一组原始 ticks；禁止分别手造 Paper fixture / BT fixture。

差异类：`MATCH` | `STRATEGY_DIFFERENCE` | `EXECUTION_DIFFERENCE` | `RESOLUTION_DIFFERENCE` | `CAPITAL_DIFFERENCE` | `FEE_DIFFERENCE` | `TEMPORAL_VIOLATION`

`RESOLUTION_DIFFERENCE` **仅当**能证明分钟内顺序/包络丢失（如 `intrabar_ambiguous` 或 tick 先高后低证据）。  
单调无歧义行情若 Realtime≠BT → **必须** `STRATEGY_DIFFERENCE`。

### HWM_BOUNDARY_PARITY

每个 **CLOSED** 1m 边界：在无提前退出导致的合理差异时，`peak_high`（RT）与 `peak_after`（BT）数值应一致。  
允许 BT 无 `peak_high_at`。

### Stop Formula Parity

相同 position / HWM / overnight / T+1 状态 → `working_stop_price` **必须**一致（STRICT STRATEGY）。

---

## 7. Gates

| Gate | 要求 |
|------|------|
| **G1 REALTIME_TEMPORAL_INTEGRITY** | 100% PASS |
| **G2 BT1M_STRATEGY_CONTRACT** | 优先级 + 歧义元数据 + characterization PASS |
| **G3 CROSS_RESOLUTION_CLASSIFICATION** | 差异可分类；TEMPORAL=0；无证据 STRATEGY=0 |
| **G4 FULL_EXIT_ORCHESTRATION** | open_protect→path→last 矩阵 + OP/PATH/LAST；见 [`PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md`](PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md) |

入口：`holdingStocks/run_regression_tests.py`。

---

## 8. AKQuant

- Realtime trailing：**CUSTOM**（非 AQ live StopTrail）  
- AQ：主要用于 BT-1m 撮合/记账  
- 版本目标：**PIN 0.3.22**（基线一致后改 `requirements.txt`）

---

## 9. 验收一句话

不要求 Realtime tick ≡ 1m OHLC。  
要求同一套 Factor26 业务规则，在两种市场观察粒度下保持同一策略定义；允许已解释的分辨率差，禁止时间完整性破坏与无法解释的策略分叉。
