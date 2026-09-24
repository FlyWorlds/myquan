# Realtime × 1m Architecture & Acceptance Redefinition

> **日期**：2026-09-24  
> **性质**：架构重定义 + 审计 + **测试设计**（不重构、不改 Factor26 trailing、不接 AQ live）  
> **修正**：Parity ≠ Paper tick ≡ BT 1m 事件；共享的是 **Strategy Semantics**，不共享 **Market Resolution**  
> **前序**：[`PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md`](PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md) 结论保留；本文件重定目标与验收

---

## 0. 最终业务目标（钉死）

| 环境 | 市场观测 | 驱动 |
|------|----------|------|
| **生产 Paper / 盯盘** | **REALTIME** quote/trade | 每个有效实时价 → HWM → Factor26 → `paper_exit_decision` → 纸面成交 |
| **正式验证回测 BT-1m** | **1m OHLC** | bar → 1m adapter → 共享策略语义 →（可选）AQ 撮合 |
| **BT-Daily** | 日线 | **RESEARCH ONLY**，不证明生产语义 |

**禁止**：

- 为 parity 把 Paper **降级**成等 1m close  
- 在 1m OHLC 里 **伪造**不存在的真实 tick 顺序  
- 用 AQ `place_trailing_stop` 接管实时 trailing（0.3.22 live 不支持且语义不等价）

---

## 1. 当前 Realtime Event Flow

```text
QuoteHub (SSE/新浪)  last / dayHigh / last_ts
        ↓
temporal_integrity
  quote_at ≤ decision_at
  STALE_QUOTE_REJECTED / FUTURE_DATA_VIOLATION
        ↓
raise_position_peak_high + stamp peak_high + peak_high_at
  （dayHigh ≠ HWM；HWM = 持仓生命周期有效观测）
        ↓
working_stop_price(peak_high, …)
        ↓
[可选] 1m path_dependent 补迟到/排序
        ↓
paper_exit_decision
  open_protect → path → last≤working_stop
        ↓
apply_exit_fill / trades.jsonl
  triggered_at / exit_kind immutable
```

**粒度**：秒级快刷（≥0.4s）+ 扫描；**不等** 1m bar close 才更新 HWM。

---

## 2. 当前 BT-1m Event Flow

```text
1m OHLC bars (sorted by ts)
        ↓
path_dependent_pullback_hit / simulate_factor26_day_1m
  （跳过 09:30 前竞价 K：path_dependent 有；simulate 可能不一致）
        ↓
每根 bar → eval_multi_tp_bar(open, high, low, …)
        ↓
action / peak_after / fill_px
        ↓
（池回测）replay 记账；非 holdings.json Paper 账本
```

**无**真实 tick；**无** `peak_high_at`；**无**完整 `paper_exit_decision` 三层。

---

## 3. 真正共享的 Factor26 代码

| 符号 | 文件 | 角色 |
|------|------|------|
| `eval_multi_tp_bar` | `pullback_wave_stop.py` | 单 bar 卖出优先级真源 |
| `working_stop_price` | 同上 | 未触达工作卖价 |
| `half_gain_stop_price` / mid_gain / vol / ladder / hard / t1_trail | 同上 | 公式积木 |
| `overnight_open_protect_px` / `overnight_peak_px` | 同上 | 隔夜保护价 |
| `raise_position_peak_high` | 同上 | HWM 只升不降（数值） |
| `entry_trigger_price` | `open_break.py` | 买点 |
| `path_dependent_pullback_hit` | `pullback_wave_stop.py` | 1m 序列调用内核（Paper path 腿也用） |

---

## 4. 重复 / 分叉的「策略编排」（非引擎）

| Paper 独有 | BT-1m 弱/缺 | 风险 |
|------------|-------------|------|
| `paper_exit_decision` 三层 | 无独立 open→path→last | 编排差 |
| `peak_high_at` + temporal | 无 | 审计差 |
| `freeze_overnight_peak` | 无 | 开盘保护差 |
| `persist_stop_noted` / heal | 日末 note 简化 | 武装差 |
| Capital V2 | 固定 shares | 仓位差 |
| 5s `last` 腿 | 无 | **分辨率**导致的退出时刻差 |

日线 `OpenBreak3Strategy`+`half_gain`：**不算**共享 Factor26 生产语义。

---

## 5. CURRENT_INTRABAR_POLICY（正式登记 · 本轮不改）

### 名称

