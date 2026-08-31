<!-- # myquan — AKQuant 框架接入说明 -->
## 盯盘要点

**启动（推荐，Mac / Windows）**

```bash
cd holdingStocks && python start_watch.py --no-wechat
# 浏览器 http://127.0.0.1:3000/  ·  Python 只提供数据 API/WS :8765
# 策略3 Tab：T-1 连板梯度情绪 + 首板晋级跟踪
```

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

**任务进度**：[`TODO.MD`](TODO.MD)（P0 行情/预警 ✅；P0 持仓入库待做；因子13 已锁定）

---

## 策略与因子注册表（摘要）

**完整真源**：[`strategy/README.md`](strategy/README.md) · 策略专题：[`docs/STRATEGY.md`](docs/STRATEGY.md) · 文档索引：[`docs/README.md`](docs/README.md)

> 新增/改因子或策略时，须同步更新 **strategy/README.md → docs/ → 本文**；任务/锁定见 [`TODO.MD`](TODO.MD)（见 [`.cursor/rules/docs-sync.mdc`](.cursor/rules/docs-sync.mdc)）。

### 因子一览

| ID | 名称 | 作用 | 模块 / 要点 |
|----|------|------|-------------|
| **factor1** | 因子1 | 开盘突破买卖 | `open_break.py`：买突破、卖止损、T+1；单票可非对称 entry/stop |
| **factor2** | 因子2 | 回撤加减仓**预警** | `dd_alert.py`：默认加仓≥20% / 减仓≤10%；**回测不注资** |
| **factor3** | 因子3·动量 | 截面选股 / 单票择时 | `momentum.py`：组合截面反转；单票 dist_hl 等 |
| **factor4** | 因子4 | 牛市持股修复 | `bull_regime.py`：牛市 regime 内暂停/放宽因子1 止损 |
| **factor5** | 因子5·Serenity | 前瞻主题研究池 | `serenity_factor5.py`：公开帖→主题→A 股概念代理 |
| **factor6** | 因子6·ETF轮动 | 宽基 ETF 轮动 | `etf_combo_momentum.py`：短长窗 ROC 合成，TopK |
| **factor7** | 因子7·行业ETF | 月频行业主线 | `industry_residual_momentum.py`：普通+残差动量各 50% |
| **factor8** | 因子8·缠论 | 结构买卖点 | `chan/`：一/二/三类买卖点；供策略二 |
| **factor9** | 因子9·多空动能 | 选股/开仓门控 | `ls_energy.py`：日线多空能量 overlay |
| **factor10** | 因子10·价格选股 | 周频开仓名单 | `s1_price_select.py`：近高/趋势/动量；供策略四 |
| **factor11** | 因子11·两段近高 | 截面选股 | `near_high_hold.py`：动量 Top20→近高 Top5；供策略五 |
| **factor12** | 因子12·反转池近高 | 截面选股（研究） | `factor12_combo.py`：20 日反转 Top20→近高 Top5；供策略六 |
| **factor13** | 因子13·契合选股 | 动态合格池 | **A 线**质量带 `factor13_fit.py`；**B 线（🔒锁定）**熊盾 `factor13_bear_shield.py` |
| **factor14** | 因子14·题材共振 | 题材联动选股 | **当日**同题材涨停同伴数≥3；见 [`docs/FACTOR14.md`](docs/FACTOR14.md) |
| **factor15** | 因子15·晋级低开 | 题材联动过滤（可选） | gap 低开带；策略八默认关闭 |
| **factor16** | 因子16·概念龙头评分 | 概念成分龙头排序 | F13质量带 + 因子1 OOS + 缠论笔；见 [`docs/FACTOR16.md`](docs/FACTOR16.md) |
| **cf1** | CF1·流动性门控 | 截面研究 | Amihud 软门 + 成交额地板 + 均线过滤 |

### 策略一览

