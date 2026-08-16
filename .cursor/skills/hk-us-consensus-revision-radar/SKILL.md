---
name: skill-hk-us-consensus-revision-radar
description: "Use when a user wants an auditable Hong Kong or US equity consensus revision radar: compare target-price and recommendation changes across five horizons, inspect the revision trajectory matrix and rule-based consensus state machine, and produce a standalone offline HTML research report using PandaData only. Do not use for ETFs, daily snapshots, scheduling, trade execution, buy/sell instructions, or return forecasts."
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-hk-us-consensus-revision-radar
  repository_url: https://github.com/quantskills/skill-hk-us-consensus-revision-radar
  project_type: skill
  collection: consensus-intelligence
  status: community-project-unreviewed
  license: GPL-3.0-only
---

# HK/US Consensus Revision Radar: Trajectory Matrix & State Machine

Generate an auditable, standalone HTML **consensus revision radar** for Hong Kong and US equities. The core output is not a point-in-time consensus snapshot: it reconstructs five-horizon aggregate revision trajectories, organizes them into a searchable revision trajectory matrix, and explains each security through a rule-based consensus state machine. All raw market and consensus data must come from PandaData. Derived metrics are deterministic calculations documented in [references/methodology.md](references/methodology.md).

## Required first step: authenticate

At the beginning of every invocation, before any PandaData query:

1. Use `PANDADATA_USERNAME` and `PANDADATA_PASSWORD` when both exist in the current process environment; this is optional automation support, not a beginner prerequisite.
2. A normal terminal run in a desktop-capable session can use the visible platform login window (PowerShell or Terminal helper) automatically when either value is missing; never leave the parent Codex/terminal process waiting for credential input.
3. A non-TTY caller must stop before authentication or data access unless it has intentionally requested `--desktop-login-window` from a GUI-capable desktop host. This flag represents caller intent only: process creation only means the window was requested, not that it is visible. Restricted or background hosts can suppress the helper window as a host limitation rather than an authentication failure.
4. Never request or accept a password in chat, screenshots, CLI arguments, files, logs, or report content.
5. Normalize only an 11-digit mainland mobile username by adding the `86` prefix; preserve an already-prefixed or non-mobile username unchanged.
6. Call the bundled authentication adapter so the PandaData SDK keeps authentication state only in process memory and does not create `user.json`. When a local login helper is used, transfer only its verified short-lived session token to the parent process over the authenticated loopback relay; never transfer the password back or issue a second login request.
7. Clear the in-memory authentication state when the run finishes or fails.

## Workflow

