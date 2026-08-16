# HK/US Consensus Revision Radar: Trajectory Matrix & State Machine

A QuantSkills Community Project powered by **PandaData**. Its focus is not a point-in-time consensus snapshot: it turns Hong Kong and US target-price and recommendation changes into a **consensus revision radar** with a five-horizon Revision Trajectory Matrix, a rule-based Consensus State Machine, and an auditable offline HTML research report.

> This project has not been reviewed or endorsed by QuantSkills. It is for research and education only, is not investment advice, and does not provide trade instructions, return promises, or position recommendations.

中文说明：[README.md](README.md)

## Core capabilities

- **Revision-radar positioning**: prioritize cross-horizon target-price and recommendation changes instead of merely listing current ratings, targets, or upside.
- **Revision Trajectory Matrix**: place weekly, 1/3/6/12-month target-price and recommendation changes in one searchable matrix to surface persistent upgrades, deceleration, reversals, and conflicting signals.
- **Consensus State Machine**: interpret aggregate evidence through states such as persistent upgrade, accelerating upgrade, target-price/recommendation resonance, and high-dispersion review. States do not alter rankings and do not represent individual analyst actions.
- **Auditable HTML delivery**: package actual interfaces, time basis, formulas, eligibility funnels, missing values, validations, and limitations into a single offline file that can be reviewed without network access.
- Collect, calculate, and rank Hong Kong and US securities separately across `week`, `1month`, `3month`, `6month`, and `12month` horizons.
- Produce target-price upgrade/downgrade, high-dispersion, recommendation-change, and price-versus-consensus divergence rankings with documented calculations.
- Provide a **Revision Trajectory Matrix** showing target-price and recommendation changes, values, and directions over five lookback horizons; search by security name or symbol.
- Provide security interpretation with target-price positioning, recommendation distribution, target-price and recommendation trajectories, rule-based consensus states, and relevant event context.
- Admit only PandaData-confirmed active ordinary shares to the core rankings; retain ETFs, preferred shares, warrants, inactive, and uncertain identities in diagnostics with explicit exclusion reasons.
- Produce a self-contained offline HTML file with no CDN, remote requests, or credentials. The end-of-report data-completeness section is collapsed by default and can be expanded on demand.

## Quick start

Requirements: Python 3.10+, a usable PandaData account, and network access to PandaData.

```powershell
python -m pip install -r requirements.txt
python -m scripts.run_report --market both --horizon 1month --min-analysts 5 --min-recommendations 5
```

Reports are written to `output/` by default:

- `consensus_revision_YYYYMMDD_HHMMSS.html`: timestamped report for the run.
- `latest.html`: stable entry point for the latest report.

## Authentication and privacy

Authentication is the first external action in every run. Supply credentials through the current process environment when appropriate:

```powershell
$env:PANDADATA_USERNAME = "your-account"
$env:PANDADATA_PASSWORD = "your-password"
python -m scripts.run_report --market both
```

When credentials are absent, desktop sessions use a visible local login window. Passwords remain only in process memory and are never written to command-line arguments, logs, configuration files, or HTML. For non-TTY callers, explicitly request a login window only from a GUI-capable desktop host:

```powershell
python -m scripts.run_report --market both --desktop-login-window
```

- Only plain 11-digit mainland China mobile usernames receive the `86` prefix automatically; other account names are unchanged.
- After the password is submitted, the terminal immediately reports that PandaData login is in progress, then reports success or failure; a failed attempt requires both credentials to be entered again.
- With the local login window, only a verified short-lived session token is relayed to the main process; the password is not relayed and no second login request is made.
- Authentication failure re-prompts for both username and password without reusing failed credentials.
- Use `--no-login-window` only for unattended environments where a visible login window is not permitted.

## Common commands

```powershell
# Focus on selected symbols (.HK routes to the Hong Kong market)
python -m scripts.run_report --market both --symbols 0700.HK,9988.HK,AAPL,NVDA

# Change horizon and target-price/recommendation coverage thresholds
python -m scripts.run_report --market both --horizon 3month --min-analysts 8 --min-recommendations 8

# Change the revision threshold and ranking size
python -m scripts.run_report --market hk --revision-threshold 0.02 --ranking-limit 30

# Change event display and discovery windows
python -m scripts.run_report --market both --event-past-days 30 --event-future-days 30 --event-discovery-days 730

# Skip event context and generate only consensus rankings and security interpretation
python -m scripts.run_report --market both --no-events
```

