# 数据源说明 — Crude Oil Briefing

## Pandadata 期货接口

| 接口方法 | 用途 | 参数 |
|---------|------|------|
| `get_future_daily` | SC 主力合约日线行情 | `symbol=["sc主力连续"], start_date, end_date` |
| `get_future_term_structure` | 期货期限结构 | `variety="SC"` |
| `get_future_warehouse_receipt` | 仓单库存数据 | `variety="SC"` |
| `get_future_ls_ratio` | 多空持仓比 | `variety="SC"` |
| `get_future_variety_posi` | 品种持仓分布 | `variety="SC"` |
| `get_future_free_spread` | 价差/期差数据 | `variety="SC"` |
| `get_future_contract_indicators` | 合约指标 | `variety="SC"` |

## EIA 开放 API

Base URL: `https://api.eia.gov/v2/`

| 数据系列 | 系列 ID | 频率 |
|----------|---------|------|
| WTI 现货价格 | `PET.EER_EPD2F_PBC_S1Y_D` | 日 |
| Brent 现货价格 | `PET.EER_EPD1_PBC_S1Y_D` | 日 |
| 美国商业原油库存 | `PET.WCRSTUS1.W` | 周 |
| 美国原油产量 | `PET.WCRFPUS2.W` | 周 |
| 炼厂原油加工量 | `PET.WCRRIUS2.W` | 周 |
| 美国原油进口量 | `PET.WCRIMUS2.W` | 周 |
| 美国原油出口量 | `PET.WCREXUS2.W` | 周 |
| 库欣原油库存 | `PET.W_CR_ST_CUSH_1.W` | 周 |

API Key 注册: https://www.eia.gov/opendata/register.php

## OPEC 数据

- OPEC Monthly Oil Market Report (MOMR)
- 成员国产量数据
- 全球需求预测
- 供需平衡表

## 新闻来源

- 东方财富网 — 原油频道
- Reuters 原油新闻
- 财联社 — 能源板块
