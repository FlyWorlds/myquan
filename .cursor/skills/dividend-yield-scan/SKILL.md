---
name: dividend-yield-scan
description: Build an A-share high-dividend / dividend-quality cross-section from Pandadata
  dividend interfaces (get_stock_cash_dividend, get_stock_dividend, get_stock_dividend_amount,
  get_stock_split), computing trailing dividend yield from cash dividends and price,
  ranking yield, measuring payout continuity (consecutive dividend years), separating
  real cash return from stock dividends (送转), listing upcoming ex-dividend dates,
  and rolling up by industry, for the whole market or a basket. Use when the user
  asks for 高股息, 股息率, 股息率排行, 红利, 红利策略, 分红质量, 连续分红, 分红稳定性, 现金分红 vs 送转, 除权除息日历,
  股息率分位, or an A-share dividend / high-yield scan.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-dividend-yield-scan
  repository_url: https://github.com/quantskills/skill-dividend-yield-scan
  project_type: skill
  collection: dividend-yield-scan
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - a-share
  - dividend
  - dividend-yield
  - high-yield
  - payout
  - corporate-action
  - pandadata
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: draft
  validation_level: runnable
  maintainer_type: community
  summary_zh: A股高股息与分红质量横截面：基于现金分红/分红/分红总额/拆分接口计算滚动股息率并排行、衡量连续分红年数与稳定性、区分现金分红与送转、列示除权除息日历、按行业聚合，全市场或篮子。
  summary_en: A-share high-dividend / dividend-quality cross-section from Pandadata dividend
    interfaces, computing trailing dividend yield, ranking it, measuring payout continuity,
    separating cash return from stock dividends, listing upcoming ex-dividend dates,
    and rolling up by industry, for the whole market or a basket.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Dividend Yield Scan

Use this skill to **build an A-share high-dividend / dividend-quality cross-section**: for the whole market or a basket, compute the trailing **dividend yield** from cash dividends and price, rank it, measure **payout continuity** (consecutive dividend years), **separate real cash return from stock dividends (送转)**, list upcoming **ex-dividend dates**, and roll names up by industry. Prefer Pandadata as the data source, keep every figure traceable to a dividend method and a dividend date, and never invent dividends, yields, continuity, or payout figures.

## Scope And Positioning (read first to avoid overlap)

This skill is the **dividend / high-yield cross-section** view. It is deliberately distinct from its siblings:

- Unlike `stock-screener` (natural-language filtering, where "连续分红" is just one boolean filter among many): this skill is a **dividend-centric analytical scan** — it computes yield, continuity, cash-vs-送转, and payout, and ranks the cross-section. If the user wants to combine dividend with unrelated filters (北向加仓, 低质押, 行业) into a screen, hand off to `stock-screener`.
- Unlike `a-share-stock-dossier` (single-name deep due diligence with dividends as one sub-section): this skill reads the dividend interfaces in depth **across the market/basket**. For a full single-company dossier, hand off to `a-share-stock-dossier`.
- Unlike `index-valuation-rotation` (index PE/PB percentiles and industry momentum): dividend yield is a **cash-return** lens, not a valuation-percentile or rotation lens. They can complement each other (红利 style vs valuation), but the dividend cross-section lives here.

## Dividend Model (read before analysis)

Four interfaces cover different facets. Join them per name; keep the units and dates straight.

- **Cash dividend `get_stock_cash_dividend`** — the core of yield:
  - `div_cash_gross` (税前每股现金分红) is stated **per `round_lot`** (分红基准单位, typically 10). **Per-share cash = `div_cash_gross` / `round_lot`.** This is the single most common mistake — always divide by `round_lot`.
  - `ex_date` (除权除息日), `record_date` (股权登记日), `payment_date` (派息日), `announcement_date`, `meeting_date`, `quarter`.
- **Dividend form `get_stock_dividend`** — `div_type`: `cash` (only cash), `transferred share` (转增), `bonus share` (送股), `cash and share` (兼有). **送转 (transferred/bonus) is NOT cash return** — it does not put cash in holders' pockets and must be separated from cash yield.
- **Total amount `get_stock_dividend_amount`** — `total_div_amount` (分红总额) with `event_stage` (预案 / 方案实施). A 预案 is proposed, not paid — label the stage.
- **Split `get_stock_split`** — `split_factor_pre/post`, `ex_date`; context for 送转/拆分 adjustments to per-share figures over time.

### Dividend yield (derived — state the method)

- **Trailing DPS** = sum of per-share cash dividends (`div_cash_gross` / `round_lot`) with `ex_date` in the trailing 12 months (or a stated trailing window).
- **Dividend yield** = trailing DPS ÷ latest close (`get_stock_daily`).
- Always state the trailing window, the price date, and that 送转 is excluded from the cash yield. Yield is **backward-looking** (based on paid/declared dividends); it is not a forecast.