| ID | 名称 | 绑定因子 | 状态 | 说明 |
|----|------|----------|------|------|
| **strategy1** | 援军战法 | factor1 + factor2 | ✅ **默认** | 开盘±2.5% 一次打满 + 回撤预警；别名 `open_break3` / `s1` |
| **strategy2** | 策略二·缠论 | factor8 | ✅ | 日线交易；30 分小转大 + 日线二/三买卖；别名 `chan` |
| **strategy3** | 策略三·首板晋级 | factor1 | ✅ | 盯盘：昨日涨停池+T-1连板梯度+冰点/正常/高潮+±阈值；回测见 `backtest/strategy3_first_board/` |
| **strategy4** | 策略四·F4止盈动量 | factor1 + factor4 + factor10 | ✅ | 突破 + 牛市放宽 + 20% 昨高全清 + 周频 Top5 |
| **strategy5** | 策略五·近高 Top5 | factor11 | ✅ 研究 | 周频等权持有；别名 `near_high` |
| **strategy6** | 策略六·反转池近高 | factor12 | ✅ 研究 | IS 优于策略五，2024–2025 未确认，不替换策略五 |
| **strategy7** | 策略七·缠论笔算盈亏比 | factor1 | ✅ 研究 | 日线笔 vs 因子1 费用后盈亏比；别名 `s7` / `strategy11` / `bi_pl` |
| **strategy8** | 策略八·题材联动 | factor14 + factor1 | ✅ 研究 | 当日涨停定题材→联动±阈值；2025→ +6.1%（±2.5%）/ +9.1%（±3%）；见 REPORT |

旧执行层研究代码在 `strategy/strategies/_unreg_s*`（因子 3/6/7 仍保留）。

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
│   ├── FACTOR13.md          # 因子13（质量带 + 熊盾锁定）
│   ├── FACTOR14.md          # 因子14 题材共振（策略八）
│   └── FACTOR16.md          # 因子16 概念龙头评分
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

# 持仓盯盘（Web 页面 + Python 数据）
cd myquan/holdingStocks && python start_watch.py --no-wechat
# 浏览器 http://127.0.0.1:3000/  ·  API/WS :8765

# 或分两终端
cd myquan/holdingStocks && python index.py watch --no-wechat
cd myquan/holdingStocks/watch-ui && npm run dev
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



- 规则与 **因子1** 同源（`strategy/open_break.py`）；**Nuxt 前端** 展示持仓 + **策略1–7 Tab**（`策略N-名称`）；策略1 展示早盘节点与阈值过门，其余 Tab 展示挂载因子说明；独立页 **`/strategies`**、**`/factors`** 全量说明（注册表 API 同源）。
- 早盘节点：9:15 竞价 → 9:20 不可撤 → 9:25 算阈值/过门 → 9:30 触发信号（`watch_config.py`）。
- 合格池：中证500∪1000 静态池 + **因子13 动态池（研究/锁定）**。
- 行情：`python index.py watch` 只推送 **JSON 快照**（`/api/snapshot` + WebSocket `/ws`）；盯盘页面只用 **watch-ui**（`:3000`）。一键启动：`python start_watch.py`。详见 [`holdingStocks/README.md`](holdingStocks/README.md)。
- 股票名/代码外链：百度财经 `finance.baidu.com/stock/ab-{code}`。
- 微信预警：OpenClaw（P0 ✅）；自动结算不下真实委托。

详见 [`holdingStocks/README.md`](holdingStocks/README.md)。

---

## 参考

- 官方文档：<https://akquant.akfamily.xyz/>
- 策略注册表：[`strategy/README.md`](strategy/README.md)
- 策略专题：[`docs/STRATEGY.md`](docs/STRATEGY.md)
- 因子13：[`docs/FACTOR13.md`](docs/FACTOR13.md)
- 凯盛审计底稿：[`strategy/STRATEGY_AUDIT.md`](strategy/STRATEGY_AUDIT.md)
- 任务清单：[`TODO.MD`](TODO.MD)


## 盯盘要点

**启动（推荐）**

```bash
cd holdingStocks && python start_watch.py --no-wechat
# 浏览器 http://127.0.0.1:3000/  ·  Python 只提供数据 API/WS :8765
```