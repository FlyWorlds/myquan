# 因子22 · 收盘动量

> 研究用途，非投资建议。叠在策略一主止损（**因子26**，旧对照为因子1）上的同日再买规则，**已挂策略一**。

## 规则

1. 当日已按因子26（或同源开盘突破止损）**止损清仓**
2. 以当日**最低价** `low` 为锚，门槛 = `low × (1 + bounce_pct)`
3. **收盘确认**（默认）：`收盘价 ≥ 门槛` 才再买；成交按门槛价（实盘更贴近收盘）
4. 可选阴阳过滤：收阳 `close>open` / 收阴 `close<open` / 不限
5. 再买后仍走因子26 的 T+1 与次日回落波止损

默认参数（策略一 bindings）：`bounce_pct=0.01`（1%），`candle=any`，`mode=close`。

盘中触价模式（`mode=intraday`：`high≥门槛`）在日线上易把「先冲高后砸低」误判成反弹，仅作对照。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor22`
- 决策：`Strategy1Decision`（有仓触止损且收盘动量成立 → 隐含先止损再买；空仓当日已卖出后因子22 为额外再买路径；**因子26 开盘/攻击波亦可同日再买**）
- 盯盘：止损结算后仍可再买；收盘动量成立时展示「待买入 / 收盘动量可再买」，因子26 再触买展示「卖出后再触买」

## 验证（仅天通 2026）

标的 `sh600330`，因子1 ±3%，区间 2026-01-01～数据末日。详见 [`backtest/tiantong_stop_rebuy_2026/REPORT.md`](../backtest/tiantong_stop_rebuy_2026/REPORT.md)。

| 方案 | 收益 | 最大回撤 | 再买次数 |
|------|------|----------|----------|
| 基线（止损后不买） | +197.5% | -21.9% | 0 |
| 收盘≥low×1.01（默认） | +352.3% | -26.5% | 40 |
| 收盘≥low×1.02 | +256.4% | -21.2% | 13 |
| 收盘≥low×1.025 | +224.6% | -25.2% | 9 |
| 收盘≥low×1.03 | +198.5% | -25.9% | 8 |

再买后几乎都会再次止损；结果路径敏感、样本窄。扩样本前保持默认 1%。

**门槛专项（天通+凯盛，含止损日反弹分布）**：[`backtest/factor22_threshold/REPORT.md`](../backtest/factor22_threshold/REPORT.md)。

## 真源

- 逻辑：`strategy/close_momentum.py`
- 注册：`strategy/factors/factor22.py`
- CLI 对照：`python backtest/tiantong_stop_rebuy_2026/run.py`
