# Data Guide: 5 Dimensions → panda_data APIs → Fields

This document maps each Munger mental-model dimension to the panda_data SDK APIs and fields used in the analysis.

## 1. Financial Dimension (财务)

| Dimension | API | Method | Fields Used | Computation |
|-----------|-----|--------|-------------|-------------|
| **财务** | `get_fina_performance` | Fetch latest financials per stock | `roe`, `gross_profit`, `operating_revenue`, `ocf` | ROE vs peer median, Gross Margin (GP/OR) vs peer median, OCF > 0 & vs peer median → 3 binary sub-scores, average to 0–100 |

**Field Mapping (panda_data → logical keys):**
- `roe` → `roe` (Return on Equity %)
- `roe_cut` → `roe_cut` (ROE adjusted for dilution, if available)
- `gross_profit` → `gross_profit` (absolute, in currency)
- `operating_revenue` → `operating_revenue` (absolute, in currency)
- `net_operate_cashflow` → `ocf` (Operating Cash Flow, absolute)

**Data Gap:** Industry median computed manually from peer constituents (no industry-median API).

---

## 2. Competition Dimension (竞争)

| Dimension | APIs | Methods | Fields Used | Computation |
|-----------|------|---------|-------------|-------------|
| **竞争** | `get_stock_industry` + `get_industry_constituents` | (1) Fetch industry for target stock; (2) Fetch all peers in that industry L2 | `symbol` (peer list), `roe`, `gross_profit`, `operating_revenue` from fina | Peer count, ROE & GM percentile ranks vs peers, concentration bonus → 0–100 |

**Process:**
1. `get_stock_industry(stock_symbol=target, level="L2")` → extract `industry_code`
2. `get_industry_constituents(industry_code=..., level="L2")` → list of `stock_symbol` (includes target)
3. Fetch financials for all peers using `get_fina_performance`
4. Compute ROE and GM percentiles, apply peer-count bonus

**Data Gap:** Peer list only via industry constituents (no alternative peer-group API).

---

## 3. Incentive Dimension (激励)

| Dimension | APIs | Fields Used | Computation |
|-----------|------|-------------|-------------|
| **激励** | `get_top_holders` (market="cn"), `get_stock_shareholder_change`, `get_stock_pledge` | `hold_percent_total`, `pledge`, `freeze` (holders); `shareholder_type`, `direction`, `ratio_up_limit` (changes) | Concentration %, exec net buy/sell, pledge/freeze penalty → 0–100; flag `related_party: data_unavailable` |

**Sub-scores:**
- `concentration_pct`: sum of top-10 hold_percent_total (%)
- `pledge_freeze_penalty`: -20 if any pledge or freeze > 0
- `exec_net_buy`: count(增持) - count(减持) for `shareholder_type == "高管"`

**Data Gaps:**
- No related-party transaction API → always flag `"related_party: data_unavailable"`
- Freeze data depends on availability in `get_top_holders` response

---

## 4. Psychology Dimension (心理)

| Dimension | API | Fields Used | Computation |
|-----------|-----|-------------|-------------|
| **心理** | `get_investor_activity` (query last `MUNGER_IR_MONTHS` months) | `date`, `institute` (unique institution count) | Meeting count & distinct institute count normalized to 0–100; flag `qa_sentiment: not_available` |

**Formula:**
- `meeting_count` = len(activity_df)
- `institute_count` = nunique(institute) if "institute" in columns else 0
- `score` = min(100, (meeting_count / 12) * 50 + (institute_count / 12) * 50)

**Data Gap:** No text sentiment analysis from QA transcripts → always flag `"qa_sentiment: not_available"`

---

## 5. Negative Checklist Dimension (反面清单)

