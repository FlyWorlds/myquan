---
name: skill-munger-mental-model
description: Munger 5-维模型与一票否决的多角度cross-validation分析工具，面向 A 股。支持单票和行业批筛。
license: GPL-3.0-only
tags: [quant, analysis, a-share, munger, mental-model]
runtime:
  claude_code: CLAUDE.md
  codex: AGENTS.md
  cursor: .cursor/rules/skill-munger-mental-model.mdc
  hermes: HERMES.md
  openclaw: OPENCLAW.md
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-munger-mental-model
  repository_url: https://github.com/quantskills/skill-munger-mental-model
  project_type: skill
  collection: mental-models
---

## 维护者

- WesleyWu2020 ([@WesleyWu2020](https://github.com/WesleyWu2020))
- 社区贡献欢迎通过 Issue / PR 参与

## 适用场景

QuantSkills 的 Munger 心理模型分析工具用于评估 A 股上市公司的投资价值，通过五个独立维度的评分与一票否决的cross-validation机制，产出高置信度的候选池。

- **研究用途**：定量评估个股在 5 个维度上的强弱，辅助投资决策研究
- **批筛用途**：按行业筛选，输出高置信度名单（CSV）与单票分析报告（JSON、PNG 雷达图）
- **数据限制**：仅使用 panda_data SDK，不涉及本地文件或第三方 API

## 5 维模型与 A 股接口映射

| 维度 | 描述 | 核心数据接口 | 主要指标 |
|------|------|-----------|---------|
| **财务** (fin) | ROE、毛利率、OCF 的相对优势 | `get_fina_performance` | ROE vs 中位数、毛利率 vs 中位数、OCF 正性与相对优势 |
| **竞争** (comp) | 行业内相对竞争力 | `get_stock_industry` + `get_industry_constituents` | 同业 ROE/毛利率百分位数、同业数量 |
| **激励** (incentive) | 大股东持股集中度、管理层增减持、质押冻结 | `get_top_holders`, `get_stock_shareholder_change` | 前十大股东持股 %、管理层净增持、质押/冻结占比 |
| **心理** (psych) | 投资者活动与机构关注度 | `get_investor_activity` | 年度投资者活动次数、参与机构数 |
| **反面清单** (neg) | 审计意见、高管变动、ST/退市、质押过高、控股股东减持 | `get_audit_opinion`, `get_stock_status_change`, `get_stock_pledge` | 审计意见（标准/非标）、代理人变动、ST 标记、质押比例 |

## 已知限制

1. **没有行业中位数 API**：自行计算行业内可比公司的中位数（财务、竞争维度）
2. **关联交易缺席**：缺乏关联交易数据，激励维度标记为 `related_party: data_unavailable`
3. **QA 文本情感分析缺席**：无法获取投资者活动的文本内容，心理维度标记为 `qa_sentiment: not_available`
4. **举牌弱代理**：用控股股东减持的 `ratio_up_limit` > 2% 作为敌意收购的弱代理，flag 为 `hostile_takeover: weak_proxy`
5. **诉讼数据缺席**：无法获取重大诉讼、违规处罚历史，自动标记 `litigation: data_unavailable`（预留，暂不触发一票否决）

## 数据边界与风险

- **数据源**：`panda_data` SDK 仅；不读本地文件，不调用其他 API
- **无未来函数**：每个维度仅使用分析基准日期当日或以前的数据
- **配置参数**（环境变量）：
  - `MUNGER_PASS_THRESHOLD=60`（分数阈值，default）
  - `MUNGER_PLEDGE_MAX=0.50`（质押比例上限，default）
  - `MUNGER_IR_MONTHS=12`（投资者活动查询范围，月数，default）
- **鉴权**：从 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 环境变量读取；不存储凭证
- **产出格式**：
  - JSON：per-stock 分析记录（`report_{symbol}.json`）
  - CSV：高置信度名单（`high_confidence_list.csv`）
  - PNG：5 维雷达图（`radar_{symbol}.png`）

## 使用方式

详见 `munger-mental-model/SKILL.md`。

### 快速开始

```bash
cd munger-mental-model/scripts

# 单票分析
python analyze.py --symbol 000001.SZ --end-date 20260630

# 行业批筛
python analyze.py --industry L2004001  # 银行业

# 验证（运行前置检查）
PYTHONPATH=. python validate.py
```

## 署名 & 灵感

本模型改编自Charlie Munger《穷查理宝典》的多角度思维方法论，并针对A股市场做出维度替换：

- 原四维（定性品质、管理质量、股价合理性、盈利稳定性）→ A股五维（财务、竞争、激励、心理、反面清单）
- 保留核心的"多角度cross-validation"与"一票否决"的决策框架
- 本工具仅供研究与教育使用，不构成投资建议，不承诺收益，不代表官方背书

---

本 repository 在 GNU General Public License v3.0 下开源。研究和教育用途，不构成投资建议。

