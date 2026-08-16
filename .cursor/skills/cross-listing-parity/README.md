# 跨市场折溢价监控 Skill

**简体中文** | [English](README.en.md)

> 社区状态：Draft（社区草案） · 创建者/维护者：[`abgyjaguo`](https://github.com/abgyjaguo)

`cross-listing-parity` 是 QuantSkills 的跨市场折溢价监控 skill，用于生成 A/H 溢价和中概 ADR 折溢价报告。它关注同一公司在 A 股、港股、美股 ADR 之间的价格折算差异，并把数据日、汇率、股数比和映射表版本写清楚。

本项目由 `abgyjaguo` 维护，面向研究和教育场景，不提供个性化投资建议。

## 适用场景

- 生成 A/H 溢价当日 snapshot。
- 监控中概 ADR 相对港股或 A 股的折溢价。
- 找出跨市场价差的异常扩张或收敛。
- 维护 A/H 与 ADR 配对映射表。
- 给定用户汇率后做 HKD、USD、CNY 之间的折算说明。

## 文件结构

```text
skills/cross-listing-parity/
├── SKILL.md
├── README.md
├── README.en.md
├── LICENSE
├── .gitattributes
├── .gitignore
├── agents/
│   ├── cursor-rule.mdc
│   ├── openai.yaml
│   └── portable-loader.md
├── references/
│   ├── pandadata-map.md
│   ├── parity-guide.md
│   └── pairs/
│       ├── a-h-pairs.csv
│       └── adr-pairs.csv
└── scripts/
    └── validate_report.py
```

`references/pairs/` 是本 skill 的核心数据契约，用来存放配对映射。用户可以扩展 CSV，但必须保留表头和 `ratio` 字段。

## 数据接口

Pandadata 方法名、参数名和字段名以 `skills/pandadata-api/references/api-docs.md` 为准。本 skill 使用以下已验证方法：

| 用途 | 方法 |
| --- | --- |
| A 股行情 | `get_stock_daily` |
| A 股交易清单 | `get_trade_list` |
| 港股行情 | `get_hk_daily` |
| 美股 ADR 行情 | `get_us_daily` |
| 港股基础信息 | `get_hk_detail` |
| 美股基础信息 | `get_us_detail` |

汇率必须覆盖 USD/HKD/CNY。若用户环境没有可验证的 Pandadata 汇率接口，报告生成前需要用户提供汇率，并在报告的数据说明中写明来源和日期。

## 报告要求

报告必须使用中文和绝对日期，并至少包含：

- 摘要
- A/H 溢价
- ADR 折溢价
- 异常、极值或收敛
- 数据说明
- 免责声明

报告必须说明 A 股、港股、美股的数据日，标注 T+1 或 snapshot。历史分位需要用户提供或长期累积数据；没有历史数据时只输出当日 snapshot。

## 配对表增补

`a-h-pairs.csv` 字段：

```text
pair_id,a_symbol,a_name,h_symbol,h_name,ratio,currency_base,notes
```

`adr-pairs.csv` 字段：

```text
pair_id,us_symbol,us_name,primary_market,primary_symbol,primary_name,ratio,adr_type,currency_base,notes
```

`ratio` 表示一份跨市场证券折算成原生普通股的比例。不要假设所有 A/H 或 ADR 都是 1:1。扩展时应核对公司公告、ADR 存托比例、拆股和退市状态。

## 验证

生成报告后运行：

```bash
python scripts/validate_report.py path/to/report.md
```

脚本只检查结构和必要声明，不判断结论是否正确。数据计算仍需要人工核对来源、汇率、股数比和停牌状态。

## 五端兼容

- Codex：使用根目录 `SKILL.md` 与 `agents/openai.yaml`。
- Cursor：使用根目录 `SKILL.md` 与 `agents/cursor-rule.mdc`。
- Claude Code、Hermes、OpenClaw：读取根目录 `SKILL.md`；无法自动发现时使用 `agents/portable-loader.md`。

## 许可

本项目使用 GNU General Public License v3.0，SPDX 标识为 `GPL-3.0-only`。
