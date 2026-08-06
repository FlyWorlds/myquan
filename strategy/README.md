# strategy — 可插拔策略 / 因子 / 决策框架

默认生效：**策略一 = 因子1 = 开盘±2.5%**（OpenBreak3）。

## 分层架构

```
因子层 (factors)     → 价位 / 信号 / 通用过滤
策略层 (bindings)    → 本策略挂哪些因子、参数、专属过滤器
决策层 (decision)    → MarketContext → Decision(buy|sell|hold)
执行层 (runner/backtest) → 下单、回测、盯盘对接
```

```
strategy/
├── core/
│   ├── protocols.py      # FactorSpec / FactorBinding / StrategySpec
│   ├── context.py        # MarketContext / Decision
│   ├── decision.py       # DecisionEngine / get_decision_engine
│   └── *_registry.py
├── factors/
│   ├── factor1.py        # 生效：开盘突破 ±pct
│   ├── factor2.py        # 占位
│   └── factor3.py        # 占位
├── strategies/
│   ├── strategy1/        # 默认
│   │   ├── bindings.py   # 策略层
│   │   ├── decision.py   # 决策层
│   │   └── __init__.py   # 注册 + 挂 runner
│   ├── strategy2/ … strategy4/
│   └── _common.py
├── open_break.py         # 因子1 规则真源
├── backtest.py / runner.py / config.py
└── registry.py           # 兼容旧 get_strategy API
```

| 层 | 职责 | 不做什么 |
|----|------|----------|
| 因子 | 可复用规则（levels/signal） | 不知「哪个策略」、不下单 |
| 策略绑定 | 选因子 + params + filter | 不做买卖裁决 |
| 决策 | 根据仓位/行情产出 Decision | 不直接调 broker |
| 执行 | 回测 Strategy / 盯盘下单 | 不写业务规则 |

## 决策层用法

```python
from strategy import MarketContext, get_decision_engine

eng = get_decision_engine("strategy1")  # 别名 open_break3 / s1
ctx = MarketContext(
    open=10.0, high=10.4, low=9.8, close=10.3, last=10.3,
    prev_open=10.1, prev_close=9.9,   # 阴线 → 过滤通过
    position_qty=0,
)
d = eng.decide(ctx)
print(d.action, d.reason, d.price)  # buy / hold / sell
```

策略一逻辑摘要：空仓+过滤通过+触买点→buy；有仓+非T+1+触止损→sell；否则 hold。

## 因子绑定（策略专属条件）

```python
from strategy import bind_factor, get_strategy_bindings

# 策略一：factor1 ±2.5% + 阴/小阳
# 策略二：同一 factor1 ±3% + 仅阴线
for b in get_strategy_bindings("strategy1"):
    print(b.factor_id, b.params, b.filter_desc)
```

```python
bind_factor(
    "factor1",
    entry_pct=0.025,
    stop_pct=0.025,
    filter=my_filter_fn,
    filter_desc="前日阴/小阳",
    role="both",  # entry / exit / both / custom
)
```

## 注册表 API

```python
from strategy import get_strategy, get_factor, get_decision_engine, list_strategies

s1 = get_strategy("strategy1")
print(s1.name, s1.factor_ids)          # 策略一 ('factor1',)
eng = get_decision_engine("strategy1") # 决策引擎
f1 = get_factor("factor1")
```

回测 CLI（行为不变）：

```bash
cd backtest && python strategy1.py --rules
cd backtest && python run.py kaicheng --no-open
```

## 如何扩展

1. **新因子**：`factors/factorN.py`，实现 `levels/filters_ok/signal`，`register_factor`
2. **新策略包**：`strategies/strategyN/{bindings,decision,__init__}.py`，设置 `decision_factory` +（可选）`run`
3. **改组合/过滤**：只改该策略的 `bindings.py`，不动因子与其它策略决策

## 兼容

| 旧 API | 新等价 |
|--------|--------|
| `get_strategy("open_break3")` | `get_strategy("strategy1")` |
| `run_open_break` | `run_strategy1` / `get_strategy("strategy1").run` |
| `OpenBreak3Strategy` | `Strategy1` |
| `from strategy.open_break import strategy_signal` | 仍可用；或 `get_factor("factor1").signal` |
