---
name: build-Q51-production
description: 当需要读取克拉曼特殊情况 BUILD Q51 的生产结果时，使用此 skill。读取 data_version 7.4.0 的本地 Parquet 结果并校验版本与范围，不重复执行重计算流程。
tags: [quant, build, production, seth-klarman, special-situations]
---

# 克拉曼特殊情况生产结果

## 工具定位

- 工具类型：分析报告型 BUILD 生产结果
- 服务对象：交易 agent、Alpha、人工复盘
- 是否可被 Alpha 调用：是（仅消费 `qualified_special_situation` 行）

## 结果文件

- 文件路径：`生产产物/数据库.parquet`
- 数据格式：Parquet
- 更新频率：每个 A 股交易日收盘后一次
- 生成任务：由 `scripts/build.py` 完成扫描后原子 upsert
- 生产看板：`validation/production_dashboard.html`（只读生产产物，不触发 Panda 查询）
- 健康报告：`validation/operations/health_latest.json`
- 点时账本：`validation/operations/replay_latest.parquet`
- 证据队列：`validation/operations/evidence_queue.json`

## 主键

- `trade_date`
- `build_id`
- `target_id`
- `result_type`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `trade_date` | date | 结果所属交易日 |
| `build_id` | string | 固定 BUILD 编号 |
| `build_name` | string | 固定 BUILD 名称 |
| `target_id` | string | A 股证券代码或事件族 ID |
| `result_type` | string | 四类事件，或 `research_digest` / `coverage_gap` / `scan_summary` |
| `result_value` | string | 事件状态：`risk_watch` / `underwriting_incomplete` / `qualified_special_situation` / `rejected` / `insufficient_evidence` |
| `result_json` | string | 事件承保门，或 `research_digest` 的研究候选、风险观察、评分拆解和补证动作 JSON 字符串 |
| `source_data_date` | date | 实际使用证据的最大 `available_date`（点时锁） |
| `data_version` | string | `7.4.0` |
| `update_time` | datetime | 结果生成时间 |
| `schema_version` | string | 外层 Parquet schema 版本，当前 `2.0.0` |
| `run_id` | string | 单次生成任务 ID |
| `coverage_status` | string | `complete` / `partial` / `insufficient` |
| `actual_source_date` | date | 实际源记录日期 |

## 读取规则

- 先执行 `python scripts/build.py --check-production`；只把 `status=current` 视为可消费，`partial_artifact` 仅作定向诊断。
- 只把 `data_version=7.4.0` 视为当前结果；旧版本仅作审计。
- 缺少 V7.4 行时返回 `stale_artifact`，不得回退到旧版本。
- `target_id=research_digest` 且 `result_type=research_digest` 只用于研究排序和风险观察；卡片固定带 `not_trade_signal=true`，不得覆盖原始事件承保状态。
- 只有 `result_json.scan_scope.type=all_a_share` 才是全市场生产扫描；定向诊断结果不得冒充全市场结果。
- 消费方按 `trade_date + result_type + result_value` 过滤所需事件。

### `get_restricted_list` 套餐配额降级

- `--check-production` 的 `status=current` 只说明版本、结构和主键可读，不等于 `get_restricted_list` 覆盖完整。
- 若当前快照包含 `result_type=coverage_gap` 且 `result_json.api=get_restricted_list`，或健康报告的 `coverage_gaps` 包含该接口，则定增解禁覆盖为部分：风险榜没有定增解禁卡不能解读为“没有解禁”或“没有供给压力”。
- 该情况会以 `failure_class=quota_or_rate_limit`、`result_value=insufficient_evidence` 和 `coverage_status=partial` 留痕；P4 健康报告会产生 `coverage_gap` 告警。
- 消费者可以继续读取其他类别的独立记录，但必须披露本次快照的定增解禁覆盖缺口；不得将旧快照拼接为当前数据，也不得使用未批准的替代数据源。
- 等套餐配额恢复或权限调整后，重新运行全市场生产任务并确认覆盖缺口消失，再将新快照作为完整定增解禁覆盖使用。

## 禁止行为

- 不允许多人查询时重复触发扫描或重计算。
- 不允许手工修改 Parquet。
- 不允许把 `risk_watch` 或 `underwriting_incomplete` 当作投资建议。
- 不允许因 `get_restricted_list` 配额限制而把空的定增解禁风险列表解释为无风险，或回填旧快照冒充当前覆盖。
- 不得输出买卖方向、具体仓位、胜率或收益承诺。
- 生产结果异常时必须提示 `trade_date` 和异常原因。