1. Confirm the requested market (`hk`, `us`, or both), optional symbols, horizon, target-price coverage threshold, recommendation coverage threshold, and output directory. Defaults are both markets, full supported universe, `1month`, 5 target-price estimates, 5 recommendations, and `output/`. When a user only asks to execute the Skill from desktop Codex / non-TTY, use the same defaults and explicitly add `--desktop-login-window` so the local login window is requested.
2. Authenticate as the first external action.
3. Read [references/pandadata-api-map.md](references/pandadata-api-map.md), call only the listed PandaData interfaces, and request only required fields.
4. Resolve security identity, status, asset category, and industry fields from `get_hk_detail` or `get_us_detail`. Only confirmed active ordinary shares enter the core ranking universe. Retain ETFs, funds, warrants, preferred shares, debt/derivative securities, inactive securities, and unknown types in diagnostics with an explicit exclusion reason. Every visible security identity uses `name · symbol`; when a name is unavailable, show the symbol and disclose the gap.
5. Keep only `TP` rows from normalized cyclic consensus and join recommendation consensus. Query the requested latest trading day first, then query every symbol whose returned close is missing, nonnumeric, or nonpositive over the preceding 14 calendar days. This fallback is per symbol and must run regardless of the overall match rate. Retain the latest valid returned close per symbol, preserve unresolved missing values, and expose fallback diagnostics and missing reasons.
6. Compute current-versus-selected-horizon target and recommendation evidence according to [references/methodology.md](references/methodology.md), using the configurable `revision_threshold`. Record each market's consensus retrieval completion time, but keep the consensus business date unavailable because the mapped PandaData responses do not provide one. Calculate current-versus-historical estimate-count changes and flag them only when both the absolute and relative thresholds are met. Validate target ranges, included-versus-total estimate counts, recommendation bucket totals, current and historical recommendation mean ranges, and currency comparability without overwriting PandaData values. Price divergence requires target currency to match the market's standard quote currency; otherwise keep it unavailable and perform no inferred conversion. Never convert the evidence into a composite buy/sell score.
7. Rank Hong Kong and US securities separately. Target-price rankings require `estimates_num >= min_analysts`; recommendation-change rankings independently require `recommendations_num >= min_recommendations`. Preserve excluded rows in data-quality counts, and exclude a validation error only from rankings that depend on the affected evidence.
8. Derive the event scope from the explicit symbols and all security symbols present in rankings and then resolve the event reference date.
9. Query event interfaces for the selected market only after ranking scope exists and authentication is complete. Use `--event-past-days`, `--event-future-days`, and `--event-discovery-days` for boundary control. The mapped interfaces are `get_stock_dividend_event`, `get_stock_market_event`, `get_stock_meeting_event`, `get_stock_financial_event`, `get_stock_ir_event`, and `get_stock_dividend_activity`, `get_stock_market_activity`, `get_stock_meeting_activity`, `get_stock_financial_activity`, `get_stock_ir_activity`. The discovery window is based on announcement date, and execution status uses execution date / effective date fields. Normalize and validate event rows, deduplicate by identity fields, and attach per-interface status/attempt diagnostics plus coverage counters; query only the mapped five event interfaces in `references/pandadata-api-map.md`.
10. Event signals are context only and must not modify ranking order (does not affect ranking). If any event interface is partial/failed, continue with available interfaces and mark event availability accordingly.
11. Render one timestamped standalone HTML file and `latest.html`. The page must contain no external CDN dependency, credential data, or remote data request.
12. In the final chat handoff, report the HTML path, selected parameters, Hong Kong and US price match rates, whether the 14-day price fallback ran, missing/excluded/validation counts, event-context availability and windows, and important limitations. State PandaData gaps explicitly; never infer or repair missing values.

Run from the repository root:

```powershell
python -m scripts.run_report --market both --horizon 1month --min-analysts 5 --min-recommendations 5 --desktop-login-window
```

If credentials are absent, a normal terminal run can use the visible PowerShell window on Windows or Terminal on macOS automatically. A non-TTY caller must stop unless it intentionally requests `--desktop-login-window` from a GUI-capable desktop host. Enter both values only in that local window; password input is hidden. Do not send credentials through the conversation. Process creation only means the window was requested, not that it is visible. Use `--no-login-window` only for unattended environments where a visible login window is not allowed.

On macOS, a normal launch opens Terminal automatically. If starting manually, change to the Skill directory and run the same workflow with `python3`:

```bash
cd "/path/to/skill-hk-us-consensus-revision-radar"
python3 -m scripts.run_report --market both --horizon 1month --min-analysts 5 --min-recommendations 5
```

When the Terminal window opens, type the username and press Return. Type the password and press Return; macOS shows no password characters or placeholder dots. The password is held only in process memory and is cleared after the run.

If PandaData returns an authentication failure, the login window must display a clear authentication failure message and immediately prompt the user to re-enter both the username and password. Do not reuse either value from the failed attempt, echo or persist the password, and continue retrying until authentication succeeds or the user cancels/closes the prompt.
After credentials are submitted, the local login window must immediately show that PandaData login is in progress, then clearly show success or failure. On success, it must transfer only a verified short-lived session token to the parent process over the authenticated local relay; the parent must reuse that session without re-entering the password or calling the login endpoint again. On failure, show that both credentials must be re-entered. The main Codex/terminal process receives the remaining progress events for each market's consensus/price/name collection, analysis, report writing, and final output path. Keep credentials and tokens in process memory and flush progress messages immediately so a slow API call never appears frozen.

