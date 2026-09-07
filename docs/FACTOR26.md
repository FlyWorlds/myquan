# 因子26 · 回落波阈值止损

> 研究用途，非投资建议。**策略一主执行因子**（替代因子1 的开盘锚定止损形态）。

## 规则

1. **买入**（同因子1）：当日最高 ≥ `ceil(开盘 × (1 + entry_pct))`，按触发价限价买；前日阴/小阳、禁双阳跨日≥5%、T+1
2. **止损**：`floor(当日分时最高 × (1 − pullback_pct))`
   - 分时最高抬升 → 止损价上移（回落波）
   - 当日最低 ≤ 止损价 → 全清
3. 默认 `entry_pct = pullback_pct = 2.5%`

与 **因子25** 不同：25 是 30m 收盘确认 + 峰值回撤半仓；26 是**当日最高固定 % 回落全清**。

日线回放用全日 high 估止损，同 bar high/low 有次序偏差；**盯盘以实时最高为准**。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor26`（主买卖）
- 决策：`Strategy1Decision.levels_for` 传入 `ctx.high`
- 盯盘：`holdingStocks/watch_config.FACTOR_ID=factor26`；`index.py` 止损跟 `q["high"]`

## 真源

- 逻辑：`strategy/pullback_wave_stop.py`
- 注册：`strategy/factors/factor26.py`
- 说明：因子1（`open_break.py`）仍可供策略三/四/八等复用
