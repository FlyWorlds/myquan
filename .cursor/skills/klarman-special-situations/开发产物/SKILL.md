---
name: klarman-special-situations
description: Seth Klarman special-situations research skill for A-share private-placement unlocks, restructurings and backdoor listings, spin-offs, and distressed turnarounds. Use for 克拉曼特殊情况投资、定增解禁、重组借壳、分拆上市、困境反转、事件驱动研究、研究候选排序或独立风险观察。Uses Panda Data and official announcement evidence, applies point-in-time and fail-closed underwriting, and never produces trading instructions or return promises.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-klarman-special-situations
  repository_url: https://github.com/quantskills/skill-klarman-special-situations
  project_type: skill
  collection: special-situations
  creator: dijia702
  creator_url: https://github.com/dijia702
  maintainer: dijia702
  maintainer_url: https://github.com/dijia702
  tags:
    - quant
    - seth-klarman
    - special-situations
    - event-driven
    - margin-of-safety
---

# 克拉曼特殊情况研究

## 工具定位

- 工具类型：分析报告型 BUILD（混合形态）
- 解决问题：把 Seth Klarman《安全边际》里的分拆/破产/重组/定增/私有化错误定价套利框架落到 A 股，用点时证据和保守估值筛选合格候选。
- 使用对象：交易 agent、Alpha、人工复盘。

## 维护与项目状态

