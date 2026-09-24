# Paper ↔ Backtest Semantic Parity Audit

> **日期**：2026-09-24  
> **性质**：**AUDIT ONLY** — 不重构、不改 Factor26 trailing、不接 AKQuant live、不改 Paper engine  
> **原则**：允许执行引擎不同；**不允许**同一策略在两环境拥有不同业务决策语义  
> **对照**：[`AKQUANT_NATIVE_CAPABILITY_AUDIT.md`](AKQUANT_NATIVE_CAPABILITY_AUDIT.md) · [`AKQUANT_DECISION_GAPS.md`](AKQUANT_DECISION_GAPS.md) · [`FACTOR26_CALL_PATHS.md`](FACTOR26_CALL_PATHS.md)

---

## 0. 路径定义（本审计用语）

| 标签 | 入口 | 引擎 |
|------|------|------|
| **Paper** | `holdingStocks/index.py` → `paper_exit_decision` + 1m path | holdingStocks mini-engine + JSON 账本 |
| **BT-1m** | `simulate_factor26_day_1m` / `replay_factor26_1m` / `path_dependent_pullback_hit` | 自研 1m 模拟（**调用** `eval_multi_tp_bar`） |
| **BT-Daily** | `OpenBreak3Strategy.on_bar` + `half_gain_stop_price` | **AKQuant** `run_backtest` |
| **Decision** | `Factor26Decision.decide` | 日线/快照编排（无 path 则不卖） |

**可比性声明**：若用户说「回测」，必须指明 BT-1m 还是 BT-Daily。二者与 Paper 的距离完全不同。

---

## 1. AKQuant Version Drift

| 项 | 值 |
|----|-----|
| Runtime（本机） | **0.3.22** |
| `requirements.txt` | **akquant==0.3.21** |
| Lock file | **无**（无 poetry.lock / uv.lock / Pipfile.lock） |
| CI workflow | **无** `.github/workflows` — 本地/手工跑测 |
| 旁挂源码 | `../akquant` = **0.3.19**（不进 path） |
| PyPI | 0.3.21（2026-07-25）、0.3.22（2026-07-26）相邻发布 |

**与本项目相关的 API 差异（基于本机 0.3.22 源码能力，非完整 changelog）**：  
未做 0.3.21 安装对照；公开能力面上本仓库实际使用的 `run_backtest` / `Strategy` / `order_target_percent` / `t_plus_one` / `vec_*` 在 0.3.21–0.3.22 属稳定表面。**风险**：干净环境 `pip install -r requirements.txt` 会装 **0.3.21**，与当前跑回测的 **0.3.22** 不一致 → 历史结果不可复现。

**建议（本轮不执行）**：**PIN_0.3.22**（与 runtime 对齐 + 在 requirements 注明校验和/日期）。  
仅当发现 0.3.22 引入与本仓相关回归时再考虑 `ROLLBACK_0.3.21`（须全员 runtime 降级）。

| 风险 | 等级 |
|------|------|
| 部署/新机装成 0.3.21 | **P1 reproducibility** |
| 无 lock / 无 CI 钉版本 | **P1** |
| 旁挂 0.3.19 误导读码 | P2 |

---

## 2. Strategy Semantic Matrix

图例：`SAME` 公式与状态转移一致 · `EQUIVALENT` 可接受等价 · `DIFFERENT` 策略语义不同 · `MISSING` 一侧没有 · `UNKNOWN` 未证明

比较对象默认：**Paper vs BT-Daily**（生产「回测」常走日线）及 **Paper vs BT-1m**（括号内）。

