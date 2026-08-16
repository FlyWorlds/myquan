# skill-ag-futures-seasonality

[简体中文](README.md) | **English**

Seasonality analysis for Chinese agricultural futures. Agricultural commodities have the strongest seasonality of any futures class — planting, growing, harvest, and hemisphere offset drive repeatable price patterns. This skill computes monthly seasonal patterns from price history, tests their statistical significance, and overlays a crop calendar to assess a variety's historical monthly tendencies and its current position in the seasonal cycle. It outputs statistical facts and inference only, not buy/sell signals.

<p align="center">
  <img alt="role" src="https://img.shields.io/badge/role-seasonality%20analysis-brightgreen">
  <img alt="output" src="https://img.shields.io/badge/output-txt%20%C2%B7%20json%20%C2%B7%20self--contained%20HTML-blue">
  <img alt="validation" src="https://img.shields.io/badge/validation-9%2F9%20self--tests-orange">
  <img alt="data" src="https://img.shields.io/badge/data-Pandadata%20futures%20daily-9cf">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-ag-futures-seasonality` is a QuantSkills community analyst skill. The existing futures DeepView skill looks at **microstructure** (broker positions, basis, warehouse receipts); this skill covers a complementary angle — **cross-year seasonal patterns**. The two do not overlap.

## What it solves

"Which months does soybean tend to rise?" "Is now the seasonal peak for soybean meal?" Agricultural commodities have strong seasonal patterns, but most people only have a vague impression — they can't say whether "July tends to be strong" is a real pattern or an illusion, nor whether it is statistically significant or backed by enough samples.

This skill makes it computable, testable, and explainable:

- Per month: historical **average return, win rate, sample years, statistical significance** in one table
- Overlaid with a **crop calendar** explaining *why* — July strength = northern-hemisphere weather premium; Nov–Dec weakness = smooth South American planting
- Where the current date sits in the crop cycle, and next month's seasonal tilt

## Statistical rigor

- **Discloses sample size**: 10 years yields only 10 samples per month; small samples easily mistake noise for pattern, so reports always show sample years
- **Tests significance**: a 70% win rate that is not statistically significant is recorded as a "tilt", not a "rule"; only months that pass the test are starred
- **Seasonality is not a guarantee**: current-year weather, policy, or supply-demand can fully override seasonal patterns — stated in every report
- **Falsifiable**: `scripts/validate.py` verifies on synthetic data that it detects planted seasonality, does not false-fire on pure noise, uses the real Student-t distribution (not a normal approximation that would overstate significance), and that the HTML report is self-contained and preserves the rigor disclosures — 9/9 pass

## Quick start

```bash
pip install -r requirements.txt
python scripts/validate.py                                          # self-tests
python scripts/seasonality.py --csv examples/data/soybean_meal_M.csv --symbol "M"
python scripts/seasonality.py --csv your_data.csv --out report/     # your data (cols: date, close)
```

With `--out`, three formats are written: `seasonality.txt` (text report), `seasonality.json` (structured data), and `seasonality.html` (a self-contained visual report — inline SVG, offline-ready, light/dark aware). In the HTML, significant months are solid and non-significant months are semi-transparent, with sample sizes and caveats preserved (see `examples/output/seasonality.html`).

Real soybean-meal output (2015–2025, 11-year sample): only Nov (−3.53%, 36% win) is starred (mean t-test p=0.09). Dec (−2.84%, 27% win) has a lower win rate but its mean t-test p=0.13 fails the 0.1 threshold and is not starred; using the Student-t distribution rather than a normal approximation avoids overstating significance on small samples. July (73% win) is not flagged strong because it fails the significance test (binomial p=0.23 on 11 samples). Every report carries a multiple-testing caveat.

## Data

Framework-neutral input: one main-continuous daily series `[date, close]`.
- **Pandadata**: `get_future_daily` + `get_future_dominant` for the continuous series, `get_future_detail` to confirm variety codes
- **Your own**: backtest or broker exports normalized to date,close

Variety examples: soybean meal M, soybean oil Y, soybean A, corn C, sugar SR, cotton CF, palm P, egg JD.

## Runtime entrypoints

This Skill supports Claude Code, Codex, Cursor, Hermes, and OpenClaw. Claude Code, Codex, and native Skill runtimes load `SKILL.md` directly; Cursor uses `agents/cursor-rule.mdc`; Hermes/OpenClaw can use `agents/portable-loader.md` when native discovery is unavailable. All entrypoints converge on the same `SKILL.md`, crop calendar, source boundary, and seasonality script rather than maintaining parallel business logic.

## How it fits the community

- `skill-futures-deepview-analyst`: positions / basis / warehouse receipts / arbitrage — **current-moment microstructure**
- **this skill**: cross-year seasonal rhythm + crop calendar — **historical seasonality**
- `skill-pandadata-api`: data retrieval

## License

GPL-3.0. Original QuantSkills community work; the seasonality method is standard quant practice and the crop calendar is compiled from public agricultural knowledge.
