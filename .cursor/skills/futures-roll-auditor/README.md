# 期货连续合约换月审计

> 检查连续合约选择序列、同日换月价差和调整因子，并生成可复查的换月账本。

## 解决什么问题

识别合约切换，计算同日 roll gap、差值和比例调整因子，并明确连续研究价格与可交易合约收益的边界。

与社区现有能力的边界：它审计连续序列构造；不重复商品期限结构观点研究，也不替代期货回测。

## 快速开始

```bash
python scripts/audit_rolls.py --demo
python scripts/audit_rolls.py --input your_data.csv --out report.json
```

## 运行参数

| 参数 | 是否必需 | 说明 |
| --- | --- | --- |
| `--demo` | 与 `--input` 二选一 | 使用内置示例；不能与 `--input` 同时使用 |
| `--input <csv>` | 与 `--demo` 二选一 | 输入 UTF-8 CSV，`date` 使用 `YYYY-MM-DD` 格式 |
| `--adjustment-method {none,difference,ratio}` | 否 | 调整方法，默认 `none` |
| `--out <json>` | 否 | 输出文件；省略时输出到标准输出 |

两种数据入口同时提供或均未提供时，命令以参数错误码 2 退出。

安装方式：克隆本仓库，或把整个目录复制到 Agent 的 skills 目录；无需安装第三方 Python 包。PandaData 取数请配合 [`skill-pandadata-api`](https://github.com/quantskills/skill-pandadata-api)。

## 工作流

1. 冻结主力/近月选择规则
2. 识别每次合约切换
3. 计算 roll gap 和差值/比例调整因子
4. 区分研究连续价格与真实合约 PnL

## 输入与输出

- 输入：包含 date、front、back、selected、front_price、back_price 的逐日合约选择 CSV。
- 输出：JSON 换月事件表、roll gap 和使用警告。

## 数据来源

- 接入模式：**直接接入**，同时保留 CSV 离线输入。
- PandaData 方法：`get_future_detail`、`get_future_dominant`、`get_future_daily`、`get_future_daily_post`。
- 真实 API 调用委托给兄弟 Skill `pandadata-api`；本 Skill 不复制账号认证逻辑。
- 详细覆盖范围、字段映射和降级规则见 `references/pandadata-integration.md`。
- 主力映射只是供应商口径；若用户策略按成交量、持仓量或固定日换月，仍需提供自身 roll rule 并与主力映射分开报告。

## 仓库结构

```text
skill-futures-roll-auditor/
├── SKILL.md
├── README.md
├── README.en.md
├── .gitignore
├── LICENSE
├── requirements.txt
├── agents/
│   ├── cursor-rule.mdc
│   ├── openai.yaml
│   └── portable-loader.md
├── scripts/audit_rolls.py
├── tests/test_audit_rolls.py
├── validation/README.md
├── validation/smoke.py
└── references/
    ├── methodology.md
    ├── output-contract.md
    └── pandadata-integration.md
```

## 研究边界

本 Skill 仅用于研究和教育，不提供买卖建议、收益承诺或自动交易。所有阈值、代理变量和数据缺口都应在报告中披露。
