"""Unified financial data cache — single source of truth.

Uses get_fina_reports with 25 curated key fields (covering income statement,
balance sheet, and cash flow). Replaces the previous split between
get_fina_performance (unreliable end_quarter filtering) and get_fina_reports.

Cached files under data/:
    fina_cache.parquet    — 25-field curated financial data (all stocks)
    fina_industry.parquet — L1/L2/L3 industry classification (all stocks)

Usage:
    # First build — CSI300
    python scripts/build_cache.py --universe 000300.SH --quarters 8

    # CSI1000 (longer)
    python scripts/build_cache.py --universe 000852.SH --quarters 8 --batch-size 50

    # Incremental
    python scripts/build_cache.py --incremental

    # Export to CSV
    python scripts/build_cache.py --export-csv fina_data.csv

    # Show summary
    python scripts/build_cache.py --info
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import data as data_mod
from scripts import universe as uni_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FINA_CACHE = CACHE_DIR / "fina_cache.parquet"
INDU_CACHE = CACHE_DIR / "fina_industry.parquet"

# ── Cache freshness constants ─────────────────────────────────────
# Industry classification changes very infrequently; 7 days is safe.
INDU_CACHE_MAX_AGE_HOURS = 168  # 7 days
# Financial data is quarterly — rebuild once per day at most.
FINA_CACHE_MAX_AGE_HOURS = 24   # 1 day

# ── 25 key financial fields ─────────────────────────────────────────────
# Selected from get_fina_reports' 320+ columns for maximum analytical value
# with minimal redundancy.

KEY_FIELDS: list[str] = [
    # Income statement (9)
    "is_revenue",               # 营业收入
    "is_oper_cost",             # 营业成本
    "is_gross_profit",          # 毛利
    "is_sell_exp",              # 销售费用
    "is_admin_exp",             # 管理费用
    "is_rd_exp",                # 研发费用
    "is_fin_exp",              # 财务费用
    "is_operate_profit",        # 营业利润
    "is_total_profit",          # 利润总额
    "is_n_income_attr_p",       # 归母净利润
    "is_n_income",              # 净利润
    # Balance sheet (10)
    "bs_total_assets",          # 总资产
    "bs_total_liab",            # 总负债
    "bs_total_hldr_eqy_exc_min_int",  # 归母权益
    "bs_total_cur_assets",      # 流动资产
    "bs_total_cur_liab",        # 流动负债
    "bs_money_cap",             # 货币资金
    "bs_inventory",             # 存货
    "bs_acct_payable",          # 应付账款
    "bs_goodwill",              # 商誉
    "bs_lt_borr",               # 长期借款
    # Cash flow (4)
    "cfs_net_cash_operating",   # 经营活动现金流净额
    "cfs_net_cash_investing",   # 投资活动现金流净额
    "cfs_net_cash_financing",   # 筹资活动现金流净额
    "cfs_end_cash_equiv",       # 期末现金余额
]

# ── Derived ratio definitions ────────────────────────────────────────────
# Each ratio: (display_name, formula_fn, pct)
# formula_fn takes a row (pd.Series) and returns a float or None


def _div(a, b):
    """Safe division: returns None if either is missing or zero."""
    if a is None or b is None:
        return None
    if pd.isna(a) or pd.isna(b):
        return None
    return float(a) / float(b) if float(b) != 0 else None


def _pct(a, b):
    r = _div(a, b)
    return r * 100 if r is not None else None


RATIOS = [
    # profitability
    ("roe",              lambda r: _pct(r.get("is_n_income_attr_p"), r.get("bs_total_hldr_eqy_exc_min_int"))),
    ("roa",              lambda r: _pct(r.get("is_n_income_attr_p"), r.get("bs_total_assets"))),
    ("gross_margin",     lambda r: _pct(_div(r.get("is_revenue"), None) if r.get("is_gross_profit") is None
                          else r.get("is_gross_profit"), r.get("is_revenue"))
                          if r.get("is_revenue") is not None else (
                          _pct(r.get("is_revenue") - r.get("is_oper_cost"), r.get("is_revenue"))
                          if r.get("is_oper_cost") is not None else None)),
    ("net_margin",       lambda r: _pct(r.get("is_n_income_attr_p"), r.get("is_revenue"))),
    ("op_margin",        lambda r: _pct(r.get("is_operate_profit"), r.get("is_revenue"))),
    # leverage
    ("debt_ratio",       lambda r: _pct(r.get("bs_total_liab"), r.get("bs_total_assets"))),
    ("equity_multiplier",lambda r: _div(r.get("bs_total_assets"), r.get("bs_total_hldr_eqy_exc_min_int"))),
    ("current_ratio",    lambda r: _div(r.get("bs_total_cur_assets"), r.get("bs_total_cur_liab"))),
    # efficiency
    ("asset_turnover",   lambda r: _div(r.get("is_revenue"), r.get("bs_total_assets"))),
    ("inv_turnover",     lambda r: _div(r.get("is_oper_cost"), r.get("bs_inventory"))),
    # cash flow quality
    ("cfo_to_np",        lambda r: _div(r.get("cfs_net_cash_operating"), r.get("is_n_income_attr_p"))),
    ("cfo_to_revenue",   lambda r: _div(r.get("cfs_net_cash_operating"), r.get("is_revenue"))),
    # growth (需要两期，调用方处理)
    # risk flags
    ("goodwill_to_equity", lambda r: _pct(r.get("bs_goodwill"), r.get("bs_total_hldr_eqy_exc_min_int"))),
    ("rd_to_revenue",    lambda r: _pct(r.get("is_rd_exp"), r.get("is_revenue"))),
]

RATIO_NAMES = [r[0] for r in RATIOS]
RATIO_LABELS: dict[str, str] = {
    "roe": "ROE(%)", "roa": "ROA(%)", "gross_margin": "毛利率(%)",
    "net_margin": "净利率(%)", "op_margin": "营业利润率(%)",
    "debt_ratio": "资产负债率(%)", "equity_multiplier": "权益乘数",
    "current_ratio": "流动比率", "asset_turnover": "资产周转率",
    "inv_turnover": "存货周转率", "cfo_to_np": "现金流/净利润",
    "cfo_to_revenue": "现金流/营收", "goodwill_to_equity": "商誉/净资产(%)",
    "rd_to_revenue": "研发/营收(%)",
}


# ── Industry ─────────────────────────────────────────────────────────────

def fetch_industry() -> pd.DataFrame:
    import panda_data
    df = panda_data.get_industry_constituents(level="L1")
    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame()
    df["fetch_time"] = datetime.now(timezone.utc).isoformat()
    return df


def get_industry_map(industry_df: pd.DataFrame) -> dict[str, dict[str, str]]:
    if industry_df.empty:
        return {}
    dedup = (industry_df.sort_values("in_date", ascending=False)
             .drop_duplicates(subset=["stock_symbol"], keep="first"))
    return {
        row["stock_symbol"]: {
            "l1_name": row.get("l1_name", ""),
            "l1_code": row.get("l1_code", ""),
            "l2_name": row.get("l2_name", ""),
            "l3_name": row.get("l3_name", ""),
        }
        for _, row in dedup.iterrows()
    }


def get_industry_peers(industry_df: pd.DataFrame, l1_name: str) -> list[str]:
    if industry_df.empty or "l1_name" not in industry_df.columns:
        return []
    return sorted(industry_df[industry_df["l1_name"] == l1_name]["stock_symbol"].unique().tolist())


# ── Fetch ────────────────────────────────────────────────────────────────

def fetch_financials(
    symbols: list[str],
    start_quarter: str,
    end_quarter: str,
    batch_size: int = 50,
) -> pd.DataFrame:
    """拉取 get_fina_reports，只取 KEY_FIELDS 来减少传输量。"""
    import panda_data

    rows = []
    total = len(symbols)
    for i in range(0, total, batch_size):
        batch = symbols[i:i + batch_size]
        try:
            df = panda_data.get_fina_reports(
                symbol=batch,
                start_quarter=start_quarter,
                end_quarter=end_quarter,
                is_latest=True,
                fields=KEY_FIELDS + ["symbol", "quarter", "date"],
            )
        except Exception as e:
            print(f"\n[warn] batch {i // batch_size} failed: {e}", file=sys.stderr)
            continue
        if df is None or (hasattr(df, "empty") and df.empty):
            continue
        # Ensure all KEY_FIELDS exist
        for f in KEY_FIELDS:
            if f not in df.columns:
                df[f] = None
        df["fetch_time"] = datetime.now(timezone.utc).isoformat()
        rows.append(df)

    if not rows:
        return pd.DataFrame(columns=["symbol", "quarter"] + KEY_FIELDS + ["date", "fetch_time"])
    return pd.concat(rows, ignore_index=True)


def resolve_quarters(n: int) -> list[str]:
    from datetime import datetime
    now = datetime.now()
    curr_q = (now.month - 1) // 3 + 1
    year, q = now.year, curr_q
    quarters = []
    for _ in range(n):
        q -= 1
        if q == 0:
            q = 4
            year -= 1
        quarters.append(f"{year}q{q}")
    return quarters


# ── File operations ──────────────────────────────────────────────────────

def _load_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _save_parquet(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)
    n_stocks = df["symbol"].nunique() if "symbol" in df.columns else 0
    print(f"[ok] {path.name}: {len(df)} rows, {n_stocks} stocks", file=sys.stderr)


def _cache_is_fresh(path: Path, max_age_hours: int) -> bool:
    """Return True if the cache file exists and is within max_age_hours."""
    if not path.exists():
        return False
    age_sec = time.time() - path.stat().st_mtime
    return age_sec <= max_age_hours * 3600


def _cache_summary(df: pd.DataFrame, path: Path) -> dict:
    if df.empty:
        return {"rows": 0, "stocks": 0, "cols": 0, "quarters": [], "mb": 0, "path": path}
    return {
        "rows": len(df),
        "stocks": df["symbol"].nunique() if "symbol" in df.columns else 0,
        "cols": len(df.columns),
        "quarters": sorted(df["quarter"].unique()) if "quarter" in df.columns else [],
        "mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
        "path": path,
    }


# ── Ratio computation ────────────────────────────────────────────────────

def compute_ratios_df(df: pd.DataFrame) -> pd.DataFrame:
    """Add computed ratio columns to the financial data DataFrame."""
    result = df.copy()
    for name, fn in RATIOS:
        try:
            result[name] = df.apply(fn, axis=1)
        except Exception:
            result[name] = None
    return result


# ── Export ────────────────────────────────────────────────────────────────

def export_full_csv(
    df: pd.DataFrame,
    indu: pd.DataFrame,
    path: str,
    include_raw: bool = True,
    include_ratios: bool = True,
) -> str:
    """Export cached data to a flat CSV with ratios and industry labels.

    Args:
        df: Financial data DataFrame.
        indu: Industry cache DataFrame.
        path: Output CSV path.
        include_raw: Include raw 25 accounting fields.
        include_ratios: Include computed ratios.

    Returns:
        The output file path.
    """
    ind_map = get_industry_map(indu)

    out = df.copy()
    # Add industry labels
    out["l1_name"] = out["symbol"].map(lambda s: ind_map.get(s, {}).get("l1_name", ""))
    out["l2_name"] = out["symbol"].map(lambda s: ind_map.get(s, {}).get("l2_name", ""))
    out["l3_name"] = out["symbol"].map(lambda s: ind_map.get(s, {}).get("l3_name", ""))

    if include_ratios:
        out = compute_ratios_df(out)

    # Build column order: metadata → raw fields → ratios → industry
    meta = ["symbol", "quarter", "date", "l1_name", "l2_name", "l3_name"]
    available_meta = [c for c in meta if c in out.columns]
    raw_cols = [c for c in KEY_FIELDS if c in out.columns and include_raw]
    ratio_cols = [r[0] for r in RATIOS if r[0] in out.columns and include_ratios]
    extra = [c for c in out.columns if c not in available_meta + raw_cols + ratio_cols]

    ordered = available_meta + raw_cols + ratio_cols + extra
    out = out[ordered]
    # Sort by symbol then quarter
    out = out.sort_values(["symbol", "quarter"]).reset_index(drop=True)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[ok] exported {len(out)} rows × {len(out.columns)} cols → {path}", file=sys.stderr)
    return path


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Build unified financial data cache")
    p.add_argument("--universe", default="000300.SH", help="Index for stock pool")
    p.add_argument("--quarters", type=int, default=8, help="Number of trailing quarters")
    p.add_argument("--incremental", action="store_true")
    p.add_argument("--industry-only", action="store_true", help="Only refresh industry cache")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--info", action="store_true", help="Show cache summary")
    p.add_argument("--export-csv", default=None, help="Export full dataset to CSV")
    p.add_argument("--stock", default=None, help="Print one stock's financial history")
    args = p.parse_args()

    # ── Read-only modes (no auth) ──
    if args.info:
        for label, path in [("Financials", FINA_CACHE), ("Industry", INDU_CACHE)]:
            s = _cache_summary(_load_parquet(path), path)
            print(f"\n{label}:")
            print(f"  File:       {s['path']}  ({s['mb']} MB)")
            print(f"  Rows:       {s['rows']}")
            print(f"  Stocks:     {s['stocks']}")
            print(f"  Fields:     {s['cols']}")
            print(f"  Quarters:   {s['quarters']}")
        return 0

    if args.stock:
        df = _load_parquet(FINA_CACHE)
        indu = _load_parquet(INDU_CACHE)
        _print_stock(df, indu, args.stock)
        return 0

    if args.export_csv:
        df = _load_parquet(FINA_CACHE)
        indu = _load_parquet(INDU_CACHE)
        if df.empty:
            print("[error] Cache is empty. Run build first.", file=sys.stderr)
            return 1
        export_full_csv(df, indu, args.export_csv)
        return 0

    # ── Auth ──
    try:
        data_mod.init_panda_data()
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    # ── Industry (always refresh — single 0.2s call, skip if fresh) ──
    if not args.industry_only:
        if _cache_is_fresh(INDU_CACHE, INDU_CACHE_MAX_AGE_HOURS) and not args.incremental:
            print("[info] industry cache is fresh (within 7d), skipping", file=sys.stderr)
        else:
            print("[fetch] industry classification...", file=sys.stderr)
            try:
                indu = fetch_industry()
                if not indu.empty:
                    _save_parquet(indu, INDU_CACHE)
            except Exception as e:
                print(f"[warn] industry: {e}", file=sys.stderr)

    if args.industry_only:
        return 0

    # ── Universe ──
    ref_date = data_mod.get_last_trade_date() or "20260731"
    weights = uni_mod.resolve_universe(index_symbol=args.universe, date=ref_date)
    symbols = uni_mod.filter_universe(weights)

    # ── Quarters ──
    target_qs = resolve_quarters(args.quarters)
    target_qs.sort()
    start_q, end_q = target_qs[0], target_qs[-1]

    # ── Existing cache ──
    existing = _load_parquet(FINA_CACHE)
    if not args.incremental and _cache_is_fresh(FINA_CACHE, FINA_CACHE_MAX_AGE_HOURS):
        print(f"[info] financial cache is fresh (within {FINA_CACHE_MAX_AGE_HOURS}h), use --incremental to force refresh",
              file=sys.stderr)
        return 0
    if args.incremental and not existing.empty:
        existing_qs = set(existing["quarter"].unique())
        new_qs = [qq for qq in target_qs if qq not in existing_qs]
        if not new_qs:
            print("[info] cache up to date", file=sys.stderr)
            return 0
        print(f"[info] incremental: {new_qs}", file=sys.stderr)

    # ── Fetch ──
    print(f"[fetch] {len(symbols)} stocks × {target_qs[0]}→{target_qs[-1]} ({len(target_qs)} quarters)",
          file=sys.stderr)
    t0 = time.time()
    new = fetch_financials(symbols, start_q, end_q, batch_size=args.batch_size)
    elapsed = time.time() - t0
    print(f"[fetch] done: {len(new)} rows in {elapsed:.0f}s", file=sys.stderr)

    if new.empty:
        print("[warn] no data fetched", file=sys.stderr)
        return 1

    # ── Merge ──
    if not existing.empty:
        combined = pd.concat([existing, new], ignore_index=True)
        combined = combined.sort_values("fetch_time", ascending=False)
        combined = combined.drop_duplicates(subset=["symbol", "quarter"], keep="first")
        combined = combined.sort_values(["symbol", "quarter"]).reset_index(drop=True)
    else:
        combined = new

    _save_parquet(combined, FINA_CACHE)

    # Summary
    s = _cache_summary(combined, FINA_CACHE)
    print(f"\n  最终: {s['rows']} rows, {s['stocks']} stocks, "
          f"{s['cols']} cols, {s['mb']} MB", file=sys.stderr)
    return 0


# ── Single stock print ───────────────────────────────────────────────────

def _format(val, unit: str = "") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    v = float(val)
    if unit == "%": return f"{v:+.2f}%"
    if abs(v) >= 1e8: return f"{v / 1e8:,.2f} 亿"
    if abs(v) >= 1e4: return f"{v / 1e4:,.2f} 万"
    return f"{v:,.2f}"


def _print_stock(df: pd.DataFrame, indu: pd.DataFrame, symbol: str):
    stock = df[df["symbol"] == symbol].sort_values("quarter")
    if stock.empty:
        print(f"No data for {symbol}")
        return

    ind_map = get_industry_map(indu)
    ind_info = ind_map.get(symbol, {})
    ind_name = ind_info.get("l1_name", "未知")

    # Compute ratios
    stock_r = compute_ratios_df(stock)

    # Get industry peer medians for latest quarter
    latest_q = stock_r["quarter"].max()
    latest = stock_r[stock_r["quarter"] == latest_q].iloc[0]
    peer_medians: dict[str, float] = {}
    if ind_name != "未知":
        peers = get_industry_peers(indu, ind_name)
        peer_df = df[df["symbol"].isin(peers)]
        peer_latest = compute_ratios_df(peer_df[peer_df["quarter"] == latest_q])
        if not peer_latest.empty:
            for rn, _ in RATIOS:
                vals = peer_latest[rn].dropna()
                if len(vals) > 0:
                    peer_medians[rn] = float(vals.median())

    print(f"\n{'=' * 75}")
    print(f"  {symbol}  ·  {ind_name} ({latest_q})")
    print(f"{'=' * 75}")

    # Key raw values
    raw_pairs = [
        ("is_revenue", "营业收入"), ("is_n_income_attr_p", "归母净利润"),
        ("bs_total_assets", "总资产"), ("bs_total_liab", "总负债"),
        ("bs_total_hldr_eqy_exc_min_int", "归母权益"),
        ("cfs_net_cash_operating", "经营现金流"),
        ("bs_money_cap", "货币资金"), ("bs_goodwill", "商誉"),
        ("bs_lt_borr", "长期借款"),
    ]
    print(f"\n  ── 核心绝对值 ──")
    for col, label in raw_pairs:
        val = latest.get(col) if col in stock_r.columns else None
        print(f"    {label:<12}: {_format(val)}")

    # Ratio table with industry comparison
    print(f"\n  ── 关键比率 vs 行业中位 ──")
    print(f"  {'比率':<18} {'本公司':>12} {'行业中位':>12} {'差异':>10}")
    print(f"  {'─' * 55}")
    for rn, rfn in RATIOS:
        val = latest.get(rn) if rn in stock_r.columns else None
        med = peer_medians.get(rn)
        fmt_val = f"{val:.1f}%" if val is not None and rn in ("roe","roa","gross_margin","net_margin","op_margin","debt_ratio","goodwill_to_equity","rd_to_revenue") else (f"{val:.2f}" if val is not None else "N/A")
        fmt_med = f"{med:.1f}%" if med is not None and rn in ("roe","roa","gross_margin","net_margin","op_margin","debt_ratio","goodwill_to_equity","rd_to_revenue") else (f"{med:.2f}" if med is not None else "—")
        diff = ""
        if val is not None and med is not None:
            d = float(val) - float(med)
            diff = f"{d:+.1f}" if rn in ("roe","roa","gross_margin","net_margin","op_margin","debt_ratio","goodwill_to_equity","rd_to_revenue") else f"{d:+.2f}"
        print(f"  {RATIO_LABELS.get(rn, rn):<18} {fmt_val:>12} {fmt_med:>12} {diff:>10}")

    # Quarter trend: quick table
    print(f"\n  ── 季度趋势 (部分指标) ──")
    qs = stock_r["quarter"].tolist()
    trend_cols = ["roe", "net_margin", "debt_ratio", "cfo_to_np"]
    header = f"  {'quarter':<10}" + "".join(f"  {RATIO_LABELS.get(c, c):>12}" for c in trend_cols)
    print(header)
    print(f"  {'─' * 65}")
    for _, row in stock_r.iterrows():
        q = row["quarter"]
        line = f"  {q:<10}"
        for c in trend_cols:
            v = row.get(c)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                line += f"  {'N/A':>12}"
            elif c == "cfo_to_np":
                line += f"  {float(v):>12.2f}"
            else:
                line += f"  {float(v):>11.1f}%"
        print(line)

    print()


if __name__ == "__main__":
    sys.exit(main())
