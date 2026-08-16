# 美股行业轮动 Skill

**简体中文** | [English](README.en.md)

> 社区状态：Draft（社区草案） · 创建者/维护者：[`abgyjaguo`](https://github.com/abgyjaguo)

`us-sector-rotation` 用于生成美股行业/板块轮动报告。它以 Pandadata 的美股接口为数据来源，用 `get_stock_sector_median` 替代 A 股行业指数口径，结合 `get_us_daily` 和 `get_us_detail` 做成分收益聚合，并在可用时加入 PE/PB 估值 snapshot。

维护者：abgyjaguo  
组织：QuantSkills  
仓库：`skill-us-sector-rotation`  
许可证：GPL-3.0-only

## 适用场景

- 美股行业/板块近 1D、1W、1M、3M、YTD 表现对比。
- 基于接口 sector 字段的成分聚合 median 分析。
- 行业 PE/PB snapshot 估值对比。
- 行业排名变化速度和轮动方向描述。

## 不适用场景

- 不生成 ETF 或指数替代口径。
- 不把 Pandadata 的 sector 分类二次映射为自定义行业体系。
- 不把 snapshot 估值称为历史分位，除非用户提供或本地维护了滚动缓存。
- 不输出个性化投资建议或交易指令。

## 数据口径

核心接口：

- `get_stock_sector_median`：行业中位指标，包含 `industry_name`、`imed_pe_ttm`、`imed_pb_ttm` 等字段。
- `get_us_daily`：美股日线，用于成分收益回填。
- `get_us_detail`：美股基础信息和行业字段，用于成分-行业映射。
- `get_stock_mktfin_metric`：可选，用于个股 PE/PB snapshot 后再做行业聚合。

报告币种统一为 USD，不与 HKD 或 CNY 混算。

## 报告结构

报告应包含：

- `# 美股行业轮动...`
- `## 摘要`
- `## 行业/板块表现`
- `## 估值`
- `## 轮动`
- `## 数据说明`
- 末尾免责声明，必须包含“不构成投资建议”。

## 使用方式

在支持 skill 的 agent 中引用本目录的 `SKILL.md`。生成报告后运行：

```bash
python scripts/validate_report.py path/to/report.md
```

验证脚本只检查结构和必要声明，不验证 Pandadata 返回值真伪。真实数据调用前仍需以 `skills/pandadata-api/references/api-docs.md` 为准核对方法名、参数名和字段名。

## 五端兼容

- Codex：使用根目录 `SKILL.md` 与 `agents/openai.yaml`。
- Cursor：使用根目录 `SKILL.md` 与 `agents/cursor-rule.mdc`。
- Claude Code、Hermes、OpenClaw：读取根目录 `SKILL.md`；无法自动发现时使用 `agents/portable-loader.md`。

## 自动化

默认不启用。用户明确要求自动化时，建议在 `Asia/Shanghai 21:30` 后运行，报告中必须写明数据日、生成时间、使用接口、T+1 或 snapshot 状态，以及缺失数据说明。
