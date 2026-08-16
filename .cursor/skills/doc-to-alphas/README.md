# 🧩 Doc to Alphas

**简体中文** | [English](README.en.md)

> 提供标准化OHLCV因子表达式格式与合成数据校验，支撑Agent基于文档生成Alpha因子并完成自动化合规校验。

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 这是什么

`skill-doc-to-alphas` 是一款自包含的 Agent 技能组件，无外部 API 依赖，也不依赖其他技能，核心由两部分构成：

1. **因子表达式格式** — `references/alpha_ops.md` 明确定义 6 个基础行情字段与 27 个内置运算函数的使用边界，所有 Alpha 表达式必须严格遵循该格式要求，从源头规避非法字段、未来函数偏差，保障因子语法统一、逻辑可复现。
2. **合成数据校验** — 配套 `scripts/generate_alphas.py --alphas <file>` 执行脚本，基于合成 OHLCV 测试数据集对所有表达式批量求值，可即时捕获语法错误、数值异常、逻辑越界三类问题并输出诊断信息，支撑迭代优化。

Agent 可依托自身大模型能力生成 Alpha 因子表达式，再调用本技能完成正确性与合规性校验。

## 🚀 快速开始

### Agent 工作流

```text
User: 从这篇动量论文生成 3 个 alpha 因子：<文本>

Agent:
1. 读取 references/alpha_ops.md 了解契约
2. 用自己的 LLM 生成 3 个 alpha（JSON 数组格式）
3. 保存到 alphas.json
4. 运行: python scripts/generate_alphas.py --alphas alphas.json
5. 报告通过/失败结果
```

### 直接使用验证器

```bash
# 创建测试 alphas
echo '[{"name":"mom","expression":"returns(close,5)"},{"name":"bad","expression":"vwap * x(close,10)"}]' > /tmp/test.json

# 验证
python scripts/generate_alphas.py --alphas /tmp/test.json
```

## 📦 目录结构

```
skill-doc-to-alphas/
├── SKILL.md                          # 技能入口
├── README.md / README.en.md          # 说明文档
├── LICENSE                           # GPL-3.0
├── references/
│   ├── alpha_ops.md                  # 📚 字段与函数契约
│   └── agent-integration.md          # 🔌 多 Agent 安装
├── scripts/
│   ├── formulas.py                   # 📐 契约的 Python 定义
│   ├── validation.py                 # 🧪 验证引擎
│   └── generate_alphas.py            # 🔧 CLI 验证器
└── agents/
    ├── openai.yaml                   # OpenAI/Codex 风格入口
    ├── cursor-rule.mdc               # Cursor 规则适配
    └── portable-loader.md            # Claude Code/Hermes/OpenClaw 通用加载器
```

## ⚠️ 免责声明

本仓库仅作研究方法层面的整理，不构成任何投资建议。

## 👤 维护者

创建与维护：`abgyjaguo`（QuantSkills community）。

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
