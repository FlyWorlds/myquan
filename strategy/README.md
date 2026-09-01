# strategy — 可插拔策略 / 因子 / 决策框架

> 项目总览：[`READ.md`](../READ.md) · 策略专题：[`docs/STRATEGY.md`](../docs/STRATEGY.md) · 因子13：[`docs/FACTOR13.md`](../docs/FACTOR13.md) · 因子14：[`docs/FACTOR14.md`](../docs/FACTOR14.md) · 任务：[`TODO.MD`](../TODO.MD)  
> **文档同步规则**见本文 [§ 文档维护规则](#文档维护规则)；Cursor 规则：`.cursor/rules/docs-sync.mdc`

默认生效：**援军战法（strategy1）= 因子1（开盘±2.5% 一次打满）+ 因子2（回撤加减仓预警）**。

动态选股（研究）：**因子13A 质量带 → 因子16 龙头排序 Top10**（[`backtest/s1_f13_refit_2025/`](../backtest/s1_f13_refit_2025/) · 无置顶）

因子13B 熊盾 Top3（🔒锁定对照）：东材 / 珠峰 / 雷赛（[`LOCKED.json`](../backtest/factor13_bear_shield/LOCKED.json)）

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
│   ├── factor7.py        # 行业 ETF 普通动量 + 改进残差动量
│   └── factor8.py        # CZSC 缠论结构与一/二/三类买卖点
│       # 另有 factor9 日线动能 / factor10 价格选股 / factor11 两段近高 / factor13 契合选股
├── factor13_bear_shield.py   # 因子13 B 线：熊市盾牌 WF + thr* Top3（🔒锁定）
├── factor13_fit.py           # 因子13 A 线：质量带 walk-forward
├── run_factor13_bear_shield_wf.py
├── run_factor13_bear_shield_tune_pit.py
├── near_high_hold.py     # 因子11 / 策略五：两段近高 Top5 等权持有

├── strategies/
│   ├── strategy1/ … strategy5/
├── open_break.py         # 因子1 默认百分比 / 规则
├── dd_alert.py           # 因子2 历史/年均回撤 → 加减仓预警线
├── dd_topup.py           # 旧版权益注资叠加（可选）
├── bull_regime.py        # 因子4 牛市判定
├── momentum.py           # 因子3 动量族
├── serenity_factor5.py   # 因子5：公开帖解析 / 主题映射 / 动态候选快照
├── etf_combo_momentum.py # 因子6：宽基 ETF 组合动量轮动
├── industry_residual_momentum.py # 因子7：行业 ETF 双动量月频 Top3
├── chan/                 # 策略二 CZSC 适配 / 状态机 / 因子挖掘
├── backtest.py / runner.py / config.py
└── registry.py
```

---

## 因子一览（`strategy/factors`）

分类真源：`strategy/factors/categories.py`（开盘执行 / 回撤补仓 / 止盈持股 / 动量 / 反转 / 缠论 / 情绪题材 / 选股质量）。

| ID | 名称 | 分类 | 作用 | 真源 / 要点 |
|----|------|------|------|-------------|
| **factor2** | 因子2-回撤预警 | 回撤补仓 | 回撤加减仓**预警** | `dd_alert.py`：默认加仓≥20% / 减仓≤10%；**回测不注资**。旧注资见 `dd_topup.py` |
| **factor3** | 因子3-动量 | 动量 | 截面选股 / 单票择时 | `momentum.py`：组合默认截面反转打分；单票可用 `dist_hl` 等（收盘确认→次日开盘） |
| **factor4** | 因子4-牛市持股 | 止盈持股 | 牛市持股修复 | `bull_regime.py`：牛市 regime 内暂停/放宽因子1止损；可选空仓开盘建仓。叠在因子1上用 |
| **factor5** | 因子5-Serenity前瞻主题 | 情绪题材 | 动态 A 股**研究候选池** | `serenity_factor5.py`：Serenity 公开帖 → 前瞻看多主题 → A 股概念代理；不复制美股代码、不直接交易 |
| **factor6** | 因子6-组合动量ETF轮动 | 动量 | 宽基 ETF 轮动 | `etf_combo_momentum.py`：短窗+长窗 ROC 合成分数，收盘 TopK，动量失效空仓；次日开盘执行 |
| **factor7** | 因子7-行业ETF双动量 | 动量 | 月频行业主线轮动 | `industry_residual_momentum.py`：12月普通+100月PCA残差各50%；月末Top3 |
| **factor8** | 因子8-缠论结构 | 缠论 | 结构买卖点 | `chan/`：一/二/三类买卖点；供策略二 |
| **factor9** | 因子9-日线多空动能 | 动量 | 选股/开仓门控 | `ls_energy.py`：T 收盘→T+1 开盘；可叠因子1（研究 overlay） |
| **factor10** | 因子10-价格选股 | 动量 | 策略1/4 周频开仓名单 | `s1_price_select.py`：近高/趋势/动量/上涨日占比；本周收盘排名，下一周才允许因子1 开仓 |
| **factor11** | 因子11-两段近高选股 | 动量 | 截面选股 | `near_high_hold.py`：3日动量 Top20 内再取贴近5日高点 Top5；周频冻结；**一字涨停开盘不可买** |
| **factor12** | 因子12-反转池近高 | 反转 | 截面选股 | `factor12_combo.py`：20日涨幅最低 Top20 内再取贴近5日高点 Top5；**研究候选**，2024–2025 未确认，不替换因子11 |
| **factor13a** | 因子13A-质量带契合选股 | 选股质量 | 动态合格池 | `factor13_fit.py`：夏普/回撤甜区 walk-forward；见 [`docs/FACTOR13.md`](../docs/FACTOR13.md) |
| **factor13b** | 因子13B-熊市盾牌 thr\* Top3 | 选股质量 | 熊年防守池（🔒锁定） | `factor13_bear_shield.py`：WF + thr\*；`LOCKED.json` |
| **factor13** | 因子13-契合选股（别名→13A） | 选股质量 | 兼容 | 等同 factor13a；新代码请用 13a/13b |
| **factor14** | 因子14-题材共振 | 情绪题材 | 题材联动选股 | **当日**同题材涨停同伴数 `theme_lu_count≥3`；见 [`docs/FACTOR14.md`](../docs/FACTOR14.md) |
| **factor15** | 因子15-题材晋级低开 | 情绪题材 | 题材联动过滤（可选） | gap ∈ [-4.5%, -0.3%]；默认关闭，需 `--gap-filter` |
| **factor16** | 因子16-概念龙头评分 | 选股质量 | 概念/池内龙头排序 | `factor16_leader_score.py`：**13A** 质量带 + 因子1 OOS 盈亏比/胜率；见 [`docs/FACTOR16.md`](../docs/FACTOR16.md) |
| **factor17** | 因子17-缠论笔盈亏比 | 缠论 | 笔归因评估 | `bi_pl_ratio.py`：因子1 费用后按买入笔记账；原策略七入口，Web 在因子池 |
| **factor18** | 因子18-低开跌停情绪 | 情绪题材 | 大盘情绪择时 | 中证1000 低开开盘跌停家数→平静/正常/恐慌；**策略十二**恐慌日空仓；CLI `run_strategy9_emotion` |
| **factor19** | 因子19-低开反包 | 反转 | 旧假设 | 压力日低开开盘买；组合**未过关** |
| **factor20** | 因子20-跌停次日开板 | 反转 | 已否决 | 昨收跌停今开未封；全样本约 −42% |
| **factor21** | 因子21-涨停次日低开 | 反转 | 策略十二选股 | 昨收涨停且曾开板、今低开；上证昨收≤−2% 空仓；调参窗强、盲测回撤未过关 |
| **cf1** | 因子CF1-流动性门控反转 | 反转 | 截面研究因子 | Amihud 软门 + 成交额地板 + 涨跌停/一字 + 收盘低于60日均线；波动门未通过验证。T 收盘→T+1 开盘 |

```python
from strategy import list_factors

for f in list_factors():
    print(f.id, f.name, f.description)
```

---

## 策略一览（`strategy/strategies`）

| ID | 名称 | 绑定因子 | 状态 | 说明 |
|----|------|----------|------|------|
| **strategy1** | 援军战法 | factor1 + factor2 + factor13a + factor16 | ✅ 默认 | 开盘±2.5% 一次打满、仅止损 + 回撤预警；股票池 13A→16 Top10；**ETF 卫星池** `S1_ETF_WATCHLIST`（8只，见 `etf_select/pool_dedup.json`）；别名 `open_break3` / `s1` / `策略一` |
| **strategy2** | 策略二·缠论 | factor8 | ✅ | 日线交易；30分钟小转大一买候选、二买确认；日线三买增强；日线二卖或三卖退出；中证500+1000；别名 `s2` / `chan` |
| **strategy3** | 策略三·首板晋级 | factor1 | ✅ | 盯盘：昨日涨停池+T-1连板梯度+冰点/正常/高潮展示+±阈值；回测：首板+gap/量比 · 别名 `s3` |
| **strategy4** | 策略四·F4止盈动量 | factor1 + factor4 + factor10 | ✅ | 开盘突破 + 牛市放宽止损 + 20%昨高全清 + 周频动量 Top5；**不是**近高等权持有；旧 run 别名 `run_strategy9` / `s9` / `策略九` |
| **strategy5** | 策略五·近高Top5等权持有 | factor11 | ✅ | 周频 3日动量 Top20 → 5日近高 Top5，下一周等权持有；一字涨停开盘买不进、一字跌停封单卖不出；旧号 `strategy10` / `s10` / `near_high`；研究，非组合默认 |
| **strategy6** | 策略六·反转池近高 | factor12 | ✅ 研究 | 20日反转 Top20 → 5日近高 Top5 等权持有；IS 优于策略五，2024–2025 未确认，**不替换**策略五 |
| **strategy8** | 策略八·题材联动 | factor14 + factor1 | ✅ 研究 | **当日涨停定题材**→联动票当日±阈值；2025→ +6.1%（±2.5%）/ +9.1%（±3%）；`backtest/strategy8_theme_linkage/` |
| **strategy12** | 策略十二·涨停次日低开 | factor18 + factor21 | ❌ 盲测未过关 | v6 昨开板+上证昨收≤−2% 空仓；调参 2020–2024 +645%/夏普 1.23，盲测 2025→ +3.6%/回撤 55%；`backtest/strategy12_emotion_gate/` |
| **strategy13** | 策略十三·因子1ETF | factor1 | ✅ 研究 | 纯因子1 ETF；WF 选参 + OOS 综合分 Top10；[`docs/STRATEGY13.md`](../docs/STRATEGY13.md) · `run_etf_wf.py` |

策略七 CLI（`run_strategy7`）已归入 **因子17**，Web 策略栏不展示。
策略九 CLI（`run_strategy9_emotion`）已归入 **因子18**，Web 策略栏不展示。

旧执行层 3/4/5/6/8 的研究代码在 `strategy/strategies/_unreg_s*`（因子 3/6/7 仍保留）。现行 strategy6 是新注册的因子12 持有，不是旧动量混合。

```python
from strategy import list_strategies, get_strategy_bindings

for s in list_strategies():
    print(s.id, s.name, s.factor_ids, "ok" if s.implemented else "skeleton")

for b in get_strategy_bindings("strategy3"):
    print(b.factor_id, b.role, b.filter_desc)
```

```python
from strategy import run_strategy3, run_strategy5, run_strategy7, run_strategy8, run_strategy12

# 策略五：因子11 近高 Top5 等权持有（研究回测，不构成投资建议）
run_strategy5(start="20200102")

# 策略三：5 个槽位，单主题1只、固定持有5日
run_strategy3(start="20200101", entry_pcts=(0.025, 0.03))

# 策略七：天通默认，日线笔 vs 因子1 费用后盈亏比（研究）
run_strategy7()  # 或 get_strategy("缠论笔算盈亏比").run()；旧名 run_strategy11
```

策略二（缠论选股，研究回测，不构成投资建议）：

```python
from strategy import run_strategy2

run_strategy2(panel_path="data_cache/strategy2_chan/feature_panel.parquet")
```

```bash
cd backtest && python strategy2.py demo --symbols 32
cd backtest && python strategy2.py symbol sh600552
cd backtest && python strategy2.py all --limit 80
```

因子5候选池刷新（处理上一 A 股交易日收盘后至当前时点的全部 Serenity 公开帖）：

```bash
python backtest/strategy3_first_board/run.py
python backtest/strategy8_theme_linkage/run.py --start 20250101
python -c "from strategy import run_strategy3; run_strategy3()"
python -c "from strategy import run_strategy8; run_strategy8(start='20250101')"
python backtest/strategy12_emotion_gate/tune.py
python backtest/strategy12_emotion_gate/run.py
python -c "from strategy import run_strategy12; run_strategy12()"
python backtest/strategy9_limit_down_emotion/run.py --start 20200101
python -c "from strategy import run_strategy9_emotion; run_strategy9_emotion()"
```

策略三：昨日涨停池 + T-1 连板梯度门槛 + 涨停家数冰点/正常/高潮展示 + 因子1 ±阈值。策略八：题材联动（**当日涨停定题材** + 因子14 + 因子1 当日阈值，因子15 默认关），报告见 `backtest/strategy8_theme_linkage/REPORT.md`。策略十二：因子18 恐慌空仓 × 因子21 涨停次日低开（v6：昨开板 + 上证昨收≤−2% 空仓，开盘买 T+1 清），调参窗强、**盲测回撤未过关**，报告见 `backtest/strategy12_emotion_gate/REPORT.md`。

### 因子13 · 熊市盾牌 thr\* Top3（🔒 锁定，研究）

- **说明**：[`docs/FACTOR13.md`](../docs/FACTOR13.md) · **锁定**：`backtest/factor13_bear_shield/LOCKED.json`
- **交易**：仍用策略一·因子1；每票 `thr*` 由 ≤T−1 拟合窗夏普择优（天通 ±3%）
- **2026 名单**：东材 ±2.5%、西藏珠峰 ±2.5%、雷赛智能 ±3%

```bash
python strategy/run_factor13_bear_shield_wf.py
python strategy/run_factor13_bear_shield_tune_pit.py   # VALID 调参（锁定前）
```

### 因子7说明：行业 ETF 双动量

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
| 因子6 ETF 组合动量 | `etf_combo_momentum.DEFAULT_*` | 直接调 `run_etf_combo_momentum(...)` |
| 因子7 行业 ETF 双动量 | `industry_residual_momentum.DEFAULT_PARAMS` / `DEFAULT_UNIVERSE` | 直接调 `run_industry_residual_momentum(...)` |
| 因子8 缠论买卖点 | `strategy/chan` / `evaluation.md` | `strategy2/bindings` / `backtest/strategy2.py` |
| 因子13 熊盾 Top3 | `factor13_bear_shield.DEFAULT_PARAMS` | **🔒锁定**见 `LOCKED.json`；解锁前勿改；真源 `factor13_bear_shield.py` |

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
# 因子6：宽基 ETF 组合动量
python -m strategy.etf_combo_momentum
# 旧对照：因子3选股+因子1止损
cd backtest && python compare_f3_select_f1_stop.py
# 策略一拟合池：三种≥2×阈值不过门（2023→今，分年）
cd backtest && python s1_gate_three.py
# 策略三：五槽位、单主题一只、固定持有5日
python -m strategy.backtest_factor5_serenity --start 20260101 --max-positions 5 --max-per-theme 1 --hold-days 5
# 因子7（Python API；离线测试不拉行情）
python -c "from strategy.industry_residual_momentum import run_industry_residual_momentum; print(run_industry_residual_momentum(start='20240206', end='20260630').stats)"
# 策略二：缠论合成数据流水线 / 真实面板挖掘
cd backtest && python strategy2.py demo --symbols 32
cd backtest && python strategy2.py mine --panel ../data_cache/strategy2_chan/feature_panel.parquet
# 因子13：熊市盾牌 WF（thr* Top3，锁定配置）
python strategy/run_factor13_bear_shield_wf.py
python strategy/run_factor13_bear_shield_tune_pit.py   # VALID 调参（锁定前）
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
| `run_strategy3` | 首板晋级组合回测；`entry_pcts` / `mkt_lianban_min` / `mkt_max_height_*` / `mkt_lu_*` / `sentiment_lag` |
| `run_strategy4` | 因子1+4+10 开盘突破组合；默认观察池；旧名 `run_strategy9` |
| `run_strategy5` | 因子11 近高 Top5 等权持有；`start` / `end` / `stage1_k` / `stage2_k`；旧名 `run_strategy10` |
| `run_strategy6` | 因子12 反转池近高 Top5 等权持有；研究候选，不替换策略五 |
| `run_strategy12` | 因子18 恐慌空仓 + 因子21 涨停次日低开（v6 昨开板+指数昨收门）；`backtest/strategy12_emotion_gate/run.py`（盲测未过关） |
| `run_strategy9_emotion` | 因子18 家数对照上证（CLI，Web 不展示） |
| `run_strategy2` | 因子8缠论选股；`panel` / `panel_path` / `factor_column` / `start` / `end` |
| `OpenBreak3Strategy` | = Strategy1 执行类 |
| `KCZZ_ETF` | 科创综指 589680 预设（买2.5%/止3.5%、T+1） |

---

## 文档维护规则

改 `strategy/` 下策略、因子、bindings、runner 或相关回测脚本时，**须同步更新文档**。

- **本文 § 文档维护规则**：开发者可读的真源（表格、顺序、自检）
- **Cursor Agent**：`.cursor/rules/docs-sync.mdc`（`alwaysApply`，与本文一致）

### 何时必须更新

| 变更类型 | 必改文件 |
|----------|----------|
| 新增/删除策略、改默认绑定 | **本文**、`docs/STRATEGY.md`、**READ.md § 策略与因子注册表** |
| 新增/删除因子、改 `DEFAULT_*` | **本文**因子表、`factors/factor*.py` 描述、`docs/FACTOR*.md`、**READ.md § 因子一览** |
| 因子13 规则/名单/门槛 | `docs/FACTOR13.md`、`backtest/factor13_bear_shield/LOCKED.json`、`READ.md` |
| 因子1 买卖/T+1/成本 | `open_break.py`、`docs/STRATEGY.md`、`STRATEGY_AUDIT.md`（审计变时） |
| 盯盘/预警/合格池 | `holdingStocks/README.md`、`READ.md` 盯盘节 |
| 新 CLI / `run_*.py` | **本文**回测 CLI 节、`READ.md` 运行示例 |
| 里程碑 / 锁定 / 解锁 | `TODO.MD`、`LOCKED.json` |

### 更新顺序

1. 代码 + `backtest/` 产物（csv / json / report）
2. **strategy/README.md**（注册表、CLI、默认参数表）
3. `docs/` 专题（`STRATEGY.md`、`FACTOR13.md` 等）
4. `READ.md`：`当前生效` + **§ 策略与因子注册表**（摘要表）、运行命令、盯盘节
5. `TODO.MD`：任务状态（✅ / 锁定表）；**不写**因子/策略注册表

### 因子13 双轨（勿混写）

| 注册 ID | 模块 | 状态 |
|---------|------|------|
| **factor13a** 质量带 | `factor13_fit.py` → `factors/factor13a.py` | 宽宇宙换池 + walk-forward |
| **factor13b** 熊盾 thr\* Top3 | `factor13_bear_shield.py` → `factors/factor13b.py` | **🔒 当前锁定** |
| **factor16** | `factor16_leader_score.py` | 13A 过门 + OOS 盈亏比排序（换池第二层） |

`factor13` = 别名 → `factor13a`。锁定期间：熊盾以 `LOCKED.json` 为准。

### 表述要求

- 回测数字须标注区间、是否样本外、是否等权；研究用途，非投资建议。
- 命令路径与仓库内实际脚本一致（优先 `python strategy/run_*.py`）。
- `READ.md` 不重复本文全文；用链接 + 一两句摘要。

### 提交前自检

- [ ] 本文因子/策略表含新增项
- [ ] 回测 CLI 命令可运行且路径正确
- [ ] `READ.md` **§ 策略与因子注册表** 与本文因子/策略表一致
- [ ] `READ.md` / `docs/` / `TODO.MD` 锁定项与默认行为一致
- [ ] 因子13 锁定项已写 `LOCKED.json` + `docs/FACTOR13.md`
- [ ] 回测数字标注区间、是否 OOS、研究免责声明

### 相关文档

| 文件 | 用途 |
|------|------|
| [`READ.md`](../READ.md) | 项目总览 |
| [`docs/STRATEGY.md`](../docs/STRATEGY.md) | 策略说明专题 |
| [`docs/FACTOR13.md`](../docs/FACTOR13.md) | 因子13 详述 |
| [`docs/FACTOR14.md`](../docs/FACTOR14.md) | 因子14 题材共振 |
| [`STRATEGY_AUDIT.md`](STRATEGY_AUDIT.md) | 凯盛单票审计底稿 |
| [`TODO.MD`](../TODO.MD) | 任务与锁定项 |
| [`.cursor/rules/docs-sync.mdc`](../.cursor/rules/docs-sync.mdc) | Cursor Agent 文档同步规则 |
