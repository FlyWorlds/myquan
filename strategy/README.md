# strategy — 可插拔策略 / 因子 / 决策框架

默认生效：**策略一 = 因子1（开盘±2.5% 买卖）+ 因子2（回撤加减仓预警）**。

- 决策/盯盘买卖只看因子1；因子2 默认只挂预警阈值（**回测不注资**）。
- 仅因子1交易：`run_open_break` 或 `python strategy1.py --no-factor2`。
- 旧版权益注资叠加：`run_strategy1(..., apply_factor2_overlay=True)`（`dd_topup`）。
- **开闭调参**：改 `bindings.py` / `BacktestConfig` / `DEFAULT_*`，不必改算法。

## 分层架构

```
因子层 (factors)     → 价位 / 信号 / 通用过滤（可复用）
策略层 (bindings)    → 本策略挂哪些因子、参数、专属过滤器
决策层 (decision)    → MarketContext → Decision(buy|sell|hold)
执行层 (runner/backtest) → 下单、回测、盯盘对接
```

```
strategy/
├── core/                 # 协议 / MarketContext / Decision / 注册表
├── factors/
│   ├── factor1.py        # 开盘突破 ±pct（买卖真源 open_break.py）
│   ├── factor2.py        # 回撤加减仓预警（真源 dd_alert.py）
│   ├── factor3.py        # 动量（策略五组合 / 单票时序）
│   └── factor4.py        # 占位
├── strategies/
│   ├── strategy1/        # 默认：factor1 + factor2（预警）
│   ├── strategy3/        # 动量因子组合（factor3）
│   ├── strategy4/        # 因子1·roll12 Top3 池 × 池内反转
│   ├── strategy5/        # 动量因子组合（factor3）
│   └── strategy2/        # 骨架（同因子不同 params）
├── open_break.py         # 因子1 默认百分比 / 规则
├── dd_alert.py           # 因子2 历史/年均回撤 → 加减仓预警线
├── dd_topup.py           # 旧版权益注资叠加（可选）
├── backtest.py / runner.py / config.py
└── registry.py
```

## 默认参数在哪改（开闭）

| 项 | 默认源 | 策略覆盖 |
|----|--------|----------|
| 因子1 ±pct、双阳跨日 | `open_break.DEFAULT_*` | `strategy1/bindings` / `BacktestConfig.threshold_pct` 等 |
| 因子2 历史最大/年均回撤 | `dd_alert.DEFAULT_HIST_MAX_DD` / `DEFAULT_AVG_YEARLY_MAX_DD` | `strategy1/bindings` |

```python
from strategy.dd_alert import derive_thresholds

# 用策略权益曲线重标定因子2阈值
th = derive_thresholds(equity_curve)
print(th.label())
```

## 决策层用法

```python
from strategy import MarketContext, get_decision_engine

eng = get_decision_engine("strategy1")
ctx = MarketContext(
    open=10.0, high=10.4, low=9.8, close=10.3, last=10.3,
    prev_open=10.1, prev_close=9.9,
    position_qty=0,
)
print(eng.decide(ctx).action)
```

## 因子绑定

```python
from strategy import get_strategy_bindings

for b in get_strategy_bindings("strategy1"):
    print(b.factor_id, b.params, b.filter_desc)
# factor1 …  | factor2 hist_max_dd/avg_yearly_max_dd …
```

## 回测 CLI

```bash
cd backtest && python strategy1.py --rules
cd backtest && python strategy1.py --no-open
cd backtest && python strategy1.py --no-factor2 --no-open   # 仅因子1
cd backtest && python run.py kaicheng --no-open
```

## 如何扩展（开闭）

1. **新因子**：`factors/factorN.py` + `register_factor`，策略 bindings 挂上即可  
2. **改百分比**：只改 `DEFAULT_*` 或该策略 `bindings` / `BacktestConfig`  
3. **新策略组合**：新 `strategies/strategyN`，复用已有因子、换 params  

## 兼容

| 旧 API | 说明 |
|--------|------|
| `get_strategy("open_break3")` | → strategy1 |
| `run_open_break` | **仅因子1交易**（不含因子2） |
| `run_strategy1` | 因子1 + 因子2预警（默认不注资） |
| `OpenBreak3Strategy` | = Strategy1 执行类 |