| 语义项 | Paper vs BT-Daily | Paper vs BT-1m |
|--------|-------------------|----------------|
| Buy Signal（开盘阈值） | SAME（`entry_trigger_price`） | SAME |
| Buy Price | EQUIVALENT（触达后引擎 fill vs 纸面买点/现价规则） | EQUIVALENT |
| Buy Time | DIFFERENT（日线 bar 时点 vs 1m/竞价） | EQUIVALENT≈ |
| Position Size | **DIFFERENT**（Capital V2 vs `initial_cash`/固定股） | **DIFFERENT**（默认 shares_in） |
| Available Qty | DIFFERENT（自研 available） | EQUIVALENT（`can_sell`） |
| T+1 | EQUIVALENT（aq `t_plus_one` vs 策略 bought_today） | SAME 内核 / Paper 多 stop_noted 门禁 |
| Cost Basis | EQUIVALENT | EQUIVALENT |
| HWM | **DIFFERENT**（无 peak_high_at；日线同 bar high） | EQUIVALENT 抬升 / Paper 多 at+冻结 |
| HWM Timestamp | **MISSING**（Daily） | **MISSING**（BT-1m 无 at） |
| Trailing（多层） | **DIFFERENT**（仅 half_gain） | EQUIVALENT 内核 / 编排 DIFFERENT |
| Hard Stop | EQUIVALENT 公式 | SAME（`eval_multi_tp_bar`） |
| Profit Stop / Ladder | **MISSING**（Daily） | SAME 内核 |
| Overnight Rule | **MISSING**（Daily） | EQUIVALENT / Paper 多 freeze |
| Open Protect | **MISSING**（Daily） | **DIFFERENT**（无 paper 三层优先） |
| Gap Handling | DIFFERENT（日线同 bar） | EQUIVALENT |
| Partial Exit（10% 半仓） | **MISSING**（Daily） | SAME 内核 / Paper 有 tp_stage 账本 |
| Exit Decision 编排 | **DIFFERENT** | **DIFFERENT**（无 open→path→last） |
| Exit Price | DIFFERENT | EQUIVALENT≈（path fill） |
| Exit Time | DIFFERENT（日线） | DIFFERENT（无 5s last；竞价 K 过滤不一致） |
| Exit Kind | **DIFFERENT** / MISSING 细类 | EQUIVALENT 子集 |
| Capital Update | DIFFERENT | DIFFERENT |
| Position Close | EQUIVALENT 动作 | EQUIVALENT |
| Re-entry | DIFFERENT（当日禁买等） | DIFFERENT |
| Persistence | DIFFERENT（JSON vs result） | DIFFERENT |

---

## 3. Factor26 Canonical Semantics（抽取 · 非两边分别描述）

### 3.1 规则真源（单 bar）

**Canonical 内核**：`strategy/pullback_wave_stop.py::eval_multi_tp_bar`

**输入（概念）**：`cost`, `peak_before`, `bar_open/high/low`, `shares`, `tp_stage`, `can_sell`, `overnight_armed`, `day_open`, `vol20_daily`, `hard_pct`, …

**输出**：`action{kind, reason, fill_px, shares}` | `None`；`peak_after`；`tp_marked` / `noted_px`（T+1）

**优先级（锁定）**：  
硬缺口开盘 → T1 峰值回落（armed 且未过 3%）→ 阶梯 15% → 中赚 mid_gain → 硬保护 → 10% 半仓 / ≥10% 后峰值回落 2% 全清。

### 3.2 Canonical 盯盘/执行编排（Paper 生产语义）

**函数**：`paper_exit_decision`（可卖日）

1. **Open Protect**：`open <= overnight_open_protect_px(冻结隔夜峰值)` → fill=今开，`exit_kind=open_protect`  
2. **Path**：1m `path_dependent_pullback_hit`（=`eval_multi_tp_bar` 序列，跳过 09:30 前）→ `exit_kind=path`  
3. **Last**：`last <= working_stop_price(...)` → fill=工作卖价，`exit_kind=last`

辅：`peak_high`+`peak_high_at` 因果；`stop_noted`；T+1 只记不卖；Capital V2。

### 3.3 谁实现了 Canonical？

