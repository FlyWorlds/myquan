# 因子18 · 低开跌停情绪

> 大盘情绪择时因子，不构成投资建议。本身不下单。

中证1000（剔 ST / 北交）每日 **低开开盘即跌停** 家数：

- 平静 ≤0
- 正常 1～3
- 恐慌 ≥4

开盘即可观测，无未来函数。研判（样本内）：恐慌日上证均 −2.05%、收涨仅 30%；平静日略偏涨。详见 `backtest/strategy9_limit_down_emotion/REPORT.md`。

## 挂到策略

当前组合：**策略十二** = 因子18 恐慌日空仓 + 因子21 涨停次日低开（研究，**OOS 未过关**）。

已否决：恐慌日叠凯盛/天通因子1 禁买；压力日买最深低开；跌停次日开板。

CLI 对照（不上 Web 策略栏）：`run_strategy9_emotion()` / `python backtest/strategy9_limit_down_emotion/run.py`。

真源：`strategy/factors/factor18.py` · 阶段划分：`strategy/strategies/strategy9/sentiment_phase.py`
