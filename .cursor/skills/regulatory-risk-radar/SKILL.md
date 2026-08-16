---
name: skill-regulatory-risk-radar
description: >
  A-share regulatory & governance risk radar. Use when a user has a holding
  list or watchlist and wants to know which names carry near-term compliance /
  event risk — share-lockup expiry (解禁), shareholder reduction plans (减持),
  equity pledge (质押), placarding (举牌), share freezes (股权冻结), trading
  halts (停牌) and ST status. Scans the pool, scores each name, and outputs a
  graded risk list with sourced evidence.
license: GPL-3.0-only
category: 工具
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-regulatory-risk-radar
  repository_url: https://github.com/quantskills/skill-regulatory-risk-radar
  project_type: skill
  collection: risk-monitoring
  status: community-draft
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "粘贴持仓/自选股票代码（如 000021.SZ, 600519.SH），或上传持仓 CSV；说明关注的风险类型与时间窗",
    "required": true
  },
  "fields": [
    {
      "key": "lookback_days",
      "label": "回溯窗口（天）",
      "type": "number",
      "default": "180",
      "help": "扫描多长时间内公告的减持/质押/举牌等事件"
    },
    {
      "key": "lookahead_days",
      "label": "前瞻窗口（天）",
      "type": "number",
      "default": "90",
      "help": "扫描未来多少天内到期的解禁"
    },
    {
      "key": "min_severity",
      "label": "最低风险等级",
      "type": "select",
      "default": "low",
      "options": [
        { "value": "low", "label": "全部（含低风险）" },
        { "value": "medium", "label": "中及以上" },
        { "value": "high", "label": "仅高风险" }
      ]
    }
  ],
  "prompt_template": "{{#task}}持仓/自选与要求：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}对上述股票池做 A 股合规/监管风险扫描。{{#lookback_days}}事件回溯窗口 {{lookback_days}} 天。{{/lookback_days}}{{#lookahead_days}}解禁前瞻窗口 {{lookahead_days}} 天。{{/lookahead_days}}{{#min_severity}}只报告风险等级 ≥ {{min_severity}} 的标的。{{/min_severity}}聚合解禁、减持计划、股权质押、举牌、股权冻结、停牌与 ST 状态，逐票打分分级，输出带证据来源与公告日期的中文风险清单，缺失数据项明确标注降级。仅研究参考，不构成投资建议。"
}
```

# skill-regulatory-risk-radar

role: skill · output: RegRiskReport (JSON + text) · paradigm: rule-based governance/compliance risk scan

把"我这一篮子 A 股里，哪些近期有踩雷风险"变成可计算、可引用、可分级的清单。这是实盘持仓监控里最刚需、组织里却没人做的**合规守门员**。

## 🎯 这个 Skill 解决什么问题

A 股实盘最怕的不是回测不准，而是**踩到治理/监管雷**：大股东突然减持、限售解禁砸盘、控股股东质押爆仓、被举牌停牌、因诉讼股权冻结、戴帽 ST。这些信号**分散在多个公告接口里**，没人盯就等着被埋。组织现有的 `event-risk-alert` 太宽泛，缺一个**专盯股东行为 + 公司行为 + 交易状态**的雷达。

本 Skill 把 6 类风险源聚合成单一分级清单：

- **限售解禁（解禁）** — 未来窗口内到期的解禁明细、解禁股数占比、股东类型。
- **股东增减持计划（减持）** — 含进度、触发价、预计金额、方向；减持是最直接的抛压信号。
- **股权质押（质押）** — 质押比例、累计质押占总股本比例；高质押 = 平仓风险。
- **举牌** — 被举牌明细、增持方、占比变化。
- **股权冻结** — 前十大股东里的冻结股数（司法风险）。
- **停牌 / ST** — 日线 `trade_status` 与 `st` 标记。

## ⚡ 工作流（Agent 按此执行）

1. **解析股票池**：从用户输入/CSV 提取 symbol 列表，标准化为 `NNNNNN.SZ/SH`。
2. **拉取各风险源**：`scripts/data_source.py` 通过 pandadata 逐接口取数（解禁 `get_restricted_list`、减持 `get_stock_shareholder_change`、质押 `get_stock_pledge`/`get_stock_pledge_stat`、举牌 `get_stock_equity_placard`、股东冻结 `get_top_holders`、停牌/ST `get_stock_daily`）。
3. **打分分级**：`scripts/scoring.py` 按每类事件的严重度权重 + 时间邻近度 + 规模占比，算每票综合风险分，映射到 low/medium/high。
4. **生成报告**：`scripts/reg_risk_report.py` 汇总 → `RegRiskReport`（JSON + 中文文本），按风险分降序，逐票列出触发项与证据（公告日期 + 数值）。
5. **解释结论**：用业务语言指出"哪些票、因为什么、多严重、看什么日期"，缺失数据项明确降级说明。

```bash
# 一行扫描持仓
python scripts/reg_risk_report.py --symbols 000021.SZ,600519.SH --lookback 180 --lookahead 90 --out report.json
# 离线演示（无凭证自动回退内置样本）
python examples/run_demo.py
```

## 🗃️ 输入契约

| 输入 | 形态 | 必需 | 说明 |
|------|------|------|------|
| `symbols` | 逗号分隔 / CSV 单列 | 是 | 股票代码，`NNNNNN.SZ/SH` |
| `lookback_days` | int | 否 | 默认 180，事件公告回溯窗口 |
| `lookahead_days` | int | 否 | 默认 90，解禁前瞻窗口 |
| `min_severity` | low/medium/high | 否 | 默认 low，输出过滤阈值 |

输出 `RegRiskReport`：`generated_at / universe_size / items[] (symbol, name, score, severity, triggers[]) / degraded_sources[]`

## 📦 输出契约

产物对象 `RegRiskReport`（JSON + 中文文本）：

| 字段 | 说明 |
|------|------|
| `generated_at / universe_size` | 生成时间与股票池规模 |
| `items[]` | 每标的：`symbol, name, score, severity(low/medium/high), triggers[]` |
| `degraded_sources[]` | 无数据/降级的风险源 |

文件产物：`--out report.json`、`--md report.md`。每条风险须带 `info_date`（公告日期）可溯源，缺失来源在 `degraded_sources[]` 显式声明，不编造。

## 🔗 管线定位

```
选股/组合构建 → 持仓 → [本 Skill：合规/监管风险守门] → 下单/持有决策
```

它是持仓监控的**风控前置**：`skill-portfolio-checkup` 看集中度/估值/暴露，本 Skill 看治理/监管踩雷。**高风险项应在建仓/持有前先看，而非事后。**

## 📦 仓库结构

```
skill-regulatory-risk-radar/
├── SKILL.md
├── README.md
├── requirements.txt
├── scripts/
│   ├── data_source.py        # panda_data 适配层（6 接口；无凭证回退样本）
│   ├── scoring.py            # 各风险源严重度 → 综合分 → 分级
│   ├── reg_risk_report.py    # 汇总 → RegRiskReport（CLI 入口）
│   └── formatters.py         # JSON / 中文文本 / Markdown 渲染
├── references/
│   ├── risk-taxonomy.md      # 6 类风险定义、字段映射、评分权重依据
│   └── data-fields.md        # 各接口字段 → 风险语义的映射表
└── examples/
    ├── run_demo.py           # 内置样本，无凭证可跑
    └── sample_report.md      # 示例输出
```

## ✅ 质量门槛

产物交付前须满足（不达标则降级并在报告显式声明，不静默通过）：

- **可溯源**：每个关键数字可回溯到具体 Pandadata 接口 + 数据日期；缺失数据进 `degraded[]`，绝不编造或用近似冒充真实值。
- **降级透明**：任一数据源为空/受限时，报告如实标注并降低结论置信度。
- **口径一致**：单位、频率、基准口径在报告中显式声明。
- **仅研究**：产物为研究/教育参考，不构成投资建议，不承诺收益。
- 每条风险须带 info_date 公告日期；severity 分级口径在报告注明。

## ⚠️ 使用规则

- 数据以**公告日期**为准，非实时；解禁/减持有信息滞后，报告须标注 `info_date`。
- 部分接口（如举牌、质押统计）为全市场返回，需按 symbol 过滤后再入池。
- `get_stock_daily` 的 `st=True` 才含 ST 股；停牌以 `trade_status != 0` 判定。
- 网关模式返回行数受套餐配额限制，大股票池需分批取数。
- 只做研究/风控参考，不构成投资建议。
