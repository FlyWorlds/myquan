---
name: skill-oversold-rebound
description: >-
  A股超跌反弹择时与选股：严格使用 PandaData，从市场情绪、大盘资金流向、资金结构、盘面特点、国家队证据五维判断 1–10 日反弹阶段，并从沪深300、中证500或中证1000成分股中筛选候选。当用户说「超跌反弹」「情绪冰点」「抢反弹」「大跌后能不能抄底」「反弹候选」「哪些股票跌透了」时触发。只做反弹环境与候选研究；长期价值分析转用 a-share-stock-dossier，系统策略回测转用 report-replication。
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-oversold-rebound
  repository_url: https://github.com/quantskills/skill-oversold-rebound
  project_type: skill
  collection: stock-screening
  type: quant
  version: 1.0.1
  license: GPL-3.0-only
---

# A股超跌反弹（Oversold Rebound）

> QuantSkills 社区项目，由 GitHub 用户 `cikeqi` 维护。项目尚未经过独立审核，不代表 QuantSkills 官方认证，也不承诺收益或生产环境适用性。

## 0. 做什么 / 不做什么

- **做**：先用全 A 股判断当前市场是否具备 1–10 个交易日反弹条件，再从沪深300、中证500或中证1000成分股中筛选候选。
- **不做**：不承诺上涨，不使用第三方行情，不把技术超卖直接等同于买点，不把 ETF/指数异动直接写成“国家队入场”。
- **转交**：长期基本面尽调使用 `a-share-stock-dossier`；完整历史回测/研报复现使用 `report-replication`。

## 1. 输入

| 输入 | 默认 | 校验 |
|---|---:|---|
| 股票池 | 沪深300成分股 | `csi300 / csi500 / csi1000`；也可手工传 `XXXXXX.SH/SZ/BJ` 覆盖指数池 |
| 分析日 | 最近完整交易日 | `YYYYMMDD`；不得读取其后的数据 |
| 候选数 | 20 | 1–100 |
| 周期 | 1–10 个交易日 | 本 Skill 不扩展为中长线判断 |

认证只允许以下方式：

1. 环境变量 `PANDA_USERNAME`、`PANDA_PASSWORD`；或
2. `~/.pandadata/pandadata.env` 中的同名变量。

不得从其他源码复制凭证，不得把凭证写入报告。

## 2. 标准流程

### 2.1 首次使用或接口变化时先探测

```bash
python3.11 $SKILL/scripts/oversold_rebound.py \
  --probe-only \
  --out-json /tmp/oversold_rebound_probe.json \
  --out-md /tmp/oversold_rebound_probe.md
```

探测结果必须逐接口显示 `ok / empty / error / unsupported`。SDK 标记为“废弃或未上线”的 ETF 接口，只有探测成功后才可参与计算。

### 2.2 全市场择时 + 沪深300选股（默认）

```bash
python3.11 $SKILL/scripts/oversold_rebound.py \
  --universe csi300 \
  --top-n 20 \
  --out-json /tmp/oversold_rebound.json \
  --out-md /tmp/oversold_rebound.md
```

### 2.3 切换中证500或中证1000股票池

```bash
python3.11 $SKILL/scripts/oversold_rebound.py --universe csi500 --top-n 20
python3.11 $SKILL/scripts/oversold_rebound.py --universe csi1000 --top-n 20
```

股票池来自 PandaData `get_index_weights` 在分析日及之前的最新成分股快照。三种指数池分别约有 300、500、1000 只股票，不是命令示例中的少数股票。

### 2.4 手工指定少量股票（可选覆盖）

```bash
python3.11 $SKILL/scripts/oversold_rebound.py \
  --symbols 000001.SZ 600519.SH 300750.SZ \
  --top-n 10
```

`--symbols` 仅用于用户明确要求研究一组具体股票时；一旦传入，会覆盖 `--universe`。

### 2.5 历史截面（防未来数据验证）

```bash
python3.11 $SKILL/scripts/oversold_rebound.py \
  --as-of 20250115 \
  --universe csi500 \
  --out-json /tmp/oversold_rebound_20250115.json \
  --out-md /tmp/oversold_rebound_20250115.md
```

运行后读取 Markdown 报告；需要检查明细或二次处理时读取 JSON。

### 2.6 示例问句

