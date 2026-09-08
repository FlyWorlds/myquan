# 因子26 · 浮盈回落一半止盈

> 研究用途，非投资建议。**策略一主执行因子**（买同开盘突破；卖由峰值回落阈值改为浮盈回落一半）。

## 规则

1. **买入**（两条任一，过滤同因子1：前日阴/小阳、禁双阳跨日≥5%、T+1）
   - **开盘突破**：当日最高 ≥ `ceil(开盘 × (1 + entry_pct))`，按触发价限价买
   - **攻击波**：当日最高 ≥ `ceil(当日最低 × (1 + entry_pct))`，自最低点向上攻击阈值亦触买
2. **卖出（浮盈回落一半）**
   - **已浮盈**：`floor(成本 + 0.5 × (持仓最高 − 成本))`（峰值浮盈回吐一半出场）
   - **未浮盈**：`floor(成本 × (1 − hard_pct))` 成本硬保护，默认 `hard_pct=2.5%`
   - **触达判定**：按 **1 分钟 K 时间顺序**——先用「此前最高」算卖价，再看该分钟最低是否跌破，然后才抬升 peak
   - **禁止**用「全日最低 ≤ 抬高后的当前卖价」
   - **实仓**：路径从**买入时刻**起算；持仓峰值写入 `peak_high`（跨日延续）
   - **T+1 当日**：持仓状态固定「已经买入」，不进「待卖出」
3. 默认 `entry_pct = 2.5%`，`giveback_ratio = 0.5`，硬保护 `2.5%`

## 双轨数据

| 用途 | 周期 | 说明 |
|------|------|------|
| 选股 / 前日过滤 / 因子2 回撤预警 | **日线** | 阴小阳、双阳、账户回撤阈值 |
| 定盘池成交回测 / 盯盘策略回放 | **1 分钟** | 近 **7 个交易日**即可（东财 1m 约近数日） |

长窗 akquant 日线回测仍有同 bar 次序偏差；池内短窗以 `replay_factor26_1m` 为准。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor26`
- 盯盘：实仓浮盈回落一半 + 策略回放近 7 日 1m
- 池回测：`PYTHONPATH=. python backtest/strategy1_pool_1m/run.py`（近7日1m；三槽；先触发先买；默认 half_gain）

## 真源

- 逻辑：`strategy/pullback_wave_stop.py`（`half_gain_stop_price` / `path_dependent_pullback_hit` / `replay_factor26_1m`）
- 注册：`strategy/factors/factor26.py`
- 单测：`strategy/test_pullback_wave_path.py`
