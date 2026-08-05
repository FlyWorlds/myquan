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

**本项目当前生效策略**：OpenBreak3 **因子1**（开盘 ±2.5%）。  
买：`high ≥ ceil(open×1.025)`，前日阴线或小阳，禁前面双阳，T+1。  
卖：仅止损 −2.5% 全清。完整规则：

```bash
python -c "from strategy import STRATEGY_RULES; print(STRATEGY_RULES)"
# 或：cd backtest && python strategy1.py --rules
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
├── READ.md                  # 本文档
├── TODO.MD                  # 任务优先级
├── requirements.txt         # 运行依赖
├── test_strategy_rules.py   # 离线规则回归（不访问网络）
├── strategy/                # OpenBreak3 规则 / 回测 / 配置
│   ├── open_break.py        # 策略因子（回测与盯盘共用）
│   ├── backtest.py          # akquant Strategy
│   ├── config.py            # BacktestConfig、标的预设
│   ├── runner.py            # run_open_break（实例传参）
│   ├── base.py              # run_backtest_pipeline 骨架
│   ├── data.py              # 日线缓存（个股 / ETF 分流）
│   ├── minute.py            # 分钟线工具
│   └── registry.py          # 策略因子注册（仅 open_break3）
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

日线缓存：`data_cache/<symbol>_daily_qfq.parquet`。首次全量拉取，后续增量补齐；前复权除权后需全量时可 `force_daily_refresh=True`。标的不符或相邻 K 线日历缺口过大时也会自动全量重拉。

---

## 盯盘要点

- **策略同源**：`holdingStocks` 与 `strategy/open_break.py` 共用因子1，不另写一套买卖逻辑。
- **合格池**：中证500 + 中证1000 筛选夏普 ≥ 1.0 且超额收益为正；明细见 `holdingStocks/README.md` / `backtest/universe_zz500_1000/`。
- **行情（watch）**：东财 SSE 优先，不健康时新浪批量兜底；页面经本地 `/ws` 推送，勿只开 `file://`。
- **微信预警**：`watch` 默认推送「待买入 / 待卖出」等；依赖本机 OpenClaw Gateway，不走大模型。
- **自动结算**仅为盯盘记账，**不会下真实委托**。

---

## 参考

- 官方文档：<https://akquant.akfamily.xyz/>
- 旁挂源码示例：`../akquant/examples/README.md`
- 策略说明：`strategy/README.md`、`strategy/STRATEGY_AUDIT.md`
- 盯盘 / 微信：`holdingStocks/README.md`、`holdingStocks/weChat接入.md`
- 任务清单：`TODO.MD`
