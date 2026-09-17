# Decision 对齐报告（Phase 1D）

> 日期：2026-09-17  
> Harness：`strategy/test_decision_parity.py`  
> 对照：`holdingStocks.index.paper_exit_decision` vs `Strategy16Decision`（Factor26Decision）  
> **未修改任何交易规则**；差异如实记录

---

## 1. 方法

同一组合成 `ParityCase` 输入分别跑：

| 路径 | 入口 |
|------|------|
| 旧盯盘 | `paper_exit_decision(...)` |
| DecisionEngine | `Strategy16Decision(FACTOR_BINDINGS).decide(MarketContext)` |

映射：

| paper | engine | 归一 |
|-------|--------|------|
| `hit=True` | `action=sell` | SELL |
| `hit_show` 且不成交 | `hold`（含 T+1） | HOLD |
| 其余不成交 | `hold` | HOLD |

引擎侧将 `path_hit` 写入 `meta.path_hit_stop`（与 Factor26Decision 约定一致）。

---

## 2. 汇总（合成 6 案）

| 指标 | 值 |
|------|----|
| 总决策数 | 6 |
| 动作一致 | **4**（66.7%） |
| 动作不一致 | **2**（均为事先标注的结构分叉） |
| SELL 一致 | 1 |
| SELL 不一致 | 2 |
| HOLD 一致 | 3 |
| 成交价可比且一致 | 1 / 1（`path_hit_sell`） |
| 引擎 SELL 的 factor_id | `factor26` |

---

## 3. 逐案

| Case | Paper | Engine | 一致？ | 说明 |
|------|-------|--------|--------|------|
| `hold_mid_range` | HOLD | HOLD | ✅ | 中性持有 |
| `path_hit_sell` | SELL (path, fill=104) | SELL (factor26, price=104) | ✅ | path 触达时动作与价格对齐 |
| `t1_path_show_only` | HOLD_SHOW (t1) | HOLD (T+1 禁卖) | ✅* | 均不成交；paper 多「展示」语义 |
| `open_protect_gap_down` | **SELL (open_protect)** | **HOLD** | ❌ 结构 | 引擎无开盘保护分支；需 path 才卖 |
| `heimiao_gap_up_no_open_protect` | HOLD | HOLD | ✅ | 黑猫高开峰值规则：两边都不卖 |
| `last_vs_working_stop_no_path` | **SELL (last)** | **HOLD** | ❌ 结构 | paper 允许现价破 working_stop；引擎无 path 不卖 |

\* `HOLD_SHOW` 与 `HOLD` 在「是否成交」上视为一致。

---

## 4. 发现的行为差异（不得为「测过」而改规则）

### 4.1 开盘保护（P0 结构差）

- **Paper**：`overnight_open_protect_px` + 今开 ≤ 保护价 → `kind=open_protect` 成交  
- **Engine**：不计算开盘保护；无 `path_hit_stop` → 一律 HOLD  
- **含义**：同一缺口低开，盯盘可卖、DecisionEngine 不卖

### 4.2 无 path 的现价破卖价（P0 结构差）

- **Paper**：`last <= working_stop` → `kind=last` 可成交  
- **Engine**：明确拒绝「全日/快照 low 冒充 path」；无 `path_hit_stop` 不卖  
- **含义**：5s 快照破卖价只在盯盘生效

### 4.3 价格语义（path 对齐时）

- path 触达时：paper `fill_px` 与 engine `Decision.price`（来自 levels.stop）在本案中均为 104.0  
- **注意**：engine 卖出价取 `levels.stop`，不一定永远等于 path `fill_px`；需更多 1m 真值样本再统计

### 4.4 reason / factor_id

- Paper：`open_protect` / `path` / `last` / `t1`  
- Engine：中文原因 + `factor_id=factor26`（卖）  
- **不可直接字符串相等**；对齐应以 action +（可选）fill 价为主

### 4.5 BUY

- 本组 case 均为有仓 EXIT 场景；**BUY 一致率本次未测**  
- 买入分叉另案：engine 可用日线 high≥买点；盯盘用 `path_dependent_buy_hit` / 开盘阈值

---

## 5. Factor 26 相关差异（对照 CALL_PATHS）

| 能力 | Paper 编排 | Engine |
|------|------------|--------|
| `eval_multi_tp_bar` 结果 | 经 `_resolve_hit_stop_path_dependent` → `path_hit` 入参 | 经 `meta.path_hit_stop` |
| 开盘保护 | ✅ | ❌ |
| last vs working_stop | ✅ | ❌ |
| T+1 | 展示不成交 | HOLD |

→ **不是「两套因子公式」**，而是 **编排层能力不等价**。统一 DecisionEngine 前必须把开盘保护与 path 触达都喂进同一入口，否则强行切换会改变盯盘成交。

---

## 6. 下一阶段建议（等待人工确认 · 不自动执行）

1. **不要**删除 `paper_exit_decision`  
2. Feature flag + shadow compare：同一 tick 双跑，落盘 diff  
3. 扩展 harness：真实 1m fixture（从 `simulate_factor26_day_1m` 抽样）补 BUY / 半仓 / 阶梯  
4. 引擎补齐「开盘保护」时，应调用 `overnight_open_protect_px` 真源，禁止复制条件  
5. 现价破卖（last）是否并入引擎需产品决策（研究口径 vs 盯盘口径）

---

## 7. 复现

```bash
python -m unittest strategy.test_decision_parity -v
python -c "from strategy.test_decision_parity import run_parity; import json; print(json.dumps(run_parity(), ensure_ascii=False, indent=2))"
```

原始 JSON（本地可生成）：`docs/_parity_raw.json`（可不提交）。

---

*Phase 1D 完成。*
