# API 与承保口径

Panda Data 是本 BUILD 唯一数据源。SDK：`panda_data==0.0.12`。接口依据为 `E:\quantskill\接口文档(1).md`（修改时间 2026-07-21 17:02:01，SHA-256 `694C193EC3714F1B25D20BBE7F03CC8D3932ECFBE5C2CB881AB15B66A0879D16`）。运行时同时兼容 `panda_data` 与 `panda-data` 两种发行包元数据命名；认证凭证从进程环境变量读入内存后立刻清除。可选 API 不可用时输出 `coverage_gap`，不切换数据源。

## 事件类型与所需接口

| 事件类型 | 核心接口 | 判定要点 |
|---|---|---|
| `private_placement_supply_risk` | `get_stock_private_placement` + `get_restricted_list` + `get_share_float` | 参与者浮盈、临近解禁股数、解禁量/流通股。发行价差不是二级市场安全边际，固定为 `risk_watch` |
| `reorganization_event` | `get_stock_csrc_approval`；`get_stock_material_contract` 仅作上下文 | 对价、条件、融资、审批、截止日、终止条款、成功价值、失败价值。批文/停复牌只走催化剂门；重大合同只按精确证券代码与关键词弱关联，不能晋级承保门 |
| `spin_off_event` | `get_stock_csrc_approval` + `get_stock_detail` | 持股比例、子公司保守价值、剩余业务、净债务、税费、控股折价、稀释股数。合同金额不能替代子公司价值 |
| `distress_event` | `get_stock_status_change` + `get_audit_opinion` + `get_fina_reports` | 资产回收、担保顺位、优先债务、或有负债、重整成本、完全稀释股数。ST 摘帽或干净审计不能直接晋级 |

辅助风险接口：`get_stock_daily`（价格、成交、停复牌）、`get_stock_pledge`、`get_stock_litigation_arbitration`、`get_cumu_guarantee`、`get_stock_equity_illegal`。非核心资本行为上下文：`get_repurchase`、`get_stock_equity_placard`、`get_stock_shareholder_change`。上下文接口不能创建事件或晋级候选。

## 最新接口字段契约

| 接口 | 必需入参 | BUILD 使用的返回字段 | 用途与边界 |
|---|---|---|---|
| `get_stock_private_placement` | `start_date`, `end_date`；`symbol` 可选 | `symbol`, `announcement_date`, `issue_type`, `issue_status`, `listed_date`, `issued_shares`, `issue_price`, `approval_date` | 识别定增发行与参与者浮盈 |
| `get_restricted_list` | `start_date`, `end_date`；`symbol`, `market` 可选 | `date`, `relieve_date`, `shareholder`, `shareholder_type`, `relieve_shares`, `actual_relieve_shares`, `relieve_reason` | 识别未来解禁及实际流通数量；套餐配额限制时按下述策略降级，不以空表代表无解禁 |
| `get_share_float` | `start_date`, `end_date`；`symbol` 可选 | `date`, `circulation_a`, `free_circulation`, `total`, `total_a` | `circulation_a` 是解禁压力比例的流通 A 股分母 |
| `get_stock_csrc_approval` | `start_date`, `end_date` | `publish_date`, `announcement_category`, `announcement_level`, `announcement_title`, `announcement_number`, `announcement_content`, `attachment_link`, `announcement_link` | 只作为监管催化剂和官方链接 |
| `get_stock_material_contract` | `start_date`, `end_date`；`symbol` 可选 | `symbol`, `info_date`, `info_id`, `project_progress`, `project_name`, `contract_title` | 只按证券代码和关键词补充背景 |
| `get_stock_status_change` | 日期范围；`symbol` 可选 | `symbol`, `date`, `change_date`, `description`, `name`, `type` | 困境事件发现与实施日期 |
| `get_stock_daily` | `start_date`, `end_date`；`symbol` 可选 | `date`, `symbol`, `open`, `close`, `volume`, `amount`, `limit_up`, `limit_down`, `trade_status` | 点时价格、停复牌、成交额/成交量和可成交性；研究榜计算 20 日平均成交额 |
| `get_fina_reports` | `date` 或季度范围；`symbol` 可选 | `symbol`, `quarter`, `date` 及财务字段 | 基本面 double check；只使用 `date <= as_of_date` 的披露 |
| `get_audit_opinion` | 季度范围；`symbol` 可选 | `date`, `symbol`, `quarter`, `audit_type`, `agency`, `opinion` | 优先使用最新财务报表审计意见，排除 `no_audit_performed` |
| `get_stock_pledge` | 日期范围；`symbol` 可选 | `publish_date`, `pledged_shares`, `pledge_ratio`, `acc_pledge_total_ratio`, `release_date` | 非核心质押风险 |
| `get_stock_litigation_arbitration` | 日期范围；`symbol` 可选 | `info_date`, `lawsuit_type`, `case_progress`, `involved_amount`, `judgment_content` | 非核心法律风险 |
| `get_cumu_guarantee` | 日期范围；`symbol` 可选 | `info_date`, `total_amount`, `ex_balance`, `total_amount_ratio`, `related_amount`, `excess_amount` | 非核心担保与或有负债风险 |
| `get_stock_equity_illegal` | 日期范围；`symbol` 可选 | `info_date`, `illegal_type`, `illegal_event`, `punish_action`, `punish_amount` | 非核心违规风险；当前 SDK 内部兼容 `get_equity_illegal` |
| `get_repurchase` | 日期范围；`symbol` 可选 | `date`, `procedure`, `purpose`, `buy_back_volume`, `value_floor`, `value_ceiling`, `price_floor`, `price_ceiling`, `buy_back_percent` | 非核心回购背景 |
| `get_stock_equity_placard` | 日期范围；`symbol` 可选 | `info_date`, `shareholder_name`, `actual_controller`, `total_share_ratio`, `average_price`, `share_holding_ratio`, `increase_plan` | 非核心举牌和控制权背景；当前 SDK 内部兼容 `get_equity_placard` |
| `get_stock_shareholder_change` | 日期范围；`symbol` 可选 | `info_date`, `progress`, `direction`, `change_up_limit`, `ratio_up_limit`, `reason` | 非核心股东供需背景 |