| Dimension | APIs | Fields Used | Veto Triggers |
|-----------|------|-------------|---------------|
| **反面清单** | `get_audit_opinion` (market="cn"), `get_stock_status_change`, `get_stock_pledge`, `get_stock_shareholder_change` | `opinion`, `agency`, `quarter` (audit); `type` (status); `pledge_ratio` (pledge); `direction`, `ratio_up_limit` (shareholder changes) | Nonstandard audit opinion, auditor switch, ST/delisting, high pledge ratio, controlling shareholder large sell |

**Veto Conditions (any = veto):**
1. **Nonstandard Audit**: Latest `opinion` ∉ {"unqualified_opinion", "no_audit_performed"} → veto, flag `"nonstandard_audit:{opinion}"`
2. **Auditor Switch**: `agency` changes across adjacent quarters → veto, flag `"agency_switch"`
3. **ST/Delisting**: Any row in `get_stock_status_change` (e.g., `type` contains "ST" or "退市") → veto, flag `"status_change:ST_or_delisting"`
4. **High Pledge**: max(`pledge_ratio`) > `MUNGER_PLEDGE_MAX` (default 0.50) → veto, flag `"high_pledge"`
5. **Controlling Shareholder Large Sell** (weak proxy for hostile takeover): `shareholder_type == "控股股东"` AND `direction == "减持"` AND `ratio_up_limit` > 0.02 → veto, flag `"large_controlling_sell"` + add `"hostile_takeover: weak_proxy"` to data_flags

**Score:** 0 if veto, else 100. Always `passed = not veto`.

---

## Data Gaps & Markers

| Gap | Marker String | Dimension | Why |
|-----|----------------|-----------|-----|
| No industry-median API | (self-computed) | fin, comp | Must fetch all industry peers and compute median in application |
| No related-party API | `related_party: data_unavailable` | incentive | Panda_data does not expose related-party transaction data |
| No QA text sentiment | `qa_sentiment: not_available` | psych | Panda_data provides activity count but not transcript text for NLP |
| No litigation history | (not triggered yet; reserved) | neg | Future expansion if litigation API becomes available |
| Weak proxy for hostile takeover | `hostile_takeover: weak_proxy` | neg | Use controlling shareholder large sell as proxy; marked for manual review |

---

## Retry & Relogin Strategy

All `panda_data` calls are wrapped in `_call_with_retry(fn, *args, **kwargs)` with:
- **Error code `200004`** (token expired): Relogin via `panda_data.init_token(username, password)` and retry
- **Error code `500010`** (server quota exceeded): Exponential backoff (0.5s, 1s, 2s, …) up to 3 retries
- **Network errors**: Exponential backoff, max 3 retries

---

## Configuration & Credentials

**Environment Variables:**
- `PANDA_DATA_USERNAME` (required)
- `PANDA_DATA_PASSWORD` (required)
- `MUNGER_PASS_THRESHOLD` (default 60.0)
- `MUNGER_PLEDGE_MAX` (default 0.50)
- `MUNGER_IR_MONTHS` (default 12)

Never write credentials into files. Always read from env vars at runtime.

---

## Output Fields

Per `analyze.py`, each analysis record contains:

```json
{
  "symbol": "000001.SZ",
  "trade_date": "2026-06-30",
  "dim_scores": { "fin": 80, "comp": 75, "incentive": 70, "psych": 60, "neg": 100 },
  "dim_passed": { "fin": true, "comp": true, "incentive": true, "psych": true, "neg": true },
  "sub_scores": { "fin": {...}, "comp": {...}, ... },
  "veto_flags": [],
  "data_flags": ["related_party: data_unavailable", "qa_sentiment: not_available"],
  "radar_scores": [80, 75, 70, 60, 100],
  "high_confidence": true,
  "verdict": "pass" | "fail" | "veto" | "insufficient_data",
  "data_version": "real-v1",
  "update_time": "2026-06-30T12:00:00"
}
```

---

## Known Cosmetic Issues

- **CJK labels in radar PNG**: If labels render as boxes, a CJK font (e.g., SimSun, WenQuanYi Zen Hei) is needed on the system. The PNG is still valid; this is a display-only issue.

