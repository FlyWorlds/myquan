---
name: qbti
description: QBTI (Quant Behavior Type Indicator, 量化行为类型指标) turns a non-professional
  user's investing personality into concrete factor directions and strategy parameters
  through a fun five-part quiz, then hands off to the QuantSkills factor libraries and
  backtest pipeline with plain-language explanations. Use when a retail user says
  我不懂量化但想试试 / 帮我做一个适合我的策略 / 我是小白该怎么开始 / 给我做个QBTI / 来一个投资版性格测试,
  when an agent needs to elicit risk tolerance, involvement level, factor taste, sector
  preferences, and time horizon from the end user before touching any factor skill, or
  when translating quiz answers into profile.json and strategy_brief.json for downstream
  evaluation and backtesting on portable agent platforms such as Claude Code, Codex, or
  OpenClaw.
license: GPL-3.0-only
compatibility: Requires Python 3.10+ to run scripts/derive_profile.py (uv recommended,
  e.g. `uv run scripts/derive_profile.py`). Pure stdlib, no third-party dependencies,
  no network access needed.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-qbti
  repository_url: https://github.com/quantskills/skill-qbti
  project_type: skill
  collection: beginner-onboarding
  license: GPL-3.0
  category: trader-research
  tags:
  - qbti
  - beginner-friendly
  - personalization
  - factor-selection
  - risk-profile
  - a-share
  - onboarding
  platforms:
  - claude-code
  - codex
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires:
  - skill-quant-factor-directional-alpha
  - skill-quant-factor-risk-pattern-alpha
  - skill-backtest
  summary_zh: QBTI 量化行为类型指标：五组趣味问答了解普通人的投资性格，按固定规则表翻译成因子方向与策略参数，再交给因子库和回测流水线，全程大白话解释。
  summary_en: 'QBTI (Quant Behavior Type Indicator): a personality-style quiz that translates
    a retail user''s investing preferences into factor directions and strategy parameters
    via a fixed rule table, then hands off to the QuantSkills backtest pipeline.'
---

# QBTI — Quant Behavior Type Indicator / 量化行为类型指标

Use this skill to walk a non-professional user from "我不懂量化" to a personalized, backtested starting strategy — think of it as an investing-flavored personality quiz (a playful homage to MBTI-style tests; QBTI is an independent community project with no affiliation to the Myers-Briggs Company). The skill is a **translation front door**: a fun five-part quiz elicits the user's investing personality, a fixed rule table (`references/preference_mapping.yaml`) deterministically translates answers into factor directions and strategy parameters, and the existing QuantSkills pipeline does the heavy lifting. The quiz is a UX device for eliciting standard research parameters, not a psychometric assessment.

**Wording rule (mandatory):** this skill *translates* preferences into parameters; it never *recommends*. Say 「我把你的回答翻译成了一组参数」, never 「我们为你推荐了以下策略」. Hedge all interpretation: 可能提示 / 需要关注, never buy/sell instructions.

## Core Workflow

1. Open with the framing.
   - Explain in one short paragraph: this is a research/education tool that translates your preferences into parameters for a historical research pipeline — not a robo-advisor, not investment advice.
   - If the user just wants a stock tip, stop and say this skill does not do that.

2. Run the quiz.
   - Cover the five dimensions in `references/question_bank.md` in order (A 亏损反应 → B 参与度 → C 策略口味 → D 选股范围 → E 时间周期).
   - **The framing is yours; the enums are not.** Pick metaphors that fit this user's interests — pets, football, gaming, cooking, anything (the question bank's 示例包装 are examples, not scripts). If a metaphor doesn't land, switch or ask plainly. What is fixed: every answer must be classified onto one of the closed enum values via the dimension's 语义锚点 column, and the classification must be confirmed with the user.
   - Never let free text flow into the answer fields directly; classify it, then confirm.
   - A refused question takes the documented default and must be disclosed later via `defaults_used`.

3. Restate and confirm.
   - Use the 复述确认模板 at the end of `references/question_bank.md`: replay every derived field in plain language, read out every consistency flag, and ask the user to correct anything that feels wrong.
   - Only when the user explicitly confirms, set `user_confirmed: true` in the answers JSON. Do not proceed without it.

