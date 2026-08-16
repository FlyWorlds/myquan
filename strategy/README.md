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
│   ├── factor5.py        # Serenity 公开前瞻主题 → A 股研究候选池
│   ├── factor6.py        # 组合动量 ETF 轮动
│   └── factor7.py        # 行业 ETF 普通动量 + 改进残差动量

├── strategies/
│   ├── strategy1/ … strategy8/
├── open_break.py         # 因子1 默认百分比 / 规则
├── dd_alert.py           # 因子2 历史/年均回撤 → 加减仓预警线
├── dd_topup.py           # 旧版权益注资叠加（可选）
├── bull_regime.py        # 因子4 牛市判定
├── momentum.py           # 因子3 动量族
├── serenity_factor5.py   # 因子5：公开帖解析 / 主题映射 / 动态候选快照
├── etf_combo_momentum.py # 因子6：宽基 ETF 组合动量轮动
├── industry_residual_momentum.py # 因子7：行业 ETF 双动量月频 Top3
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
| **factor6** | 因子6·组合动量ETF轮动 | 宽基 ETF 轮动 | `etf_combo_momentum.py`：短窗+长窗 ROC 合成分数，收盘 TopK，动量失效空仓；次日开盘执行 |
| **factor7** | 因子7·行业ETF双动量 | 月频行业主线轮动 | `industry_residual_momentum.py`：12月普通动量 + 100月PCA六因子改进残差动量，各50%合成；月末Top3 |

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
| **strategy6** | 组合动量ETF轮动 | factor6 | ✅ | 宽基ETF组合动量 Top1 轮动；动量失效空仓；别名 `s6` / `etf_combo_momentum` |
| **strategy7** | 策略七 | factor5 | ✅ | 因子5事件候选仅限中证500/1000主板非ST成分股，最多5个槽位；单主题最多1只、固定持有5日，新事件替换旧主题或最早入池持仓 |
| **strategy8** | 行业ETF双动量 | factor7 | ✅ | 15只行业ETF月频Top3；普通动量与改进残差动量各50%，月末信号、下一交易日开盘等权调仓 |

```python
from strategy import list_strategies, get_strategy_bindings

for s in list_strategies():
    print(s.id, s.name, s.factor_ids, "ok" if s.implemented else "skeleton")

for b in get_strategy_bindings("strategy7"):
    print(b.factor_id, b.role, b.filter_desc)
```

```python
from strategy import run_strategy6, run_strategy7, run_strategy8

# 策略六：因子6 宽基 ETF 组合动量轮动（研究回测，不构成投资建议）
run_strategy6(start="20200101")

# 策略七：5 个槽位，单主题1只、固定持有5日
run_strategy7(start="20260101", max_positions=5, max_per_theme=1, hold_days=5)

# 策略八：15只行业 ETF，月末双动量 Top3
run_strategy8(start="20240206", end="20260630")
```

因子5候选池刷新（处理上一 A 股交易日收盘后至当前时点的全部 Serenity 公开帖）：

```python
from strategy.strategies.strategy7 import refresh_strategy7_factor5

refresh_strategy7_factor5()
```

策略七仅使用因子5作为开仓来源；单主题最多一只、固定持有5日，不再使用因子1止损、因子4或凯盛/天通/科创综指ETF的旧默认池。

### 策略八说明：抓主线，谁最强就跟谁

先把时间说清楚：这个成绩来自 **2024年2月6日到2026年6月30日**，只代表这段牛市样本。它怎么抓到主线？方法并不神秘。把市场想成一块每月更新的行业积分榜，科技、金融、医药、资源等15只行业ETF全部上场；月底一到，策略重新打分，只留下前三名，每只三分之一仓位，然后整整拿一个月。它不预测谁会突然启动，只让资金一直跟着已经出现的主线跑。

这张积分榜先投第一张票。普通动量公式只有一行：把过去12个月的月收益从 R1 加到 R12。代码使用月度对数收益，大白话就是把这一年每个月的涨跌全部加起来，总分越高，趋势越强。它不猜下个月谁会起飞，只追已经跑出来的强者。

