# strategy — OpenBreak3 开盘±pct

## 结构

```
strategy/
├── open_break.py        # 规则、信号、945 逻辑
├── backtest.py          # OpenBreak3Strategy + 报告摘要
├── config.py            # BacktestConfig、标的预设
├── runner.py            # run_open_break 入口
├── gap945_analysis.py   # 945 规则专项分析
├── data.py              # 日线拉取
├── minute.py            # 1 分钟线
├── base.py              # akquant 回测骨架
└── registry.py          # 策略注册（仅 open_break3）

huice/
├── strategy1.py           # 凯盛科技
├── tiantong.py            # 天通股份
├── zhaoyi.py              # 兆易创新
├── zz500.py               # 中证500 ETF（同策略）
├── gap945_hold_stats.py   # 945 持仓统计
└── gap945_pnl_compare.py  # 945 盈亏对比
```

## 策略说明

开盘相对昨收 **±pct** 触发买卖：

- **买**：high ≥ ceil(open×(1+pct))，且前日须阴线或小阳，禁前面双阳
- **卖**：① 低开 09:45 未翻红全清；② 开盘 -pct 止损；③ 阴线收盘出；阳/十字持有

默认 pct = 2.5%，佣金万 0.854，滑点 0.1%。

## 用法

```python
from dataclasses import replace
from pathlib import Path
from strategy import BacktestConfig, run_open_break

cfg = BacktestConfig(
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    report_path=Path("天通股份_report.html"),
)
run_open_break(cfg, show_report=True)
```

```bash
cd huice && python tiantong.py --rules
```

注册表：

```python
from strategy.registry import get_strategy
get_strategy("open_break3").run(get_strategy("open_break3").default_config)
```
