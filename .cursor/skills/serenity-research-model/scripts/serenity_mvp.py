#!/usr/bin/env python3
"""Serenity MVP: extract public post signals, evaluate prices, and build a model report."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Za-z0-9_])")
TICKER_RE = re.compile(r"(?<![A-Za-z0-9_$])([A-Z][A-Z0-9]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Za-z0-9_])")
STOP_TICKERS = {
    "AI", "API", "CEO", "CFO", "GPU", "CPU", "IPO", "ETF", "USA", "USD", "YTD",
    "YOY", "CAPEX", "CAGR", "WSB", "X", "DD", "IMO", "ATH", "FOMO", "IR",
    "HBM", "NAND", "DRAM", "SRAM", "INP", "CPO", "ASIC", "FPGA", "UPS", "RISC",
    "VDC", "CW", "FCF", "EPS", "EV", "TAM", "SAM", "SOM", "LLM", "ML", "AGI",
}

THEME_KEYWORDS = {
    "ai-infrastructure": ["ai", "gpu", "datacenter", "data center", "hyperscaler", "compute", "inference"],
    "semiconductor": ["semi", "semiconductor", "chip", "wafer", "foundry", "asic", "fpga"],
    "photonics-cpo": ["photonics", "cpo", "optical", "laser", "inp", "silicon photonics", "transceiver"],
    "memory-hbm": ["hbm", "dram", "nand", "memory", "micron", "sk hynix", "samsung"],
    "power-grid": ["power", "grid", "800v", "ups", "energy", "electricity", "transformer"],
    "robotics-physical-ai": ["robot", "robotics", "physical ai", "actuator", "gear", "humanoid"],
    "neocloud": ["neocloud", "cloud", "gpu cloud", "leasing", "financing"],
    "crypto": ["btc", "eth", "bitcoin", "ethereum", "coinbase", "crypto"],
}

EVIDENCE_KEYWORDS = {
    "customer-capex": ["capex", "hyperscaler", "customer", "order", "backlog", "supplier"],
    "technical-constraint": ["bottleneck", "chokepoint", "constraint", "scarce", "capacity", "qualification"],
    "financial-inflection": ["revenue", "margin", "eps", "guidance", "beat", "earnings", "fcf"],
    "patent-science": ["patent", "paper", "nature", "risc-v", "physics", "material"],
    "price-volume": ["breakout", "volume", "squeeze", "iv", "options", "volatility"],
    "policy": ["tariff", "subsidy", "chips act", "policy", "regulation", "export control"],
}

ROLE_KEYWORDS = {
    "raw-material": ["substrate", "inp", "wafer", "material", "fiber"],
    "equipment-test": ["equipment", "tester", "inspection", "metrology", "packaging", "coating"],
    "component": ["laser", "module", "transceiver", "controller", "sensor", "actuator"],
    "integrator": ["server", "rack", "system", "cloud", "datacenter", "data center"],
    "end-demand": ["hyperscaler", "openai", "microsoft", "google", "amazon", "meta", "tesla"],
}

CATALYST_KEYWORDS = ["earnings", "guidance", "shipment", "launch", "contract", "order", "approval", "tariff", "upgrade"]
RISK_KEYWORDS = ["risk", "downside", "wrong", "bear", "sell", "exit", "expensive", "dilution", "fraud", "short"]
HIGH_CONVICTION = ["highest conviction", "conviction", "favorite", "best", "massive", "undervalued", "mispriced"]
LOW_CONVICTION = ["maybe", "watch", "basket", "small idea", "not advice", "speculative"]


def parse_date(value: str) -> str:
    if not value:
        return ""
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    if value.endswith("Z"):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        y, m, d = map(int, match.groups())
        return dt.date(y, m, d).isoformat()
    return ""


def read_posts(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else data.get("posts", [])
    if suffix == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    raw = path.read_text(encoding="utf-8-sig")
    chunks = [c.strip() for c in re.split(r"\n\s*---\s*\n|\n\s*\n\s*\n", raw) if c.strip()]
    posts = []
    for idx, chunk in enumerate(chunks, 1):
        date = parse_date(chunk)
        posts.append({"id": f"text-{idx}", "created_at": date, "text": chunk, "author": "", "url": ""})
    return posts


def keyword_hits(text: str, mapping: dict[str, list[str]]) -> list[str]:
    lower = text.lower()
    hits = []
    for label, words in mapping.items():
        count = sum(1 for word in words if word in lower)
        if count:
            hits.append((label, count))
    return [label for label, _ in sorted(hits, key=lambda item: (-item[1], item[0]))]


def extract_tickers(text: str) -> list[str]:
    tickers = []
    cashtags = [m.group(1).upper() for m in CASHTAG_RE.finditer(text)]
    source = cashtags if cashtags else [m.group(1).upper() for m in TICKER_RE.finditer(text)]
    for ticker in source:
        if ticker not in STOP_TICKERS and not ticker.isdigit():
            tickers.append(ticker)
    return sorted(set(tickers))


def score_conviction(text: str) -> tuple[int, list[str]]:
    lower = text.lower()
    score = 1
    reasons = []
    if len(text) > 700:
        score += 1
        reasons.append("long-form")
    for phrase in HIGH_CONVICTION:
        if phrase in lower:
            negated = f"not my {phrase}" in lower or f"not {phrase}" in lower
            if negated:
                score -= 1
                reasons.append(f"negated-{phrase}")
            else:
                score += 2
                reasons.append(phrase)
    for phrase in LOW_CONVICTION:
        if phrase in lower:
            score -= 1
            reasons.append(phrase)
    if "not financial advice" in lower or "nfa" in lower:
        reasons.append("nfa-disclaimer")
    return max(0, min(5, score)), reasons


def infer_horizon(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["today", "intraday", "0dte", "scalp"]):
        return "intraday"
    if any(w in lower for w in ["week", "earnings", "near-term", "short term"]):
        return "days-weeks"
    if any(w in lower for w in ["month", "quarter", "cycle", "2026", "2027"]):
        return "months-quarters"
    if any(w in lower for w in ["years", "long term", "decade"]):
        return "multi-year"
    return "unspecified"


def compact_claim(text: str) -> str:
    sentences = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    claim = " ".join(sentences[:2]).strip()
    return claim[:500]


def extract(args: argparse.Namespace) -> None:
    posts = read_posts(Path(args.posts))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    signals = []
    post_counter = 0
    for post in posts:
        text = str(post.get("text") or post.get("full_text") or post.get("content") or "").strip()
        if not text:
            continue
        quoted_text = str(post.get("quoted_text") or post.get("quotedText") or "").strip()
        analysis_text = f"{text}\n\nQuoted: {quoted_text}" if quoted_text else text
        post_counter += 1
        tickers = extract_tickers(analysis_text)
        if not tickers:
            tickers = [""]
        themes = keyword_hits(analysis_text, THEME_KEYWORDS) or ["unclassified"]
        evidence = keyword_hits(analysis_text, EVIDENCE_KEYWORDS)
        roles = keyword_hits(analysis_text, ROLE_KEYWORDS)
        catalysts = [w for w in CATALYST_KEYWORDS if w in analysis_text.lower()]
        risks = [w for w in RISK_KEYWORDS if w in analysis_text.lower()]
        score, reasons = score_conviction(analysis_text)
        engagement_score = 0
        for key in ("likes", "retweets", "replies", "quotes", "bookmarks"):
            try:
                engagement_score += int(str(post.get(key) or "0").replace(",", ""))
            except ValueError:
                pass
        for ticker in tickers:
            signal_id = f"s{len(signals) + 1:05d}"
            signals.append({
                "signal_id": signal_id,
                "post_id": post.get("id") or post.get("post_id") or f"post-{post_counter}",
                "created_at": parse_date(str(post.get("created_at") or post.get("createdAtISO") or post.get("date") or "")),
                "author": post.get("author") or post.get("username") or "aleabitoreddit",
                "url": post.get("url") or "",
                "ticker": ticker,
                "asset_type": "equity-or-etf" if ticker else "theme-only",
                "text": text.replace("\r", " ").replace("\n", " "),
                "quoted_author": post.get("quoted_author") or post.get("quotedAuthor") or "",
                "quoted_text": quoted_text.replace("\r", " ").replace("\n", " "),
                "is_quote": "yes" if quoted_text else "no",
                "engagement_score": engagement_score,
                "theme": themes[0],
                "subtheme": ";".join(themes[1:]),
                "supply_chain_role": ";".join(roles),
                "bottleneck_claim": compact_claim(analysis_text) if any(w in analysis_text.lower() for w in ["bottleneck", "chokepoint", "scarce", "constraint"]) else "",
                "evidence_types": ";".join(evidence),
                "catalysts": ";".join(catalysts),
                "risk_markers": ";".join(risks),
                "horizon": infer_horizon(analysis_text),
                "conviction_score": score,
                "conviction_reasons": ";".join(reasons),
                "model_tags": ";".join(sorted(set(themes + evidence + roles))),
            })
    write_csv(out_dir / "signals.csv", signals)
    write_theme_summary(out_dir / "theme_summary.csv", signals)
    print(f"Extracted {len(signals)} signal rows from {post_counter} posts into {out_dir}")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_theme_summary(path: Path, signals: list[dict]) -> None:
    grouped = defaultdict(list)
    for row in signals:
        grouped[row["theme"]].append(row)
    rows = []
    for theme, items in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        evidence = Counter()
        roles = Counter()
        tickers = Counter()
        for item in items:
            evidence.update([x for x in item["evidence_types"].split(";") if x])
            roles.update([x for x in item["supply_chain_role"].split(";") if x])
            if item["ticker"]:
                tickers[item["ticker"]] += 1
        avg = sum(int(i["conviction_score"]) for i in items) / len(items)
        rows.append({
            "theme": theme,
            "signal_count": len(items),
            "unique_tickers": len(tickers),
            "top_tickers": ";".join(t for t, _ in tickers.most_common(10)),
            "top_evidence": ";".join(k for k, _ in evidence.most_common(5)),
            "top_supply_chain_roles": ";".join(k for k, _ in roles.most_common(5)),
            "avg_conviction_score": f"{avg:.2f}",
        })
    write_csv(path, rows)


def read_ticker_stats(path: Path) -> set[str]:
    tickers: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isupper() and parts[1].isdigit():
            tickers.add(parts[0])
    return tickers


def read_post_cashtags(path: Path) -> set[str]:
    tickers: set[str] = set()
    for post in read_posts(path):
        text = str(post.get("text") or post.get("full_text") or post.get("content") or "")
        quoted_text = str(post.get("quoted_text") or post.get("quotedText") or "")
        for match in CASHTAG_RE.finditer(f"{text}\n{quoted_text}"):
            ticker = match.group(1).upper()
            if ticker not in STOP_TICKERS and not ticker.isdigit():
                tickers.add(ticker)
    return tickers


def review_flags(row: dict) -> list[str]:
    text = f"{row.get('text', '')} {row.get('quoted_text', '')}".lower()
    flags = []
    if not row.get("ticker"):
        flags.append("theme_only_no_ticker")
    if row.get("is_quote") == "yes":
        flags.append("quote_context")
    if any(token in text for token in ["nfa", "not financial advice", "not advice", "disclaimer"]):
        flags.append("disclaimer")
    if any(token in text for token in ["lol", "joke", "meme", "sarcasm", "not my", "not a long", "not short"]):
        flags.append("ambiguous_rhetoric_or_negation")
    if row.get("conviction_reasons", "").startswith("negated-") or ";negated-" in row.get("conviction_reasons", ""):
        flags.append("negated_conviction")
    return flags


def has_cashtag(text: str, ticker: str) -> bool:
    if not ticker:
        return False
    return re.search(r"(?<![A-Za-z0-9_])\$" + re.escape(ticker) + r"(?![A-Za-z0-9_])", text or "") is not None


def semantic_review(row: dict) -> dict:
    ticker = row.get("ticker", "")
    text = row.get("text", "") or ""
    quoted = row.get("quoted_text", "") or ""
    lower = text.lower()
    in_main = has_cashtag(text, ticker)
    in_quote = has_cashtag(quoted, ticker)
    result = {
        "ticker_in_main_text": "yes" if in_main else "no",
        "ticker_in_quoted_text": "yes" if in_quote else "no",
        "view_owner": "serenity" if in_main else ("quoted_context" if in_quote else "none"),
        "timing_type": "unknown",
        "signal_type": "unknown",
        "review_decision": "deweight",
        "signal_weight": "0.50",
        "review_reason": "",
        "needs_followup": "no",
    }
    if not ticker and re.fullmatch(r"https?://\S+", text.strip()):
        result.update(
            view_owner="none",
            timing_type="link_only",
            signal_type="insufficient_text",
            review_decision="delete",
            signal_weight="0.00",
            review_reason="Only a link is present; no usable thesis text or ticker.",
        )
        return result
    if in_quote and not in_main:
        result.update(
            view_owner="quoted_context",
            timing_type="quote_context",
            signal_type="quote_only_context",
            review_decision="delete_from_this_signal",
            signal_weight="0.00",
            review_reason="Ticker appears only in quoted text, so it should not be treated as this post's Serenity thesis.",
        )
        return result
    if any(token in lower for token in ["ytd:", "ytd ", "called out multiple", "do you remember", "100-1000%", "10x'd", "return %"]):
        result.update(
            view_owner="serenity",
            timing_type="retrospective_performance_claim",
            signal_type="track_record_marketing_or_thesis_validation",
            review_decision="remove_from_forward_signal_keep_as_track_record_context",
            signal_weight="0.00",
            review_reason="Retrospective performance or thesis-validation post; keep as track-record context, not as a new forward signal.",
        )
    elif any(token in lower for token in ["crowdsourced list", "will start doing dd", "need some more ideas", "what's your best ideas"]):
        result.update(
            view_owner="crowdsourced_with_serenity_curation",
            timing_type="pre_research_idea_sourcing",
            signal_type="watchlist_candidate",
            review_decision="deweight",
            signal_weight="0.25",
            review_reason="Crowdsourced candidate list before completed due diligence; useful as attention map, not a strong thesis.",
            needs_followup="yes",
        )
    elif "random" in lower and "stocks i like today and why" in lower:
        result.update(
            view_owner="serenity",
            timing_type="current_broad_long_list",
            signal_type="broad_basket_with_short_rationale",
            review_decision="keep_deweighted",
            signal_weight="0.55",
            review_reason="Broad basket of names Serenity says he likes, with short rationales; keep but deweight at single-ticker level.",
        )
    elif any(token in lower for token in ["ended the day down", "crashed today", "flash crash", "here's why silver", "market manipulation of silver"]):
        result.update(
            view_owner="serenity",
            timing_type="post_event_explainer",
            signal_type="macro_market_structure_explanation",
            review_decision="keep_as_explainer_deweight",
            signal_weight="0.20",
            review_reason="Post-event market-structure explanation rather than a clear long/short thesis.",
        )
    elif any(token in lower for token in ["chokepoint", "tAM".lower(), "photonics", "supercycle", "i'll walk through", "it's not late", "risk/reward"]):
        result.update(
            view_owner="serenity",
            timing_type="active_thesis_or_update",
            signal_type="active_supply_chain_thesis",
            review_decision="keep",
            signal_weight="0.85",
            review_reason="Active thesis or update with supply-chain mechanism, TAM, risk/reward, or chokepoint reasoning.",
        )
    elif in_main:
        result.update(
            view_owner="serenity",
            timing_type="current_or_event_context",
            signal_type="serenity_main_text_signal",
            review_decision="keep_deweighted",
            signal_weight="0.50",
            review_reason="Ticker appears in Serenity's own text, but the post does not match a higher-confidence thesis pattern.",
        )
    return result


def auto_review(args: argparse.Namespace) -> None:
    rows = read_csv(Path(args.signals))
    reviewed = []
    for row in rows:
        out = dict(row)
        out.update(semantic_review(row))
        reviewed.append(out)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (Path(args.signals).stem + "_auto_reviewed.csv")
    write_csv(out_path, reviewed)
    counts = Counter(row["review_decision"] for row in reviewed)
    lines = ["# Semantic Review Summary", "", f"- Input rows: {len(rows)}", f"- Output: `{out_path.name}`", "", "## Decision Counts"]
    lines += [f"- {decision}: {count}" for decision, count in counts.most_common()]
    (out_dir / (Path(args.signals).stem + "_review_summary.md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Reviewed {len(reviewed)} rows into {out_path}")


def clean(args: argparse.Namespace) -> None:
    signals = read_csv(Path(args.signals))
    whitelist: set[str] = set()
    whitelist_source = ""
    if args.posts:
        whitelist = read_post_cashtags(Path(args.posts))
        whitelist_source = "source_posts_cashtags"
    elif args.ticker_stats:
        whitelist = read_ticker_stats(Path(args.ticker_stats))
        whitelist_source = "ticker_stats"
    else:
        raise SystemExit("clean requires --posts or --ticker-stats for ticker whitelist generation")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cleaned = []
    removed = []
    review = []
    quotes = []
    for row in signals:
        ticker = row.get("ticker", "")
        if ticker and ticker not in whitelist:
            removed_row = dict(row)
            removed_row["removal_reason"] = "ticker_not_in_source_cashtag_stats"
            removed.append(removed_row)
            continue
        flags = review_flags(row)
        clean_row = dict(row)
        clean_row["review_flags"] = ";".join(flags)
        cleaned.append(clean_row)
        if flags:
            review.append(clean_row)
        if row.get("is_quote") == "yes":
            quotes.append({
                "signal_id": row.get("signal_id", ""),
                "post_id": row.get("post_id", ""),
                "created_at": row.get("created_at", ""),
                "ticker": ticker,
                "url": row.get("url", ""),
                "quoted_author": row.get("quoted_author", ""),
                "text": row.get("text", ""),
                "quoted_text": row.get("quoted_text", ""),
            })
    write_csv(out_dir / "signals.csv", cleaned)
    write_theme_summary(out_dir / "theme_summary.csv", cleaned)
    write_csv(out_dir / "removed_ticker_candidates.csv", removed)
    write_csv(out_dir / "manual_review_queue.csv", review)
    write_csv(out_dir / "quote_relationships.csv", quotes)
    log = [
        "# Serenity MVP Correction Log",
        "",
        f"- Input signal rows: {len(signals)}",
        f"- Cleaned signal rows: {len(cleaned)}",
        f"- Removed ticker candidates: {len(removed)}",
        f"- Source cashtag whitelist size: {len(whitelist)}",
        f"- Whitelist source: {whitelist_source}",
        f"- Manual review queue rows: {len(review)}",
        f"- Quote relationship rows: {len(quotes)}",
        "",
        "## Rules Applied",
        "- Kept ticker rows only when the ticker exists in the source cashtag whitelist.",
        "- Preserved blank ticker rows as theme-only research context.",
        "- Flagged quoted-post rows because the thesis may belong to Serenity, the quoted account, or the interaction between them.",
        "- Flagged NFA/disclaimer language and ambiguous rhetoric for human review.",
        "- Flagged negated conviction phrases such as `not my highest conviction`.",
        "",
        "## Data Boundary",
        "- This is a public-post model, not a verified portfolio or P&L reconstruction.",
        "- Replies are only represented when present in the source CSV fields; this source primarily exposes quote context rather than a full conversation tree.",
    ]
    (out_dir / "correction_log.md").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"Cleaned {len(cleaned)} rows; removed {len(removed)} ticker candidates; review queue {len(review)} rows")


def load_prices(path: Path) -> list[tuple[dt.date, float]]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            date = parse_date(row.get("date", ""))
            close = row.get("close") or row.get("Close") or row.get("adj_close") or row.get("Adj Close")
            if date and close:
                try:
                    rows.append((dt.date.fromisoformat(date), float(close)))
                except ValueError:
                    continue
    return sorted(rows)


def max_drawdown(values: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst


def evaluate(args: argparse.Namespace) -> None:
    signals = read_csv(Path(args.signals))
    price_dir = Path(args.prices)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    price_cache: dict[str, list[tuple[dt.date, float]]] = {}
    rows = []
    horizons = [1, 5, 20, 60, 120]
    for sig in signals:
        ticker = sig.get("ticker", "")
        date = parse_date(sig.get("created_at", ""))
        if not ticker or not date:
            continue
        price_path = price_dir / f"{ticker}.csv"
        if not price_path.exists():
            continue
        if ticker not in price_cache:
            price_cache[ticker] = load_prices(price_path)
        prices = price_cache[ticker]
        post_date = dt.date.fromisoformat(date)
        idx = next((i for i, (d, _) in enumerate(prices) if d >= post_date), None)
        if idx is None:
            continue
        base_date, base_close = prices[idx]
        out = {
            "signal_id": sig["signal_id"],
            "ticker": ticker,
            "post_date": date,
            "entry_date": base_date.isoformat(),
            "entry_close": f"{base_close:.6g}",
        }
        for h in horizons:
            if idx + h < len(prices):
                close = prices[idx + h][1]
                out[f"ret_{h}d"] = f"{close / base_close - 1:.4f}"
            else:
                out[f"ret_{h}d"] = ""
        window = [p for _, p in prices[idx:min(len(prices), idx + 121)]]
        out["max_drawdown_120d"] = f"{max_drawdown(window):.4f}" if window else ""
        rows.append(out)
    write_csv(out_dir / "signal_evaluation.csv", rows)
    print(f"Evaluated {len(rows)} signal rows into {out_dir / 'signal_evaluation.csv'}")


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def report(args: argparse.Namespace) -> None:
    signals = read_csv(Path(args.signals))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    themes = Counter(row["theme"] for row in signals)
    evidence = Counter()
    roles = Counter()
    risks = Counter()
    tickers = Counter()
    horizons = Counter(row["horizon"] for row in signals)
    conviction_total = 0
    for row in signals:
        evidence.update([x for x in row["evidence_types"].split(";") if x])
        roles.update([x for x in row["supply_chain_role"].split(";") if x])
        risks.update([x for x in row["risk_markers"].split(";") if x])
        if row["ticker"]:
            tickers[row["ticker"]] += 1
        conviction_total += int(row["conviction_score"])
    avg_conviction = conviction_total / len(signals) if signals else 0
    lines = [
        "# Serenity Research Model Report",
        "",
        "## Data Boundary",
        f"- Signal rows analyzed: {len(signals)}",
        f"- Unique tickers: {len(tickers)}",
        "- Private profitability is not inferred from public posts.",
        "",
        "## Theme Map",
    ]
    lines += [f"- {k}: {v}" for k, v in themes.most_common()]
    lines += [
        "",
        "## Evidence Map",
    ]
    lines += [f"- {k}: {v}" for k, v in evidence.most_common()]
    lines += [
        "",
        "## Supply-Chain Roles",
    ]
    lines += [f"- {k}: {v}" for k, v in roles.most_common()]
    lines += [
        "",
        "## Ticker Concentration",
    ]
    lines += [f"- {k}: {v}" for k, v in tickers.most_common(20)]
    lines += [
        "",
        "## Horizon And Conviction",
    ]
    lines += [f"- {k}: {v}" for k, v in horizons.most_common()]
    lines.append(f"- Average conviction score: {avg_conviction:.2f} / 5")
    lines += [
        "",
        "## Risk Markers Mentioned",
    ]
    lines += [f"- {k}: {v}" for k, v in risks.most_common()] or ["- No explicit risk markers detected."]
    lines += [
        "",
        "## Reconstructed Research Checklist",
        "1. Start with a large AI infrastructure demand wave.",
        "2. Map the physical supply chain below the obvious mega-cap beneficiaries.",
        "3. Identify bottlenecks with scarce capacity, qualification friction, or technical barriers.",
        "4. Prefer under-covered suppliers where a small revenue inflection can re-rate the equity.",
        "5. Tie the thesis to public evidence: capex, customers, capacity, technical documents, or earnings.",
        "6. Track catalysts and falsifiers after the first post instead of only saving winners.",
        "7. Treat account influence and liquidity as part of the risk model.",
        "",
        "## Next Iteration",
        "- Add replies and quote posts to improve follow-up tracking.",
        "- Add price data to create `signal_evaluation.csv`.",
        "- Manually review high-conviction rows for false ticker extraction and sarcasm.",
    ]
    (out_dir / "serenity_model_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir / 'serenity_model_report.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract", help="Extract signal rows from public posts")
    p.add_argument("--posts", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=extract)
    p = sub.add_parser("evaluate", help="Evaluate signal rows with local price CSVs")
    p.add_argument("--signals", required=True)
    p.add_argument("--prices", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=evaluate)
    p = sub.add_parser("clean", help="Clean extracted signals and create manual review files")
    p.add_argument("--signals", required=True)
    p.add_argument("--posts")
    p.add_argument("--ticker-stats")
    p.add_argument("--out", required=True)
    p.set_defaults(func=clean)
    p = sub.add_parser("auto-review", help="Apply first-pass semantic review labels to signal rows")
    p.add_argument("--signals", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=auto_review)
    p = sub.add_parser("report", help="Build model report from signals.csv")
    p.add_argument("--signals", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
