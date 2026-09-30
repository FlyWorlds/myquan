# 模拟盘量化项目审核与优化记录（2026-09-30）

> 范围：当前默认模拟盘链路（`holdingStocks/`）与默认策略十六/因子26相关代码（`strategy/`）。本文只记录工程与研究口径，不构成投资建议。

## 审核结论

项目已经具备较强的模拟盘防错基础：时间因果、T+1、跨日粘滞、HWM、持仓账本并发写入、模拟策略账本与纸面持仓隔离等关键风险都有专门模块和回归测试覆盖。本次在当前环境执行默认回归：

```bash
python3 holdingStocks/run_regression_tests.py
```

结果：166 个用例全部通过。

全量 `pytest` 未执行，原因是当前环境未安装 `pytest`。已新增 `requirements-dev.txt`，新环境可用：

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q
```

## 已验证的强项

- **时间完整性**：`holdingStocks/temporal_integrity.py` 明确拒绝未来行情、乱序旧行情覆盖、HWM 时间倒挂和用价格反推出 09:30 的成交时刻。
- **HWM 与卖出侧价**：默认回归覆盖竞价脏峰、日内新高、跨日高点、漏 tick 后通过可信 dayHigh 修复等场景。
- **跨日粘滞与 T+1**：回归覆盖昨日买点粘滞不得继承、跨日 `buy_time` 拒绝入槽、买入日不得卖、卖出日不得再买。
- **账本写入**：`HoldingsStore` 已使用进程内单对象、跨进程文件锁、三方合并和原子写入，降低多线程/多进程覆盖账本的概率。
- **模拟账本隔离**：`strategy_simulator.py` 不读写 paper cash/qty，避免策略收益与纸面持仓互相污染。

## P1 风险：策略累计历史口径仍是简化模型

`strategy_simulator.bootstrap_book_from_daily_ohlc()` 的历史 bootstrap 使用 `strategy.open_break` 的开盘阈值买入与固定止损：

- 买入：`high >= buy_level`
- 卖出：`low <= stop_level`
- T+1：买入当日不卖

但当前默认策略十六的卖出是因子26多层退出：硬保护、T1 隔夜峰值回落、中赚回落、动态波动回落、10% 半仓、15% 全清等。实时部分通过行里的 `卖出侧价`/`止损`参与 `evaluate_live_transition()`，能跟当前 UI 卖价走；历史起算段如果用于和因子26回测或真实 paper 账本对账，会产生口径偏差。

已处理：

- `strategy_simulator` 账本新增 `bootstrap_model` / `live_model` / `exit_model`。
- 策略行新增 `策略历史口径` / `策略实时口径` / `策略退出口径`。
- BUY/SELL 事件新增 `execution_model`。
- `Strategy Simulator` 历史 bootstrap 优先使用因子26 1m replay trades（`bootstrap_model=factor26_1m_replay`）；只有缺分钟回放时才退回日线开盘突破固定止损模型。
- 回归测试锁定这些字段，避免后续又变成隐含口径。

后续建议：

- 扩展本地分钟数据覆盖后，用更长窗口的因子26 1m replay 替换短窗 bootstrap。
- 做抽样人工复核，确认 simulator trades 与因子26 replay trades 在同一窗口内可解释对齐。

## 已处理：交易日历从工作日近似升级为 A 股休市日历

`watch_config.trading_session_date()` / `prev_trading_day()` 已改为委托 `holdingStocks/trading_calendar.py`，不再只跳过周末。当前内置上海证券交易所 2026 年休市安排，并支持通过 `holdingStocks/trading_calendar_overrides.json` 追加未来年份或临时休市日期。

已新增回归：

- 2026 年中秋节：2026-09-25 锚定 2026-09-24，2026-09-28 的前一交易日为 2026-09-24。
- 2026 年国庆节：2026-10-01 至 2026-10-07 均锚定 2026-09-30，2026-10-08 的前一交易日为 2026-09-30。
- 周末锚定仍保持原行为。

后续维护项：每年交易所发布下一年休市安排后，更新内置表或写入本地 override 文件。

## P2 风险：依赖与测试入口不完整

`requirements.txt` 只包含运行依赖，未包含 `pytest`。新机器上 `python3 -m pytest -q` 会失败，容易让全量回归不可复现。

已处理：

- 新增 `requirements-dev.txt`，声明 `pytest>=8.0`。
- 新增 `holdingStocks/run_all_tests.py`：先跑默认回归，再在已安装 pytest 时跑全量 pytest。

建议：

- 在 `README` 或 `holdingStocks/README.md` 中补充“默认回归”和“全量测试”两条命令。
- 若需要 CI，优先跑 `holdingStocks/run_regression_tests.py`，再跑全量 `pytest`。

## P2 风险：本地模拟收益仍未完整等同券商成交

模拟盘按触发价/当前价记录成交，目标是信号账本，不是券商交割单仿真。现有回测/模拟已经显式区分滑点、费用和实盘执行前提，但仍需继续避免误读：

- 本地 paper 成交不等同真实可成交，尤其是跌停、封单、盘口排队和开盘集合竞价。
- Strategy Simulator 买入用 live last，而不是总是买点；Paper 入槽另有“新触发买点 / 腾槽现价”规则，两者是两个账本。

建议：

- UI 上继续保持“纸面 / 策略模拟 / 回测”三套口径分离。
- 对关键字段增加来源标签：`paper_ledger`、`strategy_simulator_ledger`、`factor26_backtest`。

## 已处理：抽样对账报告

新增 `holdingStocks/audit_strategy16_reconcile.py`，只读导出 CSV，按代码合并：

- UI 快照卖出侧价 / 买点 / 状态。
- paper `trades.jsonl` 最近成交。
- Strategy Simulator `strategy_signal_events.json` 最近事件。
- 因子26 replay 触发侧 / 触发价（有本地分钟与快照字段时填充；缺失时在 `reconcile_note` 标明）。

默认输出到 `holdingStocks/runs/strategy16_reconcile_sample.csv`。

## 已处理：数据源健康告警分级

新增 `holdingStocks/health_status.py`，并在 `watch_snapshot.apply_feed_health()` 中打入：

- `block_trading`：行情过期、日线缺口/缺失等会影响交易决策的问题。
- `notification_only`：微信/通知通道异常。
- `display_only`：展示缓存或未知但不应单独阻断交易的问题。

快照会附带 `healthLevel` / `healthIssues` / `blockTrading`，便于前端和后续自动化一致使用。

## 下一步优化优先级

1. **扩展因子26 1m bootstrap 覆盖窗口**：当前优先短窗 replay；若本地分钟数据不足会降级。
2. **接入 CI**：可直接调用 `python3 holdingStocks/run_all_tests.py`。
3. **前端展示健康分级**：利用快照里的 `healthLevel` / `blockTrading` 做更明确的状态条。
4. **周期性对账**：盘后运行 `audit_strategy16_reconcile.py`，沉淀 CSV 作为回归样本。
