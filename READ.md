# myquan - 基于 AKQuant 的 A 股量化盯盘与回测项目

本项目基于 [AKQuant](https://github.com/akfamily/akquant) 构建，面向 A 股策略研究、回测、模拟盘盯盘和纸面交易状态管理。

当前主线是 **策略十六：因子27 核心龙头池 + 因子26 多层止盈 + 因子2 回撤预警**。盯盘端支持分阶段异步加载：先出持仓，再出默认策略，最后补齐其它策略和观察池。

## 快速启动

在项目根目录用已安装依赖的 Python：

```bash
python holdingStocks/index.py watch
```

开发前端时使用：

```bash
python holdingStocks/index.py watch --ui-dev
```

也可以继续用一键脚本：

```bash
cd holdingStocks
python start_watch.py --no-wechat
python start_watch.py --force
python start_watch.py --stop
```

默认页面：

- 前端：`http://127.0.0.1:3000/`
- API / WebSocket：`http://127.0.0.1:8765/`
- 板块轮动：`http://127.0.0.1:3000/sectors`
- 交割单：`http://127.0.0.1:3000/trades`

启动日志应依次出现：

```text
持仓首屏已推送
默认策略快照已推送
全量快照已推送
```

日线预热线程数可调：

```bash
WATCH_DAILY_WARM_WORKERS=16 python holdingStocks/index.py watch --ui-dev
```

## 启动加载顺序

盯盘冷启动分三段，目的是先让页面可用，再补齐重数据：

1. **持仓首屏**：只加载实仓、今日已实现和用户登记持仓池。
2. **默认策略**：加载策略16核心龙头热池和公共自选池。
3. **全量补齐**：后台补策略一池、策略16B动态池、策略17叠加观察池、策略3/8/15面板、板块轮动和画像缓存。

这些任务不再阻塞首屏：

- 股票名称缓存预热
- 个股画像/板块反查
- 策略3/8/15快照面板
- 策略17叠加观察池
- 板块轮动

行情 seed 与日线缓存预热并行执行；新浪批量失败时仍会按票兜底拉日线。

## 当前默认交易逻辑

| 模块 | 当前口径 |
| --- | --- |
| 默认策略 | **策略16 核心龙头** |
| 选股池 | 因子27 近3个月核心龙头池 + 公共自选池 |
| 买入 | 因子26 开盘阈值买入，1m path-dependent |
| 卖出 | 因子26 多层止盈/止损，1m path-dependent |
| 预警 | 因子2 回撤加减仓预警 |
| 因子22 | 默认关闭，仅研究对照 |
| 仓位 | Capital V2，模拟盘纸面交易，不接券商 |

因子26退出规则摘要：

- 硬保护 2.5%，低开已破按开盘。
- 中赚 3-10%：回落一半与 `0.5 x 20日日频sigma` 谁先到走谁。
- 10% 半仓止盈，15% 全清。
- 大赚后回落 2% 清仓。
- 买入日未到 3%，次日按隔夜高点回落 2.5%，不得低于硬保护。
- T+1：买入当日不卖，卖出当日通常不买回。**策略十六例外**：前一日止损已记、次日竞价低开走开盘保护全清后，当天过门触买允许回补（仍占日新开额度）。

## 策略16 与策略16B

### 策略16

策略16是当前默认交易池：

- 因子27核心龙头池，默认近3个月。
- 主板、非 ST、价格上限等条件由策略固定参数过滤。
- 交易内核使用因子26。
- 公共自选池全策略共用。
- 隔夜已记止损、次日竞价低开开盘保护卖出后，当天过门可回买。

刷新核心龙头池：

```bash
python strategy/run_core_leader_pool.py
```

### 策略16B

策略16B复刻策略16的买卖内核，但选股条件可以在页面里动态配置，从全A重新过滤：

- 回看月份：1/2/3/6 等。
- 概念数量、每概念数量、目标池大小。
- 价格上限。
- 非 ST、排除创业板、排除科创板、排除北交所。

页面位置在策略16右侧。点击“生成”后，后端会调用：

```text
GET /api/strategy16b/select
```

生成结果会进入策略16B Tab 和动态盯盘池，不覆盖策略16正式池。

## 盯盘页面说明

| Tab | 说明 |
| --- | --- |
| 持仓 | 实仓/今日平仓/纸面交易状态，Capital V2账户摘要 |
| 策略1 | 研究池，按距买点排序 |
| 策略3 | T-1连板梯度情绪 + 首板晋级跟踪 |
| 策略8 | 当日涨停实时定题材 |
| 策略15 | 连板减磨损与震荡处理 |
| 策略16 | 默认核心龙头交易池 |
| 策略16B | 条件可配置的核心龙头动态池 |
| 策略17 | 紫阳真君叠加观察池，非默认交易池 |

重要口径：

- `holdings_watch.json` 是本机快照缓存，不是账本真源。
- 纸面账本、交易和状态文件不要手工乱改。
- Win/Mac 持仓同步走 `origin/holdings-ledger`。
- 外网行情断开时，本机 WebSocket 仍可能正常，页面以 `quoteStale` / `feedOk` 显示行情健康。
- 微信扫描预警与纸面/策略模拟自动成交只在 **A 股交易日连续竞价**；周末和交易所休市日不推扫描预警、不成交（`market_phase=closed`）。

## 常用命令

### 回测

```bash
# 策略一规则
python backtest/strategy1.py --rules

# 策略16核心龙头池近7日1m回测
PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7 --fit-thr

# 因子22同日再买对照
PYTHONPATH=. python backtest/strategy16_core_leader/compare_f22.py --days 7

# 低开破硬保护对照
PYTHONPATH=. python backtest/strategy1_pool_1m/compare_hard_gap.py --pool strategy16 --days 7
```

### 因子池

```bash
# 策略16核心龙头池
python strategy/run_core_leader_pool.py

# 策略17紫阳真君池
python strategy/run_ziyang_pool.py
```

### 持仓同步

```bash
cd holdingStocks
python index.py holdings-push
python index.py holdings-pull
```

`holdings-ledger` 分支是多设备运行态真源，包含纸面持仓、成交流水、交割明细，以及策略16/16B 的 simulator 状态与事件。`main` 只放代码；启动 `start_watch.py` 默认先拉远程账本，清空持仓后要执行一次 `holdings-push --force`，另一台设备再启动会得到同一份空仓状态。

## 验证命令

推荐使用：

```bash
python -m py_compile holdingStocks/index.py
python -m unittest holdingStocks.test_watch_boot_perf holdingStocks.test_strategy16b_dynamic
python holdingStocks/run_all_tests.py --skip-pytest-if-missing
```

当前系统默认 `python3` 可能缺 `pandas` / `akshare`，不要用它判断项目是否坏了。

安装依赖：

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 项目结构

```text
myquan/
├── READ.md                         # 根目录说明
├── TODO.MD                         # 任务与锁定项
├── docs/                           # 策略、因子、架构和审计文档
├── strategy/                       # 因子、策略注册表、策略绑定和选股池生成
├── backtest/                       # 回测、对照实验和报告产物
├── holdingStocks/                  # 盯盘、模拟盘账本、HTTP/WS、微信通知
├── holdingStocks/watch-ui/         # Nuxt 前端
├── sectors/                        # 板块/概念数据
└── data_cache/                     # 本地行情缓存
```

关键文档：

- [架构说明](docs/ARCHITECTURE.md)
- [策略专题](docs/STRATEGY.md)
- [策略注册表](strategy/README.md)
- [因子26](docs/FACTOR26.md)
- [因子27](docs/FACTOR27.md)
- [因子28](docs/FACTOR28.md)
- [盯盘说明](holdingStocks/README.md)
- [时间完整性](docs/TEMPORAL_INTEGRITY.md)
- [交易引擎契约](docs/TRADING_ENGINE_CONTRACT.md)
- [退出编排契约](docs/PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md)

## AKQuant 接入方式

AKQuant 是 Rust 内核 + Python 策略层的混合量化框架。本项目主要使用 Python 侧能力，同时保留自定义实时盯盘和纸面交易状态。

典型数据流：

```text
akshare DataFrame
  -> normalize / load_bar_from_df
  -> Bar
  -> Strategy.on_bar
  -> Execution / Statistics
  -> BacktestResult
```

本项目策略分层：

```text
因子层 factors
  -> 策略绑定 bindings
  -> 决策层 decision
  -> 执行层 runner / backtest / watch
```

最小 AKQuant 示例：

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

## 策略与因子注册表（摘要）

完整真源：[`strategy/README.md`](strategy/README.md) · 专题：[`docs/STRATEGY.md`](docs/STRATEGY.md)。改策略/因子时同步更新注册表、`docs/` 与本文。

当前默认 **strategy16**；**strategy16B** 复刻同一买卖内核，页面动态选股，不覆盖正式池、不入默认四槽。

---

## 开发约定

- 改策略/因子时，同步更新 `strategy/README.md`、`docs/` 和本文。
- 不要把 `holdingStocks/strategy_sim_state.json`、`holdingStocks/strategy_signal_events.json`、运行快照和账本缓存当普通代码改；它们由 `origin/holdings-ledger` 同步。
- 提交前至少跑 `holdingStocks/run_all_tests.py --skip-pytest-if-missing`。
- 涉及前端时，再跑 `holdingStocks/watch-ui` 的构建或本地 dev 验证。
