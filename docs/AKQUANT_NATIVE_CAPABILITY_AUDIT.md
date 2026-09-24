# AKQuant Native Capability Audit

> **日期**：2026-09-24  
> **性质**：**AUDIT ONLY** — 不重构、不删除、不改行为  
> **依据**：本机运行时 `akquant==0.3.22`（`E:\Miniconda3\Lib\site-packages\akquant`）；`requirements.txt` 钉 `0.3.21`；旁挂 `../akquant` 为 **0.3.19 源码研读副本，不进 PYTHONPATH**

---

## 1. AKQuant Environment

| 项 | 值 |
|----|-----|
| **AKQuant version (runtime)** | **0.3.22**（`importlib.metadata` + `akquant.__version__`） |
| **Dependency declaration** | `requirements.txt`: `akquant==0.3.21` |
| **install path** | `E:\Miniconda3\Lib\site-packages\akquant\`（含 `akquant.pyd` Rust 扩展） |
| **custom patch/fork in myquan** | **无** vendored 包 |
| **sibling source** | `d:\Akquan\akquant\` = 上游研读树 **0.3.19**（与 runtime 不一致） |
| **API capability source** | **以 site-packages 0.3.22 为准**；官方文档可能超前，须对照本机源码 |
| **Version drift** | **YES**：声明 0.3.21 / 运行 0.3.22 / 旁挂 0.3.19 — 标为环境债 |

生产盯盘、纸面、单测：均走同一 Miniconda site-packages。  
日线回测：`strategy/base.run_akquant_backtest` → `aq.run_backtest`。  
**盯盘纸面：`holdingStocks` 零 `import akquant`（仅经 `akq_math.vec_*`）。**

---

## 2. Capability Matrix（摘要）

| 自研模块 | 职责 | AKQuant 对应 | 等价？ | 分类 | 迁移建议 | 风险 | 优先级 |
|----------|------|--------------|--------|------|----------|------|--------|
| `QuoteHub` / SSE / 新浪 | A 股实时 OHLC | `live` gateway / feed_adapter | **不等价**（现网绕开 AQ 行情） | D/C | 保留 QuoteHub，理由见 §9 | 中 | P2 评估 |
| `holdings.json` positions | 纸面 SoT | `ctx.get_position` / Engine | **双 SoT** | **E** | 明确唯一 SoT；勿机械合并 | **高** | **P0** |
| `trades.jsonl` / ledger | 成交事实+业务元数据 | `on_trade` / order audit | 部分重叠 | E/B | 事实←AQ；业务字段自研 | 高 | P0 |
| `peak_high` / `peak_high_at` | Factor26 HWM | `StopTrail.trail_reference_price` | **语义不等价** | **C** | HWM 可作投影；引擎勿双写 | 高 | P1 |
| `working_stop_price` / `paper_exit_decision` | 多层止盈编排 | `place_trailing_stop`（绝对 offset） | **不等价** | **C** | **CUSTOM / HYBRID** | 高 | P1 |
| `temporal_integrity.py` | 外部行情因果 | Engine UTC/event order | **互补** | C | AQ 管引擎内；adapter 管外部 | 中 | 保留 |
| `is_t1_buy_day` / available | A 股 T+1 纸面 | `t_plus_one` / china market（回测） | 回测有、纸面自研 | B/C | 回测用 AQ；纸面需适配层 | 中 | P1 |
| Capital V2 槽位/日额 | 策略仓位规则 | `RiskConfig.max_position_*` | 部分重叠 | C | 槽位策略自研；基础仓位可 Risk | 中 | P2 |
| `cmd_watch` while/sleep | 交易日调度 | `on_pre_open` / `on_before_trading` / timer | 可替代部分 | B | 仅当迁入 AQ Strategy 生命周期 | 中 | P2 |
| `akq_math` vec_* | 收益/波动 | Rust incremental indicators | 已部分复用 | A | 已对齐；扩大迁移 rolling | 低 | P3 |
| `OpenBreak3Strategy` 日线卖 | 简化止盈 | 同引擎撮合 | 与纸面分叉 | E | 标注简化；勿当生产语义 | 高 | 已文档化 |
| 1m `path_dependent_*` | path fill | `on_bar` 收盘语义 | 不同层 | C | 保留业务 path | 中 | — |
| OCO/Bracket | — | `place_oco` / Bracket | 项目几乎未用 | A | 若做联动单优先 AQ | 低 | P3 |
| WeChat / UI | 通知投影 | order audit | 不同层 | D | 保留 | — | — |

**分类**：A 完整覆盖 · B 薄适配 · C 业务自研+底设 AQ · D 不覆盖 · E 重复且危险

---

## 3. Trailing Stop 深度结论

### 3.1 AKQuant 0.3.22 实际能力

- API：`Strategy.place_trailing_stop` / `place_trailing_stop_limit` → `order_type=StopTrail|StopTrailLimit`，参数 **`trail_offset`（绝对价差）** + 可选 `trail_reference_price`。
- 回测/本地簿：`gateway/local_stop_book.py` 维护 `trail_reference_price = max(ref, high)`（卖），触发价 `ref - trail_offset`；同 bar 内可用 high/low 棘轮（**同 bar 可触发**）。
- **Live broker**：`order_submitter.py` **显式拒绝**  
  `broker_live 暂不支持追踪止损单(trail_offset/StopTrail)`。  
  条件单走客户端 `LocalStopBook`，非柜台原生 trailing。
- **无**百分比 trail、无 Factor26 多层（硬保护 / 半赚 / σ giveback / 阶梯 10%·15% / T+1 哨兵 / overnight_armed）编排。
- **无** `peak_high_at` 审计字段；参考价在订单对象内，非 `holdings.json`。

### 3.2 与我方 Factor26 对比（摘）

| 能力 | 我方 | AKQuant StopTrail |
|------|------|-------------------|
| 参考价 | `peak_high` + `peak_high_at` | `trail_reference_price`（无 At） |
| 卖价公式 | `working_stop_price` 多模式 | 固定 `ref - offset` |
| T+1 / overnight_armed | 有 | 无业务层 |
| 开盘保护 | `overnight_peak` 冻结 | 无 |
| 1m path 触达序 | `path_dependent_pullback_hit` | bar/tick 本地簿 |
| Live | 纸面 JSON | **柜台不支持 StopTrail** |
| Look-ahead 防护 | `temporal_integrity` | 引擎内事件序；**不**保外部 dayHigh |

### 3.3 决策：**CUSTOM（偏 HYBRID 远期）— 否决 FULL AKQUANT**

**选 C 路径：继续自研业务 trailing 编排；远期仅可把「绝对 offset 条件单」作可选执行腿，不能替换 Factor26。**

理由：语义不等价 + live 不支持原生 StopTrail + 无多层止盈。  
Cookbook 自维护 `highest_price` ≠ 删除我方 HWM。

---

## 4. Double Source of Truth（HIGH RISK）

| 域 | SoT A | SoT B | 风险 |
|----|-------|-------|------|
| **持仓** | `holdings.json`（纸面生产） | akquant `get_position`（仅日线回测 Strategy） | **双轨不共享**；纸面≠回测仓 |
| **成交时间/原因** | `trades.jsonl` + heal/推断 | （未接）AQ `on_trade` | 已出现 PATH→09:30 类事故 |
| **卖出规则** | `paper_exit_decision` / 1m path | `OpenBreak3Strategy`+`half_gain` | 已知 gaps（`AKQUANT_DECISION_GAPS.md`） |
| **HWM** | `positions.peak_high` | StopTrail 内部 ref（未用） | 勿并行启用两套 |
| **T+1** | `available` / `is_t1_buy_day` | `run_backtest(t_plus_one=…)` | 两套实现 |
| **策略累计** | `strategy_sim_state.json` | 纸面 qty | **故意独立**（需文档钉死） |

**当前纸面生产唯一持仓事实源建议：继续 `holdings.json`（+ ledger）**，直到存在真正接入 AQ Engine 的 paper/live 路径。  
**回测持仓事实源：akquant Engine。**  
二者不可混称「同一仓」。

---

## 5. High Risk（最易造成真实交易错误）

1. **纸面 mini-engine**（`index.py` apply/settle/heal）与 **AQ 回测引擎** 并行 — 卖出语义已分叉。  
2. **成交事实二次推断**（已部分用 temporal 收口；heal 仍须严守 open_protect-only）。  
3. **若误接 `place_trailing_stop` 当 Factor26** — live 直接报错或语义错。  
4. **requirements 0.3.21 vs runtime 0.3.22** — 文档/CI 与生产不一致。  
5. **Forming 1m / 外部 dayHigh** — AQ 不背锅；已登记技术债。

---

## 6–8. Can Replace / Adapter / Must Stay

**Can Replace Now（低风险，语义已近）**  
- 扩大 `akq_math` / AQ indicators 替代零散 pandas rolling（研究扫描）。  
- 回测侧继续用 `order_target_percent`、`t_plus_one`、费用参数（已在用）。

**Needs Adapter**  
- 若未来 paper 迁入 AQ Strategy：`on_trade` → 投影 `trades.jsonl` 业务字段（`exit_kind` 等）。  
- `RiskConfig` 管 max_position_pct；Capital V2 槽位保留策略层。  
- Lifecycle：`on_pre_open` / timers 替代部分手写 09:15 里程碑（仅当进程变为 AQ live runner）。

**Must Stay Custom**  
- Factor26 多层止盈 / 开盘保护 / stop_noted / Capital V2 日额槽位  
- QuoteHub（东财 SSE+新浪）直至 AQ gateway 证明可替代 A 股延迟行情  
- `temporal_integrity`（外部 API 因果）  
- UI / 微信 / 策略解释元数据  
- `strategy_simulator` 虚拟账本（若产品仍要求与纸面分离）

---

## 9. Trailing Stop Decision

```text
FULL AKQUANT  ✗
HYBRID        △ 仅远期：绝对 offset 执行腿 + 业务层仍算 working_stop
CUSTOM        ✓ 当前唯一正确选择
```

---

## 10–11. Position / Order-Trade SoT 建议

| 环境 | Position SoT | Order/Fill SoT |
|------|--------------|----------------|
| Paper watch（现状） | **holdings.json** | **trades.jsonl** + realized；业务 `exit_kind`/`triggered_at` |
| AQ daily backtest | **Engine position** | **Engine fills** |
| 目标（未实施） | 单环境单 SoT；业务 metadata 单向投影 | `on_trade` 事实不可改写 |

---

## 12. Temporal Integrity 边界

| 保证方 | 内容 |
|--------|------|
| **AKQuant** | 引擎内 bar/tick/order 事件序；UTC 存时间；`on_bar` 在 bar 路径上驱动（用户回调见收盘 bar） |
| **我方必须** | 外部 QuoteHub dayHigh/last_ts；`peak_high_at`；禁止 fill≈open 改写；乱序 quote；forming 上游质量债 |

勿假设 AQ 修复新浪/东财错误时间戳。

---

## 13. Backtest / Paper / Live 矩阵

| | Backtest (AQ日线) | Paper (holdingStocks) | Live broker (AQ) |
|--|-------------------|----------------------|------------------|
| 行情 | AQ DataFeed | **Custom** QuoteHub | AQ gateway（项目未用） |
| Position | **AKQuant** | **Custom** holdings | AKQuant（未接） |
| Order/Fill | **AKQuant** | **Custom** | AKQuant（Trailing **不支持**） |
| Trailing | 简化 half_gain | **Custom** Factor26 | N/A / LocalStopBook |
| Risk | 可选 RiskConfig | Capital V2 自研 | RiskConfig |
| T+1 | AQ 参数 | 自研 available | 视 gateway |
| Timestamp | Engine | 自研+temporal | Engine |
| HWM | 简化 peak | peak_high SoT | trail_ref（若用） |
| Persistence | checkpoint / result | holdings.json | checkpoint |

**不一致 = 已知架构债，非本轮修复范围。**

---

## 14. Deletion Candidates（仅列表，本轮不删）

若未来证明语义等价并完成 parity：

- 部分 heal「价格反推时间」残留（已收口，勿回潮）  
- 重复 pandas rolling（指标层）  
- 日线 `OpenBreak3Strategy` 卖出路径（或降级为「简化研究」专用入口）  
- **不可删**：`paper_exit_decision`、`working_stop_price`、`peak_high*`、QuoteHub、Capital V2、temporal_integrity

---

## 15. Migration Plan（原则：先灭双 SoT / 双引擎）

| 优先级 | 项 |
|--------|-----|
| **P0** | 钉死文档：Paper SoT=`holdings.json`；Backtest SoT=AQ；禁止交叉当事实。对齐 requirements↔runtime 版本。成交事实禁止二次推断（巩固 temporal）。 |
| **P1** | Trailing：**不迁** AQ StopTrail；parity 测试锁定 Factor26。评估 `on_trade` 投影接口（仍可不改引擎）。T+1：文档区分交易所约束 vs 策略。 |
| **P2** | 若引入 AQ live runner：生命周期 hooks、RiskConfig 基础仓位、LocalStopBook 仅作可选绝对 trail 腿。QuoteHub 替代需单独 POC。 |
| **P3** | Indicators 扩大 AQ incremental；OCO/Bracket 若产品需要再接。 |

---

## 16. Tests Required（迁移前必须）

- Factor26 paper vs 候选 AQ trail：**不得**仅 API 名相同  
- Fill timestamp / exit_kind immutability（已有 `test_temporal_integrity`）  
- T+1 available 与 AQ `t_plus_one` 分环境断言  
- Position qty：holdings vs Engine 隔离测试  
- Live：断言 StopTrail 在 broker_live 路径 **拒绝**（防误用）

---

## 最终原则（本审计）

```text
AKQuant = engine / orders / fills / risk primitives / indicators / backtest matching
Our Project = A股策略语义 / Factor26 / Capital V2 / QuoteHub / UI / 通知 / temporal(adapter)

双状态源与双交易引擎 > 代码行数重复
本轮：AUDIT ONLY · NO REFACTOR · NO DELETE · NO BEHAVIOR CHANGE
```
