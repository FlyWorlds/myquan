# 策略说明（myquan）

> 研究用途，不构成投资建议。  
> 注册表与 API 细节见 [`strategy/README.md`](../strategy/README.md)；凯盛单票审计见 [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md)。

**最后更新**：2026-08-30

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
| strategy3 | 首板晋级 | factor1；**盯盘**=昨日涨停池+T-1情绪+±阈值（不过门）；**回测**=首板+gap/量比 | 研究 |
| strategy4 | F4 止盈动量 | factor1+4+10 | 研究 |
| strategy5 | 近高 Top5 等权 | factor11 | 研究 |
| strategy6 | 反转池近高 | factor12 | 研究，未替换 strategy5 |
| strategy7 | 策略七·缠论笔盈亏比 | factor1 | 研究 |
| strategy8 | 题材联动 | factor14 + factor1 | 研究；**当日涨停**定题材→联动候选当日±阈值；2025→ 见 REPORT |

因子14：同题材昨日涨停同伴数（通达信概念 offline 索引）。

组合动量/行业 ETF：因子6、因子7（见 `strategy/README.md`）。

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
| [`TODO.MD`](../TODO.MD) | 任务优先级 |
| [`strategy/STRATEGY_AUDIT.md`](../strategy/STRATEGY_AUDIT.md) | 凯盛 OpenBreak 审计底稿 |
