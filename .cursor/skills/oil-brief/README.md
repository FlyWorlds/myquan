# 🛢️ skill-oil-brief — 原油简报生成

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL3-blue.svg)](LICENSE)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-purple)](https://claude.ai/code)

基于 Pandadata 期货接口、Yahoo Finance、EIA 开放 API 的 **原油日报自动生成工具**，输出 11 章结构化中文 Markdown 简报。

## 功能

覆盖 **十一大维度** 的原油市场分析：

| 模块 | 内容 | 数据源 |
|------|------|--------|
| 当前趋势 | Brent/WTI/SC 三品种价格、日涨跌幅、趋势判断 | Yahoo Finance + Pandadata |
| 技术分析 | MA5/10/20/60、布林带、RSI、MACD、ATR 波动率 | 基于日线 OHLCV 计算 |
| 关键支撑位 | 多强度分级（强/中/弱），标注计算依据 | 均线、枢轴点、布林带、整数关口 |
| 关键阻力位 | 同上 | 同上 |
| 消息面分析 | 实时 RSS 新闻 + 利好/利空/中性判断 | Google News RSS |
| 最新研报观点 | 基于技术面的机构观点汇总 | 数据驱动自动生成 |
| 市场情绪 | 多空信号综合评分 | RSI + MACD + 均线排列 |
| 交易计划 | 顺势/震荡/反转策略 + 仓位管理 | 趋势 + 支撑/阻力 |
| 价格预测 | ATR 短期区间 + 方向概率 | 波动率 + 趋势 |
| 风险提示 | 波动/政策/地缘风险分级 | 综合评估 |
| AI 总结 | 核心观点 + 操作建议 | 全局综合 |

## 快速开始

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置数据源凭证

```bash
cp .env.template .env
```

编辑 `.env` 填入你的 Pandadata 账号（**必填**）和 EIA API Key（可选）：

```
DEFAULT_USERNAME=your_username
DEFAULT_PASSWORD=your_password
EIA_API_KEY=your_eia_api_key
```

> Pandadata 注册: https://pandadata.pandaaiquant.com
> EIA API Key 免费注册: https://www.eia.gov/opendata/register.php

### 3. 生成原油简报

```bash
# 默认分析 Brent 原油
python -m oil_brief --output 原油简报.md

# 分析 WTI 或 SC
python -m oil_brief --variety WTI --output 原油简报_WTI.md
python -m oil_brief --variety SC --output 原油简报_SC.md

# 详细日志
python -m oil_brief --verbose
```

## 输出示例

生成的简报为 11 章中文 Markdown 报告：

```markdown
# 📊 原油日报 — Brent 原油

## 一、当前趋势
| 品种 | 最新价 | 日涨跌幅 |
|------|--------|----------|
| **Brent 原油** | **93.43 美元/桶** | **+2.66%** |
| WTI 原油 | 86.61 美元/桶 | +2.01% |
| 上海原油期货 (SC) | 531.00 元/桶 | -3.17% |

## 二、技术分析 → MA / BOLL / RSI / MACD / ATR
## 三、关键支撑位 → 多强度分级支撑位表
## 四、关键阻力位 → 多强度分级阻力位表
## 五、消息面分析 → 实时新闻 + 利好/利空评估
## 六、最新研报观点 → 数据驱动机构观点
## 七、市场情绪 → 多空信号综合评分
## 八、交易计划 → 顺势/震荡策略 + 仓位管理
## 九、价格预测 → ATR区间 + 方向概率
## 十、风险提示 → 波动/政策/地缘分级风险
## 十一、AI 总结 → 核心观点 + 操作建议
```

## 项目结构

```
skill-oil-brief/
├── SKILL.md                 # Claude Code 技能定义
├── CLAUDE.md                # Agent 行为指令
├── pyproject.toml           # 项目配置
├── requirements.txt         # Python 依赖
├── .env.template            # 凭证模板
├── .gitignore
├── src/
│   └── oil_brief/
│       ├── __init__.py
│       ├── __main__.py      # CLI 入口 (python -m oil_brief)
│       ├── client.py        # Pandadata 客户端封装
│       ├── core.py          # 协调器（并行数据采集 + 技术分析 + 渲染）
│       ├── renderer.py      # 11 章 Markdown 渲染
│       ├── analysis.py      # 技术指标引擎（MA/BOLL/RSI/MACD/ATR/S&R）
│       ├── utils.py         # 格式化工具
│       └── fetchers/
│           ├── china.py     # SC 原油期货数据（Pandadata）
│           ├── eia.py       # WTI/Brent 价格（Yahoo）+ 库存（EIA）
│           └── news.py      # 实时新闻（Google News RSS）
├── agents/                  # 多平台加载文件
├── references/              # 数据源文档
└── output/                  # 生成报告目录
```

## 作为 Claude Code Skill 使用

本项目的 `SKILL.md` 定义了技能行为。在 Claude Code 中可直接调用：

```bash
# 安装后，在当前对话中可直接要求：
"生成原油简报"

# 或指定品种：
"生成一份 WTI 原油的日报"
```

## 数据来源

| 数据 | 接口 / API | 是否需要 Key |
|------|-----------|-------------|
| Brent 日线 OHLCV | Yahoo Finance `BZ=F` | ❌ 免费 |
| WTI 日线 OHLCV | Yahoo Finance `CL=F` | ❌ 免费 |
| SC 主力合约行情 | Pandadata `get_future_daily` | ✅ 必填 |
| SC 仓单/持仓 | Pandadata 期货接口 | ✅ 必填 |
| 美国原油库存 | EIA `PET.WCRSTUS1.W` | ⚠️ 可选 |
| 原油新闻 | Google News RSS | ❌ 免费 |

## 注意事项

- 本报告 **不构成投资建议**
- 技术分析基于历史数据，过去表现不代表未来结果
- 需要有效的 Pandadata 账号凭证
- EIA API Key 可选，配置后可获取实时库存量化数据
- SC 合约有涨跌停板限制（±8% 或 ±13%）

## License

GPL-3.0

## Author

- **xixihaha-dzh** — 作者与维护者
