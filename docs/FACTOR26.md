# 因子26 · 回落波阈值止损

> 研究用途，非投资建议。**策略一主执行因子**（替代因子1 的开盘锚定止损形态）。

## 规则

1. **买入**（两条任一，过滤同因子1：前日阴/小阳、禁双阳跨日≥5%、T+1）
   - **开盘突破**：当日最高 ≥ `ceil(开盘 × (1 + entry_pct))`，按触发价限价买
   - **攻击波**：当日最高 ≥ `ceil(当日最低 × (1 + entry_pct))`，自最低点向上攻击阈值亦触买
2. **止损**：`floor(当日分时最高 × (1 − pullback_pct))`
   - 分时最高抬升 → 止损价上移（回落波）
   - **触达判定**：按 **1 分钟 K 时间顺序**——先用「此前最高」算止损，再看该分钟最低是否跌破，然后才抬升 running_high
   - **禁止**用「全日最低 ≤ 抬高后的当前止损」
   - **实仓**：止损路径从**买入时刻**起算（锚定成本），买入前分时不计入
   - **T+1 当日**：持仓状态固定「已经买入」，不进「待卖出」
3. 默认 `entry_pct = pullback_pct = 2.5%`

## 双轨数据

| 用途 | 周期 | 说明 |
|------|------|------|
| 选股 / 前日过滤 / 因子2 回撤预警 | **日线** | 阴小阳、双阳、账户回撤阈值 |
| 定盘池成交回测 / 盯盘策略回放 | **1 分钟** | 近 **7 个交易日**即可（东财 1m 约近数日） |

长窗 akquant 日线回测仍有同 bar 次序偏差；池内短窗以 `replay_factor26_1m` 为准。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor26`
- 盯盘：实仓止损 + 策略回放近 7 日 1m
- 池回测：`PYTHONPATH=. python backtest/strategy1_pool_1m/run.py`（近7日1m；三槽；先触发先买）

## 真源

- 逻辑：`strategy/pullback_wave_stop.py`（`path_dependent_pullback_hit` / `replay_factor26_1m`）
- 注册：`strategy/factors/factor26.py`
- 单测：`strategy/test_pullback_wave_path.py`
