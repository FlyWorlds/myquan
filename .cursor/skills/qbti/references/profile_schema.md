# profile.json / strategy_brief.json 字段文档（schema_version: 1.0）

两个文件均由 `scripts/derive_profile.py` 确定性生成。范式沿用 `skill-portfolio-checkup` 的 profile 惯例：**显式默认值 + 显式披露**——凡是用了默认值、触发了一致性提示，都必须出现在对应数组里，不允许静默兜底。

## profile.json —— 用户偏好画像（跨会话可复用）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 固定 `"1.0"` |
| `quiz_version` | string | 问题库版本，对应 `question_bank.md` 头部声明 |
| `mapping_version` | string | 映射表版本，对应 `preference_mapping.yaml` 头部声明 |
| `generated_at` | string (ISO 8601) | 生成时间 |
| `answers` | object | 五簇原始答案，全部为 question_bank.md 定义的枚举值（见下表） |
| `derived` | object | 映射表推导出的参数（见下表） |
| `defaults_used` | array | 每项 `{field, default_value, reason}`；用户拒答/未触及的字段必须记录在此 |
| `consistency_flags` | array | 每项 `{id, message}`；跨簇矛盾提示，复述确认环节必须逐条向用户念出 |
| `user_confirmed` | bool | 复述确认通过后才置 `true`；为 `false` 时**不得**生成 strategy_brief.json |

### `answers` 字段

| 字段 | 合法枚举 |
| --- | --- |
| `cluster_a_loss_reaction` | `cant_sleep_sell_now` / `uncomfortable_but_check_first` / `stick_to_plan` / `discount_buy_more` |
| `cluster_b_involvement` | `daily_hands_on` / `weekly_check_in` / `monthly_glance` / `quarterly_set_forget` |
| `cluster_c_taste` | `ride_the_trend` / `hunt_the_overlooked` / `steady_and_boring` / `bet_on_reversal` |
| `cluster_c_taste_secondary` | 同上，可为 `null`（用户只选一个口味时） |
| `cluster_c_volatility_stance` | `stresses_me_out` / `neutral` / `energizes_me` |
| `cluster_d_universe_style` | `familiar_only` / `explorer_no_limit` / `has_exclusions` |
| `cluster_d_preferred_sectors` | `sector_enum` 数组（仅 `familiar_only` 时必填，否则 `[]`） |
| `cluster_d_excluded_sectors` | `sector_enum` 数组（仅 `has_exclusions` 时必填，否则 `[]`） |
| `cluster_d_exclude_st` | bool |
| `cluster_e_time_capsule` | `next_month` / `year_end` / `few_years` / `decade_plus` |

### `derived` 字段

| 字段 | 类型/枚举 | 来源 |
| --- | --- | --- |
| `risk_tolerance` | `conservative` / `cautious` / `balanced` / `aggressive` | cluster_a |
| `stop_loss_discipline` | `hard_stop_tight` / `hard_stop_wide` / `soft_review` / `none_ride_through` | cluster_a |
| `max_position_pct` | int (5–15) | cluster_a |
| `involvement_level` | `daily` / `weekly` / `monthly` / `quarterly` | cluster_b |
| `rebalance_frequency` | `weekly` / `biweekly` / `monthly` / `quarterly` | cluster_b |
| `wants_monitor_skill` | bool | cluster_b |
| `factor_affinity` | array，元素 ∈ `momentum` / `reversal` / `mean_reversion` / `low_volatility` / `quality_stable`，长度 1–3 | cluster_c（主选+备选+波动调节注入） |
| `volatility_stance` | `stresses_me_out` / `neutral` / `energizes_me` | cluster_c 追问 |
| `sector_preference_mode` | `familiar_only` / `explorer_no_limit` / `has_exclusions` | cluster_d |
| `preferred_sectors` | `sector_enum` 数组 | cluster_d 追问 |
| `excluded_sectors` | `sector_enum` 数组 | cluster_d 追问 |
| `exclude_st_and_risk_flags` | bool（默认 true） | cluster_d 固定追问 |
| `time_horizon` | `short` / `medium` / `long` / `very_long` | cluster_e |
| `target_holding_period_days` | int (20–250 交易日) | cluster_e |
| `turnover_tolerance` | `low` / `medium` / `high` | cluster_e |

## strategy_brief.json —— 流水线交接参数（供下游 skill 消费）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 固定 `"1.0"` |
| `source_profile` | string | 生成本文件所用的 profile.json 路径 |
| `candidate_factor_pools` | array | 去重后的因子库仓库名（`factor_family_pools` 查表） |
| `factor_family_tags` | array | 在因子池内筛选候选因子用的家族标签 |
| `universe_filters` | object | `{preferred_sectors, excluded_sectors, exclude_st_and_risk_flags}` |
| `position_constraints` | object | `{max_position_pct, stop_loss_discipline}` |
| `rebalance_frequency` | string | 同 derived |
| `target_holding_period_days` | int | 同 derived |
| `recommended_next_skills` | array | 固定为 `["skill-factor-evaluate", "skill-backtest", "skill-backtest-overfit"]`——**顺序即推荐执行顺序** |

## 消费方对照

| 下游 | 消费的字段 |
| --- | --- |
| 因子库（`skill-quant-factor-*-alpha`） | `candidate_factor_pools` + `factor_family_tags` 选候选因子 |
| `skill-factor-evaluate` / `skill-ic-analysis` | `target_holding_period_days`（评价的前向收益期限）、`turnover_tolerance` |
| `skill-backtest` | `universe_filters`、`position_constraints`、`rebalance_frequency` |
| `skill-portfolio-optimize`（可选进阶） | `max_position_pct` → 权重上限约束；`risk_tolerance` → 风险厌恶系数档位 |
