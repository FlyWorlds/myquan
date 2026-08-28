---
name: skill-auction-yizi-linkage
description: >-
  A-share call-auction one-word limit-up linkage stock selection. Identifies
  auction/open one-word leaders as theme anchors, then ranks same-concept
  high-open followers for intraday or next-open execution. Use when the user
  asks for 竞价一字联动选股, 一字联动, auction linkage picks, or strategy12/factor14.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-auction-yizi-linkage
  repository_url: https://github.com/quantskills/skill-auction-yizi-linkage
  project_type: skill
  collection: event-driven-selection
  license: GPL-3.0
  category: strategy
  tags: [a-share, call-auction, one-word, concept-linkage, limit-up]
  platforms: [codex, openclaw, cursor]
  language: zh-en
  status: active
  validation_level: runnable
  maintainer_type: community
  requires: [skill-pandadata-api, skill-b6-limitup-pool]
  summary_zh: 竞价/开盘一字为题材锚，同概念内选高开联动标的；对接 strategy12/因子14。
  summary_en: Theme-anchor one-word leaders at auction/open, then rank high-open linkage picks in the same concept; wired to strategy12/factor14.
---

# 竞价一字联动选股 Skill

识别 **竞价/开盘一字** 龙头作为题材锚，在同代表题材（PIT 概念成分）内筛选 **高开联动** 标的。结果仅用于研究，不构成投资建议。

## 何时使用

- 用户说「竞价一字联动」「一字联动选股」「题材联动高开」
- 需要跑 **策略十二 / 因子14** 日频名单或回测
- 盘前 09:15–09:25 需要题材锚 + 联动候选清单

## 核心规则（与 B6 一字口径同源）

| 步骤 | 规则 |
|------|------|
| 锚点 | 竞价价（优先 `opn_auc`）与 `low` 均贴涨停价 → 一字龙头（通常买不进，只作题材信号） |
| 联动池 | 与锚点 **同代表题材**（`lead_concept`：所属概念中当日一字龙头数最多） |
| 过滤 | 开盘高开 `min_open_gap`–`max_open_gap`；非 ST；非一字涨停（可成交） |
| 排序 | `score = 高开幅度 × (1 + 题材内一字龙头数)` |
| 输出 | TopK（默认 5）；T 开盘等权买入，持有 `hold_days` 日（默认 1） |

## 数据与接口

1. 先读 `pandadata-api`：`get_stock_daily`（含 `open/low/limit_up/opn_auc`）、`get_concept_list`、`get_concept_constituents`（**必须带快照日**，PIT）。
2. 一字判定与 B6 / alpha-A3 保持一致，避免口径漂移。
3. 无分钟竞价快照时，回测用日线 `open/low/limit_up` 代理；有 `opn_auc` 时优先。

## 代码入口（本仓库）

```python
from strategy import run_strategy12, get_strategy

# 研究回测（默认沪深300+500+1000 缓存宇宙）
run_strategy12(start="20240101", top_k=5, hold_days=1)

# 规则说明
print(get_strategy("竞价一字联动").print_rules())

# 单日信号（自备 panel 长表 + 概念成分）
from strategy.auction_yizi_linkage import factor14_signal
factor14_signal(panel=panel_df, concepts=concept_df, date="2026-08-01")
```

## 工作流

1. **确定交易日**：非 A 股交易日则直接返回休市说明。
2. **拉行情**：全市场或指定宇宙日线；竞价时段可用实时 `opn_auc`。
3. **拉概念**：`get_concept_constituents(concept=..., date=快照日)`，禁用未来成分。
4. **跑选股**：`daily_linkage_picks` 或 `run_strategy12`。
5. **输出**：Markdown 表格列出一字锚点、代表题材、联动候选、score、可成交性提示。

## 假设与限制

- 不模拟集合竞价排队、撤单、通道优先级。
- 一字龙头默认 **不参与买入**（锚点 only）。
- 概念数据缺失时联动池为空，须显式标注「题材降级」。
- 研究模拟，不承诺收益，不提供个性化投资建议。

## 关联

- 因子14 / 策略十二：`strategy/auction_yizi_linkage.py`
- 涨停池 / 一字口径：`skill-b6-limitup-pool`
- 概念 PIT：`skill-concept-rotation-monitor`
