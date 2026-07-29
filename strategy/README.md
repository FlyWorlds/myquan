# strategy — 多策略模块化框架

## 分层

```
strategy/
├── data.py              # 共用：fetch_daily
├── minute.py            # 共用：1 分钟线
├── base.py              # 共用：run_backtest_pipeline
├── registry.py          # 策略注册表
│
├── open_break.py        # 【策略1 OpenBreak3】
├── backtest.py          # 【策略1】OpenBreak3Strategy
├── config.py            # 【策略1】
├── runner.py            # 【策略1】
├── gap945_analysis.py   # 【策略1 专用分析】
│
└── yin_yang/            # 【策略2 独立】日线阴阳
    ├── rules.py
    ├── backtest.py
    ├── config.py
    ├── runner.py
    └── summary.py

huice/
├── strategy1.py         # OpenBreak3 凯盛
├── yin_yang1.py         # YinYang 凯盛
└── ...
```

## 现有策略

| id | 说明 | 回测入口 |
|----|------|----------|
| `open_break3` | 开盘±pct + 945 全清 | `huice/strategy1.py` |
| `open_break3_zz500` | 同上，510580 ETF | `huice/zz500.py` |
| `yin_yang` | 日线阳买阴卖（独立） | `huice/yin_yang1.py` |

```python
from strategy.registry import get_strategy, list_strategies

for s in list_strategies():
    print(s.id, s.name)

entry = get_strategy("open_break3")
entry.run(entry.default_config, show_report=True)
if entry.print_rules:
    print(entry.print_rules())
```

---

## 接入新策略（四步）

### 1. 新建策略包（建议目录）

```
strategy/
  my_strategy/
    rules.py      # STRATEGY_RULES、signal 纯函数
    backtest.py   # class MyStrategy(Strategy)
    config.py     # @dataclass MyConfig(CommonBacktestParams)
    runner.py     # def run_my_strategy(cfg, **kw)
```

也可平铺在 `strategy/` 下，例如 `strategy/chanlun_rules.py` + `strategy/chanlun_backtest.py`。

### 2. 实现 rules + Strategy 类

- **rules.py**：不写 akquant 依赖，方便回测与盯盘共用
- **backtest.py**：继承 `akquant.Strategy`，在 `on_bar` 里调用 rules

### 3. 实现 runner

复用 `base.run_backtest_pipeline`：

```python
from strategy.base import run_backtest_pipeline
from strategy.my_strategy.backtest import MyStrategy
from strategy.backtest import print_summary  # 或自定义摘要

def _configure(cls, cfg):
    cls.symbol = cfg.symbol
    # ...

def run_my_strategy(cfg, *, show_report=False, verbose=True):
    return run_backtest_pipeline(
        params=cfg,
        strategy_cls=MyStrategy,
        configure=_configure,
        print_summary_fn=print_summary,
        summary_kwargs={...},
        report_title=f"{cfg.symbol_name} MyStrategy ...",
        show_report=show_report,
        verbose=verbose,
    )
```

### 4. 注册 + 薄 CLI

**registry.py**：

```python
"my_strategy": StrategyEntry(
    id="my_strategy",
    name="我的策略",
    run=run_my_strategy,
    default_config=MY_PRESET,
    print_rules=lambda: MY_STRATEGY_RULES.strip(),
),
```

**huice/my_strategy1.py**（~15 行）：

```python
from strategy.registry import get_strategy
entry = get_strategy("my_strategy")
entry.run(entry.default_config, show_report=True)
```

### 5. 盯盘（可选）

在 `holdingStocks/index.py` 的 WATCHLIST 增加 `strategy_id` 字段，按 id 调用对应 `rules.strategy_signal`。

---

## 共用 vs 策略私有

| 共用（strategy/data, minute, base） | 策略私有 |
|-------------------------------------|----------|
| 日线/分钟线拉取 | 买卖规则、过滤条件 |
| akquant 回测骨架 | Strategy 类 |
| HTML 报告流程 | 专属 config / 分析脚本 |

`_misc/demo.py`、`quan.py` 可逐步迁入 `strategy/chanlun/` 等独立包，与 OpenBreak3 并列。

---

## OpenBreak3 快捷用法

```python
from dataclasses import replace
from pathlib import Path
from strategy import BacktestConfig, run_open_break

cfg = BacktestConfig(
    symbol="sz002171",
    symbol_name="楚江新材",
    em_symbol="002171",
    report_path=Path("楚江新材_report.html"),
)
run_open_break(cfg, show_report=True)
```

```bash
cd myquan/huice && python strategy1.py --rules
```