**`PRIORITY_ENVELOPE`（优先级包络，非有序路径）**

### 实际行为（`eval_multi_tp_bar`）

**不是** `O→H→L→C` 或 `O→L→H→C` 的 tick 重放。

对单根 1m bar：

1. 同时读取 `open` / `high` / `low`（close 几乎不参与触达判定）  
2. **上涨类条件**用 `high`（如 ladder 15%/10%、`live_ok` 用 `max(high, day_open, open)`、`peak_after=max(peak,high)`）  
3. **下跌类条件**用 `low`（t1_trail / mid_gain / hard / peak_pullback）  
4. 冲突时按 **Factor26 规则优先级表** 决出唯一 `action`（硬缺口 → T1 trail → ladder15 → mid_gain → hard → ladder10 半仓 → peak_pullback），**不是**按未知的真实先后时间  

### 同 bar 新高 + 回落

- `peak_gain` / `live_ok` 可计入本 bar `high`（`peak_incl`）  
- `mid_gain_first_hit` 的峰值参数用的是 **bar 初 `peak_before`**（未必然用本 bar 新高重算 trail）  
→ 同 bar「先创新高再砸穿」与「先砸穿再冲高」在 OHLC 中 **不可区分**；当前用优先级包络 **确定性** 给出一个结果，但 **不等于** 真实 tick path。

### 政策建议（本轮只报告）

| 选项 | 说明 | 建议 |
|------|------|------|
| CONSERVATIVE | 同 bar 有歧义时偏向更差成交 | 可选未来强化 |
| OPTIMISTIC | 偏向更好 | 不推荐默认 |
| DETERMINISTIC_PATH | 强制 O-H-L-C 等 | **虚假精确**，不推荐冒充真实 |
| SKIP_AMBIGUOUS | 歧义 bar 不交易 | 改变样本量 |
| **OTHER = 保持 PRIORITY_ENVELOPE** | 现状：优先级表 | **推荐维持并文档化** |

**未来所有 BT-1m 必须统一声明：`CURRENT_INTRABAR_POLICY = PRIORITY_ENVELOPE`。**

---

## 6. INTRABAR_AMBIGUITY 场景

同一根 1m 内同时成立（OHLC 无法证明先后）时标歧义：

| 场景 | 为何歧义 |
|------|----------|
| `high` 创新高抬 HWM/trail **且** `low` 刺穿 trail/hard | 不知先冲高还是先刺穿 |
| `high≥ladder10/15` **且** `low≤` 下行止盈 | 不知先止盈上档还是先止损 |
| open 已破硬保护 **且** 盘中又冲高 | 生产 hard_gap immediate 已优先开盘；与「先拉升」不可并存于 OHLC 证明 |
| Paper 在 :20 用 last 卖出，BT 到 :00 bar 才用包络判定 | **RESOLUTION**，不是策略公式分叉 |

标记：`INTRABAR_AMBIGUITY` — 回测结果只对 **PRIORITY_ENVELOPE** 负责，不对真实 tick 负责。

---

## 7–9. Golden Tests 设计（未实施 · 规格）

### A. Realtime Engine Tests（tick/quote）

| ID | 内容 |
|----|------|
| R1 | 实时创新高 → HWM+at 立即升 |
| R2 | 回落 HWM 不降、stop 不降 |
| R3 | last≤working_stop → LAST 卖 |
| R4 | T+1 只记不卖 |
| R5 | overnight + open_protect |
| R6 | PATH 1m 补触达 |
| R7 | 乱序 STALE |
| R8 | 未来 FUTURE_DATA |
| R9 | restart 保留 peak_high |
| R10 | fill≈open 仍 PATH@真实时刻 |

（多数已有 `test_temporal_integrity` / HWM / stop_noted；缺口：系统化 R1–R3 事件序列夹具）

### B. BT-1m Tests（OHLC）

| ID | 内容 |
|----|------|
| B1 | HWM carry 跨 bar |
| B2 | Factor26 优先级表 |
| B3 | T+1 can_sell |
| B4 | overnight_armed |
| B5 | 半仓 10% / 15% / peak_pullback |
| B6 | **显式 INTRABAR_AMBIGUITY 夹具** → 断言符合 PRIORITY_ENVELOPE |
| B7 | Gap / hard_from_cost |
| B8 | 竞价 K 过滤策略（与 path_dependent 对齐） |

### C. Cross-Resolution Tests

