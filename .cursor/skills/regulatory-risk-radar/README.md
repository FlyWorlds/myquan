# skill-regulatory-risk-radar

[English](README.en.md)

A股合规/监管风险雷达 —— 扫描持仓/自选股票池，聚合**限售解禁、股东增减持、股权质押、举牌、股权冻结、停牌、ST** 七类风险源，逐票打分分级，输出带证据来源的风险清单。

> QuantSkills 组织技能 · 数据源 Pandadata · 仅供研究/风控参考，不构成投资建议。

## 快速开始

```bash
pip install -r requirements.txt

# 离线演示（无需任何凭证，用内置样本）
python examples/run_demo.py

# 真实扫描（需配置 panda_data）
python scripts/reg_risk_report.py --symbols 000021.SZ,600519.SH \
    --lookback 180 --lookahead 90 --min-severity low \
    --out report.json --md report.md
```

## 数据后端（三层回退）

`scripts/data_source.py` 按以下顺序自动选择：

1. **`panda_data` SDK**（组织生产标准）：`import panda_data` 成功即用。安装与鉴权见 `skill-pandadata-api`。
2. **内置样本**（`examples/sample_data/*.json`）：无 SDK 时回退，保证 demo 离线可跑。
3. 显式 `--prefer sample` 可强制用样本。

> 本机若通过 Hermes 的 Pandadata MCP 接入，也可在 `data_source.py` 增补一层 `call_pandadata` 调用（结构已预留 `fetch()` 统一入口）。

## 风险源 → 接口映射

| 风险 | Pandadata 接口 | 关键字段 |
|---|---|---|
| 股东增减持 | `get_stock_shareholder_change` | direction, ratio_up_limit, progress, info_date |
| 限售解禁 | `get_restricted_list` | relieve_date, relieve_shares, shareholder_type |
| 股权质押 | `get_stock_pledge` | acc_pledge_total_ratio, pledge_ratio |
| 举牌 | `get_stock_equity_placard` | total_share_ratio, shareholder_name |
| 股权冻结 | `get_top_holders` | freeze |
| 停牌 / ST | `get_stock_daily` (st=True) | trade_status, name |

## 评分方法

- 每类事件 → 0~100 子分 = 严重度基准 × 规模因子 × 时间邻近因子。
- 综合分 = `1 - ∏(1 - 子分/100)`（风险聚合，多类叠加不被平均稀释）。
- 分级：`<25 低 / 25~55 中 / ≥55 高`。
- 权重与阈值依据见 `references/risk-taxonomy.md`。

## 目录

```
scripts/       data_source.py · scoring.py · reg_risk_report.py · formatters.py
references/    risk-taxonomy.md · data-fields.md
examples/      run_demo.py · sample_data/
```

## 免责

数据以公告日期为准，非实时。本工具仅用于研究与风险监控方法论演示，不构成任何投资建议。

## 许可证

GPL-3.0-only，详见 [LICENSE](LICENSE)。
