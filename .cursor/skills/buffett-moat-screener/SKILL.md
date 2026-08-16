---
name: build-Q44
description: 当需要从 Panda Data 构建点时沪深 300 巴菲特式研究队列、运行 2010 起 A 股固定样本诊断、运行 2015 起美股固定研究池软评分回测、维护长期持仓状态并生成标准 Parquet 结果时，使用此 skill。该混合型 BUILD 可被 agent 或 Alpha 调用，不生成订单。
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-buffett-moat-screener
  repository_url: https://github.com/quantskills/skill-buffett-moat-screener
  project_type: skill
  collection: fundamental-research
  creator: dijia702
  creator_url: https://github.com/dijia702
  maintainer: dijia702
  maintainer_url: https://github.com/dijia702
tags: [quant, build, development, hybrid, cn_a_share, us_equity, buffett]
quantSkills:
  project_type: skill
  category: analyst
  platforms: [claude-code, codex, cursor, hermes, openclaw]
  status: community
  requires: [skill-pandadata-api]
  validation_level: runnable
  maintainer_type: community
  summary_zh: "基于点时数据的巴菲特式软评分、研究队列、持仓复核与多市场历史诊断。"
  summary_en: "Point-in-time Buffett-style soft scoring, research ranking, portfolio review, and multi-market retrospective diagnostics."
---

# Q44 A 股与美股巴菲特软评分长期持仓 BUILD

