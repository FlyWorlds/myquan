# 🧩 Investment Decision

**简体中文** | [English](README.en.md)

> 输入公司名称或股票代码，基于公开数据（Yahoo Finance + 网络搜索）输出长期投资决策报告（买入/中性/卖出 + 置信度）的 .docx 文件。默认英文，支持中文。自包含 — 无需付费 API。

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 这是什么

`skill-investment-decision` 是一款面向 AI Agent 的长期投资决策技能组件。给定任意公司名称或股票代码（支持 A 股、港股、美股及全球市场），Agent 会自动：

1. 通过 Yahoo Finance 公共接口获取价格历史、财务报表、关键指标（PE、PB、ROE、ROA 等）；
2. 通过网络搜索获取近期新闻、分析师评级、行业趋势、竞争格局及风险因素；
3. 按 6 个维度（财务健康、成长性、估值、动量情绪、行业地位、风险）加权打分；
4. 输出明确的 **长期（6–18个月）买入 / 中性 / 卖出** 建议及置信概率；
5. 生成格式化的 .docx 专业报告。

**自包含设计** — 无需 Pandadata 或任何付费 API，仅依赖公开数据源。

## 🚀 快速开始

### Agent 工作流

```text
User: 分析一下平安银行，给我长期投资建议

Agent:
1. 解析 ticker → 000001.SZ（网络搜索），检测语言 → zh
2. 通过 Yahoo Finance 获取价格历史（252天）、财务报表、关键指标
3. 网络搜索: 平安银行近期新闻、分析师评级、行业趋势、关键风险
4. 按决策框架打分（6 维度加权）
5. 生成中文 report.json，设置 investment_horizon: "long-term"
6. 校验: python scripts/validate_report.py --report report.json
7. 生成 docx (中文):
   python scripts/generate_report.py --report report.json \
     --output 000001.SZ_investment_decision_20260622.docx --language zh
8. 报告: "平安银行 — 长期 NEUTRAL（65% 置信度），核心逻辑：..."
   （决策在报告末尾揭示）
```

### 直接使用工具

```bash
# Step 1: 获取财务数据
python scripts/fetch_data.py --ticker MSFT --output data.json

# Step 2: Agent 填充定性部分（风险、评分、结论）

# Step 3: 校验报告
python scripts/validate_report.py --report data.json

# Step 4: 生成 .docx 报告
python scripts/generate_report.py --report data.json --output output.docx [--language zh]
```

## 📦 目录结构

```
skill-investment-decision/
├── SKILL.md                          # 技能入口（YAML 声明 + Agent 指令）
├── README.md / README.en.md          # 说明文档
├── LICENSE                           # GPL-3.0
├── .gitignore
├── requirements.txt                  # yfinance, python-docx, pandas, numpy, pyyaml, matplotlib
├── references/
│   ├── decision-contract.md          # 📚 报告结构契约、打分框架、数据源、校验规则
│   └── agent-integration.md          # 🔌 多 Agent 安装与冒烟测试
├── scripts/
│   ├── fetch_data.py                 # 📊 Yahoo Finance 数据获取（自动填充所有财务字段）
│   ├── validate_report.py            # 🧪 报告校验器（13 条规则）
│   └── generate_report.py            # 📄 .docx 报告生成器（含图表、表格、参考文献）
└── agents/
    ├── openai.yaml                   # OpenAI/Codex 适配
    ├── cursor-rule.mdc               # Cursor 规则适配
    └── portable-loader.md            # 通用 Agent 加载器
```

## ⚠️ 免责声明

本仓库仅作研究方法层面的整理与展示，不构成任何投资建议。投资有风险，决策须谨慎。

## 👤 维护者

创建与维护：`davideliu`（QuantSkills community）。

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
