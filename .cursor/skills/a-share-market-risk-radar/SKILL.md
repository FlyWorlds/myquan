---
name: skill-a-share-market-risk-radar
description: A股市场风险雷达，从全球宏观、融资资金、指数估值、市场趋势、资金流向、板块轮动、个股事件和技术面进行全链路扫描，并输出红黄绿风险等级。用于用户请求A股市场环境分析、市场风险扫描、仓位风险判断、板块风格识别、个股风险检查、解禁或融资压力排查时；不用于承诺收益或替代投资决策。
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-a-share-market-risk-radar
  repository_url: https://github.com/quantskills/skill-a-share-market-risk-radar
  project_type: skill
  collection: market-risk
  type: quant
  version: 1.0.1
  license: GPL-3.0-only
---

# A股市场风险雷达

> QuantSkills 社区项目，由 GitHub 用户 `cikeqi` 维护。项目尚未经过独立审核，不代表 QuantSkills 官方认证，也不承诺收益或生产环境适用性。

使用本 Skill 生成可解释的市场风险监测结果。把输出定位为风险预警与研究材料，不要把启发式阈值描述成已验证的 Alpha 因子。

## 运行前检查

1. 确认 Python 环境已安装 `pandas`、`numpy` 和 `panda_data`。
2. 确认以下环境变量存在；不得在代码、日志或回复中展示其值：

```bash
export PANDADATA_USERNAME="..."
export PANDADATA_PASSWORD="..."
```

3. 如果依赖或凭证缺失，停止扫描并说明缺失项，不要自动安装、登录或索要公开凭证。

## 选择扫描方式

- 用户询问整体市场环境、风险等级或仓位风险：运行完整扫描，不传股票代码。
- 用户同时给出股票代码：运行完整扫描并加入个股风险和技术面预警。
- 用户只问单一主题：运行对应的独立脚本，避免无关数据调用。

## 完整扫描

```bash
python3 scripts/full_scan.py --out /tmp/a_share_market_risk.json
python3 scripts/full_scan.py --symbols 603501.SH 688808.SH --out /tmp/a_share_market_risk.json
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

运行命令时，以本 `SKILL.md` 所在目录为工作目录，或将脚本路径解析为绝对路径。

## 解读规范

- `RED`：多个风险维度共振，提示降低风险暴露并进一步核查。
- `YELLOW`：部分维度异常，提示控制仓位并持续观察。
- `GREEN`：当前已覆盖维度未发现显著共振，不代表未来没有风险。
- `UNKNOWN`：数据不足或接口失败；不得当作低风险处理。

报告应包含扫描时间、总体等级、主要触发信号、股票专项风险（如有）、数据缺口和限制。明确区分观测事实与推断，并提醒用户这些结果不构成投资建议。

## 方法边界

- 当前评分以经验阈值和信号计数为主，尚不能替代历史回测与样本外检验。
- 市场走势模块使用指数涨跌作为市场压力代理，不等同于真实跌停家数。
- 数据口径、接口权限和延迟可能产生 `UNKNOWN` 或不完整结果。
- 不根据单次扫描直接给出买卖指令或收益承诺。