4. Run the deterministic translation.
   - `uv run scripts/derive_profile.py --answers <answers.json> --out <run_dir>` (or plain `python` if uv is unavailable — the script is pure stdlib either way)
   - This produces `profile.json` (the durable preference profile) and, when confirmed, `strategy_brief.json` (the pipeline handoff parameters). The script is pure stdlib, offline, and does exactly what `references/preference_mapping.yaml` says — no improvisation. Field semantics are documented in `references/profile_schema.md`.
   - **Show the disclaimer from `references/disclaimer_template.md` now, before presenting any factor direction.**

5. Pick candidate factors from the pre-built libraries.
   - Use `strategy_brief.json`'s `candidate_factor_pools` + `factor_family_tags` to select a handful of candidate factors from the QuantSkills factor libraries (`skill-quant-factor-directional-alpha`, `skill-quant-factor-risk-pattern-alpha`, and optionally `skill-quant-factor-volume-stat-alpha`).
   - This is a lookup, not factor mining. Do not invent new factor formulas here; users who want bespoke factors should graduate to `skill-factor-mine`.

6. Evaluate the candidates (recommended).
   - Hand the candidates to `skill-factor-evaluate` / `skill-ic-analysis`, using `target_holding_period_days` as the forward-return horizon and respecting `turnover_tolerance`.

7. Backtest with the user's constraints.
   - Hand off to `skill-backtest` with `universe_filters`, `position_constraints`, and `rebalance_frequency` from `strategy_brief.json`. Keep the standard protocol (T+1 open, costs, limit-up/suspension exclusion) — do not weaken it to make results look better.

8. Explain every chart and metric in plain language.
   - For each chart/metric in the results, write a block with exactly these five sub-headers (the `skill-report-replication` convention): `这张图回答什么问题` / `怎么看` / `我们看到了什么` / `这意味着什么` / `数据来源`.
   - Target a reader who has never seen an IC curve or a drawdown chart. Define every term the first time it appears.

9. Produce the final report and attach the disclaimer.
   - Write `qbti_report.md`: the profile in plain language, the candidate factors and why they match the profile, the backtest results with the five-sub-header explainers, known limitations, and the full disclaimer from `references/disclaimer_template.md` verbatim at the end.

10. Offer next steps as opt-in, never automatic.
    - Suggest, without invoking: `skill-factor-blend` (2+ 个评价过的因子想合成时), `skill-portfolio-optimize` (想做更精细的仓位分散时), `skill-backtest-overfit` (在把结果当真之前的统计体检 — strongly encouraged phrasing: 「在你把这当作真实交易依据之前，建议先跑一遍过拟合检查」), and `agent-market-regime-monitor` / `skill-event-risk-alert` when `wants_monitor_skill` is true.

## Interpretation Rules

- The mapping table is the single source of truth. If the user's situation genuinely doesn't fit any enum, say so and stop — do not free-style a mapping.
- Never move a user toward more aggressive parameters than their answers produced. Toward more conservative is always allowed with disclosure.
- Every default and every consistency flag must be surfaced to the user in the confirmation step; nothing is silently resolved.
- Backtest numbers are historical simulation under stated assumptions. Present them with the assumptions attached, never as expected future returns.
- This skill covers A-share research workflows by default (the factor libraries and backtest protocol it hands off to are A-share oriented).

## Output Contract

A completed run produces:

- `profile.json`: the structured preference profile (durable, reusable across sessions).
- `strategy_brief.json`: pipeline handoff parameters for downstream skills.
- `qbti_report.md`: plain-language report with the five-sub-header explainer blocks and the verbatim disclaimer.
- Pass-through artifacts (NAV curve, diagnostic charts) belong to `skill-backtest` and are referenced, not duplicated.

## Boundaries

- 只翻译，不推荐：output is parameter translation and factual explanation, never investment advice.
- No real-money claims: the skill never predicts returns, never says a strategy is safe or guaranteed.
- Research/education only; see `references/disclaimer_template.md` for the full statement shown to users twice per run.
