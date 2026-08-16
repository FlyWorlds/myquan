# Factor Mining PandaAI

**简体中文** | [English](README.en.md)

[![类型](https://img.shields.io/badge/type-community--skill-blue)](https://github.com/quantskills)
[![许可证](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

支持两种因子挖掘模式：由 AI 利用 PandaAI 数据与分析反馈主导的盲挖，
以及从公开研报、论文、PDF、DOCX 或文本中提取因子。候选可转换为
`pandaai-cli` 公式，并在用户确认后于 PandaAI 创建、回测和分析。

这是未经官方认证的 QuantSkills 社区项目，仅供研究与教育使用。

## 快速开始

```bash
python -m pip install pandaai-cli pdfplumber
pandaai-cli login
```

请使用交互式登录，不要把手机号、密码、Token 或配置文件内容写入提示词、
命令历史、示例或仓库。

示例请求：

```text
使用 $factor-mining-pandaai，从这篇论文中提取三个可复现的 A 股因子，
先列出公式、方向、参数和假设，不要立即运行回测。
```

```text
使用 $factor-mining-pandaai 做 AI 主导的盲挖，先设计 8 个跨因子族候选和
实验预算，展示后再决定是否调用 PandaAI 回测。
```

盲挖模式支持 Excel、TXT、JSON、直接字段和纯盲默认字段。Python 遗传搜索引擎执行
三阶段挖掘：字段与基础机制组合、时间序列增强、横截面
增强；程序自动完成 fitness、精英保留、交叉、突变、去重和实验台账，通过 PandaAI
反馈迭代，从而减少对话 token。文档模式先提取逻辑和来源。两种模式都只有在用户
要求或确认执行时才会调用平台计算。

## 研究边界

- 数据来源：PandaAI 平台提供的 A 股日频数据；实际字段与覆盖范围以平台为准。
- 默认股票池：PandaAI 默认沪深 A 股股票池。
- 参数：默认约 60 天回测区间、10 个分组、1 日调仓；正式研究应显式设置日期与调仓周期。
- 已知限制：公式语法、平台错误 `10075`、短样本、数据窥探、交易成本和可交易性处理均可能影响结果。
- 风险：回测结果是历史诊断，不代表未来收益，不构成投资建议。

## 目录结构

```text
skill-factor-mining-pandaai/
├── SKILL.md
├── README.md / README.en.md
├── LICENSE
├── NOTICE
├── factor-mining-pandaai.skill
├── agents/
│   ├── openai.yaml
│   ├── cursor-rule.mdc
│   └── portable-loader.md
├── references/
│   ├── pandaai_cli_reference.md
│   ├── blind_mining_workflow.md
│   ├── quant_operator_mapping.md
│   └── field_sources.md
└── scripts/
    ├── pandaai_cli_wrapper.py
    ├── blind_mining_candidates.py
    ├── blind_mining_engine.py
    ├── blind_mining_runner.py
    ├── pandaai_quant_operators.py
    └── pandaai_field_catalog.py
```

核心流程与模型、厂商和工具调用协议无关；任何能读取 Markdown、访问本地文件并
执行 Python/CLI 的 AI 都可以使用。Codex、Claude Code、Cursor、Hermes、
OpenClaw 等适配方式见 `SKILL.md` 与 `agents/`，其他 AI 可直接使用通用 loader。

## 来源与维护

- 原始作者：[`TerribleCookie`](https://github.com/TerribleCookie)
- 上游仓库：[`TerribleCookie/skill-factor-mining-pandaai`](https://github.com/TerribleCookie/skill-factor-mining-pandaai)
- QuantSkills 迁移与维护：[`abgyjaguo`](https://github.com/abgyjaguo)
- 迁移调整：补齐五运行时适配、双语文档、GPLv3 许可、社区元数据、安全登录指引与研究风险边界。

## 许可证

本迁移版本按 GNU General Public License v3.0 only（`GPL-3.0-only`）发布。
上游 MIT 许可内容见 [NOTICE](NOTICE)，完整 GPLv3 正文见 [LICENSE](LICENSE)。
