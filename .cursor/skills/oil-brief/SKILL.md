---
name: skill-oil-brief
description: >
  生成结构化原油简报（Crude Oil Briefing），覆盖当前趋势、技术分析、关键支撑/阻力位、
  今日重要事件（新闻分析）、最新研报观点、市场情绪、交易计划、价格预测、风险提示及
  AI 总结十一大维度。数据来源为 Pandadata 期货接口、EIA 开放 API、OPEC 数据。
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-oil-brief
  repository_url: https://github.com/quantskills/skill-oil-brief
  project_type: skill
  collection: oil-energy
  category: analytics
  tags:
    - crude-oil
    - commodity
    - futures
    - pandadata
    - eia
    - opec
    - energy
    - chinese
  platforms:
    - claude-code
  status: beta
  validation_level: runnable
  maintainer: xixihaha-dzh
  contributors:
    - xixihaha-dzh
  upstream: https://github.com/quantskills/skill-oil-brief
---

# Oil Brief — 原油简报生成

生成结构化原油日报/周报，数据来源为 Pandadata 期货接口、美国能源信息署（EIA）开放 API、OPEC 月度报告，输出为中文 Markdown 简报。

## 功能特性

- **11 维度深度覆盖**：当前趋势 → 技术分析 → 关键支撑位 → 关键阻力位 → 今日重要事件 → 最新研报观点 → 市场情绪 → 交易计划 → 价格预测 → 风险提示 → AI 总结
- **多数据源融合**：Pandadata 中国原油期货（SC）数据 + EIA API（WTI/Brent 价格、库存、产量）+ 新闻聚合
- **技术分析**：自动计算均线（MA5/MA10/MA20/MA60）、布林带、RSI、MACD 等指标
- **期货特色数据**：仓单库存、持仓分析、期限结构、基差等
- **综合市场情绪**：结合持仓变化、价格动量、新闻情绪等多维度判断

## 使用方式

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 Pandadata 凭证（.env 文件）
echo "DEFAULT_USERNAME=your_username" > .env
echo "DEFAULT_PASSWORD=your_password" >> .env

# 生成原油简报（默认分析 Brent 原油）
python -m oil_brief --output output/原油简报.md

# 分析其他品种
python -m oil_brief --variety WTI --output output/原油简报_WTI.md
python -m oil_brief --variety SC --output output/原油简报_SC.md

# 详细日志
python -m oil_brief --verbose
```

## 简报模板（11 章）

```
# 📊 原油日报 — YYYY-MM-DD
## 一、当前趋势
## 二、技术分析
## 三、关键支撑位
## 四、关键阻力位
## 五、今日重要事件（新闻分析）
## 六、最新研报观点
## 七、市场情绪
## 八、交易计划
## 九、价格预测
## 十、风险提示
## 十一、AI 总结
```

## 数据模块映射

| 数据模块 | Pandadata 接口 / 数据源 | 用途 |
|---------|------------------------|------|
| Brent 原油 (分析目标) | Yahoo Finance `BZ=F` | 日线 OHLCV、技术分析、支撑阻力 |
| WTI 原油 | Yahoo Finance `CL=F` | 参考价格 |
| SC 主力合约行情 | `get_future_daily` + `get_future_dominant` | 参考价格、仓单、持仓 |
| 技术指标 | 基于行情计算 | MA, BOLL, RSI, MACD |
| WTI 价格 | EIA API `PET.EER_EPD2F_PBC_S1Y_D` | 国际原油基准 |
| Brent 价格 | EIA API `PET.EER_EPD1_PBC_S1Y_D` | 国际原油基准 |
| 原油库存 | EIA API `PET.WCRSTUS1.W` | 每周库存变化 |
| 期货期限结构 | `get_future_term_structure` | 远月升贴水 |
| 仓单库存 | `get_future_warehouse_receipt` | 交割库库存 |
| 持仓分析 | `get_future_variety_posi` + `get_future_ls_ratio` | 多空比、持仓分布 |
| 基差 | `get_future_basis` | 期现价差 |
| 财经新闻 | 东方财富/Reuters API | 原油相关新闻 |
| OPEC 数据 | OPEC MOMR 月度报告 | 产量、配额数据 |

## 运行流程

1. 数据采集：并行调用 Pandadata 期货接口 + EIA API + 新闻源
2. 指标计算：基于日线数据计算技术指标（MA, BOLL, RSI, MACD）
3. 情绪分析：综合持仓变化、价格动量、新闻情感生成市场情绪评分
4. 报告渲染：按 11 章模板生成结构化 Markdown 简报
5. 输出保存：写入 output/ 目录并打印摘要

## 注意事项

- 需要有效的 Pandadata 账号凭证（配置在 .env）
- EIA API Key 可选，无 Key 时跳过 EIA 数据模块
- SC 合约有涨跌停板限制（±8% 或 ±13%）
- 数据频率：日频数据，适合日报/周报场景
- 本报告仅供参考，不构成投资建议
