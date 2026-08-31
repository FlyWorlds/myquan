# 因子17 · 大盘低开

> 研究用途，不构成投资建议。  
> 注册表见 [`strategy/README.md`](../strategy/README.md)。

**最后更新**：2026-08-31

---

## 定义

| 概念 | 口径 |
|------|------|
| **大盘低开** | 上证指数（默认 `sh000001`）开盘相对昨收 gap% < 0 |
| **实体阳 / 收阳家数** | **close > open**（相对开盘收红） |
| **非实体阳** | close ≤ open |

### 实体阳示例（用户口径）

昨收 100 → 开盘 95（-5%）→ 收盘 96（相对昨收 -4%）

- 相对昨收：仍下跌
- **实体阳：是**（96 > 95）

广度统计用此口径，**不是** close > 昨收。

## 输出

按低开幅度分桶（微跌、-1%、-2%、-3%、-5% 等），统计：

1. **当日**：指数日内涨跌、全日涨跌、指数是否实体阳
2. **成分广度**：中证1000 实体阳家数比例（可缓存）
3. **次日**：开盘相对今日收盘 gap、次日日内、次日相对今日收盘总收益
4. **买卖情景**（历史统计，非指令）：
   - 低开日开盘买 → 当日收盘卖
   - 低开日收盘买 → 次日开盘卖
   - 低开日收盘买 → 次日收盘卖
   - 低开日开盘买 → 次日收盘卖
5. **冲高个股**（中证1000）：低开日按 `high/open-1` 排序
   - **冠军**：当日最高价相对开盘冲高最大的一只
   - **Top5**：当日冲高前五；报告附「最近一次大盘低开」当日列表
   - 分桶统计冠军/Top5 的冲高%、全日%、实体阳比例、次日开/收表现
   - **冠军频次表**：哪些股经常在低开日充当冲高龙头

### 冲高示例

大盘低开日，某股开盘 10.00、最高 10.80、收盘 10.30 → **冲高%** = 8.0%，**日内%** = 3.0%，**实体阳** = 是。

## 真源

- `strategy/factor17_market_low_open.py`
- `strategy/factors/factor17.py`
- `strategy/data.py` → `fetch_index_daily`

## CLI

```bash
# 完整报告（含中证1000实体阳；首次较慢，结果缓存）
python -m strategy.run_factor17_market_low_open

# 仅指数统计（快）
python -m strategy.run_factor17_market_low_open --no-breadth

# 指定区间
python -m strategy.run_factor17_market_low_open --start 20200101 --end 20251231
```

产物：`backtest/factor17_market_low_open/report.md`、`bucket_stats.csv`、`top_high_bucket_stats.csv`、`top_high_leader_freq.csv`

## 代码调用

```python
from strategy.factor17_market_low_open import factor17_signal, is_intraday_yang

assert is_intraday_yang(95, 96) is True
sig = factor17_signal(start="20200101", with_breadth=False)
```
