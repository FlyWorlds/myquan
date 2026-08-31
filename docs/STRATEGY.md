# 策略说明（myquan）

> 研究用途，不构成投资建议。  
> 注册表与 API 细节见 [`strategy/README.md`](../strategy/README.md)；凯盛单票审计见 [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md)。

**最后更新**：2026-08-31

---

## 1. 默认与分层

| 层级 | 目录 | 职责 |
|------|------|------|
| 因子 | `strategy/factors/` | 价位、信号、截面打分 |
| 策略 | `strategy/strategies/strategyN/` | 绑定哪些因子、专属过滤 |
| 决策 | `decision.py` | `MarketContext` → buy/sell/hold |
| 执行 | `runner.py` / `backtest.py` / 盯盘 | 回测、下单模拟、预警 |

**实盘盯盘默认**：**策略一 = 因子1 + 因子2 预警**（因子2 回测不注资）。

**动态选股（研究，已锁定）**：**因子13 · 熊市盾牌 thr\* Top3**，见 [`FACTOR13.md`](FACTOR13.md)。

---

## 2. 策略一 · 援军战法（strategy1）

### 因子1 · 开盘突破

- 买：空仓；前日阴/小阳；禁双阳跨日≥5%；`high ≥ ceil(open×(1+pct))` 限价买；目标仓位约 95%。
- 卖：仅止损 `low ≤ floor(open×(1−pct))`；T+1 当日新仓不可卖；一字跌停不卖。
- 默认 pct：**±2.5%**（单票可非对称，如天通 ±3% / 凯盛 ±2.5%）。
- 真源：`strategy/open_break.py`、`strategy/factors/factor1.py`。

### 因子2 · 回撤预警

- 由历史最大回撤、年均最大回撤标定加减仓线（默认加仓≥20% / 减仓≤10%）。
- **回测默认只预警不注资**；旧版 `dd_topup` 需显式开启。

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
| strategy9 | 低开跌停情绪 | factor18 | 研究；见 §3.3 |

缠论笔盈亏比已归 **因子17**（原 strategy7 CLI 仍可用）。

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
| 定题材 | **当日**收盘涨停池 → 因子14 `theme_lu_count ≥ 3` |
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

### 3.3 策略九 · 低开跌停情绪（strategy9）

**统计口径（2020→今，研究）**

- 宇宙：中证1000（剔 ST / 北交），与策略三同源日线缓存
- **低开开盘即跌停**：开盘 < 昨收，且开盘价落在跌停价容差内（主板 10% / 科创创业 20%）
- 大盘参照：上证指数 `sh000001` 收盘相对昨收涨跌幅

**情绪阶段（`mkt_ld_open` 家数）**

- 平静：`0`（当日无低开跌停开盘）
- 正常：`1～3`
- 恐慌：`≥ 4`

**方向研判（样本内规则，非投资建议）**

- 恐慌 → 预判当日收跌；平静 → 预判当日收涨；正常 → 顺势偏空

```bash
python backtest/strategy9_limit_down_emotion/run.py --start 20200101
python -c "from strategy import run_strategy9_emotion; run_strategy9_emotion()"
```

真源：`strategy/strategies/strategy9/` · 报告：`backtest/strategy9_limit_down_emotion/REPORT.md`

---

## 4. 合格池与盯盘

- **静态合格池**：中证500∪1000 主板，夏普等筛选 → `backtest/universe_zz500_1000/`。
- **动态池（锁定）**：因子13 WF 每年 `T←≤T−1` 重算 Top3，见 `LOCKED.json`。
- **盯盘**：`holdingStocks/`，规则与因子1 同源；WebSocket + 微信预警（P0 已完成）。

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
| [`TODO.MD`](../TODO.MD) | 任务优先级 |
| [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md) | 凯盛 OpenBreak 审计底稿 |
