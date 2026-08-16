# B11 Auto Stop-Loss / Take-Profit + Position Sizing (Enhanced)

Automated stop-loss, take-profit, and single-name position-cap management for A-shares and futures. Supports next-day gap-up take-profit (+5%), next-day gap-down stop-loss (-3%), forced liquidation once holding spans ≥ 2 trading days, and reduce-to-cap when a single name's notional exceeds 10% of total equity. Emits the standard 8-field position adjustment order.

> This release is the **enhanced fix** of the previous 52/100 audited version, addressing all six identified defects (E1–E6). **v2 upgrades this BUILD to a hybrid type** — the shipped `production/trade.parquet` cache backs the trading calendar, and two new agent-facing APIs (`inspect_calendar()` / `refresh_calendar()`) let higher-level agents own the cache lifecycle.
> **v3 adds** `check_date_coverage(start_date, end_date=None)` — a single call that returns whether any date / backtest range is covered by the calendar, the natural-day gap, extension advice, and a ready-to-run `refresh_command`.

---

## ⚡ Agent Quick Integration (3-minute onboarding)

Once cloned, downstream agents can produce a trading decision in 3 steps:

### Step 1 — Install & configure (one-time)

```bash
# Dependencies
pip install panda_data pyarrow

# panda_data credentials (add to ~/.zshrc or ~/.bashrc, then source)
export PANDA_USERNAME=<your_username>
export PANDA_PASSWORD=<your_password>
```

> `production/trade.parquet` ships with the repo (971 trading days / ~18.5KB) and is ready out-of-the-box. Rerun `python3 scripts/build_calendar.py` only when you need a different date range.

### Step 2 — Call from agent code (3 lines minimum)

```python
import sys
sys.path.insert(0, "/path/to/skill-b11-auto-stop-loss-take-profit/scripts")
from build import run

order = run({
    "code":         "600036",
    "entry_price":  10.0,
    "entry_date":   "2026-06-19",   # Friday entry
    "current_qty":  800,
    "open_price":   10.55,          # next-day +5.5%
    "today":        "2026-06-22",   # following Monday (real next trading day)
    "total_equity": 1_000_000,      # ⭐ required: total equity as denominator
})
# → {"code": "600036", "action": "sell", "target_qty": 0, "qty_change": -800,
#    "reason": "[B11]next-day gap-up take-profit ...", ...}
```

Batch call: `run([pos1, pos2, ...])` returns a same-length list.

### Step 3 — When your date is outside the calendar (3-layer API)

```python
from build import check_date_coverage, refresh_calendar

# Ask the calendar first — one call gives range/coverage/advice/command
r = check_date_coverage("2020-01-15")   # or ("2020-01-15", "2029-06-01") for a range

if not r["in_range"]:
    # r already computed the parameters; agent just forwards them
    refresh_calendar(force=True,
                     years_back=r["suggested_years_back"],
                     years_forward=r["suggested_years_forward"])
# Then call run(...) normally
```

### Step 4 — Common platform integrations

| Platform | How to integrate |
|---|---|
| **Python agent (most common)** | Step 2 three-liner, or `python3 scripts/build.py` |
| **Claude Code** | `cp -R . ~/.claude/skills/skill-b11-auto-stop-loss-take-profit`; invoke `/skill-b11-...` |
| **Cursor** | Register in `.cursor/tools.json` (see `INSTALL.md § Cursor`) |
| **OpenAI Codex** | Function-tool JSON schema (see `INSTALL.md § Codex`) |
| **Hermes / OpenClaw** | YAML config (see `INSTALL.md § Hermes` / `§ OpenClaw`) |

### Required fields at a glance

| Field | Type | Required | Description |
|---|---|:---:|---|
| `code` | str | ✅ | A-share (`600036`/`sh600036`) or futures (`IF2406`/`rb2410`) |
| `entry_price` | float | ✅ | Entry price |
| `entry_date` | str | ✅ | Entry date `YYYY-MM-DD` |
| `current_qty` | int | ✅ | Current holding (A-share shares / futures lots) |
| `open_price` | float | ✅ | Today's open price |
| `today` | str | ✅ | Current date `YYYY-MM-DD` (must be ≥ entry_date) |
| `total_equity` | float | ✅ | **Total equity** (position-ratio denominator); `≤0` → hold |
| `multiplier` | float | ⭕️ | Futures contract multiplier (A-shares ignore; required for unknown futures) |

### Output contract (8-field order)

```python
{
    "code":        "600036",
    "pnl_pct":     0.055,          # unrealized P&L (decimal)
    "current_qty": 800,
    "time":        "2026-06-22",
    "action":      "sell",         # "sell" / "hold" (never emits buy)
    "qty_change":  -800,           # negative = sell, 0 = no change
    "target_qty":  0,
    "reason":      "[B11]next-day gap-up take-profit ...",
}
```

