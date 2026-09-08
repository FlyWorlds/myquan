# 策略说明（myquan）

> 研究用途，不构成投资建议。  
> 注册表与 API 细节见 [`strategy/README.md`](../strategy/README.md)；凯盛单票审计见 [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md)。

**最后更新**：2026-09-08

---

## 1. 默认与分层

| 层级 | 目录 | 职责 |
|------|------|------|
| 因子 | `strategy/factors/` | 价位、信号、截面打分 |
| 策略 | `strategy/strategies/strategyN/` | 绑定哪些因子、专属过滤 |
| 决策 | `decision.py` | `MarketContext` → buy/sell/hold |
| 执行 | `runner.py` / `backtest.py` / 盯盘 | 回测、下单模拟、预警 |

**实盘盯盘默认**：**策略一 = 因子26 多层止盈 + 因子2 预警 + 因子22 收盘动量再买**（因子2 回测不注资）。

**动态选股（研究，已锁定）**：**因子13 · 熊市盾牌 thr\* Top3**，见 [`FACTOR13.md`](FACTOR13.md)。

因子26：[`FACTOR26.md`](FACTOR26.md)。

---

## 2. 策略一 · 援军战法（strategy1）

### 因子26 · 多层止盈（主执行）

- 买：同因子1；前日阴/小阳；禁双阳跨日≥5%；开盘突破或攻击波限价买；目标仓位约 95%。盘中触达以 `holdingStocks/index.py` 的 **1 分钟路径**为准（禁止全日 OHLC 假触）。
- 卖（同分钟优先级）：隔夜武装（昨亏/止盈标记/已记）开盘下杀 1% 全清 → 阶梯 15% 全清 → 回吐一半全清 → 阶梯 10% 与峰值回落 3% 半仓（同分钟只一次；已半仓再触则清剩余）→ 抬升 peak。T+1 当日只记。
- 默认 entry **±2.5%**，阶梯 **10%/15%**，峰值回落 **3%**，giveback **50%**，硬保护 **2.5%**。
- 真源：`strategy/pullback_wave_stop.py`（`eval_multi_tp_bar`）、`strategy/factors/factor26.py`。
- 因子1（`open_break.py`）仍供策略三/四/八等复用，已非策略一主因子。

### 因子2 · 回撤预警

- 由历史最大回撤、年均最大回撤标定加减仓线（默认加仓≥20% / 减仓≤10%）。
- **回测默认只预警不注资**；旧版 `dd_topup` 需显式开启。

### 因子22 · 收盘动量（已绑策略一）

- 因子26 当日止损后：三槽执行下**当日禁再买该票**（因子22 研究路径不覆盖槽位禁买）。
- **仓位**：物理 3 槽（盘中可持 3）；当日最多买 2；尾盘空 1 槽（隔夜最多 2）。
- 对照见 `holdingStocks/watch_config.py`：`MAX_PORTFOLIO_SLOTS` / `MAX_OVERNIGHT_SLOTS` / `MAX_BUYS_PER_DAY` / `RESERVE_EMPTY_SLOTS`（`MAX_ACTIVE_SLOTS` 兼容旧名=隔夜上限）。
- 绑定：`strategy1/bindings`；决策见 `Strategy1Decision`；说明：[`FACTOR22.md`](FACTOR22.md)。
- 天通 2026 日线对照见 `backtest/tiantong_stop_rebuy_2026/`；扩样本前勿调默认 pct。

### 运行

```bash
cd backtest && python strategy1.py --rules
cd backtest && python run.py kaicheng
python -c "from strategy import run_open_break; ..."
```

---

## 3. 其他已实现策略（摘要）

| ID | 名称 | 核心 | 状态 |
|----|------|------|------|
| strategy2 | 缠论 | factor8 | 研究 |
| strategy3 | 首板晋级 | factor1 | 研究；见 §3.1 |
| strategy4 | F4 止盈动量 | factor1+4+10 | 研究 |
| strategy5 | 近高 Top5 等权 | factor11 | 研究 |
| strategy6 | 反转池近高 | factor12 | 研究，未替换 strategy5 |
| strategy8 | 题材联动 | factor14 + factor1 | 研究；见 §3.2 |
| strategy12 | 涨停次日低开 | factor18 + factor21 | 研究，v6 盲测回撤未过关；见 §3.3 |

缠论笔盈亏比已归 **因子17**（原 strategy7 CLI 仍可用）。
低开跌停情绪已归 **因子18**（原 strategy9 CLI 仍可用）。

因子14：**当日**同题材涨停同伴数（通达信概念 offline 索引），见 [`FACTOR14.md`](FACTOR14.md)。

组合动量/行业 ETF：因子6、因子7（见 `strategy/README.md`）。

---

### 3.1 策略三 · 首板晋级（strategy3）

**盯盘口径**

- 宇宙：中证1000 **昨日收盘涨停**全池
- **T-1 情绪门槛**（决定是否今日可做）：连板家数 `mkt_lianban ≥ 2`，最高板 `mkt_max_height ∈ [2, 5]`
- **T-1 涨停家数阶段**（展示用，与门槛独立）：
  - 冰点：`mkt_lu ≤ 6`
  - 正常：7～14
  - 高潮：`≥ 15`
- 执行：晋级日 **因子1 ±阈值**突破买（盯盘不过阴/小阳过门）；T+1 止损或收盘清

**回测口径**（`backtest/strategy3_first_board/`）

- 选股：昨日首板（近5日无涨停）、非一字/秒板、量比≥1.4、晋级日低开带
- 同上 T-1 连板梯度门槛；可选 `--mkt-lu-min/max`

真源：`strategy/strategies/strategy3/`、`strategy/strategies/strategy3/sentiment_phase.py`、`holdingStocks/strategy3_watch.py`

