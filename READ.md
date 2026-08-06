<!-- # myquan — AKQuant 框架接入说明 -->

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

**本项目策略分层（开闭原则）：**

```
因子层 (factors)           → 价位 / 信号 / 通用过滤
策略层 (bindings)          → 本策略挂哪些因子、参数、专属过滤器
决策层 (decision)          → MarketContext → Decision(buy|sell|hold)
执行层 (runner / backtest / 盯盘) → 下单、回测、预警推送
```

**当前生效**：**策略一 · 因子1**（开盘 ±2.5%，OpenBreak3）。  
买：`high ≥ ceil(open×1.025)`，前日阴线或小阳，禁前面双阳，T+1。  
卖：仅止损 −2.5% 全清。完整规则：

```bash
python -c "from strategy import STRATEGY_RULES; print(STRATEGY_RULES)"
# 或：cd backtest && python strategy1.py --rules
# 决策层：python -c "from strategy import get_decision_engine, MarketContext; ..."
```

分层细节见 [`strategy/README.md`](strategy/README.md)。

**进度（见 [`TODO.MD`](TODO.MD)）**：P0 已完成（WebSocket 实时行情 + 微信预警推送）；下一步为 P1 选股因子框架。

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
├── READ.md                  # 本文档
├── TODO.MD                  # 任务优先级（P0 已完成）
├── requirements.txt         # 运行依赖
├── test_strategy_rules.py   # 离线规则回归（不访问网络）
├── strategy/                # 可插拔策略框架（详见 strategy/README.md）
│   ├── core/                # 协议 / MarketContext / Decision / 注册表
│   ├── factors/             # 因子1(生效) · 因子2/3(占位)
│   ├── strategies/          # strategyN/{bindings,decision} 策略层+决策层
│   ├── open_break.py        # 因子1 规则真源（回测与盯盘共用）
│   ├── backtest.py          # akquant Strategy（执行层）
│   ├── config.py / runner.py / data.py / minute.py
│   └── registry.py          # 兼容 get_strategy / get_decision_engine
├── backtest/                # 回测 CLI / 标的脚本 / 合格池
│   ├── run.py               # 统一入口：python run.py kaicheng
│   ├── strategy1.py         # 薄封装 → 预设
│   ├── universe_zz500_1000.py
│   └── read.md              # 合格标的池说明
├── holdingStocks/           # 持仓盯盘 + 微信预警
│   ├── index.py             # CLI / HTML / watch
│   ├── watch_config.py      # 标的池
│   ├── quote_feed.py        # 东财 SSE + 新浪兜底 + 本地 WS
│   ├── wechat_notify.py     # OpenClaw 微信推送（不走大模型）
│   └── weChat接入.md
├── sectors/                 # 板块轮动（不依赖 akquant）
└── data_cache/              # 前复权日线 parquet
```

运行示例：

```bash
# 回测
cd myquan/backtest && python run.py --list
cd myquan/backtest && python run.py kaicheng
cd myquan/backtest && python strategy1.py --rules

# 离线规则测试
cd myquan && python -m unittest -v test_strategy_rules.py

# 持仓盯盘（一次性 / 长驻）
cd myquan/holdingStocks && python index.py
cd myquan/holdingStocks && python index.py watch --interval 5 --port 8765
# 浏览器：http://127.0.0.1:8765/holdings_report.html
# 默认开启微信预警；关闭：--no-wechat；自检：python index.py wechat-test

# 板块轮动
cd myquan/sectors && python index.py
```

盯盘细节见 [`holdingStocks/README.md`](holdingStocks/README.md)；微信接入见 [`holdingStocks/weChat接入.md`](holdingStocks/weChat接入.md)。

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

本项目回测：

```python
from strategy import KAICHENG, run_open_break
run_open_break(KAICHENG, show_report=True)
# 等价：get_strategy("strategy1").run(...)
```

本项目决策层（不下单，只裁决）：

```python
from strategy import MarketContext, get_decision_engine

eng = get_decision_engine("strategy1")  # 别名 open_break3 / s1
d = eng.decide(MarketContext(
    open=10.0, high=10.4, low=9.8, close=10.3, last=10.3,
    prev_open=10.1, prev_close=9.9, position_qty=0,
))
print(d.action, d.reason, d.price)  # buy / sell / hold
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
- 策略一通过实例写入参数（`apply_strategy_config`），避免类属性并行串扰。

| 资产 | 接口 | 说明 |
|------|------|------|
| A 股 | `stock_zh_a_daily` | `strategy.data` 默认 |
| ETF | `fund_etf_hist_em` | `sh51*` / `sz15*` 等自动分流 |

日线缓存：`data_cache/<symbol>_daily_qfq.parquet`。首次全量拉取，后续增量补齐；前复权除权后需全量时可 `force_daily_refresh=True`。标的不符或相邻 K 线日历缺口过大时也会自动全量重拉。

---

## 盯盘要点

- **策略同源**：`holdingStocks` 与 `strategy/open_break.py`（因子1）共用规则；架构上对应策略一绑定 + 决策意图，不另写买卖逻辑。
- **合格池**：中证500 + 中证1000 筛选夏普 ≥ 1.0 且超额收益为正；明细见 `holdingStocks/README.md` / `backtest/universe_zz500_1000/`。
- **行情（watch，P0-1 ✅）**：东财 SSE 优先，不健康时新浪批量兜底；页面经本地 `/ws` 推送，勿只开 `file://`。
- **微信预警（P0-2 ✅）**：`watch` 默认推送【触发预警】/【接近预警】/【策略触发】等；依赖本机 OpenClaw Gateway，不走大模型。关闭：`--no-wechat`。
- **行情复盘**：`python index.py review` 汇总大盘/账户/持仓/策略事件并推送【行情复盘】；本地写入 `market_review_latest.txt`。仅本地：`--no-wechat`。
- **定时复盘**：周一、周五 **15:00**（`python index.py review-schedule install`）。
- **自动结算**仅为盯盘记账，**不会下真实委托**。

---

## 参考

- 官方文档：<https://akquant.akfamily.xyz/>
- 旁挂源码示例：`../akquant/examples/README.md`
- 策略说明：`strategy/README.md`、`strategy/STRATEGY_AUDIT.md`
- 盯盘 / 微信：`holdingStocks/README.md`、`holdingStocks/weChat接入.md`
- 任务清单：`TODO.MD`（P0 完成 → 下一档 P1 选股因子框架）
