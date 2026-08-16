# Parity Guide

本指南说明 A/H 溢价与中概 ADR 折溢价报告的口径。它不替代 Pandadata 文档，也不替代上市公司公告中的股数比、存托比例和交易状态说明。

## 输入

必需输入：

- 报告数据日，格式使用绝对日期。
- A/H 配对表：`references/pairs/a-h-pairs.csv`。
- ADR 配对表：`references/pairs/adr-pairs.csv`。
- USD/HKD/CNY 汇率、来源和日期。
- Pandadata 行情和基础信息。

可选输入：

- 用户维护的历史折溢价滚动缓存。
- 用户补充的公司公告或 ADR 存托比例说明。
- 用户限制的行业、公司或市场范围。

## 配对表格式

### A/H 配对

字段：

```text
pair_id,a_symbol,a_name,h_symbol,h_name,ratio,currency_base,notes
```

说明：

- `pair_id`：稳定配对编号。
- `a_symbol`：A 股代码。
- `h_symbol`：港股代码。
- `ratio`：一份 H 股折算为同一经济权益单位的比例；不要默认 1。
- `currency_base`：报告折算基准，首版通常为 `CNY`。
- `notes`：股数比、停牌、名称差异或其他说明。

### ADR 配对

字段：

```text
pair_id,us_symbol,us_name,primary_market,primary_symbol,primary_name,ratio,adr_type,currency_base,notes
```

说明：

- `primary_market`：`HK`、`A` 或 `NONE`。
- `primary_symbol`：原生市场代码；无可比原生上市时填空。
- `ratio`：一份 ADR 对应的原生普通股或经济权益比例。
- `adr_type`：`H-share`、`A-share`、`Red-chip`、`VIE` 或 `Other`。
- `notes`：存托比例、对应关系和限制。

用户可以扩展两张 CSV，但必须保留表头。扩展前应检查公司公告、存托银行信息、拆股、退市、停牌和代码变更。

## 计算

### A/H 溢价

```text
A/H 溢价 = A股收盘价(CNY) / (H股收盘价(HKD) * HKD/CNY * ratio) - 1
```

报告中应输出百分比，并保留使用的 A 股数据日、港股数据日、汇率日期和 `ratio`。

### ADR 折溢价

当原生市场为港股：

```text
ADR 折溢价 = ADR收盘价(USD) / (港股收盘价(HKD) * HKD/USD * ratio) - 1
```

当原生市场为 A 股：

```text
ADR 折溢价 = ADR收盘价(USD) / (A股收盘价(CNY) * CNY/USD * ratio) - 1
```

当 `primary_market=NONE` 时，只输出 ADR 原币行情、数据日和说明，不计算相对折溢价。

## 排名与异常

首版默认只输出当日 snapshot：

- A/H 溢价从高到低排行。
- A/H 折价从低到高排行。
- ADR 相对原生市场折溢价排行。
- 缺少任一市场价格、汇率或 `ratio` 的配对列入不可计算清单。

历史分位和快速收敛/扩张需要滚动缓存。没有缓存时，不输出历史分位数；报告应写明历史分位需要从后续报告持续累积。

## 数据说明

报告 `数据说明` 至少包含：

- 数据来源接口。
- A 股、港股、美股各自数据日。
- USD/HKD/CNY 汇率来源和日期。
- `ratio` 字段含义和映射表版本。
- T+1、snapshot、财报滞后或一致预期 snapshot 说明。
- 不可计算配对和原因。

## 限制

- HKD、USD、CNY 必须先折算，不能直接合并。
- A/H 同股同权不等于价格折算一定 1:1。
- ADR 可能是 H 股、A 股、红筹或 VIE 结构，不能混为同一种对应关系。
- 停牌、低流动性、假期错位和盘后事件会放大折溢价。
- 本 skill 的输出仅用于研究和教育材料，不构成投资建议。
