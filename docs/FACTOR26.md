# 因子26 · 多层止盈

> 研究用途，非投资建议。**策略一主执行因子**（买同开盘突破；卖按浮盈分三段）。

## 规则

1. **买入**（过滤同因子1：前日阴/小阳、禁双阳跨日≥5%、T+1）
   - **开盘阈值**：当日最高 ≥ `ceil(开盘 × (1 + entry_pct))`；**盯盘按 1 分钟顺序**判定
   - 攻击波仅研究对照：`--buy-mode open_or_attack`（产物加 `_attack` 后缀，不覆盖默认 `REPORT.md`）
   - 空仓「将买入/待买入」：现价距**开盘突破买点** ≤1%；生产关闭攻击波时**不用**下砸低点派生价（避免一字开板后再触「待买入」误报）
   - 空仓**不**把「现价≤开盘派生卖价」标成「已触止损」（无仓无可止；止损触达仅实仓/纸面持仓 + 1m path）
2. **卖出（多层止盈，同分钟优先级）**
   1. **买点硬保护**：亏损达 **2.5%**；**低开已破硬保护按开盘立刻卖**（先于 T1 回落）
   2. **买入日收盘盈利 <3%（已记）**且当日尚未 **>3%** → 次日按 **max(隔夜持仓高点, 当日高点) 回落 2.5%** 全清，且不得低于买点硬保护（禁止用今开重置峰值把止损打得更低）
   3. **大赚阶梯**：浮盈 ≥ **15%** → 可卖全清；≥ **10%** → 卖一半（不足 200 股则全清）
   4. **中赚（>3% 且 <10%）**：**回落一半**（卖价=`floor(成本+0.5×(买入后最高−成本))`）与 **动态高点回落 0.5×近20日日频σ** 并行；从峰值往下**谁先碰到走谁**（同分钟若两线都打穿，成交价更高的那条）。波动 = akquant `vec_log_returns` + `vec_rolling_std`（点时点、不含当日）
   5. **买入当日已记**：收盘盈利 **≥3% 不记**；其余都记（含小亏、盈利 <3% 的小赚）
   6. **大赚后回落 2 个点**：峰值浮盈 ≥10% 后，`floor(峰值×0.98)` 触达 → 清仓（同分钟若同时触 10% 半仓，优先档位）
   - 触达按 **1 分钟 K 顺序**；禁止用全日 low 对抬高后卖价；**已平仓留痕成交价走 `first_session_exit_fill`**（策略统一，无个股特例），禁止用收盘后抬高的止损去撞今开
   - **T+1 当日**：不卖；峰值只从买入之后算，未卖出前创新高则抬升
   - 次日：低开破硬保护按开盘卖；未过 3% 走隔夜高点回落 2.5%（地板=买点硬保护）；过 3% 走中段；过 10% 走分段
3. **三槽组合**：物理 3 槽（盘中/隔夜均可持 3）；当日最多买 3；当日有卖出（含半仓）禁再买该票
4. 默认 `entry_pct=2.5%`，中段门槛 `3%`，`ladder 10%/15%`，大赚回落 `2%`，回落一半 `50%`，波动回落 `50%×20日日频σ`，T1 峰值回落 `2.5%`，硬保护 `2.5%`

口径：超 10% 分段止盈；3–10% 回落一半与波动回落赛跑；买入后未站上 3% 则次日用峰值回落 2.5% 防回吐。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor26`
- 池回测：`PYTHONPATH=. python backtest/strategy1_pool_1m/run.py`（近7日1m；三槽；默认开盘阈值买）
- 研究对照：`--buy-mode open_or_attack` 加回攻击波（产物 `REPORT_attack.md`）
- 研究对照：低开破硬保护立刻卖 vs 再下杀 1%：`PYTHONPATH=. python backtest/strategy1_pool_1m/compare_hard_gap.py --pool strategy16 --days 7` → `backtest/strategy16_core_leader/COMPARE_HARD_GAP.md`
- 研究对照：卖出后开盘阈值同日再买：`PYTHONPATH=. python backtest/strategy16_core_leader/compare_open_rebuy.py --days 7` → `COMPARE_OPEN_REBUY.md`；全池等权 `--all-pool` → `COMPARE_OPEN_REBUY_ALL.md`

## 真源

- 逻辑：`strategy/pullback_wave_stop.py`（`eval_multi_tp_bar` / `mid_gain_first_hit` / `half_gain_stop_price` / `vol_giveback_stop_price` / `realized_vol_daily` / `replay_factor26_1m`）
- 收益率/波动/今日盈亏：`strategy/akq_math.py`（akquant `vec_returns` / `vec_log_returns` / `vec_rolling_std`）
- 注册：`strategy/factors/factor26.py`
- 单测：`strategy/test_pullback_wave_path.py`

研究用途，非投资建议。
