# 因子18 · 低开跌停情绪

> 大盘情绪门控因子，不构成投资建议。本身不下单。

中证1000（剔 ST / 北交）每日 **低开开盘即跌停** 家数：

- 平静 ≤0
- 正常 1～3
- 恐慌 ≥4

开盘即可观测，无未来函数。研判（样本内）：恐慌日上证收跌概率偏高；平静日收涨略多。详见 `backtest/strategy9_limit_down_emotion/REPORT.md`。

## 挂到策略

Web **因子说明 → 情绪题材**。任意策略 `bindings.py`：

```python
from strategy.core.protocols import bind_factor

bind_factor(
    "factor18",
    label="低开跌停情绪门控",
    role="filter",
    filter_desc="恐慌日禁止新开仓",
)
```

当前交易组合：**策略十二** = 因子18 门控 + 因子1 执行 + 因子2 预警。

CLI 对照（不上 Web 策略栏）：`run_strategy9_emotion()` / `python backtest/strategy9_limit_down_emotion/run.py`。

真源：`strategy/factors/factor18.py` · 阶段划分：`strategy/strategies/strategy9/sentiment_phase.py`
