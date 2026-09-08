# 因子26 · 多层止盈

> 研究用途，非投资建议。**策略一主执行因子**（买同开盘突破；卖=阶梯 + 回吐 + 峰值半仓 + 隔夜下杀）。

## 规则

1. **买入**（两条任一，过滤同因子1：前日阴/小阳、禁双阳跨日≥5%、T+1）
   - **开盘突破**：当日最高 ≥ `ceil(开盘 × (1 + entry_pct))`；**盯盘按 1 分钟顺序**判定，禁止用全日 high/low 假攻击波
   - **攻击波**：按分钟维护 running_low；**先用此前最低算买点，再更新本分钟最低**（禁止同一根 K 的低+高自造攻击波）
2. **卖出（多层止盈，同分钟优先级）**
   1. **隔夜武装**（昨收相对成本亏损 / 昨止盈标记 / 止损已记）→ 基于开盘价下杀 **1%** 全清（已记另走缺口开盘卖）
   2. **阶梯**：浮盈 ≥ **15%** → 可卖全清；≥ **10%** → 卖一半（不足 200 股则全清）
   3. **T+1 后利润回吐一半**：`floor(成本 + 0.5×(持仓最高−成本))`；未浮盈 → 成本硬保护默认 2.5%
   4. **峰值回落 X=3%**：`floor(峰值×0.97)` 触达 → 清一半；**已半仓后再触 → 剩余全清**
   5. **同分钟**规则1 的 10% 半仓与规则3 半仓：**只减一次**（优先阶梯 10%）
   - 触达按 **1 分钟 K 顺序**；禁止用全日 low 对抬高后卖价
   - **T+1 当日**：不卖，记 `tp_marked` / `stop_noted`；次日走隔夜规则
3. **三槽组合**：物理 3 槽（盘中可持 3）；当日最多买 2；尾盘空 1（隔夜最多 2）；当日有卖出（含半仓）禁再买该票
4. 默认 `entry_pct=2.5%`，`giveback_ratio=0.5`，`ladder 10%/15%`，`peak_pullback_x=3%`，硬保护 `2.5%`

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor26`
- 池回测：`PYTHONPATH=. python backtest/strategy1_pool_1m/run.py`（近7日1m；三槽；`exit_mode=half_gain` 已接多层）

## 真源

- 逻辑：`strategy/pullback_wave_stop.py`（`eval_multi_tp_bar` / `half_gain_stop_price` / `replay_factor26_1m`）
- 注册：`strategy/factors/factor26.py`
- 单测：`strategy/test_pullback_wave_path.py`

研究用途，非投资建议。