| 层 | Paper | BT-1m | BT-Daily |
|----|-------|-------|----------|
| `eval_multi_tp_bar` | ✅ via path | ✅ | ❌ |
| `paper_exit_decision` 三层 | ✅ | ❌ | ❌ |
| `half_gain` only | 子集 | 子集 | ✅ **仅此** |

**结论**：唯一完整实现「生产决策语义」的是 **Paper**。BT-1m 实现 **内核** 但非完整编排。BT-Daily **不是** Factor26 生产语义。

---

## 4. Strategy Gaps（精确）

### G-S1 Paper vs BT-Daily（最高）

| 维度 | Paper | BT-Daily | 影响 |
|------|-------|----------|------|
| 输入 | 1m+tick、冻结 overnight_peak、HWM+at | 日线 OHLC、实例 peak_high | 同日序列决策时刻不同 |
| 公式 | 全优先级 + open_protect + last | **仅** `half_gain_stop_price(peak,cost)` | stop 价与是否半仓不同 |
| 状态 | tp_stage、stop_noted、armed | 无 | 次日行为不同 |
| 时间 | 09:30 竞价核 / 分钟触达 | **BAR_CLOSE 语义日线**（同 bar high 抬峰再 low 判卖） | 卖出日/时不同 |
| 输出 | open_protect/path/last + kind | 简化 sell | exit_kind 不可比 |

**典型分叉**：中赚走 vol_giveback、或 10% 半仓、或开盘保护 — Daily **全部不会**按生产规则触发。

### G-S2 Paper vs BT-1m

| 维度 | 差异 | 影响 |
|------|------|------|
| 编排 | 无独立 open_protect 优先于 path；无 5s last 腿 | 同行情可能 path 价 ≠ paper 开盘保护价 |
| 竞价 K | `simulate_*` **可能不跳过** 09:30 前；`path_dependent_*` 跳过 | 触及时刻/是否触发分叉 |
| 峰值冻结 | 无 9:15 `freeze_overnight_peak` | 开盘保护峰值可能含「今日」污染（若误传） |
| stop_noted | 无 persist/heal 门禁 | 武装条件与 Paper 不完全同 |
| HWM at | 无 | 审计维度缺失（非必改卖价） |
| Capital | 固定股数 | 仓位不可比 |

### G-S3 Factor26Decision vs Paper

无 `meta.path_hit_stop` → **不卖**；无 open_protect 优先序。≠ Paper。

### G-S4 Buy

阈值公式 **SAME**；入槽/资金/日额 **DIFFERENT**（策略仓位层）。

---

## 5. Execution Gaps（允许存在）

| 项 | 分类 | 说明 |
|----|------|------|
| AQ 滑点/佣金/印花 | EXECUTION / FEE | Paper 按触发价记账，**未**套 `strategy.costs` 引擎 |
| 日线 fill_policy `CurrentClose` | EXECUTION | 与 1m 触达价模型不同 |
| Lot / initial_cash 10万 vs 纸面 30万 | CAPITAL | 收益曲线不可比 |
| Bar 分辨率 | EXECUTION | 日线 vs 1m vs 5s |

**禁止**把 stop_price / exit_kind / T+1 / HWM 差异说成 execution difference。

---

## 6. HWM Parity

| | Paper | BT-1m | BT-Daily |
|--|-------|-------|----------|
| 定义 | `raise_position_peak_high` 至 t | path 内 running_high | 同 bar `max(peak, high, cost)` |
| `peak_high_at` | ✅ temporal | ❌ | ❌ |
| 禁完整日K提前 | ✅（用 as-of quote/1m） | ✅（按 bar 序） | ⚠️ **同日 high 参与该 bar 决策**（日线固有） |
| Decision timing | tick/1m close 路径 | 1m bar 序 | **必须标为 BAR 内 OHLC 启发式，非点时点** |

**HWM parity：Paper ↔ BT-1m = PARTIAL；Paper ↔ BT-Daily = FAIL（策略语义）。**

---

## 7. T+1 Parity

