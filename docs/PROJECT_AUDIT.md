# 策略十六 / 因子26 算法审核（2026-09-11）

> 研究用途，不构成投资建议。  
> **范围**：现行默认 **策略十六 = 因子27 宇宙 + 因子26 买卖 + 因子2 预警 + 因子22 研究再买**。  
> **不覆盖**：2026-08 凯盛单票因子1 底稿（见 [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md)）。

审核对象是**最新生产规则的逻辑/算法**，不是注册表文案盘点。

## 1. 结论

| 项 | 判断 |
|----|------|
| 生产真源 | 盯盘 `holdingStocks/index.py` 的 `collect_rows` + `strategy/pullback_wave_stop.py` 的 1 分钟顺序 |
| 可对账回测 | `backtest/strategy1_pool_1m/run.py --pool strategy16`（1m + 三槽 + `eval_multi_tp_bar`） |
| **不要用来对账盯盘** | `run_strategy16()` / `run_factor26_strategy()`：日线 `OpenBreak3`，无三槽、无完整多层止盈、无因子22 |
| 内核 `eval_multi_tp_bar` | 优先级（硬保护 / T1 峰值回落 / 15% / 中赚赛跑 / 10% 半仓 / 峰值回落 2%）自洽 |
| 本次已修 | 三槽 1m 半仓后 `sold_today` 误禁剩余仓当日止盈；单票 `simulate_factor26_day_1m` 半仓不减股；**单测误写 `holdings.json`**；盯盘 7 日回放恢复 10% 全清口径 |
| 未改盯盘成交 | 盯盘 `collect_rows` 仍把任意止盈触达当**全清**（全历史 1m 回放无 `tp_stage`） |

**可行性**：规则在 A 股连续竞价时段可执行（开盘后算阈值、预挂限价/条件单）。当前系统仍是「1m 路径回测 + 信号盯盘 + 本地模拟记账」，不是券商实盘自动成交。回测数字只作研究参考。

## 2. 三条执行路径（不要混）

```
规则真源 eval_multi_tp_bar
    ├─ 盯盘 collect_rows          每次从买入时刻重放当日 1m → 触达即全清
    ├─ 三槽 1m 回测 pool_1m       逐根 1m 增量 → 半仓后可继续卖剩余（本次已对齐规则）
    └─ Decision / run_strategy16  日线 OHLC 快照；默认把 low≤stop 当卖出（同 bar 次序未知）
```

决策引擎 `Factor26Decision` **不是**盯盘成交路径；`TODO.MD`「规则已对齐、未替换旁路」仍成立。改 bindings / Decision **不会**自动改盯盘。

## 3. 算法缺陷（按严重度）

### P0 · 已修复：半仓后剩余仓被 `sold_today` 禁卖

`simulate_portfolio_3slots` 在 10% 半仓后把 `sold_today=True`（正确：禁同日再买），却把它一并送进 `eval_multi_tp_bar(..., can_sell=not sold_today)`。

结果：剩余仓当日无法再走 15% / 峰值回落 2% / 中段止盈，仓位挂到收盘。注释写「半仓后仍可继续止盈剩余仓」，与代码相反。

**修复**：`can_sell` 只表示 T+1；`sold_today` 只挡再买。回归：`test_strategy16_half_remaining.py`。

### P0 · 已修复：单票 1m 模拟半仓不减股

`simulate_factor26_day_1m` 碰到 `kind=half` 只把 `tp_stage=1`，**不减 shares**。下一根若仍在 10% 以上，会按「已半仓再触 10%」把**全部 1000 股**当剩余清掉，等于延迟一分钟的全清，不是半仓。

**修复**：半仓扣减股数并跨日保留 `tp_stage` / 剩余股数。回归：`strategy/test_pullback_wave_path.py`。

### P1 · 盯盘：10%「半仓」实际全清

规则写「浮盈 ≥10% 卖一半」。盯盘每次扫描从买入时刻重放当日全部 1m：

1. `path_dependent_pullback_hit` 固定 `shares=1000`、`tp_stage=0`，10% 返回 `kind=half`。
2. `_hit()` 把 `half` 与 `full` 都标成 `hit_stop=True`。
3. `apply_stop_fill` 卖掉全部可卖数量。
4. `realized_today[code]` 一日一条，半仓后再卖会被幂等短路。

若只改结算股数、不推进 `since_ts` / `tp_stage`，下一轮回放会在**同一根 10% K**上把剩余当 `ladder_half_10_clear` 立刻清掉。

**因此盯盘维持全清是有意的执行简化，不是内核公式算错。** 与三槽 1m 回测（增量 bar）不一致。要对齐需：持仓记 `tp_stage`、半仓后把 `since_ts` 推到触达分钟之后、允许同一标的当日第二笔卖出。

### P1 · `run_strategy16()` 不是因子26

`run_factor26_strategy` 在 `stop_anchor=open` 时改成 `day_high`，然后走 `run_open_break`。`OpenBreak3Strategy` 只用 `half_gain_stop_price` 的日线 low 触达，没有 10%/15% 阶梯、T1 峰值回落、波动赛跑、三槽、因子22。

单票 CLI 收益不能当成策略十六生产表现。

### P1 · 因子22：绑定开着，生产成交关着

| 路径 | 当日止损后再买 |
|------|----------------|
| 盯盘 / 默认 `pool_1m` | **禁**（`sold_today`） |
| `Factor26Decision` | 允许（`implied_stop_then_rebuy`） |
| `docs/FACTOR22.md` | 仍写盯盘可再买 |

