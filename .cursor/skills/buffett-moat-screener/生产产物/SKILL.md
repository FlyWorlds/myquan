---
name: build-Q44-production
description: 当 agent 或 Alpha 需要读取 Q44 巴菲特软评分 BUILD 的已生成 A 股候选、组合状态、点时沪深 300、2010 固定 A 股名单或美股固定研究池验证结果时，使用此 skill；直接查询 Parquet，不重复执行全量计算。
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-buffett-moat-screener
  repository_url: https://github.com/quantskills/skill-buffett-moat-screener
  project_type: skill
  collection: fundamental-research
  maintainer: dijia702
  maintainer_url: https://github.com/dijia702
tags: [quant, build, production, hybrid, cn_a_share, us_equity]
---

# Q44 A 股与美股巴菲特软评分生产结果

## 工具定位
- 工具类型：混合型 BUILD 的结果读取端
- 服务对象：agent / Alpha / 人工复盘
- 是否可被 Alpha 调用：是

## 结果文件
- 文件路径：`数据库.parquet`
- 数据格式：Parquet，14 列
- 数据版本：`9.4.0`
- 模式版本：`soft-five-dimension-v1`
- 更新频率：财报/审计事件触发，交易日价格更新
- 生成任务：`scripts.build.run(..., config={"materialize": True})` 或已验证的生产汇总任务

## 主键
- `trade_date`
- `build_id`
- `target_id`
- `result_type`

## 字段说明
| 字段 | 类型 | 说明 |
|---|---|---|
| `trade_date` | string | 结果日期 |
| `build_id` | string | `Q44` |
| `build_name` | string | BUILD 名称 |
| `target_id` | string | 股票或验证对象 |
| `result_type` | string | 候选、组合、验证或股票池摘要 |
| `result_value` | string | 核心结果 |
| `result_json` | string | 合法 JSON 证据 |
| `source_data_date` | string | 原始数据日期 |
| `data_version` | string | `9.4.0` |
| `update_time` | string | UTC 生成时间 |
| `schema_version` | string | `3.0.0` |
| `run_id` | string | 运行标识 |
| `coverage_status` | string | 覆盖状态 |
| `actual_source_date` | string | 实际证据日期 |

## 读取规则
1. 读取 `数据库.parquet` 后过滤 `data_version=9.4.0` 与 `schema_version=3.0.0`。
2. 按主键查询；解析 `result_json` 获取五维评分、银行 N/A、覆盖率和回测证据。
3. `strategy_validation` 仅描述对应的量化历史诊断，不得外推为未来收益承诺。
4. 目标权重不是订单，不得直接提交交易。
5. A 股固定名单和美股固定研究池只读取 `strategy_validation`；不得当作历史指数成分或已批准交易候选。

## 禁止行为
- 不允许多人查询时重复触发全量计算。
- 不允许手工修改 Parquet。
- 不允许把 2017 年以前描述为完整点时沪深 300 历史。
- 不允许把 2010 固定 A 股名单描述为无幸存者偏差，也不允许把美股固定研究池描述为历史标普 500 或伯克希尔持仓。
- 结果异常时必须报告数据日期、版本与覆盖状态。