- 上游仓库：`quantskills/skill-klarman-special-situations`。
- 创建者与维护者：[`dijia702`](https://github.com/dijia702)。
- 项目身份：QuantSkills 社区项目。未经社区维护者审核，不得表述为官方、认证、验证、背书或保证可用于生产交易的项目。
- 支持场景：A 股定增解禁供给风险、重组/借壳、分拆上市、困境反转的事件扫描、研究排序、证据补齐和严格承保。
- 重要限制：输出仅供研究、教育、复核和系统集成，不构成投资建议；不保证数据持续可用、候选有效或任何投资收益。

## 原理

Klarman《安全边际》：特殊情况的错误定价源自事件复杂性与被动卖压，而非市场无效。把事件当作研究入口，不把事件本身当作收益来源。先确认二级市场实际取得的证券权利，再检查催化剂、条款、资本结构、保守价值、失败价值、法律审计和流动性。核心证据缺失时保持不完整；零合格候选是有效结果。

## 适用场景

- 用户或 agent 需要在 A 股上扫描四类特殊情况候选。
- Alpha 需要 event-driven 事件流并配套保守估值证据。

## 四类特殊情况与筛选逻辑

| 事件 | 核心接口 | 判定要点 | 关键坑 |
|---|---|---|---|
| 定增折价解禁 | `get_stock_private_placement` + `get_restricted_list` + `get_share_float` | 定增发行价 vs 市价，折价 > 20% 且解禁临近；解禁量/流通盘比重 | 发行价差是参与者浮盈，不是二级市场安全边际；固定为 `risk_watch`，必须计入供给压力 |
| 重组 / 借壳 | `get_stock_csrc_approval`；`get_stock_material_contract` 仅作非核心上下文 | CSRC 批文 + 停复牌事件驱动；对价、条件、融资、审批、截止日、失败价值 | 重大合同弱关联不得晋级；失败率 30%+，必须独立评估失败价值并分散押注 |
| 分拆上市 | `get_stock_csrc_approval` + `get_stock_detail` | 母公司持股比例、子公司保守价值、剩余业务、净债务、税费、控股折价、稀释股数 SOTP | 合同金额不能替代子公司价值 |
| 困境反转 | `get_stock_status_change` + `get_audit_opinion` + `get_fina_reports` | 资产回收、担保顺位、优先债务、或有负债、重整成本、完全稀释股数股权回收瀑布 | ST 摘帽或干净审计不能直接晋级，看清偿顺位不看利润改善 |

每类都需要事件驱动 + 基本面 double check。安全边际 = `1 - market_price / conservative_value`。核心门：可交易证券、催化剂、交易条款、保守价值、失败价值、资本结构、法律审计、流动性、安全边际。任一 `fail` 或 `missing` 都不得晋级 `qualified_special_situation`。

只研究 A 股多头现货，不假设融券、对冲腿或衍生品。不输出买卖指令、具体仓位、胜率或收益承诺。

研究优先级是人工研究排序，不是买入信号。研究候选最多 5 只、每类最多 3 只，最低 60 分且不足不凑数；定增解禁只进入独立风险观察。只有 `qualified_special_situation` 才能继续供 Alpha 读取，研究榜中的 `not_trade_signal=true` 和承保状态不会改变原始事件行。

## 输入

BUILD 输入必须来自 Panda Data 或调用方传入的标准结构化数据；如数据源、字段含义、接口权限或生产路径不明确，先咨询项目工作人员。

| 字段 | 类型 | 说明 |
|---|---|---|
| `as_of_date` | str `YYYYMMDD` | 决策日；证据 `available_date` 不得晚于此 |
| `start_date` | str `YYYYMMDD`，可选 | 事件回看起点，默认由 policy 决定 |
| `symbols` | list[str]，可选 | 限定证券池；缺省全 A 股 |

`config` 可选：`evidence_dir` / `evidence_provider`、`policy_path`、`output_path`、`manifest_dir`、`checkpoint_dir`、`checkpoint_batch_size`（1–200）、`max_api_attempts`（1–4）。库入口不读取环境变量；Panda Data 凭证只从 CLI 子进程环境读入内存并立刻清除。回购、举牌和股东增减持只写入 `panda_non_core_context`，不得改变承保状态。

### `get_restricted_list` 套餐配额降级

`get_restricted_list` 是定增解禁供给风险的必需输入。服务端错误含“限额 / 套餐 / quota / rate limit”时，P0 将其分类为 `quota_or_rate_limit`，按 `max_api_attempts`（默认 2，范围 1–4）有界退避重试。仍失败时：

- `source.capabilities.get_restricted_list` 记录 `status=unavailable`、`failure_class=quota_or_rate_limit`、异常类型和尝试次数；
- 产出一条 `result_type=coverage_gap`、`result_value=insufficient_evidence` 的记录，定增解禁链路不生成或刷新 `private_placement_supply_risk` 风险卡；
- `research_digest` 标记为部分覆盖，P4 健康报告列出 `get_restricted_list` 覆盖缺口；风险榜没有定增卡不等于没有解禁；
- 其他事件类别可继续扫描，但调用方必须披露定增解禁覆盖不完整；不得切换未批准数据源、手工填零，或把旧快照混入当前决策日。

配额恢复后，对同一决策日需要重新执行完整、点时一致的扫描；只把旧完整快照作为带日期的历史审计材料。完整字段与恢复契约见 [API 与承保口径](references/api_guide.md)。

## 输出

`run()` 返回稳定的 BUILD envelope。混合形态：全 A 股扫描可同时写入 `生产产物/数据库.parquet`；定向证券扫描默认禁止写入生产库。

| 字段 | 类型 | 说明 |
|---|---|---|
| `build_id` / `build_name` / `data_version` | str | BUILD 身份与逻辑版本 |
| `as_of_date` | str | 决策日 |
| `status` | str | BUILD 执行状态 |
| `scan_scope` | dict | `all_a_share` 或明确的 `symbols` 定向范围 |
| `source` | dict | Panda SDK 版本、接口清单与逐接口能力状态 |
| `summary` | dict | 总数、类型计数与覆盖状态计数 |
| `research_digest` | dict | 最多 5 个研究候选与最多 5 个独立风险观察；实时榜使用决策日前最新公开证据 |
| `records` | list[dict] | 事件、能力缺口、扫描摘要或 `research_digest` 聚合行；承保门和证据位于各行 `payload` |
| `production_path` | str，可选 | 落地 parquet 的绝对路径 |

事件状态枚举：`risk_watch`、`underwriting_incomplete`、`qualified_special_situation`、`rejected`、`insufficient_evidence`、`no_events`。研究聚合行的 `result_value` 为 `available` 或 `no_high_priority_candidates`。

## 调用方式

```python
from scripts.build import run

result = run(
    {"as_of_date": "20260715", "start_date": "20210101"},
    config={"evidence_dir": "path/to/official_evidence"},
)
```

CLI：

```powershell
$env:PANDA_DATA_USERNAME = "<账号>"
$env:PANDA_DATA_PASSWORD = "<密码>"
python scripts/build.py --as-of 20260724 --start 20250724 --progress
python scripts/build.py --check-production
```

## 可被 Alpha 调用

- 是。
- 调用限制：Alpha 只能读 `qualified_special_situation` 结果并自行组合仓位；不得直接消费 `risk_watch` 或 `underwriting_incomplete`。
- 依赖数据：Panda Data + `evidence_dir` 官方公告 JSON。

## 是否需要生产结果

- 生成 `生产产物/数据库.parquet`：是（混合形态）。
- 更新频率：交易日收盘后一次；BUILD 版本与生产逻辑 `data_version=7.4.0`，`schema_version=2.0.0`。研究榜使用调用日前最新公开证据，历史回放继续使用事件时点证据；新增成交额/成交量与定增解禁消化天数；流通股本只查询定增相关证券并逐证券断点缓存；点时过滤按行从空 `date` 回退到有效 `announcement_date`。
- 全市场落盘：CLI 加 `--materialize`。定向扫描只有显式 `--allow-partial-materialization --output-path <独立路径>` 才可诊断落盘，不得覆盖默认生产库。
- 字段结构：14 列外层，新增承保字段进 `result_json`。生产键 `trade_date + build_id + target_id + result_type`。

## 严格交付验收

- 开发包路径：`开发产物/`；生产包路径：`生产产物/`。
- 使用 `python scripts/validate_build.py` 执行离线 BUILD V2 验收；根声明另使用通用 Skill 校验器检查运行时兼容性。

## P0–P4 生产链

| 阶段 | 已实现能力 | 验收口径 |
|---|---|---|
| P0 接口治理 | Panda 失败分类、1–4 次有界重试、coverage gap | `get_restricted_list` 套餐配额耗尽时记为 `quota_or_rate_limit` + `coverage_gap`，不把缺失解释为无解禁；不落凭据或服务端原文 |
| P1 可恢复全市场任务 | 按证券批次 Parquet 检查点、原子运行清单 | 同参数重跑复用已完成分片；成功/失败均关闭 manifest |
| P2 官方公告证据包 | `EvidenceAtom` 校验与补证队列 | 只有核心门完备的包进入承保；占位哈希和坏 schema 失败封闭 |
| P3 点时验证 | 生产事件账本、knowledge cutoff、右删失 | 非 qualified 不计算收益；尚未解决事件不得伪造结果 |
| P4 调度与告警 | 单一生产任务、健康 JSON、生产看板 | 生成结构化告警；外部通知需另行授权配置 |

生产任务入口：

```powershell
$env:PANDA_DATA_USERNAME = "<账号>"
$env:PANDA_DATA_PASSWORD = "<密码>"
python scripts/production_job.py --as-of 20260724 --start 20250724 --evidence-dir <官方证据目录>
```

展示入口：`validation/production_dashboard.html`。它只读取生产 Parquet 与 `validation/operations/`，不会触发 Panda 查询；`validation/dashboard.html` 是历史验证扫描看板，不代表当前生产状态。

演示讲解页：在 BUILD 根目录运行 `python scripts/demo_html.py`，一键生成 `validation/skill_demo.html`。该脚本只读取最新的 `生产产物/数据库.parquet` 中 `data_version=7.4.0` 的 `research_digest`，不读取凭证、不连接 Panda Data、不触发扫描；可用 `--production-path` 和 `--output` 指向其他已有快照。录制讲解按 `validation/录制讲稿.md`，重点展示研究候选、独立风险观察和承保边界。

## 跨运行时使用

- Codex 与 Claude Code：直接加载本目录的 `SKILL.md`；技能名为 `$klarman-special-situations`。
- Cursor：把完整目录安装到 `.cursor/skills/klarman-special-situations`，使用 `agents/cursor-rule.mdc` 作为项目规则入口。
- Hermes 与 OpenClaw：优先从各自的 Skill 目录加载完整文件夹；不支持原生发现时，使用 `agents/portable-loader.md` 作为加载提示。
- OpenAI/Codex 界面元数据位于 `agents/openai.yaml`。调整触发词、工作流或风险边界时，同步维护所有运行时入口。

## 依赖

- Panda Data（`panda_data==0.0.12`）
- numpy、pandas、pyyaml
- 项目指定数据源：如接口权限或字段口径不明确，咨询项目工作人员

## 参考

- [API 与承保口径](references/api_guide.md)