| | Paper | BT-1m | BT-Daily |
|--|-------|-------|----------|
| 不可卖 | `available` / `is_t1_buy_day`；只记 `stop_noted` | `can_sell=False` → noted | aq `t_plus_one` + `bought_today` skip sell |
| 次日武装 | persist/heal + overnight_armed | `resolve_t1_overnight_note` / armed 入参 | **无** t1_trail 业务层 |

**T+1 parity：交易所约束 ≈ EQUIVALENT；业务哨兵/武装 Paper 最完整，Daily FAIL。**

---

## 8. Capital Parity — **FAIL**

| | Paper Capital V2 | AQ Backtest |
|--|------------------|-------------|
| 本金 | 默认 30 万纸面 | 默认常 10 万 |
| 规则 | ≤5 票、日新≤2、单票≤20%、禁加仓、禁负现金 | 无对等槽位规则 |
| 股数 | `target_position_notional` / lot 100 | 策略 `order_target_percent` 或 1m 固定 shares |

信号相同也不代表仓位/收益可比。

---

## 9. Fee Parity — **FAIL（Paper 侧近乎无引擎费）**

| | Backtest (`strategy/costs` → `run_backtest`) | Paper |
|--|-----------------------------------------------|-------|
| 佣金+杂费 | 万 0.86+0.10 并入 commission | 成交按触发价，**未扣**同口径引擎费 |
| 印花 | 卖万 5 | 未扣 |
| 滑点 | 0.1% 参数 | README「成本内」≠ AQ 双边滑点 |

**FEE MODEL PARITY: FAIL**（若要比收益，须先统一费用或明确「Paper 净值不含 AQ 费」）。

---

## 10. Trading-time Parity

| | Paper | BT-1m | BT-Daily |
|--|-------|-------|----------|
| 竞价 / 09:30 | 里程碑 + open_protect 09:30 | 依赖 simulate 是否滤 K | 无 |
| 午休 | market_phase | bar 缺口 | 无盘中 |
| Decision timing | 5s + 1m | 1m close 序 | **日线：同 bar high/low，非纯 OPEN/CLOSE 二选一** |

日线策略若声称与 Paper 等价 → **无效**；须标注 **SIMPLIFIED RESEARCH**。

---

## 11. Golden Scenarios — 当前状态

| ID | 场景 | Canonical/Paper | BT-1m | BT-Daily | 对拍测试 |
|----|------|-----------------|-------|----------|----------|
| A | 上涨→回落 | 有单元 | 有单元 | 仅 half_gain | **无成对** |
| B | 跨日→次回落 | Paper+stop_noted | 部分 | 弱 | 无成对 |
| C | 高开 | open_protect 冻结 | 弱 | 无 | 无 |
| D | 低开 | 硬缺口 | 有 | 部分 | 无成对 |
| E | 盘中新高→回落 | HWM+working | 有 | 同 bar | 无成对 |
| F | T+1 不可卖 | 有 | can_sell | aq T+1 | 无成对 |
| G | 隔日可卖 | 有 | 有 | 有 | 无成对 |
| H | Gap 穿 stop | 有 | 有 | 弱 | 无成对 |
| I | 创新高后 restart | peak 持久化 | N/A | N/A | Paper only |
| J | 乱序行情 | temporal | N/A | N/A | Paper only |
| K | future quote | temporal | N/A | N/A | Paper only |
| L | fill≈open 但 PATH 09:58 | temporal PASS | open_auction 限首根 | N/A | Paper 有；无跨环境 |

**Golden harness PASS/FAIL：全部未建端到端 Paper↔BT 对拍 → 记 FAIL（未测）**。  
现有：`test_temporal_integrity`、`test_exit_fixture_parity`（Paper↔ExitEngine）、`test_pullback_wave_path`（内核）— **不能**替代 A–L 跨环境黄金集。

---

## 12. Gap Register（P0–P3）