但只看谁涨得快还不够，第二张票叫残差动量。原始计算看着复杂，大白话只有两步：先用过去100个月的数据，把股票、债券和黄金等共同涨跌压缩成6股共同风向；再用行业当月真实涨幅减去共同风向能够解释的涨幅，剩下的记作 epsilon。把最近12个月的 epsilon 加起来，就是残差动量。分数越高，说明扣掉大盘顺风以后，它自己还在变强。

然后再做一个小手术：在这12个月里找出日波动最高、最吵的那一个月，把它的 epsilon 从加分改成扣分。公式就是“12个月 epsilon 总和 − 2 × 最吵月 epsilon”。翻一次符号，相当于先拿掉它，再以相反方向放回去，目的只有一个：别让一次尖叫盖过十一句正常说话。

两张票合起来，普通动量和改进残差动量先各自在15个行业里排百分位，再各占一半合成总分，每月买前三名。给定历史口径下，组合年化为 **61.79%**；同期普通动量为 **58.51%**，改进残差动量为 **33.57%**，组合最大回撤为 **18.93%**。

再次强调：上述数字是2024年2月6日至2026年6月30日这段发表后样本的历史结果，不是收益承诺。它是牛市猎手，不是熊市盾牌；策略始终满仓，没有现金开关。把起点推回2023年，给定口径下最大回撤扩大到 **42.76%**，收益也主要集中在2025年以后，所以它更适合作为研究中的进攻仓，用来负责追主线。想穿越牛熊，还需要另外加入市场状态和风控。

---

## 默认参数在哪改（开闭）

| 项 | 默认源 | 策略覆盖 |
|----|--------|----------|
| 因子1 ±pct、双阳跨日 | `open_break.DEFAULT_*` | `strategy1/bindings` / `BacktestConfig.threshold_pct`；非对称用 `entry_pct`/`stop_pct` |
| 因子2 历史最大/年均回撤 | `dd_alert.DEFAULT_HIST_MAX_DD` / `DEFAULT_AVG_YEARLY_MAX_DD` | `strategy1/bindings` |
| 因子4 牛市参数 | `bull_regime` / `FACTOR4_REPAIR_*` | `resolve_factor4_repair(cfg)` / `BacktestConfig.factor4_*` |
| 因子6 ETF 组合动量 | `etf_combo_momentum.DEFAULT_*` | `strategy6/bindings` / `run_strategy6(...)` |
| 因子7 行业 ETF 双动量 | `industry_residual_momentum.DEFAULT_PARAMS` / `DEFAULT_UNIVERSE` | `strategy8/bindings` / `run_strategy8(...)` |

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
# 策略六：因子6 ETF 组合动量
python -m strategy.etf_combo_momentum
# 旧对照：策略五袖套 vs 因子3选股+因子1止损（不再注册为策略六）
cd backtest && python compare_f3_select_f1_stop.py
# 策略七：五槽位、单主题一只、固定持有5日
python -m strategy.backtest_factor5_serenity --start 20260101 --max-positions 5 --max-per-theme 1 --hold-days 5
# 策略八（Python API；离线测试不拉行情）
python -c "from strategy import run_strategy8; print(run_strategy8(start='20240206', end='20260630').stats)"
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
| `run_strategy6` | 因子6 ETF 组合动量轮动；`start` / `n` / `n2` / `top_k` / `hold_days` / `min_score` |
| `run_strategy7` | 因子5事件开仓 + 固定持有；`start` / `end` / `max_positions` / `max_per_theme` / `hold_days` |
| `run_strategy8` | 因子7行业ETF双动量；`start` / `end` / `momentum_months` / `pca_window_months` / `n_components` / `top_k` |
| `OpenBreak3Strategy` | = Strategy1 执行类 |
| `KCZZ_ETF` | 科创综指 589680 预设（买2.5%/止3.5%、T+1） |
