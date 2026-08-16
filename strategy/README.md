# strategy — 可插拔策略 / 因子 / 决策框架

默认生效：**策略一 = 因子1（开盘±2.5% 买卖）+ 因子2（回撤加减仓预警）**。

- 决策/盯盘买卖只看因子1；因子2 默认只挂预警阈值（**回测不注资**）。
- 仅因子1交易：`run_open_break` 或 `python strategy1.py --no-factor2`。
- 旧版权益注资叠加：`run_strategy1(..., apply_factor2_overlay=True)`（`dd_topup`）。
- **开闭调参**：改 `bindings.py` / `BacktestConfig` / `DEFAULT_*`，不必改算法。

## 分层架构

```
因子层 (factors)     → 价位 / 信号 / 通用过滤（可复用）
策略层 (bindings)    → 本策略挂哪些因子、参数、专属过滤器
决策层 (decision)    → MarketContext → Decision(buy|sell|hold)
执行层 (runner/backtest) → 下单、回测、盯盘对接
```

```
strategy/
├── core/                 # 协议 / MarketContext / Decision / 注册表
├── factors/
│   ├── factor1.py        # 开盘突破 ±pct
│   ├── factor2.py        # 回撤加减仓预警
│   ├── factor3.py        # 动量（截面 / 单票时序）
│   ├── factor4.py        # 牛市持股 regime
│   └── factor5.py        # Serenity 公开前瞻主题 → A 股研究候选池

├── strategies/
│   ├── strategy1/ … strategy7/
├── open_break.py         # 因子1 默认百分比 / 规则
├── dd_alert.py           # 因子2 历史/年均回撤 → 加减仓预警线
├── dd_topup.py           # 旧版权益注资叠加（可选）
├── bull_regime.py        # 因子4 牛市判定
├── momentum.py           # 因子3 动量族
├── serenity_factor5.py   # 因子5：公开帖解析 / 主题映射 / 动态候选快照
├── backtest.py / runner.py / config.py
└── registry.py
```

---

## 因子一览（`strategy/factors`）

| ID | 名称 | 作用 | 真源 / 要点 |
|----|------|------|-------------|
| **factor1** | 因子1 | 开盘突破买卖 | `open_break.py`：买=`ceil(open×(1+pct))`，卖=开盘−pct 止损；前日阴/小阳；禁双阳跨日≥5%；T+1。支持非对称 `entry_pct`/`stop_pct` |
| **factor2** | 因子2 | 回撤加减仓**预警** | `dd_alert.py`：默认加仓≥20% / 减仓≤10%；**回测不注资**。旧注资见 `dd_topup.py` |
| **factor3** | 因子3·动量 | 截面选股 / 单票择时 | `momentum.py`：组合默认截面反转打分；单票可用 `dist_hl` 等（收盘确认→次日开盘） |
| **factor4** | 因子4 | 牛市持股修复 | `bull_regime.py`：牛市 regime 内暂停/放宽因子1止损；可选空仓开盘建仓。叠在因子1上用 |
| **factor5** | 因子5·Serenity前瞻主题 | 动态 A 股**研究候选池** | `serenity_factor5.py`：Serenity 公开帖 → 前瞻看多主题 → A 股概念代理；不复制美股代码、不直接交易 |

```python
from strategy import list_factors

for f in list_factors():
    print(f.id, f.name, f.description)
```

---

## 策略一览（`strategy/strategies`）

| ID | 名称 | 绑定因子 | 状态 | 说明 |
|----|------|----------|------|------|
| **strategy1** | 策略一 | factor1 + factor2 | ✅ 默认 | 开盘±2.5% 仅止损 + 回撤预警；别名 `open_break3` / `s1` |
| **strategy2** | 策略二 | factor1 + factor2 | ❌ 骨架 | ±3% / 仅阴线；决策仅因子1；`run` 未实现 |
| **strategy3** | 策略三 | factor3 | ✅ | 挂因子3动量组合（中证500+1000主板截面）；与策略五同族 |
| **strategy4** | 策略四 | factor1 + factor3 | ✅ | 因子1 roll12 Top3 建池 × 池内反转选股 |
| **strategy5** | 动量因子组合 | factor3 | ✅ | 中证主板截面 TopK 袖套；别名 `s5` / `momentum` |
| **strategy6** | 因子3选股+因子1止损 | factor3 + factor1 | ✅ | 因子3选票买入，因子1开盘止损卖；最长持有 N 日 |
| **strategy7** | 策略七 | factor5 + factor1 | ✅ | 因子5事件候选填充最多5个槽位，因子1仅执行 T+1 后止损；每日补空槽，候选不足时保留现金 |

