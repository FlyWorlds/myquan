# Oil Brief Skill — 原油简报生成工具

## 简介

生成结构化原油日报/周报，覆盖当前趋势、技术分析、关键支撑/阻力位、今日重要事件、最新研报观点、市场情绪、交易计划、价格预测、风险提示及 AI 总结十一大维度。

## 安装

```bash
pip install -r requirements.txt
```

## 配置

在 `.env` 文件中配置数据源凭证：

```
DEFAULT_USERNAME=your_pandadata_username
DEFAULT_PASSWORD=your_pandadata_password
EIA_API_KEY=your_eia_api_key
```

## 使用

```bash
python -m oil_brief --output 原油简报.md
python -m oil_brief --variety SC --days 120 --verbose
```

## 数据源

- Pandadata 期货接口：SC 原油期货行情、持仓、期限结构
- EIA 开放 API：WTI/Brent 价格、美国原油库存
- OPEC 月报：产量、供需数据

## 输出

生成中文 Markdown 格式的 11 章结构化原油简报，包含技术分析图表数据、基本面分析和交易建议。

## 注意事项

- 需要有效的 Pandadata 账号
- 报告仅供参考，不构成投资建议
