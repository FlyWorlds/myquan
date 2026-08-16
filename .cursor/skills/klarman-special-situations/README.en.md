# Klarman Special Situations Skill

[简体中文](README.md) | **English**

> An A-share event-driven research skill based on Seth Klarman's special-situations framework. It turns private-placement unlocks, restructurings and backdoor listings, spin-offs, and distressed turnarounds into traceable research tasks with explicit evidence gaps and risk boundaries.

**Creator / Maintainer**: [`dijia702`](https://github.com/dijia702)<br>
**Project status**: QuantSkills Community Project. It is not official, certified, verified, endorsed, or approved for live trading unless community maintainers explicitly state otherwise.

## What This Skill Does

`skill-klarman-special-situations` separates three layers that must not be conflated:

1. **Research priority**: ranks up to five events worth investigating next, with transparent score components, reasons, missing evidence, and follow-up actions.
2. **Independent risk watchlist**: lists up to five supply, audit, financial, or distress risks. Private-placement unlocks belong here rather than in the opportunity shortlist.
3. **Strict underwriting**: checks the tradable security, catalyst, transaction terms, conservative value, failure value, capital structure, legal and audit evidence, liquidity, and margin of safety. A missing or failed core gate cannot be offset by a high research score.

Every research card carries `not_trade_signal=true`. Only an original event record with `qualified_special_situation` may be consumed by a downstream Alpha workflow, subject to its own risk and compliance controls.

## Supported Scenarios

| Scenario | Research question | Primary Panda Data methods | Boundary |
|---|---|---|---|
| Private-placement unlock | Could the unlock create supply pressure, and how many average trading days might be needed to absorb it? | `get_stock_private_placement`, `get_restricted_list`, `get_share_float`, `get_stock_daily` | Supply-risk watch only. The placement price and participant gain are not a secondary-market margin of safety. |
| Restructuring / backdoor listing | Is there a verifiable regulatory catalyst, unique security mapping, complete transaction terms, and defensible failure value? | `get_stock_csrc_approval`; `get_stock_material_contract` as context only | Every card warns that failure pressure is at least 30%; terms, approvals, financing, legal risk, and failure value still require evidence. |
| Spin-off listing | Does the parent's retained stake, subsidiary value, remaining business, debt, tax, dilution, and holding-company discount support a conservative SOTP view? | `get_stock_csrc_approval`, `get_stock_detail` | Contract value does not substitute for subsidiary valuation. Missing mapping or valuation evidence blocks qualification. |
| Distressed turnaround | Have warning status, financial quality, audit quality, and recovery priority improved substantively? | `get_stock_status_change`, `get_fina_reports`, `get_audit_opinion` | Warning removal, positive earnings, or a clean audit is only a research entry point, not complete underwriting. |

## Research Output

The callable entry point is `run(input_data, config=None)` from `scripts.build`:

```python
from scripts.build import run

result = run(
    {"as_of_date": "20260724", "start_date": "20250724"},
    config={"evidence_dir": r"<official-announcement-evidence>", "materialize": False},
)

shortlist = result["research_digest"]["shortlist"]
risks = result["research_digest"]["risk_watchlist"]
```

The response includes:

| Field | Meaning |
|---|---|
| `research_digest.shortlist` | Up to five research candidates, no padding below the score threshold, all marked `not_trade_signal=true` |
| `research_digest.risk_watchlist` | Up to five independent risk observations, all marked `not_trade_signal=true` |
| `excluded_summary` | Counts and reasons for excluded events, such as missing price, low score, missing mapping, or category caps |
| `unmapped_event_count` | Regulatory events that could not be mapped to a unique listed security |
| `records` | Raw events, coverage gaps, scan summaries, and the aggregated research digest |
| `production_path` | Optional Parquet path returned only when materialization is enabled |

The real-time digest uses the latest public evidence available on or before the decision date. Historical replay uses only evidence visible on the event date. These two evidence clocks are stored separately and must never be mixed.

## `get_restricted_list` Quota Degradation

`get_restricted_list` is required to identify unlock dates, quantities, and supply pressure. Some Panda Data plans may intermittently return quota or rate-limit errors. Such an error does **not** mean that no unlock exists.

- Classify matching errors as `quota_or_rate_limit` and use bounded retry through `max_api_attempts` (1-4 attempts, default 2).
- After retries are exhausted, set `source.capabilities.get_restricted_list.status=unavailable` and emit a `coverage_gap` record with `result_value=insufficient_evidence`.
- Do not create or refresh `private_placement_supply_risk` cards from missing unlock evidence.
- Mark `research_digest` as partial coverage and disclose the gap in the P4 health report.
- Continue other event families only with an explicit statement that unlock coverage is incomplete.
- Do not switch to an unapproved source, fill missing values with zero, or merge an old snapshot into the current decision date.
- After quota access is restored, rerun the complete point-in-time scan for the same decision date.

## Quick Start

Install the complete repository so that `SKILL.md`, `scripts/`, `references/`, and `agents/` remain together:

```bash
# Codex / Agent Skills
mkdir -p ~/.agents/skills
cp -r skill-klarman-special-situations ~/.agents/skills/klarman-special-situations

# Claude Code
mkdir -p ~/.claude/skills
cp -r skill-klarman-special-situations ~/.claude/skills/klarman-special-situations

# Cursor project skill
mkdir -p .cursor/skills
cp -r skill-klarman-special-situations .cursor/skills/klarman-special-situations
```

Example requests:

```text
Scan the last year of A-share special situations and return the research shortlist and independent risk watchlist.
Explain the private-placement unlock pressure in today's risk watchlist and list the missing supply and liquidity evidence.
Underwrite this restructuring in the Klarman style: identify missing facts first and do not give trading advice.
Review a warning-status removal as a distressed-turnaround event and explain why it is not yet fully underwritten.
```

Panda Data credentials must be supplied only through the local process environment. Never place usernames, passwords, tokens, or raw server error text in code, documentation, logs, or the repository.

## Runtime Adapters

| Runtime | Entry point |
|---|---|
| Codex / Claude Code | Load the root `SKILL.md` directly as `$klarman-special-situations` |
| Cursor | Install under `.cursor/skills/klarman-special-situations` and use `agents/cursor-rule.mdc` |
| Hermes / OpenClaw | Load the complete skill folder; use `agents/portable-loader.md` when native discovery is unavailable |
| OpenAI / Codex UI | Read display metadata from `agents/openai.yaml` |

Keep all adapters aligned whenever triggers, workflows, output contracts, or investment-risk guardrails change.

## Data, Assumptions, and Limitations

- Data source: Panda Data structured interfaces plus caller-supplied official announcement evidence.
- Coverage: A-share long-only cash-equity research. It does not assume short selling, hedge legs, or derivatives.
- Parameters: candidate score threshold 60; at most five candidates overall, three per category, and five independent risk observations.
- Data availability, mapping, corporate actions, audit evidence, and liquidity can be missing, delayed, revised, or plan-dependent.
- Research ranking is a workflow priority, not a buy or sell signal. The project provides no return promise, position size, win-rate claim, or personalized investment advice.

## Repository Layout

```text
skill-klarman-special-situations/
|-- SKILL.md
|-- README.md
|-- README.en.md
|-- LICENSE
|-- skill.json
|-- skill.yml
|-- agents/
|   |-- openai.yaml
|   |-- cursor-rule.mdc
|   `-- portable-loader.md
|-- scripts/
|-- references/
|-- validation/
|-- 开发产物/
`-- 生产产物/
```

## License

This project is licensed under the GNU General Public License v3.0, SPDX identifier `GPL-3.0-only`. See [LICENSE](LICENSE).

## Disclaimer

All outputs are generated from public data, official announcement evidence, and rule-based analysis for research, education, review, and system integration only. Nothing in this repository constitutes investment advice. Special-situation events may have high failure, liquidity, legal, and information risks; users remain responsible for independent valuation, portfolio, risk, and compliance decisions.
