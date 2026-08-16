# skill-ma-crossover-signal

[简体中文](README.md) | **English**

Single-symbol moving-average crossover analysis. Given a ticker and fast/slow MA periods, it computes both MAs (SMA/EMA) on the **same cleaned close series** and detects a golden/death cross by the **sign change of `(fast − slow)`**, returning the current trend state, the latest cross (date + bars-ago), the MA gap and the price bias (乖离率), auto-routing A-share / HK / US by suffix. It reports signal facts only — no buy/sell instructions.

<p align="center">
  <img alt="role" src="https://img.shields.io/badge/role-MA%20crossover-brightgreen">
  <img alt="output" src="https://img.shields.io/badge/output-golden%2Fdeath·trend·bias-blue">
  <img alt="market" src="https://img.shields.io/badge/market-A--share·HK·US-9cf">
  <img alt="data" src="https://img.shields.io/badge/data-panda__data·tqx__data-yellow">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-ma-crossover-signal` is a QuantSkills community single-symbol trend Skill. It answers "did X golden-cross / is X still trending up" — a single-symbol timing question — and is complementary to `skill-pair-correlation` (two-symbol relationship) and `skill-risk-return-metrics` (single-symbol risk/return), with no overlap.

## What problem it solves

"Did Moutai golden-cross?" "Is it still in an uptrend?" is the most frequent single-symbol question, but the naive answer — "fast MA is above slow MA" — **hides whether the cross is fresh or 40 bars stale**.

This skill turns it into a checkable, structured result:

- computes MA5 / MA20 (or custom, optionally EMA) on one cleaned close series and detects the cross **by the sign change of `(fast − slow)`**, so it returns the *actual last cross with its date and bars-ago*, not "who is on top right now";
- also returns the **trend state, MA gap `ma_gap`, price bias `price_bias` (乖离率)** and a list of recent crosses;
- when history is shorter than `slow_period`, `state` / `last_cross` return `null` gracefully — no crash, no fabrication.

## How it is computed

| Field | Meaning / Formula |
|---|---|
| `state` | `bullish` when `fast_ma ≥ slow_ma` on the last bar, else `bearish` |
| `ma_gap_pct` | `(fast_ma − slow_ma) / slow_ma` |
| `price_bias_pct` | price bias `(last_close − slow_ma) / slow_ma` |
| `last_cross.type` | `golden` (fast crosses above slow) / `death` (fast crosses below slow) |
| `bars_ago` | trading bars since that cross (0 = crossed on the last bar) |
| `recent_signals` | up to `max_signals` most-recent crosses, oldest→newest |

`last_cross` is `null` when no cross occurred in the window (or history < `slow_period`). This is a **signal descriptor, not a backtest**: no transaction costs, slippage, or position sizing.

## Quick start

```bash
# deps: pandas / numpy + panda_data (A-share) / tqx_data (HK/US)
python scripts/ma_crossover_signal.py 600519.SH --fast-period 5 --slow-period 20
python scripts/ma_crossover_signal.py AAPL.NB --ma-type ema --fast-period 10 --slow-period 50
```

As a platform skill the entry point is `async def run(...) -> str` in `scripts/ma_crossover_signal.py` (Panda QuantFlow skill contract). Missing data libs → a structured `Error: …` string rather than a raise.

## Example output

`600519.SH` MA5/MA20 example (full files in [`examples/output/`](./examples/output/)):

```
last close 1685.0    MA5 = 1690.2    MA20 = 1662.4
state bullish    ma_gap = +1.67%    price bias = +1.36%
last cross: golden  20260512  9 bars ago  close 1650.0
```

> A bullish alignment 9 bars into a golden cross, with modest bias — "early cross, not yet overheated".
> Structured JSON: [`examples/output/ma_crossover_signal.json`](./examples/output/ma_crossover_signal.json).
> Example values are taken from the SKILL.md output schema, not a live feed.

## Where the data comes from

The suffix drives market routing (when `market=auto`):

- **A-share** `.SH` / `.SZ` / `.BJ` or a bare 6-digit code → `panda_data` daily closes;
- **HK** `.HK` → `tqx_data`;
- **US** `.NB` / `.US` / `.NY` → `tqx_data`.

You can also force it with `--market cn|hk|us`. Data is injected by the platform runtime; output quality depends on upstream availability and correctness.

## Directory layout

```
skill-ma-crossover-signal/
├── SKILL.md                       # Agent spec (core): usage, params, output schema, definitions, when-NOT-to-use
├── README.md                      # Chinese readme (first paragraph = platform summary)
├── README.en.md                   # this file (English)
├── LICENSE                        # full GPLv3 license text
├── quantskills.yaml               # QuantSkills upstream manifest: provenance / deps / license: GPL-3.0-only
├── agents/                        # per-platform runtime entrypoints (all fall back to the same SKILL.md)
│   ├── cursor-rule.mdc            #   Cursor rule entrypoint
│   ├── openai.yaml                #   OpenAI-style / OpenClaw runtime manifest (display_name / default_prompt)
│   └── portable-loader.md         #   Hermes / OpenClaw portable loader
├── scripts/
│   └── ma_crossover_signal.py     # executable: async def run(...) -> str + standalone CLI; MA + cross detection
└── references/
    └── example_output.md          # per-field output notes
└── examples/
    └── output/                    # example output (values from the SKILL.md schema)
        ├── ma_crossover_signal.json   #   structured JSON example
        └── ma_crossover_signal.txt    #   human-readable summary + reading + disclaimer
```

## Runtime entrypoints

This Skill supports Claude Code, Codex, Cursor, Hermes and OpenClaw. Claude Code, Codex and native skill runtimes load `SKILL.md` directly; Cursor uses `agents/cursor-rule.mdc`; Hermes / OpenClaw use `agents/portable-loader.md` when they cannot discover the skill natively (`agents/openai.yaml` provides OpenClaw display info). Every entrypoint falls back to the same `SKILL.md` and the same script — no parallel business logic.

## How it divides work with sibling skills

- **this skill**: single-symbol trend / golden-death cross — **timing signal on one name**;
- `skill-pair-correlation`: two-symbol correlation / hedge beta / spread — **relationship between two names**;
- `skill-risk-return-metrics`: single-symbol Sharpe / drawdown / Calmar — **risk/return of one name**;
- RSI / MACD / KDJ indicator series or a full strategy P&L backtest → use the relevant indicator / backtest skill.

## Disclaimer

- **Research & educational use only.** Output is informational research, **not investment advice**, and makes **no promise of returns**.
- **Data sources:** A-share via `panda_data`; HK / US via `tqx_data` (platform-provided). Output quality depends entirely on upstream data availability and correctness.
- **Assumptions & limitations:** MAs are computed on daily closes; a cross is the sign change of `(fast − slow)`. This is a **signal descriptor, not a backtest** — no costs / slippage / sizing; a crossover is not a buy/sell recommendation; `last_cross` is `null` when history `< slow_period`.
- **Risk boundary:** do not use as the sole basis for real-money entries/exits; validate independently and understand market risk.

## License

GPL-3.0-only. This skill is original to the QuantSkills community; MA and crossover detection are standard quant methods. Full text in [`LICENSE`](./LICENSE).