## Workflow

1. Resolve the target: whole-market high-yield scan, a basket (index constituents via `get_index_weights`, industry via `get_industry_constituents`, or a user list), or a single name's dividend history.
2. Read `references/dividend-playbook.md` before the first run in a session. Use it for the routing table, yield/continuity/cash-vs-送转 definitions, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the dividend-method sections in `references/api-docs.md` to confirm parameters and fields (especially `round_lot`); do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Cash dividends: `get_stock_cash_dividend` over a multi-year window (for continuity + trailing DPS).
   - Dividend form: `get_stock_dividend` (`div_type`) to separate cash from 送转.
   - Total amount / stage: `get_stock_dividend_amount` for scale and 预案/实施 stage.
   - Split context: `get_stock_split` where 送转/拆分 matters.
   - Price: `get_stock_daily` for the close used in yield.
   - Identity & industry: `get_stock_detail`, `get_stock_industry` for naming and rollup.
   - Payout (optional): `get_fina_performance` / `get_fina_reports` net profit to compute 分红率 (payout = total_div_amount ÷ net profit) — mark clearly as optional and derived.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound windows and the ex-dividend calendar.
5. Compute per name: trailing DPS and yield, consecutive-dividend-year streak, cash-vs-送转 split, upcoming ex-dates, and (optional) payout; then rank the cross-section and roll up by industry.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/dividend/<scope>-<date>.md` (e.g. `reports/dividend/market-20260705.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing yield-method / cash-vs-送转 caveats, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 分红事件总览 | `get_stock_cash_dividend`, `get_stock_dividend` | Recent dividends in scope; cash vs 送转 mix. |
| 股息率榜 | `get_stock_cash_dividend` (`div_cash_gross`/`round_lot`) + `get_stock_daily` | Highest trailing dividend yield. |
| 连续分红与稳定性 | `get_stock_cash_dividend` (multi-year) | Consecutive dividend years; payout continuity. |
| 现金分红 vs 送转 | `get_stock_dividend` (`div_type`) | Which "dividends" are real cash vs 送转. |
| 除权除息日历 | `get_stock_cash_dividend` (`ex_date`) | Upcoming ex-dividend dates. |
| 分红率（可选） | `get_stock_dividend_amount` + fina | Payout ratio vs net profit. |
| 行业分布 | `get_stock_industry` + the above | Which industries pay the most cash. |

## Analysis Modes

- **High-yield scan**: rank the cross-section by trailing dividend yield (cash only), then attach continuity and cash-vs-送转 flags. State the trailing window and price date; a high yield on a one-off special dividend is not the same as a stable high yield.
- **Dividend-quality read**: prefer names with long consecutive-dividend streaks and predominantly cash payouts. Report the streak length and the 送转 share; do not equate a 送转-heavy history with cash return.
- **Single-name dividend history**: one ticker's per-year cash DPS, div_type, total amount (with 预案/实施 stage), and ex-date timeline.
- **Ex-dividend calendar**: upcoming `ex_date` entries in scope, so the reader knows when the price adjusts — a schedule, not a recommendation.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always state the yield method.** Every dividend yield must carry: trailing window, per-share = `div_cash_gross` / `round_lot`, price date, and "cash only, 送转 excluded". Never print a yield without its method.
- **Separate cash from 送转.** A `transferred share` / `bonus share` dividend is not cash return; never fold it into cash yield or call it "分红" without the cash/送转 label.
- **Label the stage.** `get_stock_dividend_amount` carries `event_stage` (预案 vs 方案实施); a proposed dividend is not paid. Mark it.
- Mark the scan window, the trailing window for yield, and the price date. Yield is backward-looking, not a forecast.
- Separate facts (raw cash per lot, div_type, amounts, dates), derived metrics (per-share DPS, trailing yield, streak, payout, industry aggregates), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "滚动股息率较高", "连续 N 年现金分红", "以送转为主非现金回报" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated dividend watch, create a task that runs periodically (dividend disclosures cluster around annual/interim reporting — a weekly cadence during 分红季 is reasonable, or after-close on trading days). Make it idempotent: if `reports/dividend/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days for price-dependent runs.

## Resource Guide

- `references/dividend-playbook.md`: routing table, yield/continuity/cash-vs-送转 definitions, the `round_lot` pitfall, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, yield-method disclosure, cash-vs-送转 separation, window/date labels, and the disclaimer.

## Quality Bar

- Every dividend yield states its method: trailing window, per-share = `div_cash_gross` / `round_lot`, price date, cash-only.
- Cash dividends and 送转 are always separated; 送转 never counted as cash return.
- `get_stock_dividend_amount` stages (预案 vs 实施) are labeled; proposed ≠ paid.
- Continuity is computed from multi-year cash-dividend history and stated as a streak.
- Yield is framed as backward-looking, not a forecast.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
