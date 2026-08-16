# PandaAI 工作流文件审计

像做 code review 一样审计 PandaAI 导出的工作流 JSON：检查工作流结构、策略与因子代码、数据时序、参数自由度、回测假设和验证证据，并逐条给出严重级别、证据、影响与优化方案。

## 能发现什么

- 悬空连线、重复节点 ID、执行环和 LiteGraph 数据不一致；
- Python 语法错误、负向 `shift`、疑似同 bar 信号与成交；
- 硬编码标的池、过多可调阈值与未知试验次数；
- 回测区间过短或只有单一区间；
- 零佣金、零滑点和缺少成本压力测试；
- 隐式外部数据、随机过程不可复现；
- 缺少真实运行结果、收益序列、交易明细或完整试验矩阵。

工具不会执行工作流中的代码，也不会把“证据不足”误写成“没有过拟合”。

## 输入

支持：

1. PandaAI 前端“导出”产生的 JSON；
2. 保存为 JSON 的 `GET /api/workflow/query` 响应；
3. 外层包含 `data` 字段的 API 响应包装。

主要读取 `nodes`、`links`、`static_input_data`，并用 `litegraph` 做兼容和交叉校验。

## 使用

```powershell
uv run scripts/audit_workflow.py workflow.json --json-out audit.json --markdown-out audit.md
```

没有 `uv` 时可直接使用 Python：

```powershell
python scripts/audit_workflow.py workflow.json --format markdown
```

脚本为纯 Python 标准库实现，要求 Python 3.10+，无需网络和第三方依赖。

## 输出原则

每条 finding 都包含：

- 严重级别；
- 具体缺陷；
- 可核对证据；
- 对研究可信度的影响；
- 可执行优化方案。

当导出文件没有真实运行结果时，结论为：

```json
{
  "verdict": "insufficient-evidence",
  "overfit_risk": "unassessable",
  "evidence_level": "static-only"
}
```

这表示“无法完成统计判断”，不表示通过。

## 与其他 QuantSkills 的关系

本技能负责 PandaAI 工作流解析与研究审计。取得周期收益、所有试验配置和诚实试验次数后，可以再交给 `skill-backtest-overfit` 计算 DSR、PBO 等统计量。本项目不重复伪造这些统计结论。

## 自测

```powershell
python -m unittest discover -s tests -v
```

## 免责声明

本技能仅供研究与教育用途，不构成投资建议。完整、固定措辞见 `references/disclaimer_template.md`。

本项目为社区独立贡献，属于非官方项目，不隶属于 PandaAI、PandaData 或任何金融机构，也不代表 QuantSkills 组织的官方立场。

## License

GPL-3.0-only。