For a focused sample:

```powershell
python -m scripts.run_report --market both --symbols 0700.HK,9988.HK,AAPL,NVDA
```

```powershell
python -m scripts.run_report --market both --symbols 0700.HK,9988.HK,AAPL,NVDA --event-past-days 30 --event-future-days 30 --event-discovery-days 730 --no-events
```

## Output contract

The HTML report must include:

- a key-findings brief before charts, covering the largest upgrade, downgrade, analyst dispersion, and recommendation change;
- a clear positioning note that distinguishes this revision radar from a point-in-time consensus report: cross-horizon trajectory, state interpretation, and offline auditability are the primary deliverables;
- a data-completeness block at the end of the report whenever PandaData price, historical, name, recommendation, or analyst-coverage inputs are missing;
- the data-completeness block is collapsed by default (`collapsed by default`) with a keyboard-accessible disclosure control; basic disclosure remains available when JavaScript is unavailable (`JavaScript is unavailable`);
- restrained motion for view changes and numeric emphasis, with a `reduced-motion` fallback;
- generation time, market, horizon, separate target/recommendation coverage thresholds, and PandaData interface provenance;
- a time-basis disclosure that separates report generation time, per-market consensus retrieval time, and the unavailable PandaData consensus business date; current values must be labeled as the `PandaData latest available snapshot`, never as values updated at retrieval time;
- market-separated overview and search;
- the revision trajectory matrix with case-insensitive contains search (`case-insensitive contains search`) by security name or symbol; the individual-security interpretation reuses the current market's `trajectory_matrix` data rather than issuing a separate or cross-market query;
- ranking tables must show the revision, price-distance, dispersion, coverage, historical target-price mean, current target-price mean, and latest close fields, plus the formulas used to calculate them;
- the individual-security interpretation panel must appear as a prominent full-width section directly below the ranking table;
- event enrichment is for interpretation only and must not change ranking output (does not affect ranking);
- target-price upgrades and downgrades, high dispersion, recommendation change, and price-consensus divergence;
- a single-security detail card;
- `name · symbol` everywhere a security code is shown;
- per-security target evidence, recommendation evidence, latest-close evidence, and coverage diagnostics;
- per-security current-versus-historical total/included estimate-count changes, with a significant-change note only when `abs(change) >= 2` and `abs(change_ratio) >= 20%`;
- chained target-revision and rating-change eligibility funnels, with each stage's count and retention versus the previous stage; the final counts must match the actual dependent ranking pools;
- total, core-universe, universe-excluded, target-eligible, rating-eligible, missing-coverage, low-coverage, missing-data and validation counts, classified price/universe reasons, price match rate, and 14 calendar days fallback status; the CLI and HTML must disclose these gaps explicitly, and missing values must remain missing;
- formulas, `revision_threshold`, direction rules, assumptions, known limitations, and risk boundaries;
- an explicit statement that PandaData supplies aggregate consensus here, so analyst-level revision breadth is unavailable and must not be inferred;
- an explicit Community Project and research/education-only disclaimer.

## Parameters