| ID | 描述 | 级 | 类 |
|----|------|----|-----|
| GAP-01 | BT-Daily 非 Factor26 全语义（half_gain only） | **P0** | STRATEGY |
| GAP-02 | 用 BT-Daily 收益/交易日对比 Paper 生产 | **P0** | STRATEGY/COMPARABILITY |
| GAP-03 | Paper 三层编排 vs BT-1m 无 open_protect/last | **P1** | STRATEGY |
| GAP-04 | simulate 竞价 K 过滤 vs path_dependent 不一致 | **P1** | STRATEGY/TIME |
| GAP-05 | Capital V2 vs AQ/固定股 | **P1** | CAPITAL |
| GAP-06 | Fee 模型 Paper≠AQ | **P2** | FEE/EXEC |
| GAP-07 | HWM at 仅 Paper | **P2** | AUDIT |
| GAP-08 | akquant 版本漂移 0.3.21/0.3.22 | **P1** | REPRO |
| GAP-09 | Factor26Decision 无 path 不卖 | **P1** | STRATEGY |
| GAP-10 | 日志/UI/微信 | **P3** | META |

**本轮不修，只登记。**

---

## 13. 适合抽成 Shared Pure Function（候选 · 不实施）

```text
eval_multi_tp_bar          ✅ 已是
working_stop_price         ✅ 已是
overnight_open_protect_px  ✅ 已是
raise_position_peak_high   ✅ 已是
entry_trigger_price        ✅ 已是

候选下一层（概念）：
strategy_exit_decision(state) → DecisionResult
  = open_protect? | path_action? | last_hit?
  无 IO / 无 JSON / 无 QuoteHub / 无 wall-clock
```

Paper / BT-1m adapter 只负责填 `MarketState`/`PositionState` 与执行。

---

## 14. 必须留在 Adapter / Engine

| 层 | 职责 |
|----|------|
| AKQuant Engine | 日线事件、撮合、费用、T+1 交易所参数、仓位记账 |
| holdingStocks | QuoteHub、JSON 持久化、Capital V2、5s 扫描、微信/UI |
| temporal_integrity | **外部**行情因果（引擎不保证） |
| BT-Daily Strategy | 若保留：必须标 **SIMPLIFIED**，禁止称 Factor26 生产语义 |

---

## 15. 最小迁移方案（仍 AUDIT 建议 · 不实施）

1. **文档钉死**：生产语义 = Paper 编排 + `eval_multi_tp_bar`；BT-Daily = 简化研究。  
2. **PIN_0.3.22**（另轮执行）。  
3. **可比回测默认改 BT-1m**（`replay_factor26_1m`），并对齐竞价 K 过滤与 open_protect 优先（抽 shared decision）。  
4. **Golden A–L**：同一 fixture → Canonical / Paper adapter / BT-1m adapter 比 `action/stop/exit_kind/decision_at`。  
5. **收益对比前**统一 Capital+Fee 或声明「不可比净值」。  
6. **禁止**为统一而动已验收 Paper temporal / trailing。

目标形态：

```text
        strategy_exit_decision (pure)
              ↙            ↘
     BT-1m adapter      Paper adapter
     (bars → state)     (quotes → state)
              ↓                ↓
        AQ or sim fill     JSON fill
```

---

## 最终判定

### STRATEGY SEMANTIC PARITY: **FAIL**

（相对「同一 Factor26 生产语义」：BT-Daily 明确失败；BT-1m 部分内核对齐但编排未对齐；无黄金对拍证明 PASS。）

### BACKTEST ↔ PAPER COMPARABILITY: **PARTIAL**

| 配对 | 判定 |
|------|------|
| Paper ↔ BT-1m（内核） | **PARTIAL**（可朝 PASS 治理） |
| Paper ↔ BT-Daily | **FAIL**（不可比作生产策略验证） |
| 收益曲线任意配对 | **FAIL** 直至 Capital+Fee 对齐或降级为「信号对照」 |

---

*本文件仅审计登记；不改变已验收的 Paper temporal integrity 与 Factor26 trailing。*