## 维护与社区状态
- 上游仓库：`quantskills/skill-buffett-moat-screener`
- 创建者与维护者：[`dijia702`](https://github.com/dijia702)
- 项目状态：QuantSkills Community Project，未经社区审核不得宣称官方、认证、验证、背书或保证可用于生产交易
- 许可证：`GPL-3.0-only`

## 工具定位
- 工具类型：混合型 BUILD（分析评估 + 结果生产）
- 解决问题：从 Panda Data 的点时指数成分、财报、行业、审计和价格中生成可解释研究队列、长期持仓状态与多市场历史诊断
- 使用对象：agent / Alpha / 人工复盘
- 边界：只输出研究候选和目标状态，不输出订单，不承诺收益

## 适用场景
- 当用户需要从当时真实的沪深 300 成分中寻找巴菲特式 A 股候选时
- 当统一 ROE、毛利率、CapEx 或 PE 硬门槛过度排除公司，需要改用连续软评分时
- 当银行毛利率为 N/A，必须避免填入虚假中性分时
- 当需要把回测延长到 2010，但必须区分固定 A 股名单与完整点时沪深 300 时
- 当需要复用美股巴菲特式软评分策略，并按公告日过滤 `get_fina_ex` 财报时
- 当 Alpha 需要结构稳定、可复用的候选、组合状态或回测诊断时

## 输入
BUILD 输入必须来自 Panda Data 或调用方传入的标准 Python 结构化数据。不得用静态现今成分倒推历史。

标准 `scripts.build.run()` 仍是 A 股生产入口；美股固定研究池通过 `scripts.us_strategy.run_us_backtest()` 生成历史验证，不生成生产交易候选。

| 字段 | 类型 | 说明 |
|---|---|---|
| `as_of_date` | str `YYYYMMDD` | 必填，信号日 |
| `universe` | str | `all_a`，与 `symbols`、`index_symbol` 互斥 |
| `symbols` | list[str] | 显式沪深 A 股股票池 |
| `index_symbol` | str | 点时指数成分池，例如 `000300.SH` |
| `config.selection_mode` | str | `soft`（默认）或 `hard`（旧硬门槛对照） |
| `config.reference_capital` | float | 流动性容量参考资金，默认 1000 万元 |
| `config.materialize` | bool | 是否写入生产 Parquet |

Panda 凭证只从 `PANDA_DATA_USERNAME`、`PANDA_DATA_PASSWORD` 和可选 `PANDA_DATA_BASE_URL` 读取；读取后从环境清除。禁止把凭证写入代码、日志、JSON、视频、缓存或 Parquet。

## 财务软评分

普通企业按以下五维连续打分。表中上下界是 0/100 分锚点，不是一票否决门槛。

| 维度 | 权重 | 评分 |
|---|---:|---|
| 资本回报 | 30% | 10 年 ROE 均值：5%=0，18%=100，区间线性 |
| 护城河 | 25% | 5 年毛利率均值：10%=0，50%=100；标准差每 1pp 扣 3 分 |
| 轻资产 | 15% | 5 年 `abs(cfs_cash_paid_asset)` / 归母净利润：10%=100，60%=0 |
| 安全边际 | 15% | 5 年营业利润率：2%=0，25%=100 |
| 合理估值 | 15% | 当前 PE：10 倍=100，40 倍=0 |

普通企业缺失指标不得自动获得 50 分：只对可观察维度求分，并按覆盖率施加惩罚。银行毛利率明确输出 `N/A`、分数和有效权重均为空/0；剩余维度按银行 ROE、ROA、ROA 下限/PB 和 PE 重分配为 40%/20%/20%/20%。旧硬门槛只在 `selection_mode="hard"` 时启用。

## 输出
`run()` 返回结构化 `dict`。生产结果写入 `生产产物/数据库.parquet`，使用 `data_version=9.4.0`、`schema_version=3.0.0`。

除原始 `records` 与 `portfolio` 外，每次调用还返回 `buffett_guidance`，供后续用户或 agent 直接复用：

- `overall`：巴菲特式研究优先级，即可理解生意、可持续资本回报、现金创造、合理价格和长期持有。
- `research_actions`：最多 12 个股票的“长期持有复核 / 优先研究候选 / 观察名单 / 暂缓研究”建议，以及评分、行业、覆盖率和风险关注项。
- `portfolio`：持仓数、现金权重与现金建议；机会不足或约束未满足时，保留现金而非为满仓降低标准。
- `boundary`：研究建议不构成买卖指令、收益承诺或个性化投资建议。

| 字段 | 类型 | 说明 |
|---|---|---|
| `trade_date` | string | 结果所属日期 |
| `build_id` | string | `Q44` |
| `build_name` | string | BUILD 名称 |
| `target_id` | string | 股票、组合或验证对象 |
| `result_type` | string | 候选、权重、状态、验证或股票池摘要 |
| `result_value` | string | 核心结果，固定字符串类型 |
| `result_json` | string | 合法 JSON 证据 |
| `source_data_date` | string | 原始数据日期 |
| `data_version` | string | `9.4.0` |
| `update_time` | string | UTC 生成时间 |
| `schema_version` | string | `3.0.0` |
| `run_id` | string | 运行标识 |
| `coverage_status` | string | 覆盖状态 |
| `actual_source_date` | string | 实际证据日期 |

主键为 `trade_date + build_id + target_id + result_type`。`result_type` 包括 `buffett_research_candidate`、`qualitative_review`、`portfolio_target_weight`、`portfolio_state_transition`、`portfolio_summary`、`strategy_validation`、`universe_summary`。

## 调用方式
```python
from scripts.build import run

result = run(
    {"as_of_date": "20260724", "index_symbol": "000300.SH"},
    config={"selection_mode": "soft", "soft_review_top": 50},
)
```

## 一键演示
默认演示离线读取已交付的生产快照与 A 股回测产物，不调用 Panda Data、不读取凭证、不创建订单；它同时输出可复用 JSON 与同源的独立可视化 HTML（含候选分层、持仓/换仓复核、年度持仓建议/标的和研究边界）。2010-2016 年度记录明确标为固定名单诊断，2017 起使用严格点时沪深 300 年度记录。

```powershell
python scripts/demo.py --open
```

输出为 `output/demo_result.json` 与 `output/demo_report.html`。只有显式传入 `--live --as-of-date YYYYMMDD` 时，才会使用已配置在环境变量中的 Panda Data 凭证刷新研究结果；该模式仍不创建订单。

回测严格使用每个信号日可见的沪深 300 截面：

```powershell
python scripts/backtest_runner.py --start 20170103 --end 20260724 `
  --markets a_share --a-mode strict --top-symbols 300 `
  --output "生产产物/backtest_a_share_strict.json"
```

`--a-mode strict` 表示点时指数池严格、财务阈值为软锚点；`--a-mode hard` 才是旧硬门槛对照。Panda Data 的 `000300.SH` 权重在本环境从 2017-01-03 起可验证，2017 年以前不得声称为完整点时沪深 300 历史。

2010 起 A 股固定经典名单诊断：

```powershell
python scripts/backtest_runner.py --start 20100104 --end 20260724 `
  --markets a_share --a-mode roster `
  --output "生产产物/backtest_a_share_roster_2010.json"
```

该模式存在幸存者偏差，只能称为固定样本诊断，不得称为 2010 起沪深 300 选股。

美股固定研究池点时财务回测：

```powershell
python scripts/us_strategy.py --start 20150102 --end 20260724 `
  --output "生产产物/backtest_us_fixed_roster.json"
```

Panda `get_us_daily` 对 2010-2014 返回空，且对 SPY/IVV/VOO/QQQ/DIA 无数据；不得虚构 2010 起美股历史或零收益基准。收益为按明确拆股事件校正的价格收益，不含现金分红。

## 组合规则
1. 健康老仓不因年度排名下降或估值上涨退出。
2. 仅在离开目标指数、审计否定、利润转负、债务极端恶化或季度利润转负时退出。
3. 最多 8 只；等权回测中最多 1 家银行、同一已识别行业最多 2 家。
4. 空缺按软评分顺序补位；未知行业不合并成虚假的同一行业。
5. 回测采用下一可用区间、15bp 调仓成本；只有 Panda 返回真实基准数据时才报告基准。
6. 美股最多 8 只、同一行业最多 2 只；健康老仓不因排名或估值变化自动退出。

## 可被 Alpha 调用
- 是
- 调用限制：仅提供候选、证据、目标权重和整手参考，不生成订单
- 依赖数据：Panda Data 财报、原始/后复权行情、指数权重、行业、审计和交易日

## 是否需要生产结果
- 是否生成 `数据库.parquet`：是
- 生产形态：混合型 BUILD
- 更新频率：财报/审计事件触发，交易日价格更新
- 读取生产结果时不得重复触发全量计算

## 验证边界
- 严格点时沪深 300：2017-01-03 至 2026-07-24，软版年化 5.63%，沪深 300 年化 3.52%；跨期证据仍为混合，旧 hard 集中组合样本内收益更高。
- A 股固定名单：2010-01-04 至 2026-07-24，年化 13.71%，但固定 18 只当代经典公司具有明确幸存者偏差，不是历史沪深 300 选股证据。
- 美股固定研究池：2015-01-02 至 2026-07-24，年化 15.47%、最大回撤 -30.19%；固定 12 只研究池不是历史标普 500 或伯克希尔持仓复原，且收益不含现金分红、无可用 Panda ETF 基准。

现有三条基准回放均属于 `quantitative_retrospective_diagnostic`。所有候选、持仓和换仓说明均由 Panda 点时市场与财务数据的量化规则生成；不得宣称普遍提高收益或保证未来表现。

## 依赖
- Panda Data `0.0.12`
- pandas / numpy / pyarrow / PyYAML / matplotlib

接口字段与点时规则见 [references/api_guide.md](references/api_guide.md)，方法边界见 [references/buffett_methodology.md](references/buffett_methodology.md)。

## 跨运行时入口
- Claude Code：直接加载根目录 `SKILL.md`
- Codex / OpenAI 兼容运行时：读取 `agents/openai.yaml`
- Cursor：读取 `agents/cursor-rule.mdc`
- Hermes / OpenClaw：原生加载本目录；无法发现时使用 `agents/portable-loader.md`
- 所有适配器都必须回到本文件执行，不得复制或改写评分、组合和风险边界
