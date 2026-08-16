# skill-ag-futures-seasonality

**简体中文** | [English](README.en.md)

农产品期货季节性分析。农产品受种植、生长、收割及南北半球错季驱动，是季节性最强的期货品类。本 skill 从历史行情计算月度季节性规律、检验统计显著性并叠加作物日历，用于判断品种在各月份的历史涨跌倾向及当前所处的季节周期位置。仅输出统计事实与推断，不提供买卖指令。

<p align="center">
  <img alt="role" src="https://img.shields.io/badge/role-季节性分析-brightgreen">
  <img alt="output" src="https://img.shields.io/badge/output-月度季节性·显著性·作物日历-blue">
  <img alt="validation" src="https://img.shields.io/badge/validation-9%2F9自检通过-orange">
  <img alt="data" src="https://img.shields.io/badge/data-Pandadata期货日线-9cf">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-ag-futures-seasonality` 是 QuantSkills 社区的季节性分析 Skill。社区已有的期货 DeepView skill 看的是席位持仓、基差、仓单等**微观结构**；本 skill 补的是另一个角度——**跨年的季节性规律**，两者互补不重叠。

## 这个 Skill 解决什么问题

"大豆几月容易涨？""现在是不是豆粕的季节性旺季？"——农产品有很强的季节规律，但大多数人只有模糊印象，说不清"7 月偏强"到底是历史规律还是错觉，也不知道这个规律**在统计上显不显著、样本够不够**。

本 skill 将其转化为可计算、可检验、可解释的统计结果：

- 每个月历年**平均涨跌、上涨概率、样本年数、统计显著性**汇总为一张表
- 叠加**作物日历**解释"为什么"——7 月偏强是北半球生长期天气升水，11–12 月偏弱是南美种植顺利
- 明确当前处在作物周期哪个阶段、下月季节性倾向如何

## 统计严谨性

- **披露样本量**：10 年数据每月仅 10 个样本，小样本易将噪声误判为规律，报告一律显示样本年数
- **检验显著性**：上涨概率 70% 若统计不显著，仅记为"倾向"而非"规律"，只有通过检验的月份才标星
- **季节性不等于保证**：当年天气、政策、供需可完全覆盖季节性规律，此说明写入每份报告
- **可证伪**：`scripts/validate.py` 用合成数据验证"能识别人造季节性、纯随机不误报、显著性检验用真实 t 分布不高估、HTML 报告自包含且保留严谨性"，9/9 通过

## 快速开始

```bash
pip install -r requirements.txt

# 自检（构造已知季节性验证算法）
python scripts/validate.py

# 用自带的豆粕示例
python scripts/seasonality.py --csv examples/data/soybean_meal_M.csv --symbol "M 豆粕"

# 用你自己的数据（列：date, close）
python scripts/seasonality.py --csv your_data.csv --symbol "品种" --out report/
```

指定 `--out` 时输出三种格式：`seasonality.txt`（文字报告）、`seasonality.json`（结构化数据）、`seasonality.html`（自包含可视化报告，内联 SVG、离线可用、明暗主题自适应）。HTML 中显著月份实心、不显著月份半透明，样本量与免责说明一并保留（示例见 `examples/output/seasonality.html`）。

豆粕示例真实输出（2015–2025，11 年样本）：

```
季节性偏强月份：无显著
季节性偏弱月份：11月
逐月季节性：
   7月    +1.37%     73%    11年
   8月    -1.54%     27%    11年
  11月    -3.53%     36%    11年   *
  12月    -2.84%     27%    11年
```

7 月上涨概率虽达 73%，但样本仅 11 年、二项检验 p=0.23，统计不显著，故未标为强月。仅 11 月标星（均值 t 检验 p=0.09）；12 月平均涨跌 −2.84%、胜率 27%，但均值 t 检验 p=0.13，未过 0.1 阈值，不标星——小样本下采用 t 分布而非正态近似，避免高估显著性。报告附多重检验提示。

## 数据从哪来

框架中立，输入就是一张主力连续日线 `[date, close]`：
- **Pandadata**：`get_future_daily` + `get_future_dominant` 拼主力连续，`get_future_detail` 确认品种代码
- **自备**：回测导出、券商行情导出，整理成 date,close 即可

品种代码示例：豆粕 M、豆油 Y、大豆 A、玉米 C、白糖 SR、棉花 CF、棕榈 P、鸡蛋 JD。

## 目录结构

```
skill-ag-futures-seasonality/
├── SKILL.md                    # Agent 使用说明（核心）
├── README.md / README.en.md
├── agents/
│   ├── openai.yaml              # OpenAI-style runtime manifest
│   ├── cursor-rule.mdc          # Cursor rule entrypoint
│   └── portable-loader.md       # Hermes/OpenClaw portable loader
├── scripts/
│   ├── seasonality.py          # 季节性计算 + 显著性检验 + 报告（txt/json/html）
│   └── validate.py             # 9 项合成数据自检
├── references/
│   ├── crop-calendar.md        # 作物日历与季节性机理（豆/玉米/糖/棉/棕/蛋）
│   └── source_boundary.md
└── examples/
    ├── data/soybean_meal_M.csv
    └── output/                 # 豆粕季节性报告示例（txt + json + html）
```

## 运行时入口

本 Skill 支持 Claude Code、Codex、Cursor、Hermes 和 OpenClaw。Claude Code、Codex 与原生 Skill 运行时直接加载 `SKILL.md`；Cursor 使用 `agents/cursor-rule.mdc`；Hermes/OpenClaw 在无法原生发现 Skill 时使用 `agents/portable-loader.md`。所有入口最终都回到同一份 `SKILL.md`、作物日历、来源边界和季节性脚本，不维护平行业务逻辑。

## 与社区其他 skill 的分工

- `skill-futures-deepview-analyst`：席位持仓、基差、仓单、跨期套利等微观结构 —— **看当下博弈**
- **本 skill**：跨年季节性规律 + 作物日历 —— **看历史节律**
- `skill-pandadata-api`：负责取数

## License

GPL-3.0。本 skill 为 QuantSkills 社区原创，季节性方法为量化通用做法，作物日历为公开农业常识整理。
