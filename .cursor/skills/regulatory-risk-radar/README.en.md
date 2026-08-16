# Regulatory Risk Radar

[Chinese README](README.md) | English

This skill scans an A-share holding or watch list for governance and regulatory events:
lock-up releases, shareholder reduction plans, equity pledges, placarding, freezes,
trading halts, and ST status. It scores each name and returns sourced evidence.

## Quick start

```bash
pip install -r requirements.txt
python examples/run_demo.py
python scripts/reg_risk_report.py --symbols 000021.SZ,600519.SH \
  --lookback 180 --lookahead 90 --min-severity low \
  --out report.json --md report.md
```

The demo is offline and uses bundled samples. The data adapter prefers the Pandadata
SDK and falls back to samples when requested. Each event keeps its announcement date,
source, severity, and degradation note.

## Method and output

Event scores combine severity, scale, and time proximity. The aggregate uses a
non-averaging risk union so multiple events remain visible. The output contains a
per-symbol severity, evidence list, source dates, and `degraded` reasons.

## Research boundary

Announcements and status fields can be delayed or incomplete. Data is not real time.
Outputs are for research and risk-monitoring education only; this project does not place
orders and is not investment advice. Verify primary disclosures before acting on a
finding.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