```text
synthetic ticks (已知序)
    → Paper realtime adapter
    → aggregate OHLC 1m
    → BT-1m adapter
比较 HWM / stop / exit / exit_kind
自动分类：STRATEGY | EXECUTION | RESOLUTION | CAPITAL | FEE | TEMPORAL
```

**仅当差异可证明为 RESOLUTION LOSS（丢失 tick 序）时允许 Paper≠BT。**

---

## 10. 差异六类登记（更新）

| 类 | 含义 | 示例 | 允许？ |
|----|------|------|--------|
| STRATEGY_DIFFERENCE | 公式/状态机/优先级不同 | Daily half_gain vs 全 Factor26 | **否**（生产验证） |
| EXECUTION_DIFFERENCE | 撮合/滑点模型 | AQ fill_policy | 是 |
| **RESOLUTION_DIFFERENCE** | realtime vs 1m 包络 | 分钟内先卖、BT bar 末才知 | **是**（须证明） |
| CAPITAL_DIFFERENCE | Capital V2 vs 固定股 | 仓位 | 是（净值不可比） |
| FEE_DIFFERENCE | Paper 未套 AQ 费 | 收益 | 是 |
| TEMPORAL_VIOLATION | 未来/乱序/改写时间 | 已禁 | **否** |

---

## 11–13. Shared Core / Adapters（候选边界）

**未来 Shared Strategy Core（pure）**  
`eval_multi_tp_bar`、`working_stop_price`、overnight/HWM 数值语义、exit priority、exit_kind 枚举、T+1/overnight 状态转移（无 IO）。

**Realtime Adapter（必须留下）**  
QuoteHub、temporal_integrity、`peak_high_at`、5s last 腿、`paper_exit_decision` 编排、JSON/Capital V2、微信/UI。

**1m Adapter（必须留下）**  
OHLC→`eval_multi_tp_bar` 喂入、`PRIORITY_ENVELOPE` 声明、竞价 K 过滤、歧义标记、（可选）AQ 撮合与费用。

---

## 14. 最小重构计划（仍不本轮实施）

| 步 | 内容 |
|----|------|
| 0 | 文档钉死：Realtime first；BT-1m = 正式验证；Daily = research |
| 1 | 基线测试 → **PIN akquant 0.3.22**（另轮） |
| 2 | 规格化 `CURRENT_INTRABAR_POLICY` 单测（锁定现状，不改公式） |
| 3 | Cross-resolution 夹具 + 六类自动分类 |
| 4 | 可选：抽 `strategy_exit_decision` pure（Realtime/1m 共用优先级意图） |
| 5 | **永不**：Paper 降 1m；AQ live trailing；为对齐牺牲 temporal |

---

## 目标结构图

```text
           Shared Factor26 Semantics
                      │
          ┌───────────┴───────────┐
          │                       │
   REALTIME ADAPTER          1M BAR ADAPTER
   QuoteHub + temporal       PRIORITY_ENVELOPE
          │                       │
   Paper / Monitor            AKQuant / 1m sim
```

---

## 最终判定（按新标准）

### REALTIME TEMPORAL INTEGRITY: **PASS**

（已验收：`temporal_integrity`、原子 HWM、PATH 不改写、禁 fill≈open；实时路径不依赖 1m close。）

### BT-1M STRATEGY SEMANTICS: **PARTIAL → 定向 PASS 条件**

- **内核**（`eval_multi_tp_bar`）：与 Paper path 腿共享 → 可作为共享语义基础  
- **编排 / HWM at / open_protect / last / 竞价 K**：仍有 STRATEGY 或 RESOLUTION 缺口  
- **Intrabar**：已确定性，但须正式承认 `PRIORITY_ENVELOPE`，不得声称 tick 忠实  
- 在完成 B6 锁定 + 编排对齐计划前：**不记满 PASS**

### CROSS-RESOLUTION COMPARABILITY: **PARTIAL**

- 允许 RESOLUTION_DIFFERENCE  
- **已落地** `strategy/cross_resolution.py` + Gate3 分类（见 [`TRADING_ENGINE_CONTRACT.md`](TRADING_ENGINE_CONTRACT.md)）  
- 对 BT-Daily：**FAIL**（研究用途）  
- 全量 path/open_protect / Capital / Fee：仍 PARTIAL

---

### 一句话

**生产 = 真成交驱动；回测 = 1m 包络策略语义；共享公式与状态机，不共享市场分辨率；永远不要用 1m 假装拥有 tick 顺序。**