| Option | Description |
|---|---|
| `--market` | `hk`, `us`, or `both`; default `both`. |
| `--symbols` | Comma-separated symbols; uses the supported full universe when omitted. |
| `--horizon` | `week`, `1month`, `3month`, `6month`, or `12month`. |
| `--min-analysts` | Minimum estimate count for target-price rankings; default 5. |
| `--min-recommendations` | Minimum recommendation count for recommendation-change rankings; default 5. |
| `--revision-threshold` | Absolute target-price direction threshold; default `0.01`. |
| `--ranking-limit` | Maximum rows per ranking; default 20. |
| `--start-date` / `--end-date` | Optional price-query window in `YYYYMMDD`. |
| `--output-dir` | Output directory; default `output/`. |

## Reading the report

### Rankings and measures

- **Revision**: current mean target price ÷ historical mean target price − 1.
- **Price distance**: current mean target price ÷ latest valid close − 1; available only when currencies are comparable.
- **Dispersion**: target-price standard deviation ÷ |current mean target price|.
- **Coverage**: target-price rankings use `estimates_num`; recommendation rankings use `recommendations_num`.
- **Recommendation change**: historical recommendation mean − current recommendation mean. A lower PandaData recommendation mean represents a more positive aggregate level.

### Trajectories and security interpretation

The primary reading path is **Revision Trajectory Matrix → Consensus State Machine → auditable security evidence**, rather than a one-point consensus lookup. The matrix and security trajectory display aggregate target-price and recommendation changes across five horizons. States such as “persistent upgrade”, “target-price and recommendation resonance”, or “high-dispersion review” explain aggregate evidence only. They do not change rankings and are not individual analyst revision records.

Event context is explanatory only and does not change rankings. The data-completeness section discloses called interfaces, missing inputs, price fallback, core-universe exclusions, and validation information; it is collapsed by default to keep the report focused.

## PandaData data source

PandaData is the **only raw data source** for this project; no other provider is used to fill values. See [references/pandadata-api-map.md](references/pandadata-api-map.md) for fields and collection rules, and [references/methodology.md](references/methodology.md) for formulas.

| Purpose | Hong Kong interface | US interface |
|---|---|---|
| Security identity, status, type, industry | `get_hk_detail` | `get_us_detail` |
| Aggregate target-price consensus | `get_stock_ncycl_consensus` | `get_stock_ncycl_estimate` |
| Aggregate recommendation consensus | `get_stock_recommendation_consensus` | `get_stock_recommendation_estimate` |
| Latest returned daily quote / close | `get_hk_daily` | `get_us_daily` |
| Dividend and split events | `get_stock_dividend_event` | `get_stock_dividend_activity` |
| Market/disclosure events | `get_stock_market_event` | `get_stock_market_activity` |
| Company meeting events | `get_stock_meeting_event` | `get_stock_meeting_activity` |
| Financial disclosure events | `get_stock_financial_event` | `get_stock_financial_activity` |
| Investor-relations events | `get_stock_ir_event` | `get_stock_ir_activity` |
| Optional latest-trading-day probe | `get_last_trade_date` | `get_last_trade_date` |

## Auditable design

- **More than a snapshot report**: the revision radar, trajectory matrix, and state machine are the primary deliverables; current target price and recommendation are merely the current anchors for those trajectories.
- **Conservative universe**: detail endpoints validate security identity, status, and asset category. Non-core securities do not enter rankings but remain in diagnostics.
- **Per-symbol price fallback**: query the requested trading day first, then retry every missing, nonnumeric, or nonpositive close over the preceding 14 calendar days, regardless of aggregate match rate.
- **No invented values**: missing inputs remain missing; the skill does not replace them with zeroes, prior values, or third-party data. Dependent measures and rankings show exclusions explicitly.
- **Separate coverage thresholds**: target-price and recommendation rankings use independent coverage criteria.
- **Provenance and time basis**: the report lists interfaces actually called and separates report generation time, per-market retrieval completion time, and returned close date.
- **Offline review**: HTML reports load no external resources; data completeness and methodology travel with the report.

## Limitations and risk boundaries

- The mapped PandaData endpoints provide **aggregate consensus**, not individual analyst or broker revisions, revision timestamps, or revision breadth. Do not infer individual behavior or analyst accuracy.
- Current aggregate target-price and recommendation observations have no available concrete business date. The report labels them as the PandaData latest available snapshot; retrieval time is collection evidence only and returned price dates are shown separately.
- Consensus may be sparse, stale, biased, or revised after market moves. Cross-market values are not FX-normalized.
- Corporate actions, liquidity, transaction costs, taxes, slippage, execution feasibility, and derivative risks are outside scope.
- This project is not investment advice. Rankings and states must not be used as a standalone investment decision.

## Contributing and license

Issues and review feedback are welcome. This is an unreviewed QuantSkills Community Project; the PandaData SDK and data service remain subject to their own terms. Code is released under the [GNU GPL v3.0 (GPL-3.0-only)](LICENSE).
