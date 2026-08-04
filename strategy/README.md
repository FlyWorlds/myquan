# strategy — OpenBreak3 开盘±pct

## 结构

```
strategy/
├── open_break.py        # 规则与盯盘信号
├── backtest.py          # OpenBreak3Strategy + 报告摘要
├── config.py            # BacktestConfig、标的预设
├── runner.py            # run_open_break 入口
├── data.py              # 日线拉取
├── minute.py            # 通用分钟线工具
├── base.py              # akquant 回测骨架
└── registry.py          # 策略注册（仅 open_break3）

huice/
└── strategy1.py           # 凯盛科技
```

## 当前生效策略（因子1 · 唯一在用）

默认阈值 **±2.5%**。买卖均相对当日开盘（买入另有前日过滤）。

**买**

- 触发：`high ≥ ceil(open × 1.025)`，按触发价限价，仓位约 95%
- 过滤：前一日为阴线，或小阳（收盘涨幅严格 &lt; 2.5%）；且前面不能连续两根阳线
- T+1：买入当日不可卖（ETF 可设 `t0=True`）

**卖（优先级从高到低）**

1. 开盘 −2.5% 止损 → **全清**
2. 未触止损 → 无论阴线、阳线或十字均继续持有

低开定时退出、阴线收盘退出、减半、回撤仓位和同日再买代码均已从生效路径移除。

## 用法

```python
from dataclasses import replace
from pathlib import Path
from strategy import BacktestConfig, run_open_break

cfg = BacktestConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    report_path=Path("凯盛科技_report.html"),
)
run_open_break(cfg, show_report=True)
```

```bash
cd huice && python strategy1.py --rules
```

注册表：

```python
from strategy.registry import get_strategy
get_strategy("open_break3").run(get_strategy("open_break3").default_config)
```