### Fast troubleshooting

| Symptom | Fix |
|---|---|
| `RuntimeError: 需要 panda_data` | `pip install panda_data pyarrow` |
| `RuntimeError: 需要 PANDA_USERNAME / PANDA_PASSWORD` | Set env vars, then `source ~/.zshrc` |
| `ValueError: 未知期货品种` | Pass `multiplier` explicitly |
| `ValueError: 缺少字段: total_equity` | v2 requires `total_equity` |
| All positions return `hold` with reason "总权益非正" | `total_equity ≤ 0` on input |
| Date out of calendar range | `check_date_coverage()` → apply suggested `refresh_calendar(force=True, ...)` |

---

## ⚠️ Disclaimer

- **Research & educational use only.** This skill is a quantitative research tool. It is **not** investment advice, financial advice, or a trading recommendation.
- **No profit guarantee.** Backtest or simulation results do not represent live performance. Past performance does not predict future results. Users bear all trading risk.
- **Risk boundaries.** The tool does not model liquidity, price limits (up/down), trading halts, slippage, or auction phases. The trading calendar defaults to the A-share convention (`panda_data` SH exchange); HK and US markets are not supported. Long-only.
- **Not officially endorsed.** This is a QuantSkills community project. It has not been audited or certified and must not be treated as a production-grade tool endorsed by QuantSkills.

## Layout

```
├── SKILL.md                                ← skill spec (metadata / decision rules / Agent SOP)
├── README.md                               ← Chinese version
├── README.en.md                            ← this file
├── LICENSE                                 ← GPL-3.0-only
├── INSTALL.md                              ← 5-platform install guide
├── requirements.txt                        ← dependency notes (panda_data required + pyarrow)
├── scripts/
│   ├── build.py                            ← main entry (run / validate_input / check_date_coverage / inspect_calendar / refresh_calendar)
│   ├── test.py                             ← self-test (68 cases)
│   ├── build_calendar.py                   ← standalone bootstrap: fetch calendar → write production/trade.parquet
│   └── _verify_prod.py                     ← production-path verifier
├── references/
│   └── api_guide.md                        ← API guide (with change log + Agent SOP)
└── production/
    └── trade.parquet                       ← trading calendar cache (today−3y → today+1y, snappy, ~18.5KB)
```

## Quick Start

```bash
# 1) Bootstrap the trading-calendar cache (first run only; needs PANDA_USERNAME/PANDA_PASSWORD)
python3 scripts/build_calendar.py

# 2) Unit tests (no external data required, 68 cases)
python3 scripts/test.py

# 3) Main entry demo
python3 scripts/build.py

# 4) Optional: production verifier (needs panda_data + env credentials)
python3 scripts/_verify_prod.py
```

## Agent Usage (detailed)

The "⚡ Agent Quick Integration" section above is the shortest path. Below is the full three-layer SOP built around `check_date_coverage`:

```python
from scripts.build import check_date_coverage, refresh_calendar, run

# 1) One-shot query: agent asks the calendar about any unknown date
r = check_date_coverage("2020-01-15")   # or ("2020-01-15", "2029-06-01") for a range
# {
#   "in_range": False,
#   "coverage": {"date_min": "2023-07-06", "date_max": "2027-07-05", "count": 971},
#   "gap_before": 1268, "gap_after": 0,
#   "suggested_years_back": 7, "suggested_years_forward": 1,
#   "suggested_action": "extend_back",
#   "refresh_command": "refresh_calendar(force=True, years_back=7, years_forward=1)",
#   "reason": "start=2020-01-15 is before date_min=2023-07-06 (gap 1268 days) ..."
# }

# 2) Extend cache per suggestion (agent just forwards the suggested_* fields)
if not r["in_range"]:
    refresh_calendar(force=True,
                     years_back=r["suggested_years_back"],
                     years_forward=r["suggested_years_forward"])

# 3) Regular invocation (single dict or batch list[dict])
order = run({
    "code": "600519", "entry_price": 1_800.0, "entry_date": "2025-01-02",
    "current_qty": 100, "open_price": 1_890.0, "today": "2025-01-03",
    "total_equity": 5_000_000,
})
```

Underlying `inspect_calendar()` (read-only health check) and `refresh_calendar(force, years_back, years_forward)` (idempotent refresh) remain available. Full three-layer SOP and 7-scenario decision table are in `SKILL.md` § Agent SOP.

## v3 Changelog

Four changes since v2 (commit `abf1227`):

1. **New `check_date_coverage(start_date, end_date=None)` public API.** The recommended agent entry point: returns `in_range` / `coverage` / `gap_before` / `gap_after` / `suggested_years_back` / `suggested_years_forward` / `suggested_action` / `refresh_command` / `reason` in a single call.
2. **Three-layer agent SOP** — `check_date_coverage` (query + advice) → `inspect_calendar` (health) → `refresh_calendar` (refresh). `SKILL.md` documents when to use each layer.
3. **Tests expanded 62 → 68.** Six new cases covering `check_date_coverage` (in-range, before `date_min`, after `date_max`, both ends out, missing parquet fallback, reversed range auto-swap).
4. **`production/trade.parquet` and all v2 behaviour preserved** — agents remain out-of-the-box.

