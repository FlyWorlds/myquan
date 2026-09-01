# 策略十三 · 纯因子1 ETF

研究组合，非默认盯盘。不构成投资建议。

## 做什么

- **仅因子1**：开盘突破买入 / 开盘止损卖出；ETF 强制 T+1；印花 0
- **宇宙**：全市场场内 ETF（AkShare 列表）
- **Walk-forward 选票**：
  - **Cohort A**（2023 前上市）：IS `2023-01-02～2025-12-31` 选参 → OOS `2025-01-02～今`
  - **Cohort B**（2025 上市）：IS `上市日～2025-12-31` 选参 → OOS `2026-01-02～今`
- **排名**：冻结 IS 最优参数后，只看 **OOS 综合分** 取 Top10

## OOS 综合分（研究打分）

截面分位加权（`strategy/strategies/strategy13/scoring.py`）：

| 指标 | 权重 |
|------|------|
| OOS 夏普 | 30% |
| OOS 超额 | 30% |
| OOS 收益 | 20% |
| 胜率（全段闭环） | 20% |

## 运行

```bash
python strategy/strategies/strategy13/run_etf_wf.py
```

产物：`strategy/strategies/strategy13/etf_wf/report.md`、`top10_pool.json`

## 注册

- ID：`strategy13` · 别名 `s13` / `etf_f1` / `策略十三`
- 绑定：仅 `factor1`
- 真源池：`etf_wf/top10_pool.json`
