# A股市场风险雷达

简体中文 | [English](README.en.md)

> QuantSkills 社区项目，由 GitHub 用户 `cikeqi` 维护。项目尚未经过独立审核，不代表 QuantSkills 官方认证，也不承诺收益或生产环境适用性。

这是一个面向 A 股市场的多维风险监测 Skill。它从全球宏观、融资资金、指数估值、市场趋势、资金流向、板块轮动、个股事件和技术面进行扫描，并输出可解释的红、黄、绿或未知风险等级。

本项目用于风险预警和研究，不预测确定收益，也不替代投资决策。

## 环境要求

安装 Python 依赖：

```text
pandas
numpy
panda_data
```

通过环境变量提供 PandaData 凭证：

```bash
export PANDADATA_USERNAME="..."
export PANDADATA_PASSWORD="..."
```

不得将真实账号、密码或 Token 写入代码、报告或 GitHub 仓库。

## 快速运行

完整市场扫描：

```bash
python3 scripts/full_scan.py --out /tmp/a_share_market_risk.json
```

完整扫描并加入指定股票：

```bash
python3 scripts/full_scan.py \
  --symbols 603501.SH 688808.SH \
  --out /tmp/a_share_market_risk.json
```

## 专项扫描

```bash
python3 scripts/global_macro.py
python3 scripts/market_radar.py
python3 scripts/capital_flows.py --symbols 603501.SH 688808.SH
python3 scripts/sector_rotation.py
python3 scripts/stock_risk.py 603501.SH
python3 scripts/tech_alert.py 603501.SH 688808.SH
python3 scripts/margin_scan.py --symbols 603501.SH 688808.SH
python3 scripts/unlock_calendar.py --symbols 603501.SH 688808.SH
python3 scripts/expectation_gap.py --symbols 603501.SH 688808.SH
```

## 可以直接问

- 扫描当前 A 股市场风险，并总结最重要的预警信号。
- 当前市场是高风险、需警惕还是相对稳定？请说明依据和数据缺口。
- 检查融资资金、北向持仓和市场成交是否出现脆弱性。
- 分析当前板块轮动、风格切换与拥挤风险。
- 检查 `603501.SH` 和 `688808.SH` 的个股事件与技术面风险。
- 查看未来 30 天限售股解禁压力较大的股票。
- 检查指定股票的高估值、业绩预期和技术面风险是否共振。

## 风险等级

- `RED`：多个风险维度共振，需要降低风险暴露并进一步核查。
- `YELLOW`：部分维度异常，需要控制仓位并持续观察。
- `GREEN`：当前已覆盖维度未发现显著共振，不代表未来没有风险。
- `UNKNOWN`：数据不足或接口失败，不得当作低风险。

## 文件结构

- `SKILL.md`：触发条件、工作流与风险边界。
- `agents/`：Codex、Cursor、Hermes 和 OpenClaw 等运行时入口。
- `scripts/full_scan.py`：完整市场风险扫描。
- `scripts/global_macro.py`：全球宏观环境扫描。
- `scripts/market_radar.py`：A 股市场风险雷达。
- `scripts/capital_flows.py`：资金流向分析。
- `scripts/sector_rotation.py`：板块轮动分析。
- `scripts/stock_risk.py`：个股风险检查。
- `scripts/tech_alert.py`：技术面风险预警。
- `scripts/margin_scan.py`：融资脆弱性扫描。
- `scripts/unlock_calendar.py`：限售股解禁检查。
- `scripts/expectation_gap.py`：市场预期差分析。

## 数据来源、假设与限制

- 数据来源：量化结论仅使用 PandaData。
- 关键假设：各模块的经验阈值和风险信号可以用于风险监测，但尚未替代完整历史回测和样本外检验。
- 已知限制：指数涨跌只能作为市场压力代理；接口权限、更新延迟和数据缺失可能导致不完整结果或 `UNKNOWN`。
- 风险边界：输出仅供研究与教育，不构成投资建议、收益承诺、仓位指令或自动交易决策。

## 维护与许可

- 维护者：GitHub 用户 `cikeqi`
- 仓库：`quantskills/skill-a-share-market-risk-radar`
- 许可：[GNU GPL v3.0 only](LICENSE)（SPDX：`GPL-3.0-only`）
