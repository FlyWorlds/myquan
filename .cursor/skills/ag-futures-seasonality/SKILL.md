---
name: ag-futures-seasonality
description: Analyze seasonal price patterns of Chinese agricultural futures (soybean meal/oil, corn, sugar, cotton, palm, egg) from historical prices — per-month average return, win rate, and statistical significance, overlaid with a crop calendar. Evidence-first, not a buy/sell signal. Use when the user asks 豆粕/大豆季节性, 农产品季节性规律, 这个品种几月容易涨, 现在是不是季节性旺季, or 季节性择时, on Claude Code, Codex, Cursor, Hermes, or OpenClaw.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-ag-futures-seasonality
  repository_url: https://github.com/quantskills/skill-ag-futures-seasonality
  project_type: skill
  collection: ag-futures-seasonality
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - agricultural-futures
  - seasonality
  - soybean
  - crop-calendar
  - pandadata
  platforms:
  - claude-code
  - codex
  - cursor
  - hermes
  - openclaw
  language: zh-en
  status: stable
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 从历史行情计算农产品期货的月度季节性规律（平均涨跌/上涨概率/显著性）并叠加作物日历，事实优先，不输出买卖指令。
  summary_en: Month-by-month seasonal patterns for Chinese agricultural futures from price history, overlaid with a crop calendar. Evidence-first, no signals.
---

# 农产品期货季节性分析（Ag Futures Seasonality）

农产品受种植、生长、收割及南北半球错季驱动，是季节性最强的期货品类。本 skill 从历史行情计算月度季节性规律、检验统计显著性并叠加作物日历，用于判断品种当前所处的季节周期位置。

**输出范围**：历年同期的统计规律，事实与推断分离。
**不做的事**：不预测点位、不给出多空方向、不输出无条件买卖指令——季节性是概率，不是保证。

## 何时使用

- "豆粕几月容易涨 / 大豆季节性规律是怎样的"
- "现在（某月）是不是这个品种的季节性旺季 / 淡季"
- "帮我看看白糖/棉花/玉米/豆油的季节性，做择时参考"

## 输入数据

一张主力连续合约的日线（至少数年，越长越好）：`[date, close]`。

从 Pandadata 取：
- `get_future_daily`（期货日线）+ `get_future_dominant`（主力合约映射）拼出主力连续
- 品种代码用 `get_future_detail` 确认（如豆粕 M、豆油 Y、大豆 A、玉米 C、白糖 SR、棉花 CF、棕榈 P、鸡蛋 JD）
- 具体接口以 `skill-pandadata-api` 的清单为准；本 skill 只做季节性计算，取数交给数据类 skill

## 工作流

### 第 1 步：确认品种与数据窗口
- 用 `get_future_detail` 把用户的口语品种（"豆粕""大豆"）对齐到规范代码
- 取尽可能长的主力连续日线（建议 ≥10 年；不足 8 年须在结论里显著提示样本少）

### 第 2 步：计算月度季节性
运行 `scripts/seasonality.py --csv <日线> --symbol <品种>`，得到每月：
- 历年**平均涨跌**、中位涨跌、标准差
- **上涨概率**（历年该月上涨的年数占比）
- **样本年数**（几年就是几个样本，务必披露）
- **显著性**：上涨概率的二项精确检验 p 值、平均涨跌的 t 检验 p 值（用真实 t 分布，非正态近似——小样本下正态会高估显著性）

### 第 3 步：叠加作物日历
把统计规律和农业周期对上，解释"为什么"（见 `references/crop-calendar.md`）：
- 例：豆粕 7 月偏强 ← 北半球大豆生长期天气升水；11–12 月偏弱 ← 南美种植顺利 + 北美收割上量
- 只在有农业逻辑支撑时才把季节性当"可信规律"，否则标为"统计现象、机理存疑"

### 第 4 步：定位当前
- 数据截至月份 + 下月季节性倾向（平均涨跌/上涨概率/是否显著）
- 明确当前处在作物周期的哪个阶段（种植/生长/收割/进口窗口）

### 第 5 步：输出报告
结构化中文报告，含逐月季节性表、显著月份、当前位置、作物日历解释。**每个结论标注：数据窗口、样本年数、是事实还是推断。**

指定 `--out 目录` 时写出三种格式：`seasonality.txt`（文字报告）、`seasonality.json`（结构化数据）、`seasonality.html`（自包含可视化报告，内联 SVG 柱状图，零外部依赖、离线可用）。HTML 中显著月份实心、不显著月份半透明，样本年数与免责说明一并保留——图形不弱化严谨性。加 `--no-html` 可跳过 HTML。

## 严谨性红线（本 skill 的立身之本）

- **披露样本量**：10 年数据每个月就 10 个样本，小样本极易把噪声当规律——报告必须显示样本年数，`scripts/validate.py` 用合成数据验证过"纯随机不报假季节性"
- **看显著性**：上涨概率 70% 若 p 值不显著，只能算"倾向"，不能当"规律"；只有过检验的月份才标显著
- **季节性 ≠ 保证**：当年基本面（天气异常、政策、进出口、疫病）可以完全覆盖季节性——这一条必须写进每份报告
- **防未来函数**：只用截至分析日的历史，不得用未来数据回填
- **不输出指令**：仅给出择时"倾向"与证据，不输出买卖指令

## 自检

```bash
python scripts/validate.py   # 9 项：能识别人造强/弱月、纯噪声不误报、样本护栏触发、边界月份不丢、显著性检验用真实 t 分布、HTML 报告自包含且保留严谨性
```

## 边界与来源

数据来源边界见 `references/source_boundary.md`。本 skill 为 QuantSkills 社区原创，季节性方法为量化通用做法，作物日历为公开农业常识整理。它与社区的 `skill-futures-deepview-analyst` 互补：后者看席位持仓/基差/仓单等**微观结构**，本 skill 看**跨年季节性规律**，两者角度不重叠。
