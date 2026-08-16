---
name: alpha-f8-family-main-divergence
description: Use when developing, computing or validating the F8 commodity futures broker-position divergence factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, development, future]
---

# 家人主力分歧 Alpha

## 适用场景

- 计算商品期货 F8 家人主力分歧因子。
- 验证东方财富、徽商期货、平安期货与永安期货、中信期货、国泰君安之间的反向持仓信号。
- 生成商品期货横截面 `buy` / `sell` / `hold` 候选信号。

## 因子逻辑

- 家人席位：`东方财富`、`徽商期货`、`平安期货`，按精确字符串匹配。
- 主力席位：`永安期货`、`中信期货`、`国泰君安`，按精确字符串匹配。
- 市场总规模：当日该品种所有席位 `abs(net_margin)` 之和（`total_abs_margin`）。
- 有效分母：`denom = total_abs_margin + min(family_bull, family_bear) × 2`（加回家人内部对冲量）。
- 家人净比例：`family_ratio = family_net / denom`。
- 主力净比例：`major_ratio = major_net / denom`。
- 主力一致性：`consistency = max(major_bull, major_bear) / (major_bull + major_bear)`。
- 一致性强度：`consistency_strength = clip(2 × consistency - 1, 0, 1)`。
- 原始权重：`raw_weight = (major_ratio - family_ratio) × consistency_strength`。
- 因子值：横截面百分位映射到 `[-1, 1]`，`factor_value = rank_pct(raw_weight) × 2 - 1`（当日全品种截面，非时序）。
- 信号门槛：`rank ≤ ceil(n × 0.1)` → buy（前10%）；`rank > n - ceil(n × 0.1)` → sell（后10%）；其余 → hold。
- 排序方向：`factor_value` 越大越好（rank=1 为最高）。

## 使用方式

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

运行前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD`。可选设置 `PANDA_DATA_START_DATE`、`PANDA_DATA_END_DATE` 和 `PANDA_DATA_UNDERLYING`。

## 成功标准

- `factor.py` 输出非空，包含 12 个必需字段，`factor_id=F8`，`data_version=real-v1`。
- `validate.py` 输出验证通过信息，且家人席位和主力席位均至少出现一家。
- `backtest.py` 输出研究口径和可交易口径两组指标，包含 1D-20D IC 衰减、Bootstrap IC 95% CI、成本四档分析和可交易 ARR/IR。
- `test.py` 使用合成数据离线验证回测可导入、Bootstrap CI 和可交易口径输出。
- 数据来源为 Panda data SDK，不读取本地文件作为正式输入。

## 边界

本 skill 仅用于研究和验证，不构成投资建议，不承诺收益，不代表任何平台或组织的官方背书。不得记录、提交或传播 Panda data 凭据。