- “判断现在是不是情绪冰点，并从沪深300找 20 只超跌反弹候选。”
- “用中证500股票池，筛选跌透但开始止跌的股票。”
- “看看中证1000现在有没有反弹机会，列出评分最高的 30 只。”
- “大跌之后能不能抄底？先判断市场阶段，再从沪深300选股。”
- “中证500里哪些股票 RSI 超卖、抛压衰竭，并且出现止跌确认？”
- “截至 2025-01-15，用当时的中证1000成分股做一次超跌反弹扫描。”
- “只分析 000001.SZ、600519.SH 和 300750.SZ 是否具备短线反弹条件。”

如果用户没有点名股票池，默认使用沪深300；提到“中证500”或“中证1000”时，分别映射为 `csi500`、`csi1000`。

## 3. 五维环境与阶段

| 维度 | 核心内容 | 主要 PandaData 接口 |
|---|---|---|
| 市场情绪 | 涨跌家数、涨跌比、中位数涨幅、极端涨跌、连续下跌、离散度 | `get_stock_daily` |
| 大盘资金流向 | 成交额变化、上涨股成交额占比、宽基量价共振、可用时 ETF 净申赎 | `get_stock_daily`, `get_index_daily`, `get_fund_etf_cr_net` |
| 资金结构 | 融资趋势、北向持仓变化、龙虎榜机构净买卖 | `get_margin`, `get_hsgt_hold`, `get_lhb_detail` |
| 盘面特点 | 指数回撤、RSI/MACD/布林修复、量能衰竭、止跌 K 线 | `get_index_daily` |
| 国家队 | 明确主体股东持仓变化；ETF 仅作代理，不能冒充事实 | `get_top_holders`，可用时 `get_fund_etf_cr_net` |

阶段必须从以下五类中选择：

1. `恐慌加速`：下跌广度和价格/量能仍在恶化，市场门控不通过。
2. `情绪冰点`：极端超卖已出现，但止跌确认不足。
3. `止跌试探`：跌幅收窄、抛压衰竭或底部形态开始出现。
4. `反弹确认`：市场广度、宽基趋势及资金至少两个维度同步改善。
5. `反弹衰竭`：已有反弹但短线过热、量价背离或广度回落。

## 4. 候选股输出

每只候选必须包含：

- 总分（0–100）与数据覆盖率；
- 超跌程度、抛压衰竭、止跌确认、资金回流、板块共振五项分数；
- 预计观察窗：`1–3日 / 3–5日 / 5–10日`；
- 入选证据、反证、失效条件；
- 是否通过市场门控；
- 被否决时的明确原因。

## 5. 硬规则

1. **严格 PandaData**：禁止 WebSearch、第三方 API、手工补行情或合成数据。
2. **N/A 不是 0**：无数据必须显示 `N/A + 原因`；按剩余可用权重归一化，不得静默当中性。
3. **证据分级**：中央汇金/证金等明确股东记录才是 `HARD`；ETF/指数行为最多是 `PROXY`；二者都没有则为 `N/A`。
4. **不得冒充精确涨跌停统计**：若未可靠处理 ST、新股和不同板块涨跌幅规则，只能称“近涨停/近跌停（统一阈值口径）”。
5. **禁止未来函数**：`--as-of` 之后的数据不得读取；日线收盘信号只能假设下一交易日执行。
6. **先市场、后个股**：市场处于 `恐慌加速` 时可以列候选，但必须标记“市场门控未通过”。
7. **事实/代理/判断分离**：持仓变化不是实时交易流量；成交额不是主力净流入；指数拉升不是国家队事实。
8. **可追溯**：每项衍生指标注明公式或字段，每个数据模块注明接口、窗口、行数和最新日期。
9. **股票池必须真实展开**：不得把命令示例中的 3 只股票当作默认股票池；必须通过 `get_index_weights` 拉取所选指数在分析日及之前的最新成分股快照，并在报告中显示指数名称、成分日期和数量。

## 6. 输出顺序

1. 结论摘要
2. 反弹阶段与市场门控
3. 五维环境评分
4. 国家队证据等级
5. Top 候选股
6. 否决/降级名单
7. 数据覆盖与缺失项
8. 接口溯源表
9. 免责声明

> 本报告基于 PandaData 公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。超跌可能继续下跌，任何候选均需结合下一交易日价格确认和风险控制。