---

### 3.2 策略八 · 题材联动（strategy8 · v3 当日定题材）

| 项 | 说明 |
|---|---|
| 定题材 | **当日**涨停池 → 因子14 `theme_lu_count ≥ 3`；盯盘 9:15 起跟实时涨停走，集合变则重算 |
| 股池 | 默认 `linkage`：热题材内**非当日涨停**联动票 |
| 买卖 | **当日**因子1 ±阈值突破即买（非次日晋级买） |
| 情绪 | T-1 连板梯度（与策略三同源）；T-1 涨停家数阶段同策略三展示 |
| 因子15 | 默认**关闭**；`--gap-filter` 可选启用低开带 |

**回测参考**（2025-01-02 → 2026-08-11，研究，非投资建议）：

| 阈值 | 总收益 | 最大回撤 | 笔数 |
|------|--------|----------|------|
| ±2.5% | +6.1% | 4.4% | 179 |
| ±3.0% | +9.1% | 2.9% | 184 |

真源：`strategy/strategies/strategy8/theme_linkage.py` · 报告：`backtest/strategy8_theme_linkage/REPORT.md`

---

### 3.3 策略十二 · 涨停次日低开（strategy12）

不绑定凯盛/天通。宇宙中证1000 截面。

**组合**

| 因子 | 角色 |
|------|------|
| factor18 | 恐慌日（低开开盘跌停≥4）空仓 |
| factor21 | 昨收涨停且曾开板 + 今日低开 [−4.5%, −0.3%] 未封涨停；上证昨收≤−2% 空仓；开盘买、T+1 收盘清；每日 Top3 |

**结论：未过关**（研究，非盯盘默认）。调参窗 2020-01-02～2024-12-31 +645% / 夏普 1.23；盲测 2025-01-02～2026-08-28 +3.6% / 回撤 55%。今日开盘涨停不买；卖出遇一字跌停顺延；昨一字/未开板剔除。不在盲测窗上再调参。

已否决：v1 恐慌禁买叠因子1；v2/v3 压力日低开；v4 跌停次日开板；v5 无开板过滤。

```bash
python backtest/strategy12_emotion_gate/tune.py
python backtest/strategy12_emotion_gate/run.py
python -c "from strategy import run_strategy12; run_strategy12()"
```

真源：`strategy/strategies/strategy12/` · 报告：`backtest/strategy12_emotion_gate/REPORT.md`  
因子说明：[`FACTOR18.md`](FACTOR18.md) · [`FACTOR21.md`](FACTOR21.md)

因子18 家数对照上证的 CLI 仍为 `run_strategy9_emotion()`（Web 策略栏不展示）。

---

## 4. 合格池与盯盘

- **静态合格池**：中证500∪1000 主板，夏普等筛选 → `backtest/universe_zz500_1000/`。
- **动态池（锁定）**：因子13 WF 每年 `T←≤T−1` 重算 Top3，见 `LOCKED.json`。
- **盯盘**：`holdingStocks/`，规则与因子1 同源；首页 Tab：策略1 / 3 / 8 / **15**。

---

## 4.5 策略十五 · 连板减磨损（strategy15）

> 研究用途，不构成投资建议。盯盘有实时面板；**持仓 Tab 仍按策略一自动结算**，本策略为减磨损对照。

- **建仓**：因子1 开盘突破（过门与策略一相同）。
- **止损 / 震荡减磨损**：因子24 判定震荡/常规时启用 **因子25（30m）**：连续 2 根 30m 收盘确认止损、涨约 12% 后回撤 5% 半仓、止损后 ±1.5% 卖飞回补（回补窗禁新 F1）。完整路径见 `backtest/strategy15_m30_chop/`。
- **止盈减半（高潮/无 F25）**：因子23×24 日线固定 % 减半。
- **卖飞接回（无 30m）**：因子22 收盘动量；与 F25 同由因子24 门控，高潮关掉接回。

情绪口径与策略三相同：盯盘读 T-1 `mkt_max_height` / `mkt_ladder_score` / `mkt_lianban`。

---

## 5. 回测约定

- 日线：前复权 qfq，缓存 `data_cache/`。
- 成本：佣金、杂费、印花税、滑点见 `strategy/costs.py` / 各 `BacktestConfig`。
- 样本外：选股/阈值 **禁止** 使用交易年数据；见因子13 WF 协议。

---

## 6. 文档索引

| 文档 | 内容 |
|------|------|
| [`READ.md`](../READ.md) | 项目总览、安装、运行 |
| [`strategy/README.md`](../strategy/README.md) | 因子/策略注册表、CLI |
| [`FACTOR13.md`](FACTOR13.md) | 因子13 质量带 + 熊市盾牌 |
| [`FACTOR14.md`](FACTOR14.md) | 因子14 题材共振（策略八） |
| [`FACTOR18.md`](FACTOR18.md) | 因子18 低开跌停情绪（策略十二择时） |
| [`FACTOR19.md`](FACTOR19.md) | 因子19 低开反包（旧假设，未过关） |
| [`FACTOR20.md`](FACTOR20.md) | 因子20 跌停次日开板（已否决） |
| [`FACTOR22.md`](FACTOR22.md) | 因子22 收盘动量 |
| [`FACTOR23.md`](FACTOR23.md) | 因子23 最高连板止盈 |
| [`FACTOR24.md`](FACTOR24.md) | 因子24 连板梯度情绪 |
| [`FACTOR25.md`](FACTOR25.md) | 因子25 30m 震荡减磨损 |
| [`TODO.MD`](../TODO.MD) | 任务优先级 |
| [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md) | 凯盛 OpenBreak 审计底稿 |