## `get_restricted_list` 套餐配额降级契约

该接口是 `private_placement_supply_risk` 的核心输入。若 Panda Data 返回“限额 / 套餐 / quota / rate limit”类错误，执行以下失败封闭策略：

1. **分类与重试**：记录失败分类 `quota_or_rate_limit`，按 `max_api_attempts` 做有界退避重试。默认值为 2，允许范围是 1–4；认证失败不重试，其他不可重试错误按其分类直接降级。
2. **调用结果**：仍失败时，`source.capabilities["get_restricted_list"]` 固定记录 `status="unavailable"`、`failure_class="quota_or_rate_limit"`、`error_type` 和 `attempts`。不持久化服务端原文、凭证或请求敏感信息。
3. **生产记录**：生成 `result_type="coverage_gap"`、`result_value="insufficient_evidence"` 的独立记录；其 `result_json` 包含 `api="get_restricted_list"`、`failure_class`、`attempts`、`discovery_status="coverage_gap"` 和 `underwriting_status="underwriting_incomplete"`。
4. **业务降级**：本次获取失败后，定增发行仍可被扫描，但不得从空解禁表推导“无解禁”。没有可验证的解禁日期和数量时，不生成或刷新 `private_placement_supply_risk`；因此 `risk_watchlist` 中缺少定增卡不代表不存在供给风险。`research_digest` 聚合记录标记 `coverage_status="partial"`，其余事件类别按各自接口继续运行。
5. **消费与恢复**：P4 健康报告将 `get_restricted_list` 写入 `coverage_gaps` 并产生 `coverage_gap` 告警，通常状态为 `attention`（除非另有 critical 告警）。消费者不能只凭 `--check-production` 的结构状态就视为定增覆盖完整，必须同时检查 `source.capabilities`、`coverage_gap` 记录或 `validation/operations/health_latest.json`。待套餐额度恢复或权限调整后，重新执行全市场、点时一致的扫描；不得自动切换第三方数据源、手工补零，或把旧快照混入当前决策日结果。

## 承保门与状态

安全边际 = `1 - market_price / conservative_value`。失败压力概率 `p_close × close_value + (1-p_close) × break_value - market_price - costs` 只作敏感性，不替代逐案证据。

核心门：可交易证券、催化剂、交易条款、保守价值、失败价值、资本结构、法律审计、流动性、安全边际。每门 `pass` / `missing` / `fail`，不加权。

状态：

- `risk_watch`：定增解禁供给风险
- `underwriting_incomplete`：事件真实但核心事实缺
- `qualified_special_situation`：全部核心门 + 冻结 policy 安全边际通过
- `rejected`：证据表明核心门失败
- `insufficient_evidence`：身份或必需 API 不可用
- `no_events`：扫描成功但无可观察事件

## 关键坑（Klarman）

- 每类事件都需事件驱动 + 基本面 double check
- 定增折价必须计入解禁供给风险
- 重组/借壳失败率 30%+，必须分散押注、独立评估失败价值
- 分拆的 SOTP 不能用合同金额充数
- 困境反转要看清偿顺位、股权回收瀑布，不看利润改善

## 点时与证据契约

