# myquan — AKQuant 框架接入说明

本目录基于 [AKQuant](https://github.com/akfamily/akquant) 做 A 股策略回测与盯盘。

**运行时依赖**：全局 / pip 安装的 `akquant`（见 `requirements.txt`，当前钉死 `0.3.21`）。  
**旁挂源码**：同级目录 `../akquant/` 仅供阅读、对照实现，**不会**自动进入 `PYTHONPATH`。若要改用本地可编辑安装：

```bash
cd ../akquant && uv sync && uvx maturin develop
# 或：pip install -e ../akquant
```

---

## 框架概览

**AKQuant** 是 Rust 内核 + Python 策略层的混合量化框架。

**数据流：**

```
akshare DataFrame
    → normalize / load_bar_from_df
    → Bar → Strategy.on_bar → Execution → Statistics
    → BacktestResult
```

---

## 安装

```bash
cd myquan
pip install -r requirements.txt
```

官方文档：<https://akquant.akfamily.xyz/>

---

## 本项目结构

```
myquan/
├── READA.md                 # 本文档
├── requirements.txt         # 运行依赖（含 akquant 版本钉死）
├── strategy/                # OpenBreak3 规则 / 回测 / 配置
│   ├── open_break.py        # 纯规则（回测与盯盘共用）
│   ├── backtest.py          # akquant Strategy
│   ├── runner.py            # run_open_break（实例传参）
│   ├── base.py              # run_backtest_pipeline 骨架
│   └── data.py              # 日线缓存（个股 / ETF 分流）
├── backtest/                # 回测 CLI
│   ├── run.py               # 统一入口：python run.py kaicheng
│   ├── strategy1.py         # 薄封装 → 预设
│   └── universe_zz500_1000.py
├── holdingStocks/           # 持仓盯盘
│   ├── index.py             # CLI / HTML / watch
│   ├── watch_config.py      # 标的池
│   └── quote_feed.py        # SSE / WS
├── sectors/                 # 板块轮动（不依赖 akquant）
└── data_cache/              # 前复权日线 parquet
```

运行示例：

```bash
cd myquan/backtest && python run.py --list
cd myquan/backtest && python run.py kaicheng
cd myquan/backtest && python strategy1.py --rules
cd myquan/holdingStocks && python index.py
cd myquan/sectors && python index.py
```

---

## 最小接入示例

```python
import akquant as aq
from akquant import Strategy, CurrentClose

class MyStrategy(Strategy):
    def on_bar(self, bar):
        if self.get_position(bar.symbol) == 0 and bar.close > bar.open:
            self.buy(symbol=bar.symbol, quantity=100)

result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    symbols="sh600000",
    initial_cash=100_000.0,
    lot_size=100,
    t_plus_one=True,
    fill_policy=CurrentClose(),  # 0.3.x 用 FillMode，不再用 dict
)
```

本项目：

```python
from strategy import KAICHENG, run_open_break
run_open_break(KAICHENG, show_report=True)
```

---

## 回测要点（akquant 0.3.x）

```python
from akquant import CurrentClose

result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,       # 也可传策略实例
    symbols="sh600000",
    lot_size=100,
    t_plus_one=True,
    timezone="Asia/Shanghai",
    fill_policy=CurrentClose(),
    slippage={"type": "percent", "value": 0.001},
)
```

- `CurrentClose` 控制**成交时点**（当根可撮合）。限价单的 `price=` 仍按**限价 ± 滑点**成交。
- 旧版 `fill_policy={"price_basis": "close", ...}` 已移除，勿再使用。
- OpenBreak3 通过实例写入参数（`apply_strategy_config`），避免类属性并行串扰。

| 资产 | 接口 | 说明 |
|------|------|------|
| A 股 | `stock_zh_a_daily` | `strategy.data` 默认 |
| ETF | `fund_etf_hist_em` | `sh51*` / `sz15*` 等自动分流 |

日线缓存：`data_cache/<symbol>_daily_qfq.parquet`。标的不符或相邻 K 线日历缺口过大时自动全量重拉；`force_daily_refresh=True` 可手动全量。

---

## 参考

- 官方文档：<https://akquant.akfamily.xyz/>
- 旁挂源码示例：`../akquant/examples/README.md`
- 策略说明：`strategy/README.md`、`strategy/STRATEGY_AUDIT.md`
