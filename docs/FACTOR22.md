# 因子22 · 收盘动量

> 研究用途，非投资建议。叠在主止损（**因子26**）上的同日再买规则。**策略十六默认关闭**；策略一 bindings 仍挂（研究）。三槽执行下当日已卖出通常禁再买（策略十六仅隔夜已记+竞价低开开盘保护卖出后过门可回买，不经由因子22）。

## 规则

1. 当日已按因子26（或同源开盘突破止损）**止损清仓**
2. 以当日**最低价** `low` 为锚，门槛 = `low × (1 + bounce_pct)`
3. **收盘确认**（默认）：`收盘价 ≥ 门槛` 才再买；成交按门槛价（实盘更贴近收盘）。盯盘仅 **14:57 后**把现价当收盘；决策引擎 `meta.close_confirmed=False` 时不走因子22
4. 可选阴阳过滤：收阳 `close>open` / 收阴 `close<open` / 不限
5. 再买后仍走因子26 的 T+1 与次日多层止盈

默认参数（策略一 bindings）：`bounce_pct=0.01`（1%），`candle=any`，`mode=close`。

盘中触价模式（`mode=intraday`：`high≥门槛`）在日线上易把「先冲高后砸低」误判成反弹，仅作对照。

## 绑定

- `strategy/strategies/strategy1/bindings.py` → `factor22`（研究，enabled）
- `strategy/strategies/strategy16/bindings.py` → `factor22`（**enabled=False**，生产不改成交）
- 盯盘 / 默认 `pool_1m`：当日卖出通常禁再买。策略十六隔夜已记+竞价低开回买走开盘阈值，不走因子22。对照见 `backtest/strategy16_core_leader/COMPARE_F22.md`。

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