```python
from strategy import list_strategies, get_strategy_bindings

for s in list_strategies():
    print(s.id, s.name, s.factor_ids, "ok" if s.implemented else "skeleton")

for b in get_strategy_bindings("strategy7"):
    print(b.factor_id, b.role, b.filter_desc)
```

```python
from strategy import run_strategy7

# 策略七：5 个槽位，因子1止损、每日补仓
run_strategy7(start="20260101", max_positions=5, stop_pct=0.025)
```

因子5候选池刷新（处理上一 A 股交易日收盘后至当前时点的全部 Serenity 公开帖）：

```python
from strategy.strategies.strategy7 import refresh_strategy7_factor5

refresh_strategy7_factor5()
```

策略七使用因子5作为唯一开仓来源，并使用因子1作为持仓止损覆盖层；不再使用因子4或凯盛/天通/科创综指ETF的旧默认池。

---

## 默认参数在哪改（开闭）

| 项 | 默认源 | 策略覆盖 |
|----|--------|----------|
| 因子1 ±pct、双阳跨日 | `open_break.DEFAULT_*` | `strategy1/bindings` / `BacktestConfig.threshold_pct`；非对称用 `entry_pct`/`stop_pct` |
| 因子2 历史最大/年均回撤 | `dd_alert.DEFAULT_HIST_MAX_DD` / `DEFAULT_AVG_YEARLY_MAX_DD` | `strategy1/bindings` |
| 因子4 牛市参数 | `bull_regime` / `FACTOR4_REPAIR_*` | `resolve_factor4_repair(cfg)` / `BacktestConfig.factor4_*` |

```python
from strategy.dd_alert import derive_thresholds

th = derive_thresholds(equity_curve)
print(th.label())
```

## 决策层用法

```python
from strategy import MarketContext, get_decision_engine

eng = get_decision_engine("strategy1")
ctx = MarketContext(
    open=10.0, high=10.4, low=9.8, close=10.3, last=10.3,
    prev_open=10.1, prev_close=9.9,
    position_qty=0,
)
print(eng.decide(ctx).action)
```

## 回测 CLI

```bash
cd backtest && python strategy1.py --rules
cd backtest && python strategy1.py --no-open
cd backtest && python strategy1.py --no-factor2 --no-open   # 仅因子1
cd backtest && python run.py kaicheng --no-open
# 策略五 vs 策略六
cd backtest && python compare_f3_select_f1_stop.py
# 策略七：五槽位、因子1止损、每日补仓
python -m strategy.backtest_factor5_serenity --start 20260101 --max-positions 5 --stop-pct 0.025
```

## 如何扩展（开闭）

1. **新因子**：`factors/factorN.py` + `register_factor`，策略 bindings 挂上即可  
2. **改百分比**：只改 `DEFAULT_*` 或该策略 `bindings` / `BacktestConfig`  
3. **新策略组合**：新 `strategies/strategyN`，复用已有因子、换 params  

### 因子5更新

因子5依赖 `.cursor/skills/serenity-research-model` 的公开材料与语义规则。每日在公开归档更新后运行：

```bash
python -m strategy.run_factor5_serenity --refresh
# 事件驱动回测：发帖次交易日开盘入槽，因子1止损后每日补空槽
python -m strategy.backtest_factor5_serenity --start 20260101 --max-positions 5 --stop-pct 0.025
```

它会更新 `strategy/runs/factor5_serenity_thesis_picks_latest.csv`：默认分析**上一 A 股交易日 15:00（Asia/Shanghai）之后至当前时点**发布的全部 Serenity 公开帖，再通过 Serenity Research Model Skill 做主题提取、引用污染清洗和语义复核，最后映射为 A 股研究池。候选总数最多 5 只、单主题最多 2 只，并按主题信号强度轮询分配席位。周末会自然覆盖周五收盘后的帖子。没有合格新帖时，候选池为空，不延续旧主题。回测中信号按下一交易日开盘进入、每笔持有期由策略参数指定。映射是概念代理，不代表 Serenity 点名、持有或推荐相应 A 股公司；候选池不能直接当成买卖指令。

## 兼容

| 旧 API | 说明 |
|--------|------|
| `get_strategy("open_break3")` | → strategy1 |
| `run_open_break` | **仅因子1交易**（不含因子2） |
| `run_strategy1` | 因子1 + 因子2预警（默认不注资） |
| `run_strategy7` | 因子5事件开仓 + 因子1止损；`start` / `end` / `max_positions` / `stop_pct` / `max_themes` |
| `OpenBreak3Strategy` | = Strategy1 执行类 |
| `KCZZ_ETF` | 科创综指 589680 预设（买2.5%/止3.5%、T+1） |