## v2 Changelog

Seven changes since v1 (commit `ea1585e`):

1. **Trading calendar is a hard `panda_data` dependency.** The four v1 fallback entries (`config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]`) are removed; `panda_data.get_trade_cal` is the single source of truth.
2. **Automatic env-based login.** `build.py` reads `PANDA_USERNAME` / `PANDA_PASSWORD` and calls `init_token` on first use; missing credentials raise `RuntimeError` with a guidance link.
3. **New production artifact `production/trade.parquet`.** The BUILD is now hybrid — a local parquet cache backs the calendar to avoid per-call network round-trips.
4. **New bootstrap script `scripts/build_calendar.py`.** Fetches today−3y through today+1y and writes a snappy-compressed parquet (~18.5KB / 971 trading days).
5. **New agent APIs.** `inspect_calendar()` (read-only) and `refresh_calendar(force=False)` (idempotent refresh) expose cache state to callers.
6. **Complete schema doc + Agent SOP.** `SKILL.md` documents the parquet's 5-column schema, date format, four-step update flow, and a 7-scenario decision table.
7. **Tests expanded 49 → 62.** New coverage for parquet cache, `inspect_calendar`, and `refresh_calendar`; `pyarrow` absence is skipped gracefully.

## Core Design

1. **Five-level decision priority**: `guard (invalid → hold) → next-day take-profit (+5%) → next-day stop-loss (-3%) → forced close on ≥ 2 trading-day holding → reduce when single-name notional > 10% of total equity → hold`.
2. **Trading-day semantics (E1).** Entry day = trading day 0; `holding_trading_days` counts trading days spanned. Next-day = `holding_trading_days == 1`, forced close = `holding_trading_days >= 2`. Friday entry's "next day" is the following Monday (3 calendar days) — correctly recognised by the calendar.
3. **Position denominator (E2).** Ratio = notional / `total_equity` (option A: caller-provided total equity, **not** `available_cash`). Notional = `current_qty × open_price × multiplier` (A-shares multiplier = 1).
4. **Code classification (E3).** Strip `sh/sz/SH/SZ` prefix first; 6-digit numeric → A-share, otherwise → futures.
5. **Futures contract multipliers (E4).** Built-in table covers IF/IC/IH/IM/rb/cu etc.; unknown symbols must be overridden by `multiplier`.
6. **Robustness (E5).** NaN/inf prices, `total_equity ≤ 0`, and `today < entry_date` are all short-circuited to `hold`.
7. **Calendar single source of truth (v2).** `panda_data.get_trade_cal` is a hard dependency; `production/trade.parquet` provides the local persistence layer. All four v1 fallback entries are removed to eliminate cross-source drift.
8. **Pure Python stdlib for business logic**: `math / numbers / re / datetime / bisect`. Only the cache layer depends on `panda_data` + `pyarrow`.

## Supported Runtimes

See `INSTALL.md` for Claude Code, Codex, Cursor, Hermes, and OpenClaw setups.

## Acceptance

- **Tests**: `scripts/test.py` — **68 / 68 passing** (happy path, edge cases, exceptional input, E1–E6, v2 parquet-cache / `inspect_calendar` / `refresh_calendar`, plus v3 `check_date_coverage` coverage).
- **Enhancements delivered**:
  - E1 trading-day semantics (`panda_data.get_trade_cal` as sole source) ✅
  - E2 denominator switched to `total_equity` ✅
  - E3 code classification strips `sh/sz` prefix first ✅
  - E4 futures multiplier table + `multiplier` override ✅
  - E5 hardened guards (NaN/inf, non-positive equity, time reversal) ✅
  - E6 test suite expanded to 62 cases covering v2 additions ✅
- **v2 hybrid artifact**: `production/trade.parquet` (971 trading days / snappy / ~18.5KB) ships with the repo.
- **Production verifier**: `scripts/_verify_prod.py` — passes against real `panda_data.get_trade_cal` with env credentials.
- `build.py` runs standalone; `validate_input` / `inspect_calendar` / `refresh_calendar` APIs are complete.

## Known Limitations

1. Trading calendar defaults to A-shares (SH exchange). HK / US not supported.
2. No awareness of price limits, halts, or auction states.
3. Long-only. No short, hedge, spread, or calendar combos.
4. Unknown futures symbols require an explicit `multiplier`.
5. No liquidity, slippage, or market-impact modelling.

## Maintainer

- Upstream org: QuantSkills (<https://github.com/quantskills>)
- License: GPL-3.0-only (see `LICENSE`).
