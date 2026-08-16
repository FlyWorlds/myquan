# 港美股分红事件 Skill

**简体中文** | [English](README.en.md)

> 社区状态：Draft（社区草案） · 创建者/维护者：[`abgyjaguo`](https://github.com/abgyjaguo)

`hk-us-dividend-events` 是一个 Agent Skill，用于基于 Pandadata 外盘接口生成港股和美股分红事件报告。它覆盖未来除息日程、近期派息、TTM 股息率排行、币种分池和 DRIP 再投资简化示意。

维护者：abgyjaguo  
项目类型：QuantSkills skill  
许可证：GPL-3.0-only

## 能做什么

- 生成港股或美股 Dividend calendar，重点列出未来 30/60/90 日即将除息事件。
- 汇总近期派息记录，区分公告日、执行日、每股金额和币种。
- 计算过去 12 个月现金分红合计，并按币种列示 TTM 股息率排行。
- 给出 DRIP 再投资简化示意，明确不考虑税、费、最小买入单位和汇兑。
- 在接口失败或字段缺失时降级输出，并在“数据说明”中写清原因。

## 数据接口

本 skill 只使用 Pandadata 文档中存在的方法：

| 市场 | 分红事件 | 行情 | 基础信息 |
| --- | --- | --- | --- |
| 港股 | `get_stock_dividend_event` | `get_hk_daily` | `get_hk_detail` |
| 美股 | `get_stock_dividend_activity` | `get_us_daily` | `get_us_detail` |

参数名和字段名以 `pandadata-api/references/api-docs.md` 为准。股票代码参数使用 `symbol`，不要写成复数。

## 报告结构

报告应包含以下章节：

1. 标题：港美股/港股/美股 + 分红/Dividend + 事件/Calendar
2. 摘要
3. 即将除息
4. 近期派息
5. 高股息/Yield 榜
6. DRIP
7. 数据说明
8. 免责声明

## 使用示例

```text
用 hk-us-dividend-events 生成 2026-07-07 起未来 60 日港美股分红事件日历。
```

```text
查看 AAPL 和 0005.HK 过去 12 个月派息，并给出 DRIP 简化示意。
```

## 校验

报告写出后运行：

```bash
python scripts/validate_report.py path/to/report.md
```

校验内容包括必备章节、数据来源、数据日、T+1/snapshot 声明和“不构成投资建议”免责。

## 五端兼容

- Codex：使用根目录 `SKILL.md` 与 `agents/openai.yaml`。
- Cursor：使用根目录 `SKILL.md` 与 `agents/cursor-rule.mdc`。
- Claude Code、Hermes、OpenClaw：读取根目录 `SKILL.md`；无法自动发现时使用 `agents/portable-loader.md`。

## 限制

- 本 skill 不提供下单指令或个性化投资建议。
- TTM 只使用过去 12 个月现金分红累加，不做未来外推。
- HKD/USD/CNY 等币种分池展示，不做混算。
- DRIP 仅为算术示意，不考虑税、费、最小买入单位、汇兑和账户规则。

## 许可证

本项目采用 GNU General Public License v3.0。详见 [LICENSE](LICENSE)。