- `--market`: `hk`, `us`, or `both`; default `both`.
- `--symbols`: comma-separated symbols; `.HK` routes to Hong Kong when both markets are selected.
- `--horizon`: `week`, `1month`, `3month`, `6month`, or `12month`; default `1month`.
- `--min-analysts`: minimum target-price estimate coverage; default `5`.
- `--min-recommendations`: minimum recommendation coverage for the rating-change ranking; default `5`.
- `--revision-threshold`: minimum absolute target-price change classified as an upgrade or downgrade; default `0.01` (1%).
- `--ranking-limit`: rows per ranking; default `20`.
- `--start-date`, `--end-date`: optional `YYYYMMDD` price query window.
- `--event-past-days`: include events in the display window `event_reference_date - event_past_days`.
- `--event-future-days`: include events in the display window `event_reference_date + event_future_days`.
- `--event-discovery-days`: announcement discovery back-search window in days (default `730`).
- `--no-events`: disable event context queries and only return rankings.
- `--output-dir`: report directory; default `output/`.

## Guardrails and known limitations

- Supported ranking scope is confirmed active ordinary shares listed in Hong Kong and the US with PandaData consensus coverage. Other security types and unknown identities are retained only for diagnostics; ETF-specific analysis is intentionally excluded.
- No daily snapshot, history database, scheduler, alert, or unattended recurring job is created.
- The mapped PandaData consensus responses do not expose a concrete `date`, `as_of`, or `updated_at` for the current aggregate target-price value. Display the retrieval time only as retrieval evidence, keep the consensus business date unavailable, display the returned price date separately, and do not describe the report as real-time.
- The mapped consensus interfaces provide aggregate consensus, not broker/analyst-level revision events. Do not calculate or imply revision breadth, revision timing, or analyst hit rate.
- Missing values remain missing. Zero denominators do not produce ratios. Never render missing numeric values as zero.
- PandaData contradictions are tagged, never silently repaired. Severe target/rating validation failures affect only dependent rankings; recommendation bucket-count mismatches are warnings because contributor-count definitions can differ.
- Analyst consensus can be stale, sparse, biased, or revised after market moves. Cross-market values are not currency-normalized.
- Corporate actions, FX, liquidity, transaction costs, tax, and execution feasibility are outside scope.
- Do not emit target entries, position sizes, stop losses, profit promises, or investment advice.

## Maintenance and project status

Maintained by community contributors through the repository issue and review process. This is an unreviewed QuantSkills Community Project. It has not been reviewed, endorsed, or approved for production use by QuantSkills. It is provided only for research and education.
## Report provenance and security visuals
- The end-of-report data-completeness block must identify PandaData as the exclusive raw-data source and list the actual interfaces called for the selected market, including each interface purpose.
- The interface provenance must cover security detail, target-price consensus, recommendation consensus, daily close, and get_last_trade_date when it was called.
- The individual-security interpretation must include an offline target-price positioning chart and recommendation-distribution chart when the corresponding PandaData fields are available.
- Charts must preserve missing values, label their source as PandaData aggregate consensus, use no CDN or external network resource, and never imply an investment instruction.

## 修订轨迹与状态解读

- 本 Skill 的重点是将多个回看期的聚合一致预期变化组织为“修订轨迹矩阵 + 一致预期状态机 + 可审计离线 HTML”，而不是只展示某一时点的评级或目标价快照。
- 报告按周度、1个月、3个月、6个月、12个月展示目标价与评级的五个回看期；每个轨迹单元格同时显示符号、数值和方向文字，缺失值为 `—`。
- 八种规则化状态为：持续上修、上修加速、上修减速、趋势反转待核验、目标价与评级共振改善、目标价与评级信号冲突、高分歧待核验、覆盖变化待核验。状态只用于解读，不改变榜单排序，不是分析师个人修订，也不构成投资建议。
- 评级均值越低代表评级更积极（绝对水平）。评级变化公式为“历史评级均值 − 当前评级均值”；历史评级均值 − 当前评级均值越大代表评级改善/更积极（变化）。高分歧以有效核心样本 P75 为阈值；覆盖变化沿用既有绝对变化不少于 2 且变化率不少于 20% 的规则。
- PandaData 聚合数据不提供精确历史时间戳或个人分析师信息；因此状态 evidence 只能说明聚合证据，不能推断个人修订、修订时间或分析师广度。
