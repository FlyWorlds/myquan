# 策略十五 · 因子25 30m 震荡减磨损（天通）

> 研究用途，非投资建议。区间窄、同样本调参。

- 标的：天通股份 `sh600330`，因子1 ±3%
- 区间：2026-08-14 ～ 2026-09-03
- 成本：佣金+印花近似 + 滑点合计约 0.25%/边

## 结果对照

| 方案 | 收益 | vs 买入持有 | 备注 |
|------|------|-------------|------|
| 买入持有 | +9.85% | 0 | 首末 30m 日收 |
| 纯因子1（日线触价止损近似） | -3.04% | -12.89% | 影线易假破 |
| **因子25 默认** | **+12.34%** | **+2.49%** | MDD 8.04% |

## 默认参数

```json
{
  "stop_confirm_bars": 2,
  "reclaim_band": 0.015,
  "reclaim_premium_max": 0.015,
  "reclaim_horizon": 8,
  "reclaim_require_yang": true,
  "reclaim_break_prior_high": true,
  "reclaim_require_above_day_stop": true,
  "reclaim_enabled": true,
  "trail_arm_pct": 0.12,
  "trail_giveback_pct": 0.05,
  "trail_reduce_ratio": 0.5,
  "suppress_f1_during_reclaim": true,
  "no_f1_if_day_low_hit_stop": true
}
```

## 成交

- 2026-08-14 10:30 F1买 3800@24.94 (open_break)
- 2026-08-19 10:00 trail半仓 1900@28.02 (trail arm≥12% giveback≥5%)
- 2026-08-24 11:30 止损 1900@25.96 (m30_close×2≤stop)
- 2026-08-25 11:30 F1买 3800@26.25 (open_break)
- 2026-08-28 11:00 trail半仓 1900@28.7 (trail arm≥12% giveback≥5%)
- 2026-08-28 11:30 止损 1900@28.74 (m30_close×2≤stop)
- 2026-08-28 13:30 回补 1900@29.05 (reclaim near±1.5% prem≤1.5%)
- 2026-09-01 10:30 止损 1900@27.18 (m30_close×2≤stop)

## 真源

- `strategy/m30_chop.py` / `strategy/factors/factor25.py`
- CLI：`PYTHONPATH=. python backtest/strategy15_m30_chop/run.py`
