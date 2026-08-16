---
name: alpha-a06
description: 当需要开发、计算、验证 A06 游资席位冷却反转与协同突破因子时，使用此 skill。支持 PandaData 数据获取、因子计算、三层沙漏检测、可成交回测和生产发布。
tags: [quant, alpha, development, stock, lhb]
---

# A06 游资席位冷却反转与协同突破 Alpha

## 适用场景

- 计算或更新 A06 因子。
- 验证因子是否存在未来函数、过拟合或样本外失效。
- 生成候选信号并构建已验收的生产 Parquet。

## 因子逻辑

- 核心假设：龙虎榜游资协同后的短期拥挤会反转；少数不过热、重复席位协同的高强度净买入具有突破延续性。
- 计算公式：`(-z(net_buy_to_amount)-z(ret_5d)-z(ret_10d))/3 + 0.25*watch + 3.0*buy`。
- 排序方向：`factor_value` 越大越强。
- 适用市场：A 股龙虎榜股票。
- 唯一模式：`hotmoney_executable_open`。

## 输入数据

正式计算只使用 PandaData 数据拉取库。固定 Parquet 仅作为 PandaData 原始快照用于可复现发布验收，不接受旧因子面板作为正式输入。

| 字段 | 说明 | 来源 |
|---|---|---|
| date / trade_date | 交易日期 | `get_lhb_detail` / `get_trade_cal` / `get_market_data` |
| symbol / ts_code | 股票代码 | PandaData |
| agency / rank / b_value / s_value | 龙虎榜席位与买卖金额 | `get_lhb_detail` |
| open / close / limit_up / trade_status | 可成交回测与停牌涨停处理 | `get_market_data` |
| amount / volume / high / low | 拥挤度与位置诊断 | `get_market_data` |

依赖：Python、pandas、pyarrow、PandaData；真实数据运行需配置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD`。

## 输出结果

| 字段 | 说明 |
|---|---|
| factor_value | 因子原始值 |
| score | 每日横截面 0-100 评分 |
| signal | `buy` / `watch` / `hold` |
| confidence | 0-1 置信度 |
| data_version | `pandadata-lhb-hotmoney-executable-open-a06-v1` |

## 可成交口径

信号在 `t` 日收盘后形成；`t+1` 开盘买入，停牌或开盘涨停跳过；`t+2` 收盘卖出。标准双边成本 `0.30%`，压力成本 `0.50%`。

## 使用方式

```powershell
python scripts\factor.py --demo
python scripts\validate.py
python scripts\backtest.py
python scripts\update_production.py --full-refresh --bootstrap-start-date 20230601
```

使用 PandaData 固定原始快照构建发布版：

```powershell
python scripts\build_release.py `
  --details <panda_lhb_detail.parquet> `
  --calendar <panda_trade_calendar.parquet> `
  --quotes <panda_market_data.parquet> `
  --start-date 20230601 `
  --end-date 20260605 `
  --output <数据库.parquet> `
  --report <发布验收报告.json>
```

## 验收要求

- 不允许未来函数。
- 必须通过训练/测试、跨年度样本外和过拟合检查。
- 必须输出 IC、Rank IC、ICIR、五层收益、顶底层多空、最大回撤、换手率和信号样例。
- 标准成本与 `0.50%` 压力成本必须同时通过发布门槛。
- 不通过验证不得进入生产。
