<!-- # myquan — AKQuant 框架接入说明 -->

本目录基于 [AKQuant](https://github.com/akfamily/akquant) 做 A 股策略回测与盯盘。

**运行时依赖**：全局 / pip 安装的 `akquant`（见 `requirements.txt`，当前钉死 `0.3.21`）。  
**旁挂源码**：同级目录 `../akquant/` 仅供阅读、对照实现，**不会**自动进入 `PYTHONPATH`。

文档维护：改策略/因子/回测时同步更新本文、`TODO.MD`、`docs/`（规则见 `.cursor/rules/docs-sync.mdc`）。

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

**当前生效**

| 场景 | 配置 |
|------|------|
| **盯盘 / 默认回测** | **策略一 = 因子1 + 因子2 预警**（因子2 回测不注资） |
| **因子1** | 开盘 ±2.5%（单票可 ±3% 等）；买突破、卖仅止损、T+1 |
| **动态选股（研究，🔒锁定）** | **因子13 熊市盾牌 thr\* Top3** → 2026：东材、珠峰、雷赛 |

因子13 详情：[`docs/FACTOR13.md`](docs/FACTOR13.md) · 锁定：[`backtest/factor13_bear_shield/LOCKED.json`](backtest/factor13_bear_shield/LOCKED.json)

```bash
cd backtest && python strategy1.py --rules
python strategy/run_factor13_bear_shield_wf.py   # 因子13 WF 回测
```

策略与因子注册表：[`strategy/README.md`](strategy/README.md) · 策略专题：[`docs/STRATEGY.md`](docs/STRATEGY.md)

**任务进度**：[`TODO.MD`](TODO.MD)（P0 行情/预警 ✅；P0 持仓入库待做；因子13 已锁定）

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
├── READ.md                  # 本文档（项目总览）
├── TODO.MD                  # 任务优先级与锁定项
├── docs/
│   ├── STRATEGY.md          # 策略说明专题
│   └── FACTOR13.md          # 因子13（质量带 + 熊盾锁定）
├── .cursor/rules/
│   └── docs-sync.mdc        # 文档同步规则
├── strategy/                # 可插拔策略框架
│   ├── README.md            # 因子/策略注册表
│   ├── factor13_bear_shield.py
│   ├── run_factor13_bear_shield_wf.py
│   └── ...
├── backtest/
│   ├── factor13_bear_shield/   # LOCKED.json、recommended.json
│   └── factor13_bear_shield_wf/
├── holdingStocks/           # 盯盘 + 微信预警
└── data_cache/              # 前复权日线 parquet
```

运行示例：

```bash
# 策略一回测
cd myquan/backtest && python run.py kaicheng
cd myquan/backtest && python strategy1.py --rules

# 因子13 熊市盾牌 WF（thr* Top3，锁定配置）
cd myquan && python strategy/run_factor13_bear_shield_wf.py

# 离线规则测试
cd myquan && python -m unittest -v test_strategy_rules.py

# 持仓盯盘
cd myquan/holdingStocks && python index.py watch --interval 5 --port 8765
```

盯盘细节：[`holdingStocks/README.md`](holdingStocks/README.md)

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
    fill_policy=CurrentClose(),
)
```

本项目回测：

```python
from strategy import KAICHENG, run_strategy1
run_strategy1(KAICHENG, show_report=True)   # 因子1+因子2 预警
```

---

## 回测要点（akquant 0.3.x）

- `CurrentClose` 控制成交时点；策略一参数经 `BacktestConfig` / `apply_strategy_config` 注入。
- 日线缓存：`data_cache/<symbol>_daily_qfq.parquet`；除权后可 `force_daily_refresh=True`。

| 资产 | 接口 | 说明 |
|------|------|------|
| A 股 | `stock_zh_a_daily` | `strategy.data` 默认 |
| ETF | `fund_etf_hist_em` | `sh51*` / `sz15*` 等 |

---

## 盯盘要点

- 规则与 **因子1** 同源（`strategy/open_break.py`）。
- 合格池：中证500∪1000 静态池 + **因子13 动态池（研究/锁定）**。
- 行情：东财 SSE + 新浪兜底 + 本地 WS（P0 ✅）。
- 微信预警：OpenClaw（P0 ✅）；自动结算不下真实委托。

---

## 参考

- 官方文档：<https://akquant.akfamily.xyz/>
- 策略注册表：[`strategy/README.md`](strategy/README.md)
- 策略专题：[`docs/STRATEGY.md`](docs/STRATEGY.md)
- 因子13：[`docs/FACTOR13.md`](docs/FACTOR13.md)
- 凯盛审计底稿：[`strategy/STRATEGY_AUDIT.md`](strategy/STRATEGY_AUDIT.md)
- 任务清单：[`TODO.MD`](TODO.MD)
