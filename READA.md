# myquan — AKQuant 框架接入说明

本目录基于 [AKQuant](https://github.com/akfamily/akquant) 做 A 股策略回测。框架源码位于同级目录 `../akquant/`。

---

## 框架概览

**AKQuant** 是 Rust 内核 + Python 策略层的混合量化框架：

| 层级 | 路径 | 职责 |
|------|------|------|
| Rust 核心 | `akquant/src/` | 引擎、撮合、风控、统计、事件管道 |
| Python 绑定 | `akquant/python/akquant/akquant.pyi` | `Engine`、`Bar`、`Order` 等原生类型 |
| Python 封装 | `akquant/python/akquant/` | 策略基类、回测入口、数据归一化、报告 |
| 示例 | `akquant/examples/` | 70+ 可运行示例 |

**数据流：**

```
akshare DataFrame
    → normalize / load_bar_from_df
    → Bar 列表 或 NumPy 数组（Zero-Copy 进 Rust）
    → Pipeline: Data → Strategy.on_bar → Execution → Statistics
    → BacktestResult
```

---

## 安装

```bash
pip install akquant akshare pandas
# 可选：可视化报告
pip install "akquant[plot]"
```

本地源码开发（使用仓库内 `../akquant`）：

```bash
cd ../akquant
uv sync
uvx maturin develop
```

官方文档：<https://akquant.akfamily.xyz/>

---

## 本项目结构

```
myquan/
├── READA.md                 # 本文档
├── holdingStocks/           # 持仓盯盘（多标的）
├── zz500/                   # 中证500ETF (510500)
│   ├── ZZ500ETF.py          # 主策略（参数优化）
│   ├── zz500ETF2.py         # 开盘±N% / 首阳连阳
│   ├── zz500ETF3.py         # 动态牛熊版
│   └── 510500_*.parquet/csv # 行情缓存与报告
├── hs300/                   # 沪深300ETF (510300)
│   ├── HS300ETF.py
│   └── 510300_*             # 缓存与报告
├── kskj600552/              # 凯盛科技 (600552)
│   ├── KSKJ600552.PY        # 开盘±2.5% 策略
│   └── _scan_*.py           # 参数扫描
└── _misc/                   # 示例杂项（demo / quan）
```

运行示例：

```bash
cd myquan/zz500 && python ZZ500ETF.py
cd myquan/hs300 && python HS300ETF.py
cd myquan/kskj600552 && python KSKJ600552.PY
cd myquan/holdingStocks && python index.py
```

---

## 最小接入示例

与 `quan.py` 对应的推荐写法（已修正 A 股参数与 API）：

```python
import akquant as aq
import akshare as ak
from akquant import Strategy

df = ak.stock_zh_a_daily(
    symbol="sh600000",
    start_date="20250430",
    end_date="20260503",
)


class MyStrategy(Strategy):
    def on_bar(self, bar):
        pos = self.get_position(bar.symbol)
        if pos == 0 and bar.close > bar.open:
            self.buy(symbol=bar.symbol, quantity=100)
        elif pos > 0 and bar.close < bar.open:
            self.close_position(symbol=bar.symbol)


result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    initial_cash=100_000.0,
    symbols="sh600000",
    lot_size=100,       # A 股一手 100 股（默认 1，必须显式设置）
    t_plus_one=True,    # A 股 T+1
)

print(result)

# 基准对比报告
benchmark = (
    df.set_index("date")["close"]
    .pct_change()
    .fillna(0.0)
    .rename("BENCH")
)
result.viz.report(
    filename="report.html",
    show=False,
    benchmark=benchmark,
)
```

---

## 核心 API

### 1. 回测入口 `run_backtest`

```python
import akquant as aq

result = aq.run_backtest(
    data=df,                          # DataFrame / dict[str, DataFrame] / list[Bar]
    strategy=MyStrategy,              # 策略类 / 实例 / on_bar 回调函数
    symbols="sh600000",               # 单标的或列表
    initial_cash=100_000.0,
    lot_size=100,                     # int 全局，或 dict[str, int] 按标的
    t_plus_one=True,
    timezone="Asia/Shanghai",         # 默认上海时区
    commission_rate=0.0003,           # 佣金率
    stamp_tax_rate=0.001,             # 印花税（卖出）
    slippage={"type": "percent", "value": 0.0002},
    volume_limit_pct=0.25,            # 成交量限制比例
    history_depth=60,                 # 自动维护历史 K 线长度
    show_progress=True,
    start_time="2025-01-01",          # 可选：回测区间
    end_time="2026-01-01",
    fill_policy={                     # 成交语义
        "price_basis": "close",       # open / close / ohlc4 / hl2
        "bar_offset": "0",            # 0 当根 / 1 下一根
        "temporal": "same_cycle",     # same_cycle / next_event
    },
    broker_profile="cn_stock_t1_low_fee",  # 预设 A 股参数模板
    on_event=callback,                # 流式事件回调（可选）
)
```

**配置优先级（高 → 低）：** 函数显式参数 > `BacktestConfig` 对象 > 默认值。

**函数式策略（无需继承 Strategy）：**

```python
def on_bar(ctx, bar):
    if ctx.get_position(bar.symbol) == 0:
        ctx.buy(symbol=bar.symbol, quantity=100)

result = aq.run_backtest(data=df, strategy=on_bar, symbols="sh600000")
```

---

### 2. 策略基类 `Strategy`

继承 `akquant.Strategy`，重写事件钩子：

| 方法 | 触发时机 |
|------|----------|
| `on_bar(bar)` | 每根 K 线（最常用） |
| `on_tick(tick)` | Tick 数据 |
| `on_timer(payload)` | 定时器 |
| `on_start()` | 回测 / 实盘启动 |
| `on_stop()` | 结束 |
| `on_order(order)` | 订单状态变化 |
| `on_trade(trade)` | 成交 |
| `on_reject(order)` | 拒单 |
| `on_before_trading(date_ns)` | 盘前 |
| `on_after_trading(date_ns)` | 盘后 |
| `on_pre_open(ctx)` | 集合竞价前决策 |
| `on_cross_section(bars, date_ns)` | 横截面（多标的） |
| `on_portfolio_update(state)` | 组合更新 |
| `on_train_signal()` | ML 滚动训练信号 |
| `on_expiry(event)` | 期货 / 期权到期 |

**策略参数声明（用于网格搜索）：**

```python
from akquant import Strategy, IntParam, FloatParam

class MyStrategy(Strategy):
    window = IntParam(default=20, min=5, max=60)
    threshold = FloatParam(default=0.02)

    def on_bar(self, bar):
        w = self.params.window  # 通过 self.params 访问
        ...
```

---

### 3. 交易 API

| 方法 | 说明 |
|------|------|
| `buy(symbol, quantity, price=None)` | 买入；`price=None` 为市价 |
| `sell(symbol, quantity, price=None)` | 卖出；quantity 省略则卖全部 |
| `short()` / `cover()` | 做空 / 平空 |
| `close_position(symbol)` | 平掉当前标的全部持仓 |
| `submit_order(...)` | 底层下单 |
| `cancel_order(order_id)` | 撤单 |
| `cancel_all_orders(symbol)` | 撤销全部挂单 |
| `place_oco(id1, id2)` | OCO 联动单 |
| `place_bracket(...)` | 括号单（进场 + 止损 + 止盈） |
| `order_target(symbol, target)` | 目标持仓数量 |
| `order_target_percent(symbol, pct)` | 目标仓位比例 |
| `order_target_value(symbol, value)` | 目标市值 |
| `rebalance_weights(weights)` | 按权重调仓 |
| `rebalance_positions(targets)` | 按目标仓位调仓 |

**查询 API：**

| 方法 | 说明 |
|------|------|
| `get_position(symbol)` | 持仓数量 |
| `get_available_position(symbol)` | 可用持仓（T+1 后） |
| `get_positions()` | 全部持仓 dict |
| `get_cash()` | 可用现金 |
| `get_portfolio_value()` | 组合总市值 |
| `get_buying_power()` | 购买力 |
| `get_open_orders(symbol)` | 未完成订单 |
| `get_holding_bars(symbol)` | 持仓 Bar 数 |
| `get_history(count, symbol)` | 历史 K 线（Rust 缓冲，推荐替代手动 list） |
| `get_history_df(count, symbol)` | 历史 K 线 DataFrame |

**Sizer（默认下单量）：**

```python
from akquant import FixedSize, PercentSizer, AllInSizer

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__()
        self.sizer = PercentSizer(0.1)  # 每次用 10% 资金
```

---

### 4. Bar 数据结构

```python
bar.timestamp      # int，Unix 纳秒时间戳
bar.timestamp_iso  # str，UTC ISO 8601（推荐用于日志）
bar.symbol         # 标的代码
bar.open / high / low / close / volume
bar.extra          # dict，扩展字段
```

> 注意：Bar **没有** `timestamp_str` 属性，请使用 `timestamp_iso` 或自行格式化。

---

### 5. 回测结果 `BacktestResult`

```python
result                          # 打印指标摘要
result.equity_curve             # pd.Series 权益曲线
result.daily_returns            # 日收益率
result.trades_df                # 成交明细
result.orders_df                # 订单明细
result.positions_df             # 持仓快照
result.metrics_df               # 夏普、回撤、胜率等
result.closed_trades            # 已平仓交易列表

# 结构化分析
result.exposure_df()
result.attribution_df(by="symbol")
result.capacity_df()
```

**可视化（`result.viz` 命名空间）：**

```python
result.viz.report(filename="report.html", benchmark=benchmark_returns)
result.viz.dashboard()          # Plotly 交互仪表盘
result.viz.indicators()         # 指标图
result.viz.quantstats()         # QuantStats 报告
result.viz.review()             # LWC K 线交易复盘
```

> 注意：报告入口是 `result.viz.report()`，不是 `result.report()`。

---

### 6. AKShare 接入

AKQuant **不绑定** AKShare，但官方示例和本项目均以 AKShare 作为行情数据源。接入只需两步：**拉取 → 标准化列名 → 传入 `run_backtest`**。

#### 6.1 安装

```bash
pip install akshare akquant pandas
pip install akshare --upgrade   # 分钟线接口更新频繁，建议保持最新
```

#### 6.2 标准清洗模板

AKShare 返回中文列名，需转为 AKQuant 规范格式后再回测：

```python
import akshare as ak
import pandas as pd

RENAME = {
    "日期": "date", "时间": "date",
    "开盘": "open", "最高": "high", "最低": "low",
    "收盘": "close", "成交量": "volume",
}

def to_akquant_df(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = raw.rename(columns=RENAME)[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    df["symbol"] = symbol          # 必须！与 run_backtest(symbols=...) 一致
    return df
```

框架也内置列名别名识别（`date/日期`、`open/开盘` 等），但**显式标准化更稳妥**。

#### 6.3 常用接口对照

| 资产类型 | AKShare 接口 | symbol 格式 | 频率 | 本项目示例 |
|----------|-------------|-------------|------|-----------|
| A 股日线 | `ak.stock_zh_a_daily()` | `sh600000` / `sz000001` | 日线 | `demo.py` |
| A 股日线 | `ak.stock_zh_a_hist()` | `600000`（纯数字） | 日/周/月 | 教材 ch03 |
| A 股分钟 | `ak.stock_zh_a_hist_min_em()` | `600000` | 1/5/15/30/60 分 | — |
| ETF 日线 | `ak.fund_etf_hist_em()` | `510500` | 日线 | — |
| ETF 分钟 | `ak.fund_etf_hist_min_em()` | `510500` | 1/5/15/30/60 分 | `zz500.py`（首选） |
| 新浪分钟 | `ak.stock_zh_a_minute()` | `sh510500`（带前缀） | 1/5/15/30/60 分 | `zz500.py`（备用） |
| 内置封装 | `fetch_akshare_symbol()` | `600519`（自动加前缀） | 日线 | — |

#### 6.4 A 股日线（demo.py 用法）

```python
import akquant as aq
import akshare as ak
from akquant import Strategy

df = ak.stock_zh_a_daily(
    symbol="sh600000",
    start_date="20250212",
    end_date="20260212",
)
df = to_akquant_df(df, symbol="sh600000")

result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    symbols="sh600000",       # 与 df["symbol"] 一致
    initial_cash=100_000.0,
    lot_size=100,
    t_plus_one=True,
    timezone="Asia/Shanghai",
)
```

或使用框架内置 fetch（自动标准化，但不含 `symbol` 列，需自行添加）：

```python
from akquant import fetch_akshare_symbol

df = fetch_akshare_symbol("600000", "20250212", "20260212", adjust="qfq")
df["symbol"] = "600000"
```

#### 6.5 ETF 日线

```python
df = ak.fund_etf_hist_em(
    symbol="510500",
    period="daily",
    start_date="20260401",
    end_date="20260630",
    adjust="qfq",
)
df = to_akquant_df(df, symbol="510500")
```

#### 6.6 ETF / 股票 分钟线（zz500.py 用法）

```python
# 东方财富 30 分钟（部分网络环境可能连接失败）
df = ak.fund_etf_hist_min_em(
    symbol="510500",
    period="30",
    adjust="qfq",
    start_date="2026-04-01 09:30:00",
    end_date="2026-06-30 15:00:00",
)
df = to_akquant_df(df, symbol="510500")

# 新浪 30 分钟（备用，通常更稳定）
df = ak.stock_zh_a_minute(symbol="sh510500", period="30", adjust="qfq")
df = to_akquant_df(df, symbol="510500")
```

分钟线注意：
- 东财 `fund_etf_hist_min_em` / `stock_zh_a_hist_min_em` 共用 `push2his.eastmoney.com`，网络不稳时可切新浪
- 1 分钟数据仅近 5 个交易日；30/60 分钟可拉更长历史
- 建议本地缓存 Parquet，避免重复请求（见 `zz500.py` 的 `510500_30m.parquet`）

#### 6.7 多标的 ETF 拼接

```python
ETF_LIST = ["510300", "510500", "159915"]
frames = []
for code in ETF_LIST:
    raw = ak.fund_etf_hist_em(symbol=code, period="daily",
                              start_date="20200101", end_date="20251231", adjust="qfq")
    frames.append(to_akquant_df(raw, symbol=code))

df_all = pd.concat(frames).sort_values(["date", "symbol"]).reset_index(drop=True)

result = aq.run_backtest(
    data=df_all,
    strategy=ETFRotationStrategy,
    symbols=ETF_LIST,
    lot_size=100,
    t_plus_one=True,
)
```

#### 6.8 接入后传入 AKQuant 的方式

| 方式 | 代码 | 场景 |
|------|------|------|
| DataFrame 直传 | `run_backtest(data=df, ...)` | 最常用 |
| dict 分标的 | `run_backtest(data={"510500": df1, ...})` | 多文件 |
| 本地 Parquet | `write_canonical_parquet(df, "x.parquet")` | 缓存 / 大数据 |
| Catalog | `ParquetDataCatalog().write("510500", df)` | 持久化目录 |

#### 6.9 symbols 与代码格式

| 数据源 | symbol 示例 | run_backtest symbols |
|--------|------------|---------------------|
| `stock_zh_a_daily` | 接口用 `sh600000` | `"sh600000"` |
| `stock_zh_a_hist` | 接口用 `600000` | `"600000"` |
| `fund_etf_hist_em` | 接口用 `510500` | `"510500"` |
| `stock_zh_a_minute` | 接口用 `sh510500` | `"510500"`（df 里写什么就传什么） |

**规则：`df["symbol"]` 必须与 `run_backtest(symbols=...)` 完全一致。**

#### 6.10 A 股回测参数（AKShare 数据必配）

```python
result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    symbols="510500",
    lot_size=100,              # A 股/ETF 一手 100 份
    t_plus_one=True,           # T+1
    timezone="Asia/Shanghai",
    commission_rate=0.0003,
    stamp_tax_rate=0.001,      # 卖出印花税
    broker_profile="cn_stock_t1_low_fee",  # 一键 A 股默认参数
)
```

#### 6.11 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `ConnectionError` / `RemoteDisconnected` | 东财接口网络问题 | 换新浪 `stock_zh_a_minute`；关 VPN/代理 |
| 回测无成交 | `symbols` 与 `df["symbol"]` 不一致 | 统一代码格式 |
| 分钟数据为空 | 日期超出接口范围 | 缩短区间或换数据源 |
| 列名报错 | 未标准化 | 用 `to_akquant_df()` 清洗 |
| 买入日无成交 | 节假日休市 | 改为「买入日及之后首个交易日」 |

#### 6.12 本项目文件对照

| 文件 | AKShare 接口 | 频率 |
|------|-------------|------|
| `demo.py` | `stock_zh_a_daily("sh600000")` | 日线 |
| `quan.py` | `stock_zh_a_daily("sh600000")` | 日线 |
| `zz500.py` | `fund_etf_hist_min_em` → 新浪 `stock_zh_a_minute` 回退 | 30 分钟 |

参考框架示例：`akquant/examples/59_akshare_etf_rotation.py`

---

### 7. 其他数据接入

**Parquet 目录：**

```python
result = aq.run_backtest(catalog_path="/path/to/parquet", strategy=MyStrategy)
```

**列名自动识别：** 框架 `schema.COLUMN_ALIASES` 支持 `date/日期`、`open/开盘` 等中英文别名，但 AKShare 接入建议显式标准化。

---

## 框架支持的功能

### 回测与执行

- 多标的、多频率（日 / 小时 / 分钟，via `DataFeedAdapter`）
- 混合资产：股票、期货、期权、基金、Crypto、Forex
- T+1、涨跌停、停牌、成交量限制
- 佣金 / 印花税 / 过户费 / 最低佣金
- 滑点：`percent` / `fixed` / `ticks` / `zero`
- 成交语义：`fill_policy`（价格基准、Bar 偏移、时序）
- 复杂订单：OCO、Bracket、Trailing Stop
- 流式回测：`on_event` 实时消费进度 / 权益 / 成交事件
- 断点续跑：`save_checkpoint` / `load_checkpoint` / `run_from_checkpoint`

### 策略开发

- 类风格 / 函数式策略
- 策略参数模型 + 网格搜索 / Walk-Forward 优化
- 内置指标：`SMA`、`EMA`、`MACD`、`RSI`、`BollingerBands`、`ATR`
- TA-Lib 兼容：`akquant.talib`（103 个指标，python/rust 双后端）
- 自定义指标：`Indicator` / `indicator_factory`（增量 / 预计算）
- 定时器：`schedule` / `schedule_daily` / `schedule_weekly`
- 横截面：`on_cross_section` + `rebalance_weights`
- Analyzer 插件：扩展 `on_bar` / `on_trade` / `on_finish` 生命周期

### 风控

- 单票仓位上限、行业集中度
- 策略级：单笔金额 / 数量 / 持仓 / 日内亏损 / 回撤限制
- 账户级风险预算
- 信用账户 / 强平审计（`margin` 模式）

### 机器学习

- Walk-Forward 滚动训练框架
- `on_train_signal` + PyTorch / Scikit-learn 集成
- 模型热切换（pending → active）

### 因子引擎

- Polars 驱动的高性能因子计算
- Alpha101 风格表达式：`Rank(Ts_Mean(Close, 5))` 等

### 参数优化

```python
from akquant import run_grid_search, run_walk_forward

opt = run_grid_search(
    data=df,
    strategy=MyStrategy,
    param_grid={"window": [10, 20, 30]},
    symbols="sh600000",
)
print(opt.best_params, opt.best_result)
```

### 实盘（Gateway）

- `run_live()` 统一入口
- 内置 Broker：CTP、MiniQMT、PTrade
- 本地止损簿、订单审计、断线恢复

### 可视化与报告

- 原生 HTML 报告（权益 / 回撤 / 月度热力图 / 基准对比）
- Plotly 交互仪表盘
- QuantStats 报告
- Lightweight Charts K 线复盘

---

## A 股回测注意事项

| 项目 | 推荐值 | 说明 |
|------|--------|------|
| `lot_size` | `100` | 默认 1，A 股必须显式设置 |
| `t_plus_one` | `True` | 启用 T+1，卖出受可用持仓约束 |
| `symbols` | 与数据一致 | akshare 用 `sh600000`，或 DataFrame 加 `symbol` 列 |
| `commission_rate` | `0.0003` 左右 | 可按券商实际调整 |
| `stamp_tax_rate` | `0.001` | 卖出印花税 |
| `broker_profile` | `"cn_stock_t1_low_fee"` | 一键注入 A 股常用默认值 |

**用框架历史缓冲替代手动维护 bars：**

```python
class MyStrategy(Strategy):
    def on_bar(self, bar):
        hist = self.get_history(20, bar.symbol)  # 最近 20 根
        closes = [b.close for b in hist]
        ...
```

---

## 常用 import 速查

```python
import akquant as aq
from akquant import (
    Strategy,
    Bar,
    BacktestConfig,
    StrategyConfig,
    FixedSize,
    PercentSizer,
    Indicator,
    IntParam,
    FloatParam,
    run_grid_search,
    run_walk_forward,
    fetch_akshare_symbol,
    load_bar_from_df,
    prepare_dataframe,
)
```

---

## 运行本项目

```bash
cd myquan
python quan.py
```

生成报告后可在浏览器打开 `chan_daily_strategy.html`。

---

## 参考链接

- 官方文档：<https://akquant.akfamily.xyz/>
- API 参考：<https://akquant.akfamily.xyz/reference/api.html>
- 示例索引：`../akquant/examples/README.md`
- 快速入门示例：`../akquant/examples/01_quickstart.py`
- README 演示：`../akquant/examples/17_readme_demo.py`