生产以盯盘为准：因子22 不改变三槽成交。7 日对照见 `COMPARE_F22.md`（研究，窗口极短）。

### P1 · Decision 用日线 low 判卖（同 bar 前视）

无 `meta.path_hit_stop` 时：`path_stop = low <= stop_px`。当日先高后低会在未知先后下成交。盯盘强制 1m 顺序。Decision 也未传 `vol20_daily` / `overnight_armed`，中段 σ 回落与 T1 武装与盯盘可不一致。

### P2 · 同一根 1m：用当根 high 切档、用切档前 peak 算卖价

`eval_multi_tp_bar`：`live_ok` / `peak_gain` 含本分钟最高，从而关掉 T1、打开中段；`mid_gain_first_hit` 的 peak 仍是 `peak_before`。

- 若本分钟先冲过 3% 再砸：档位已切中段，卖价却按旧峰，既不是「先高后低」也不是「先低后高」。
- 1 分钟内高低次序本就不可观测；影响小于日线 OHLC，但与「先用此前峰值再抬峰」的注释不完全一致。

### P2 · 因子27 宇宙不是 PIT 成分

池按通达信**现价**概念成交额 + **当前**成分涨跌幅在 `as_of` 打一次，再冻结约 3 个月。概念成分与活跃度都不是历史时点截面；退市/调入调出未建模。短窗 1m 回测用的是冻结后的当期池，有幸存者与前视选股成分。

### P2 · 生产对账窗只有约 7 个交易日

开盘阈值 `{2, 2.5, 3}%` 用 2026 至今日线夏普择优（`--fit-thr`），再在近 7 日 1m 上看组合。样本外独立 bets 远少于稳健推断所需；**无显著净边际的统计结论**，只能当执行核对。

### P2 · 仍成立的执行假设（沿用 8 月底稿）

- 盯盘触发价必成，无滑点、无佣金/印花税；回测 `costs.py` 另计。
- 日线失败盯盘吞异常 → 前日过滤不通过，买点被静默抑制。
- 前复权研究 vs 未复权盘面：除权附近 0.01 元档位可能不一致。
- 无盘口/排队/一字反复开板。

## 4. 偏差清单（对照回测偏差技能）

| 偏差 | 级别 | 触发 | 说明 |
|------|------|------|------|
| 前视（日线 Decision / 日线 runner） | High | 同 bar 用 high 决策、low 成交 | 生产盯盘已用 1m 顺序规避；CLI `run_strategy16` 未规避 |
| 过拟合 / 短窗选参 | Medium | 有效样本过小；7 日 + 阈值网格 | 不得把近 7 日收益当策略期望 |
| 幸存者 / 非 PIT 宇宙 | Medium | 因子27 当前成分快照 | 冻结池减轻盘中换股，不消除建池时点偏差 |
| 成本忽略（盯盘账本） | Medium | 扣费后与账面可分叉 | 本地盈亏不能对券商交割单 |
| 执行模型 | Medium | 触发价必成 | 真实止损可能更差或未成 |

未计算 CSCV/PBO/DSR：缺少完整试验矩阵与足够长的 1m 收益序列。不得声称过拟合概率数值。

## 5. 建议（算法，不扩功能）

1. **对账只跑** `PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7`；文档/CLI 标明 `run_strategy16()` 是日线简化内核。
2. 若要盯盘也半仓：必须持仓 `tp_stage` + 半仓后推进 `since_ts`，并允许 `realized_today` 第二笔；不要只改卖出股数。
3. Decision 在无 `path_hit_*` 时不要用全日 low 成交；或停用 Decision 作为执行参考。
4. 因子22：要么从默认 bindings 关掉，要么改文档为「生产禁再买、仅研究对照」。
5. 因子27 建池改为历史时点概念活跃度后再谈样本外。

### 审核副作用（已修，2026-09-11 下午）

审核回归跑 `unittest` 时，`_apply_trigger_date_fields` → `remember_factor_trigger` **直接写了生产 `holdingStocks/holdings.json`**（unittest 不设 `PYTEST_CURRENT_TEST`）。表现为因子触发价/日期被测试夹具盖掉（例如天通 `last_sell=9.8` / `2026-09-07`），持仓页「已触发因子价」会跟着变。另：半仓减股修进了 `replay_factor26_1m`，盯盘 7 日「策略回放持有」一度按半仓剩仓展示，与盯盘全清不一致。

**修复**：单测默认内存账本、不碰生产 JSON；qty/成本/因子记忆变化时另存 `holdings.json.bak`；盯盘回放 `flatten_ladder_half=True`（10% 全清）。本地若已被单测改过，把 `holdings.json.bak` 拷回，或用 `python index.py set-cost` 按券商持仓重登。

## 6. 方法附录

| 阶段 | 方法 | 窗口 | 关键参数 | 结果 |
|------|------|------|----------|------|
| 静态读码 | `eval_multi_tp_bar` / 盯盘 / pool_1m / Decision | 仓库 main 2026-09-11 | 因子26 默认 2.5%/3%/10%/15%/2% | 发现半仓状态机分叉 |
| 回归 | `python -m unittest` 下列用例 | 合成 1m | 成本 100、10% 半仓 | 修复后半仓减股、剩余可卖 |
| 未跑 | 全市场长窗 1m | — | — | 环境无保证拉齐分钟；不把 7 日数字当结论 |

本报告基于仓库规则与合成路径复核生成，仅供研究参考，不构成任何投资建议。
