# strategy — 可插拔策略 / 因子 / 决策框架

默认生效：**策略一 = 因子1（开盘±2.5% 买卖）+ 因子2（回撤阶梯补仓）**。

- 决策/盯盘买卖只看因子1；因子2 在 `run_strategy1` 里叠权益。
- 仅因子1交易：`run_open_break` 或 `python strategy1.py --no-factor2`。
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
│   ├── factor2.py        # 回撤阶梯补仓（真源 dd_topup.py）
│   └── factor3.py        # 占位
├── strategies/
│   ├── strategy1/        # 默认：factor1 + factor2
│   └── strategy2…4/      # 骨架（同因子不同 params）
├── open_break.py         # 因子1 默认百分比 / 规则
├── dd_topup.py           # 因子2 默认档位·加仓比例 / 规则
├── backtest.py / runner.py / config.py
└── registry.py
```

## 默认参数在哪改（开闭）

| 项 | 默认源 | 策略覆盖 |
|----|--------|----------|
| 因子1 ±pct、双阳跨日 | `open_break.DEFAULT_*` | `strategy1/bindings` / `BacktestConfig.threshold_pct` 等 |
| 因子2 档位、各档加仓%、上限 | `dd_topup.DEFAULT_LEVELS` / `DEFAULT_ADD_PCTS` / `DEFAULT_MAX_INJECT_PCT` | bindings 或 `BacktestConfig.factor2_*` |

```python
from dataclasses import replace
from strategy import KAICHENG, run_strategy1

# 只改因子2加仓比例，不动算法
run_strategy1(replace(KAICHENG, factor2_add_pct=0.12), show_report=False)
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
# factor1 …  | factor2 add_pct/levels …
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
| `run_open_break` | **仅因子1交易**（不含因子2叠加） |
| `run_strategy1` | 因子1 + 因子2（默认） |
| `OpenBreak3Strategy` | = Strategy1 执行类 |