每个 `EvidenceAtom` 必须带 `atom_id`、`field_name`、`value`、`source_type`、`source_record_id`、`available_date`（YYYYMMDD）、`content_hash`（SHA-256）、`extraction_method`、`evidence_kind`、`core`。核心原子只接受 `extraction_method=provider` + `evidence_kind=structured_fact`。人工备注仅作非核心叙述证据。

信号日 = 实际使用证据的最大 `available_date`；入场为其后首个可成交开盘。停牌、一字板、退市和右删失必须显式处理。默认往返成本 100 bps，25/50 bps 仅敏感性；基准 `000985.SH`。

`evidence_dir` 用 `event_family_id + revision_id` 追加修订；后续状态变化创建新 revision，不回写首次信号。

## 生产契约

逻辑 `data_version=7.4.0`，Parquet `schema_version=2.0.0` 的 14 列外层结构不变；新增一条 `target_id=research_digest`、`result_type=research_digest` 聚合行，完整榜单保存在其 `result_json`，原始事件行保持不变。研究榜使用调用日前最新公开证据，历史回放继续使用事件时点可见证据，禁止混用。`get_stock_daily` 的成交额/成交量用于 20 日均值和定增解禁消化天数。新上下文写入 `result_json.panda_non_core_context`。流通股本仅查询定增相关证券，并逐证券断点缓存以适应账户额度；公告日期按行从 `publication_date`、`date`、`info_date`、`announcement_date`、`stage_date` 依次取首个有效值。生产键：`trade_date + build_id + target_id + result_type`；同一 `trade_date + build_id` 是完整快照并整分区原子替换，其他交易日历史保留。默认 policy `v7-baseline`：20% 安全边际、30% 失败压力、20% 定增浮盈警报。定向扫描不得覆盖默认全市场生产库。

### `research_digest` 聚合结果

- `shortlist`：最多 5 张研究卡；困境反转、重组和分拆统一按透明规则排序，每类最多 3 张，低于 60 分或缺证券/事件日后证据/当前价格的事件不进入主榜。
- `risk_watchlist`：最多 5 张独立风险卡；定增解禁使用解禁占流通盘、参与者浮盈、距解禁日和 20 日成交额消化天数，困境风险使用仍生效风险警示、审计警示、财务失败、负经营现金流和股东减持。
- 每张卡固定带 `score_breakdown`、`thesis`、`positive_signals`、`risk_flags`、`missing_core_evidence`、`next_research_actions`、`current_market_evidence`、`underwriting_status` 和 `not_trade_signal=true`。
- 聚合榜仅用于研究排序；原始事件的 `underwriting_status` 不被覆盖，只有原始行的 `result_value=qualified_special_situation` 可以被 Alpha 消费。

## P0 接口失败语义

接口能力状态额外记录：`attempts` 与 `failure_class`。失败分类固定为 `quota_or_rate_limit`、`transient_transport`、`api_unavailable`、`data_or_service_error`。前两类最多按 `max_api_attempts` 有界退避；认证失败立即抛出。`get_restricted_list` 的套餐配额限制必须走上述独立 `coverage_gap` 降级，不得用空表宣称没有解禁。持久化内容只保留安全分类和异常类名，不保存 Panda 服务端原始消息。

## P1 运行与恢复契约

- 证券列表请求按 `checkpoint_batch_size` 分片，完成分片原子写入 Parquet。
- 检查点键由 API、证券批次和非证券参数的稳定哈希组成；同配置重跑直接读取。
- `validation/operations/Q51-*.json` 记录 `scan_started` 至 `scan_completed`，并以 `completed` 或 `failed` 关闭。
- 清单不得包含账号、密码、token 或完整异常消息。

## P2 证据队列

`scripts/evidence_queue.py` 把 atom 字段映射为 situation-specific Klarman 门，输出 `ready_for_underwriting`、`ready_for_risk_watch`、`evidence_incomplete` 或 `invalid_bundle`。正式产物为 `validation/operations/evidence_queue.json`。定增只进入供给风险观察，不进入特殊情况承保。

## P3 点时账本

`scripts/replay.py` 只读生产 Parquet，输出 `validation/operations/replay_latest.parquet`。当前阶段是事件验证账本，不是收益回测；仅当事件同时满足 `qualified_special_situation` 且已有 `resolution_date` 时，才能进一步用 Panda 日线按 knowledge cutoff 后首个可交易开盘、成本和统一基准进行价格回放。

## P4 任务与告警

`scripts/production_job.py` 串联扫描、证据队列、回放、健康报告和看板。`health_latest.json` 检查当前版本、全市场范围、空分区、坏 JSON、重复主键、时效、运行失败、运行 SLA 与 coverage gap。此 BUILD 只生成结构化告警，不自行向微信、邮件或其他外部渠道发送通知。

## 禁止

只做 A 股多头现货；不假设融券、对冲腿或衍生品。不输出买卖指令、具体仓位、胜率、收益承诺。
