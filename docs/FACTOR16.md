# 因子16 · 概念龙头评分

> 研究用途，不构成投资建议。  
> 注册表见 [`strategy/README.md`](../strategy/README.md)；Web 编排见 [`sectors/leader_score.py`](../sectors/leader_score.py)。

**最后更新**：2026-08-31

---

## 定义

在**给定股票池**（如通达信概念成分）内，对每只股票计算：

| 阶段 | 区间 | 模块 | 输出 |
|------|------|------|------|
| **FIT 定参** | 2020-01-01 → 2023-12-31 | 因子13A `factor13_fit` | 截面 `score_quality`、`f13_pass` |
| **OOS 样本外** | 默认 2025-01-01 → 今 | 因子1 `ai_concept_f1_f13_report.eval_window` | 盈亏比、胜率、超额、回撤、收益 |
| **缠论对照** | 同 OOS 窗 | 因子17 `bi_pl_ratio` | `chan_pl_ratio` / `chan_win_rate`（不参与主排序） |

## 排序（主表）

与 [`backtest/ai_concept_f1_f13_report.py`](../backtest/ai_concept_f1_f13_report.py) 一致：

1. `f13_pass` 降序（因子13A 质量带通过优先）
2. `oos_pl_ratio` 降序
3. `oos_profit_factor` 降序
4. `score_quality` 降序

门槛：FIT `n_bars ≥ 60`；OOS 闭环 `n_trades ≥ 3`。

## 真源

- `strategy/factor16_leader_score.py` — 打分/排序核心
- `strategy/factors/factor16.py` — 因子注册
- `sectors/leader_score.py` — 概念成分拉行情 + 缓存 + HTTP API

## 用法

```python
from strategy.factor16_leader_score import eval_stock_metrics_from_daily, factor16_signal
import pandas as pd

# 已有日线 DataFrame daily
row = eval_stock_metrics_from_daily("600313", daily, oos_end="20260831")
sig = factor16_signal(metrics=pd.DataFrame([row]), top_k=5)
picks = sig["picks"]
```

Web API：

```
GET /api/sectors/concept/{概念名}/leaders?start=2025-01-01&top_n=5
```

## 说明

- 概念成分按**当前名单**回测历史，存在幸存者偏差。
- 缠论依赖 `czsc`；因子1 回测与 [`ai_concept_f1_f13_report.py`](../backtest/ai_concept_f1_f13_report.py) 共用 `eval_window` / `simulate_with_trades`。
