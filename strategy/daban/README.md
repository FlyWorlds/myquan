# 打板战法（DaBan）

涨停封板买入、连板持有、不连板卖出的日线回测策略。与 `open_break`（OpenBreak3）、`yin_yang`、`oversold_bounce` **完全独立**，不共享买卖逻辑。

注册 id：`daban`

---

## 目录结构

```
strategy/daban/
├── README.md       # 本文档
├── rules.py        # 规则常量、涨停/封板判定纯函数
├── backtest.py     # DaBanStrategy（akquant）
├── config.py       # DaBanConfig、KAICHENG_DABAN 预设
├── runner.py       # run_daban() 回测入口
└── summary.py      # 回测摘要、封板日统计

huice/daban1.py     # 凯盛科技薄 CLI
```

---

## 策略规则

### 买入（空仓）

当日 **涨停封板** → 按收盘价附近建仓，目标仓位约 **95%**。

| 条件 | 说明 |
|------|------|
| 涨停价 | `ceil(昨收 × (1 + limit_pct))`，主板默认 `limit_pct=0.10` |
| 收盘涨停 | 收盘 ≥ 涨停价 − 1tick |
| 封板 | 收盘贴近最高价：`\|收 − 高\| ≤ seal_high_ticks × tick`（默认 1 分） |

对应函数：`is_sealed_limit_up()`、`limit_up_price()`

### 卖出（有仓，T+1 起）

优先级从高到低：

1. **低开止损**：开盘相对昨收低开 ≥ `gap_down_exit_pct`（默认 **3%**）→ 按开盘价全卖  
2. **不连板**：当日收盘未涨停 → 按收盘价全卖  
3. **连板**：收盘继续涨停封板 → 继续持有  

A 股 **T+1**：买入当日不可卖（由 akquant `t_plus_one=True` 控制）。

### 回测近似与局限

- 买入价 = 封板日 **收盘价**（默认能成交）  
- 未模拟：排板排队、炸板、一字板买不进、盘中开板再回封  
- 未区分：首板 / 二板 / 连板数、量能、题材  
- 创业板 / 科创板需自行设 `limit_pct=0.20`  

---

## 配置参数（`DaBanConfig`）

| 字段 | 默认 | 含义 |
|------|------|------|
| `symbol` | `sh600552` | 标的代码 |
| `symbol_name` | 凯盛科技 | 显示名称 |
| `start_date` / `end_date` | `20200101` / 今日 | 回测区间 |
| `target_pct` | `0.95` | 建仓目标仓位 |
| `limit_pct` | `0.10` | 涨停幅度（10% / 20%） |
| `gap_down_exit_pct` | `0.03` | 低开卖出阈值（3%） |
| `seal_high_ticks` | `1.0` | 封板判定：收与高相差 tick 数 |
| `initial_cash` | `100000` | 初始资金 |
| `commission_rate` | 万 0.854 | 佣金 |
| `stamp_tax_rate` | `0.001` | 卖出印花税 |
| `slippage_value` | `0.001` | 滑点 0.1% |

预设：`KAICHENG_DABAN`（凯盛科技，2020 年起）

---

## 快速使用

### CLI（推荐）

```bash
cd myquan/huice

# 打印规则
python daban1.py --rules

# 凯盛科技回测
python daban1.py --start 20200101

# 调参：20% 涨停 + 低开 5% 走
python daban1.py --limit-pct 0.20 --gap-exit 0.05
```

### 注册表

```python
from strategy.registry import get_strategy

entry = get_strategy("daban")
entry.run(entry.default_config, show_report=True)
if entry.print_rules:
    print(entry.print_rules())
```

### 代码直调

```python
from dataclasses import replace
from pathlib import Path
from strategy.daban.config import KAICHENG_DABAN
from strategy.daban.runner import run_daban

cfg = replace(
    KAICHENG_DABAN,
    symbol="sz002171",
    symbol_name="楚江新材",
    start_date="20200101",
    report_path=Path("楚江新材_daban_report.html"),
)
run_daban(cfg, show_report=True)
```

### 仅用规则函数（无回测）

```python
from strategy.daban.rules import (
    limit_up_price,
    is_limit_up_close,
    is_sealed_limit_up,
)

prev = 10.00
lu = limit_up_price(prev)           # 11.00
is_sealed_limit_up(10.5, 11.0, 10.2, 11.0, prev)  # True
```

---

## 模块说明

| 文件 | 职责 |
|------|------|
| `rules.py` | `STRATEGY_RULES` 文案；涨停价、封板、低开判定；**无 akquant 依赖** |
| `backtest.py` | `DaBanStrategy.on_bar`：封板买 / 低开卖 / 不连板卖 / 连板持 |
| `config.py` | 继承 `CommonBacktestParams` 的配置 dataclass |
| `runner.py` | `run_backtest_pipeline` 封装：拉日线 → 回测 → 摘要 → 可选 HTML |
| `summary.py` | 收益、回撤、胜率；历史封板日计数与最近样本列表 |

---

## 与其他策略关系

```
strategy/
├── open_break.py + backtest.py    # 策略1 OpenBreak3
├── yin_yang/                      # 策略2 阳买阴卖
├── oversold_bounce/               # 超跌形态统计（非自动交易）
└── daban/                         # 策略3 打板战法 ← 本模块
```

共用：`strategy/data.py`（日线）、`strategy/base.py`（回测骨架）、`strategy/registry.py`（注册）。

---

## 扩展建议

可按需在 `rules.py` / `backtest.py` 增加，而不影响其他策略：

- 首板 / 连板过滤（统计连续涨停天数）  
- 量能：`volume > N 日均量 × k`  
- 炸板过滤：曾开板（`high` 封板但 `low` 远离涨停）  
- 分钟线排板：接入 `strategy/minute.py`  
- 盯盘：在 `holdingStocks/index.py` 引用 `rules` 中信号函数  

修改规则后请同步更新 `rules.py` 内 `STRATEGY_RULES` 与本文档。
