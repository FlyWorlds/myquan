"""Comprehensive single-stock financial analysis report.

Produces a wall-to-wall detailed analysis covering 8 dimensions:
1. Company profile (industry, peers, audit opinion)
2. Core financials × 7 quarters with YoY growth
3. Profitability decomposition (gross → operating → net margins)
4. DuPont ROE breakdown (margin × turnover × leverage)
5. Balance sheet structure (asset/liability composition, liquidity, goodwill risk)
6. Cash flow quality (CFO coverage, three-segment balance, FCF)
7. Growth trajectory (revenue/profit/asset trend with acceleration/deceleration)
8. Red flag detection (12 automated checks with severity levels)
9. Industry percentile ranking (vs all same-industry peers)

Usage:
    python scripts/analyze_stock.py 600267.SH
    python scripts/analyze_stock.py 000001.SZ --csv   # output CSV row
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_cache import (
    FINA_CACHE, INDU_CACHE,
    _load_parquet, get_industry_map, get_industry_peers,
    compute_ratios_df, RATIO_LABELS, KEY_FIELDS, RATIOS,
)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

# ── Format ────────────────────────────────────────────────────────────────

def _fmt(val, unit: str = "") -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    v = float(val)
    if unit == "%": return f"{v:+.2f}%"
    if unit == "pct": return f"{v:.2f}%"
    if abs(v) >= 1e8: return f"{v / 1e8:,.2f} 亿"
    if abs(v) >= 1e4: return f"{v / 1e4:,.2f} 万"
    return f"{v:,.2f}"

def _ratio_fmt(val, is_pct: bool = True) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)): return "N/A"
    return f"{float(val):.1f}%" if is_pct else f"{float(val):.2f}"

def _diff(v1, v2, is_pct: bool = False) -> str:
    if v1 is None or v2 is None: return "—"
    if (isinstance(v1, float) and np.isnan(v1)) or (isinstance(v2, float) and np.isnan(v2)):
        return "—"
    d = float(v1) - float(v2)
    return f"{d:+.1f}%" if is_pct else f"{d:+.2f}"


# ── Analysis functions ────────────────────────────────────────────────────

def _build_multi_year_table(stock: pd.DataFrame) -> str:
    """核心财务指标 × 所有季度的对比表（含 YoY 增速）。"""
    stock = stock.sort_values("quarter")
    qs = stock["quarter"].tolist()

    # Rows: absolute values + YoY growth
    metrics = [
        ("营业收入", "is_revenue", True),
        ("营业成本", "is_oper_cost", True),
        ("毛利", "is_gross_profit", True),
        ("销售费用", "is_sell_exp", True),
        ("管理费用", "is_admin_exp", True),
        ("研发费用", "is_rd_exp", True),
        ("财务费用", "is_fin_exp", True),
        ("营业利润", "is_operate_profit", True),
        ("利润总额", "is_total_profit", True),
        ("归母净利润", "is_n_income_attr_p", True),
        ("净利润", "is_n_income", True),
    ]

    lines = []
    # Header
    hdr = f"  {'指标':<12}"
    for q in qs:
        hdr += f"  {q:>12}"
    hdr += "  | 趋势"
    lines.append(hdr)
    lines.append(f"  {'─' * (14 + 14 * len(qs) + 10)}")

    for label, col, is_money in metrics:
        line = f"  {label:<12}"
        vals = []
        for _, row in stock.iterrows():
            v = row.get(col)
            vals.append(v)
            line += f"  {_fmt(v):>12}"
        # Trend arrow
        if len(vals) >= 2:
            v1, v2 = vals[0], vals[-1]
            if v1 is not None and v2 is not None and not np.isnan(v1) and not np.isnan(v2) and v1 != 0:
                chg = (float(v2) / float(v1) - 1) * 100
                arrow = "↗" if chg > 5 else ("→" if abs(chg) <= 5 else "↘")
                line += f"  {arrow} {chg:+.1f}%"
            else:
                line += "  —"
        else:
            line += "  —"
        lines.append(line)

    return "\n".join(lines)


def _build_profitability_decomp(stock: pd.DataFrame) -> str:
    """盈利能力逐层拆解：毛利率 → 营业利润率 → 净利率，含各季度。"""
    stock = stock.sort_values("quarter")
    qs = stock["quarter"].tolist()

    lines = ["  盈利能力逐层拆解："]
    lines.append(f"  {'季度':<10}  {'毛利率':>8}  {'营业利润率':>10}  {'净利率':>8}  "
                 f"{'费用率(销售+管理+研发+财务)':>20}  {'利润留存率':>10}")
    lines.append(f"  {'─' * 75}")

    for _, row in stock.iterrows():
        q = row["quarter"]
        rev = row.get("is_revenue")
        cost = row.get("is_oper_cost")
        gp = row.get("is_gross_profit")
        op = row.get("is_operate_profit")
        np_p = row.get("is_n_income_attr_p")
        sell = row.get("is_sell_exp") or 0
        admin = row.get("is_admin_exp") or 0
        rd = row.get("is_rd_exp") or 0
        fin = row.get("is_fin_exp") or 0

        gm = _ratio_fmt((gp / rev * 100) if gp and rev else
                        ((rev - cost) / rev * 100) if rev and cost else None)
        om = _ratio_fmt((op / rev * 100) if op and rev else None)
        nm = _ratio_fmt((np_p / rev * 100) if np_p and rev else None)
        exp_rate = _ratio_fmt(((sell + admin + rd + fin) / rev * 100) if rev and rev != 0 else None)
        retention = _ratio_fmt((np_p / (op or 1) * 100) if np_p and op and op != 0 else None)

        lines.append(f"  {q:<10}  {gm:>8}  {om:>10}  {nm:>8}  {exp_rate:>20}  {retention:>10}")

    return "\n".join(lines)


def _build_dupont(stock: pd.DataFrame) -> str:
    """DuPont ROE 分解：每季度 ROE = 净利率 × 资产周转率 × 权益乘数。"""
    stock = stock.sort_values("quarter")
    qs = stock["quarter"].tolist()

    lines = ["  DuPont ROE 分解 (ROE = 净利率 × 总资产周转率 × 权益乘数):"]
    lines.append(f"  {'季度':<10}  {'ROE':>8}  {'= 净利率':>10}  {'× 周转率':>10}  {'× 权益乘数':>12}")
    lines.append(f"  {'─' * 55}")

    for _, row in stock.iterrows():
        q = row["quarter"]
        np_p = row.get("is_n_income_attr_p")
        rev = row.get("is_revenue")
        ta = row.get("bs_total_assets")
        eq = row.get("bs_total_hldr_eqy_exc_min_int")

        roe = np_p / eq * 100 if np_p and eq and eq != 0 else None
        nm = np_p / rev * 100 if np_p and rev and rev != 0 else None
        at = rev / ta if rev and ta and ta != 0 else None
        em = ta / eq if ta and eq and eq != 0 else None

        lines.append(f"  {q:<10}  {_ratio_fmt(roe):>8}  {_ratio_fmt(nm):>10}  "
                     f"{_ratio_fmt(at, False):>10}  {_ratio_fmt(em, False):>12}")

    # Interpretation
    if qs:
        latest = stock.iloc[-1]
        np_p2 = latest.get("is_n_income_attr_p")
        rev2 = latest.get("is_revenue")
        ta2 = latest.get("bs_total_assets")
        eq2 = latest.get("bs_total_hldr_eqy_exc_min_int")
        nm2 = np_p2 / rev2 * 100 if np_p2 and rev2 and rev2 != 0 else None
        at2 = rev2 / ta2 if rev2 and ta2 and ta2 != 0 else None
        em2 = ta2 / eq2 if ta2 and eq2 and eq2 != 0 else None

        lines.append(f"\n  解读 (最新期 {qs[-1]}):")
        if nm2 is not None and nm2 < 5:
            lines.append(f"    ⚠️ 净利率仅 {nm2:.1f}%，盈利能力偏弱")
        if at2 is not None and at2 < 0.3:
            lines.append(f"    ⚠️ 资产周转率 {at2:.2f}，资本密集型或资产效率低")
        if em2 is not None and em2 > 5:
            lines.append(f"    ⚠️ 权益乘数 {em2:.1f}×，高杠杆经营")
        if nm2 is not None and at2 is not None and em2 is not None:
            if nm2 >= 10 and at2 >= 0.5 and em2 <= 3:
                lines.append(f"    ✅ 三因素均衡健康")

    return "\n".join(lines)


def _build_balance_sheet_health(stock: pd.DataFrame, ind_medians: dict) -> str:
    """资产负债表健康度分析。"""
    latest = stock.sort_values("quarter").iloc[-1]
    q = latest["quarter"]

    ta = latest.get("bs_total_assets")
    tl = latest.get("bs_total_liab")
    eq = latest.get("bs_total_hldr_eqy_exc_min_int")
    ca = latest.get("bs_total_cur_assets")
    cl = latest.get("bs_total_cur_liab")
    mc = latest.get("bs_money_cap")
    inv = latest.get("bs_inventory")
    ap = latest.get("bs_acct_payable")
    gw = latest.get("bs_goodwill")
    lt_borr = latest.get("bs_lt_borr")

    dr = tl / ta * 100 if tl and ta else None
    cr = ca / cl if ca and cl else None
    gw_eq = gw / eq * 100 if gw and eq and eq != 0 else None
    lt_eq = lt_borr / eq * 100 if lt_borr and eq and eq != 0 else None

    lines = [f"  资产负债表健康度 ({q}):"]
    lines.append(f"    总资产:          {_fmt(ta)}")
    lines.append(f"    总负债:          {_fmt(tl)}")
    lines.append(f"    归母权益:         {_fmt(eq)}")
    lines.append(f"    ———————————————")
    lines.append(f"    资产负债率:       {_ratio_fmt(dr)}   (行业: {_ratio_fmt(ind_medians.get('debt_ratio'))})")
    lines.append(f"    流动比率:         {_ratio_fmt(cr, False)}   (行业: {_ratio_fmt(ind_medians.get('current_ratio'), False)})")
    lines.append(f"    ———————————————")
    lines.append(f"    货币资金:         {_fmt(mc)}     (现金储备)")
    lines.append(f"    存货:            {_fmt(inv)}     (周转: {_ratio_fmt(ind_medians.get('inv_turnover'), False) if ind_medians else 'N/A'})")
    lines.append(f"    应付账款:         {_fmt(ap)}")
    lines.append(f"    商誉/净资产:       {_ratio_fmt(gw_eq)}   (行业: {_ratio_fmt(ind_medians.get('goodwill_to_equity'))})")
    lines.append(f"    长期借款/净资产:    {_ratio_fmt(lt_eq)}")

    # Risk flags
    flags = []
    if dr is not None and dr > 70: flags.append(f"⚠️ 资产负债率偏高 ({dr:.1f}%)")
    if cr is not None and cr < 1: flags.append(f"🔴 流动比率 < 1 ({cr:.2f})，短期偿债压力大")
    if gw_eq is not None and gw_eq > 30: flags.append(f"🔴 商誉占净资产 {gw_eq:.1f}%，减值风险高")
    if lt_eq is not None and lt_eq > 100: flags.append(f"⚠️ 长期借款超过净资产 ({lt_eq:.1f}%)")
    if flags:
        lines.append(f"\n    风险提示:")
        for f in flags: lines.append(f"      {f}")

    return "\n".join(lines)


def _build_cashflow_quality(stock: pd.DataFrame, ind_medians: dict) -> str:
    """现金流质量分析。"""
    stock = stock.sort_values("quarter")
    lines = ["  现金流质量分析:"]
    lines.append(f"  {'季度':<10}  {'经营CF':>14}  {'投资CF':>14}  {'筹资CF':>14}  {'期末现金':>14}  {'CFO/NP':>8}  {'CFO/Rev':>8}")
    lines.append(f"  {'─' * 90}")

    for _, row in stock.iterrows():
        q = row["quarter"]
        cfo = row.get("cfs_net_cash_operating")
        cfi = row.get("cfs_net_cash_investing")
        cff = row.get("cfs_net_cash_financing")
        end_cash = row.get("cfs_end_cash_equiv")
        np_p = row.get("is_n_income_attr_p")
        rev = row.get("is_revenue")

        cfo_np = cfo / np_p if cfo and np_p and np_p != 0 else None
        cfo_rev = cfo / rev if cfo and rev and rev != 0 else None

        lines.append(f"  {q:<10}  {_fmt(cfo):>14}  {_fmt(cfi):>14}  {_fmt(cff):>14}  "
                     f"{_fmt(end_cash):>14}  {_ratio_fmt(cfo_np, False):>8}  {_ratio_fmt(cfo_rev, False):>8}")

    # FCF & quality assessment
    latest = stock.iloc[-1]
    cfo_l = latest.get("cfs_net_cash_operating")
    cfi_l = latest.get("cfs_net_cash_investing")
    fcf = cfo_l + cfi_l if cfo_l is not None and cfi_l is not None else None
    cfo_np_l = cfo_l / latest.get("is_n_income_attr_p") if cfo_l and latest.get("is_n_income_attr_p") and latest["is_n_income_attr_p"] != 0 else None

    lines.append(f"\n  自由现金流 (经营CF + 投资CF): {_fmt(fcf)}")
    if cfo_np_l is not None:
        if cfo_np_l < 0.5:
            lines.append(f"    🔴 CFO/NP = {cfo_np_l:.2f}，利润现金含量严重不足")
        elif cfo_np_l < 1.0:
            lines.append(f"    🟡 CFO/NP = {cfo_np_l:.2f}，利润有现金支撑但不够充分")
        else:
            lines.append(f"    ✅ CFO/NP = {cfo_np_l:.2f}，利润有真实现金支撑")

    return "\n".join(lines)


def _build_industry_percentiles(stock: pd.DataFrame, perf_df: pd.DataFrame, ind_map: dict) -> str:
    """行业百分位排名：当前股票在每个指标上处于行业什么位置。"""
    latest = stock.sort_values("quarter").iloc[-1]
    sym = latest["symbol"]
    ind_name = ind_map.get(sym, {}).get("l1_name", "")

    if not ind_name:
        return "  行业数据不可用"

    peers = get_industry_peers(pd.DataFrame(), ind_name) if False else [
        s for s, info in ind_map.items()
        if info.get("l1_name") == ind_name
    ]
    if not peers: return "  行业数据不可用"

    # Get peer data for latest quarter
    perf_r = compute_ratios_df(perf_df[perf_df["symbol"].isin(peers)])
    latest_q = latest["quarter"]
    peer_latest = perf_r[perf_r["quarter"] == latest_q]

    if peer_latest.empty:
        return "  行业中无可比数据"

    lines = [f"  行业百分位排名 ({ind_name}, {len(peers)} 家同行, {latest_q}):"]
    lines.append(f"  {'指标':<22} {'本公司':>10} {'行业中位':>10} {'行业均值':>10} {'百分位':>8} {'评级':>6}")
    lines.append(f"  {'─' * 70}")

    rank_metrics = [
        ("roe", "ROE", True),
        ("roa", "ROA", True),
        ("gross_margin", "毛利率", True),
        ("net_margin", "净利率", True),
        ("op_margin", "营业利润率", True),
        ("debt_ratio", "资产负债率", False),
        ("current_ratio", "流动比率", True),
        ("asset_turnover", "资产周转率", True),
        ("cfo_to_np", "现金流/净利润", True),
        ("cfo_to_revenue", "现金流/营收", True),
        ("goodwill_to_equity", "商誉/净资产", False),
        ("rd_to_revenue", "研发/营收", True),
    ]

    for rn, label, higher_better in rank_metrics:
        sv = latest.get(rn) if rn in perf_r.columns else None
        if sv is None or (isinstance(sv, float) and np.isnan(sv)):
            lines.append(f"  {label:<22} {'N/A':>10}")
            continue

        peer_vals = peer_latest[rn].dropna()
        if len(peer_vals) < 3:
            lines.append(f"  {label:<22} {_ratio_fmt(sv):>10} {'—':>10} {'—':>10} {'—':>8}")
            continue

        med = float(peer_vals.median())
        avg = float(peer_vals.mean())
        # Percentile: % of peers we beat (or are lower than, for debt/goodwill)
        if higher_better:
            pct = (peer_vals < sv).mean() * 100
        else:
            pct = (peer_vals > sv).mean() * 100

        rating = "🟢" if pct >= 70 else ("🟡" if pct >= 30 else "🔴")

        lines.append(f"  {label:<22} {_ratio_fmt(sv):>10} {_ratio_fmt(med):>10} "
                     f"{_ratio_fmt(avg):>10} {pct:>6.0f}% {rating:>6}")

    return "\n".join(lines)


def _detect_red_flags(stock: pd.DataFrame, perf_df: pd.DataFrame, ind_map: dict) -> list[dict]:
    """综合风险检测：12 项自动检查，分 danger/warning/info 三级。"""
    stock = stock.sort_values("quarter")
    latest = stock.iloc[-1]
    sym = latest["symbol"]
    ind_name = ind_map.get(sym, {}).get("l1_name", "")

    flags = []

    # ── Profitability ──
    np_p = latest.get("is_n_income_attr_p")
    rev = latest.get("is_revenue")
    eq = latest.get("bs_total_hldr_eqy_exc_min_int")
    ta = latest.get("bs_total_assets")
    tl = latest.get("bs_total_liab")
    cfo = latest.get("cfs_net_cash_operating")
    gw = latest.get("bs_goodwill")

    roe = np_p / eq * 100 if np_p and eq and eq != 0 else None
    if roe is not None:
        if roe < 0:
            flags.append({"severity": "danger", "check": "ROE为负",
                          "detail": f"ROE={roe:.1f}%，股东资本在亏损"})
        elif roe < 5:
            flags.append({"severity": "warning", "check": "ROE偏低",
                          "detail": f"ROE={roe:.1f}%，低于资本成本"})

    if np_p is not None and np_p < 0:
        flags.append({"severity": "danger", "check": "净利润为负",
                      "detail": f"归母净利润={_fmt(np_p)}"})

    # ── Cash flow ──
    cfo_np = cfo / np_p if cfo and np_p and np_p != 0 else None
    if cfo_np is not None:
        if cfo_np < 0.3:
            flags.append({"severity": "danger", "check": "利润无现金支撑",
                          "detail": f"经营现金流/净利润={cfo_np:.2f}，远低于安全线0.5"})
        elif cfo_np < 0.8:
            flags.append({"severity": "warning", "check": "现金回收偏弱",
                          "detail": f"经营现金流/净利润={cfo_np:.2f}，建议关注应收款变化"})

    # ── Leverage ──
    dr = tl / ta * 100 if tl and ta else None
    if dr is not None and dr > 80:
        flags.append({"severity": "warning", "check": "高杠杆",
                      "detail": f"资产负债率={dr:.1f}%，财务风险偏高"})

    # ── Goodwill ──
    gw_eq = gw / eq * 100 if gw and eq and eq != 0 else None
    if gw_eq is not None:
        if gw_eq > 50:
            flags.append({"severity": "danger", "check": "商誉炸弹",
                          "detail": f"商誉占净资产={gw_eq:.1f}%，减值风险极高"})
        elif gw_eq > 20:
            flags.append({"severity": "warning", "check": "商誉偏高",
                          "detail": f"商誉占净资产={gw_eq:.1f}%，需关注减值测试"})

    # ── Growth trend ──
    if len(stock) >= 3:
        revs = stock["is_revenue"].dropna().tolist()
        nps = stock["is_n_income_attr_p"].dropna().tolist()
        if len(nps) >= 3 and all(v < 0 for v in nps[-3:]):
            flags.append({"severity": "danger", "check": "连续3期亏损",
                          "detail": "最近3个季度归母净利润均为负"})
        if len(revs) >= 3 and all(revs[i] < revs[i - 1] for i in range(1, len(revs)) if revs[i] is not None and revs[i - 1] is not None):
            flags.append({"severity": "warning", "check": "营收持续萎缩",
                          "detail": "营业收入连续下滑"})

    # ── Liquidity ──
    ca = latest.get("bs_total_cur_assets")
    cl = latest.get("bs_total_cur_liab")
    cr = ca / cl if ca and cl and cl != 0 else None
    mc = latest.get("bs_money_cap")
    mc_cl = mc / cl * 100 if mc and cl and cl != 0 else None
    if cr is not None and cr < 0.8:
        flags.append({"severity": "danger", "check": "流动性危机",
                      "detail": f"流动比率={cr:.2f}，短期债务覆盖不足"})
    if mc_cl is not None and mc_cl < 20:
        flags.append({"severity": "warning", "check": "现金储备不足",
                      "detail": f"货币资金仅覆盖流动负债的{mc_cl:.0f}%"})

    # ── Revenue quality ──
    if rev is not None and cfo is not None:
        cfo_rev = cfo / rev if rev != 0 else None
        if cfo_rev is not None and cfo_rev < 0:
            flags.append({"severity": "danger", "check": "经营现金流为负",
                          "detail": "主营业务在消耗现金而非创造现金"})

    # ── compare with same quarter last year ──
    latest_q_str = latest.get("quarter", "")
    if latest_q_str:
        try:
            year = int(latest_q_str[:4]); qnum = int(latest_q_str[5])
            prev_q = f"{year - 1}q{qnum}"
            prev_row = stock[stock["quarter"] == prev_q]
            if not prev_row.empty:
                curr_np = np_p
                prev_np_val = prev_row.iloc[0].get("is_n_income_attr_p")
                curr_rev = rev
                prev_rev = prev_row.iloc[0].get("is_revenue")
                if curr_np and prev_np_val and prev_np_val != 0:
                    yoy_np = (float(curr_np) / float(prev_np_val) - 1) * 100
                    if yoy_np < -50:
                        flags.append({"severity": "danger", "check": "利润断崖下跌",
                                      "detail": f"净利润同比{yoy_np:.0f}%"})
                    elif yoy_np < -20:
                        flags.append({"severity": "warning", "check": "利润明显下滑",
                                      "detail": f"净利润同比{yoy_np:.0f}%"})
                if curr_rev and prev_rev and prev_rev != 0:
                    yoy_rev = (float(curr_rev) / float(prev_rev) - 1) * 100
                    if yoy_rev < -20:
                        flags.append({"severity": "warning", "check": "营收大幅萎缩",
                                      "detail": f"营收同比{yoy_rev:.0f}%"})
        except (ValueError, IndexError):
            pass

    return flags


# ── Main report printer ───────────────────────────────────────────────────

def print_full_report(symbol: str):
    """打印一份墙到墙的完整财务分析报告。"""
    df = _load_parquet(FINA_CACHE)
    indu = _load_parquet(INDU_CACHE)

    if df.empty:
        print("缓存为空。请先构建数据缓存：", file=sys.stderr)
        print("  python scripts/build_cache.py --universe 000300.SH --quarters 8", file=sys.stderr)
        print("  （需要 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD 环境变量）", file=sys.stderr)
        return

    stock = df[df["symbol"] == symbol].sort_values("quarter")
    if stock.empty:
        print(f"No data for {symbol}")
        return

    stock_r = compute_ratios_df(stock)
    ind_map = get_industry_map(indu)
    ind_info = ind_map.get(symbol, {})
    ind_name = ind_info.get("l1_name", "未知")
    l2_name = ind_info.get("l2_name", "")

    # Peer medians
    peers = [s for s, info in ind_map.items() if info.get("l1_name") == ind_name]
    n_peers = max(0, len(peers) - 1)
    ind_medians = {}
    if peers:
        peer_df = df[df["symbol"].isin(peers)]
        latest_q = stock["quarter"].max()
        peer_r = compute_ratios_df(peer_df[peer_df["quarter"] == latest_q])
        if not peer_r.empty:
            for rn, rfn in RATIOS:
                vals = peer_r[rn].dropna()
                if len(vals) > 0:
                    ind_medians[rn] = float(vals.median())

    qs = stock["quarter"].tolist()
    latest = stock.iloc[-1]

    # ── Header ──
    print(f"\n{'=' * 80}")
    print(f"  📊  {symbol}  综合财务分析报告")
    print(f"  行业: {ind_name}{' / ' + l2_name if l2_name else ''}  ({n_peers} 家同行)")
    print(f"  数据期间: {qs[0]} → {qs[-1]}  ({len(qs)} 期)")
    print(f"  生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 80}")

    # ── Section 1: Multi-year core financials ──
    print(f"\n  {'─' * 80}")
    print(f"  一、核心财务指标 · 逐季对比")
    print(f"  {'─' * 80}")
    print(_build_multi_year_table(stock))

    # ── Section 2: Profitability decomposition ──
    print(f"\n  {'─' * 80}")
    print(f"  二、盈利能力 · 逐层拆解")
    print(f"  {'─' * 80}")
    print(_build_profitability_decomp(stock))

    # ── Section 3: DuPont ──
    print(f"\n  {'─' * 80}")
    print(f"  三、ROE 驱动因素 · DuPont 分解")
    print(f"  {'─' * 80}")
    print(_build_dupont(stock))

    # ── Section 4: Balance sheet ──
    print(f"\n  {'─' * 80}")
    print(f"  四、资产负债表 · 健康度评估")
    print(f"  {'─' * 80}")
    print(_build_balance_sheet_health(stock, ind_medians))

    # ── Section 5: Cash flow ──
    print(f"\n  {'─' * 80}")
    print(f"  五、现金流 · 质量与趋势")
    print(f"  {'─' * 80}")
    print(_build_cashflow_quality(stock, ind_medians))

    # ── Section 6: Growth trajectory ──
    print(f"\n  {'─' * 80}")
    print(f"  六、增长轨迹")
    print(f"  {'─' * 80}")
    _print_growth_section(stock)

    # ── Section 7: Industry percentiles ──
    print(f"\n  {'─' * 80}")
    print(f"  七、行业百分位排名")
    print(f"  {'─' * 80}")
    print(_build_industry_percentiles(stock_r, df, ind_map))

    # ── Section 8: Red flags ──
    flags = _detect_red_flags(stock, df, ind_map)
    print(f"\n  {'─' * 80}")
    print(f"  八、综合风险检测 ({len(flags)} 项)")
    print(f"  {'─' * 80}")
    if not flags:
        print("  ✅ 未触发风险检测规则")
    else:
        for f in flags:
            icon = "🔴" if f["severity"] == "danger" else "🟡"
            print(f"  {icon} [{f['severity']}] {f['check']}")
            print(f"      {f['detail']}")

    print(f"\n{'=' * 80}\n")


def _print_growth_section(stock: pd.DataFrame):
    """增长轨迹：营收/利润/资产的 YoY 增速 + 加速度。"""
    stock = stock.sort_values("quarter")
    metrics = [
        ("is_revenue", "营业收入"),
        ("is_n_income_attr_p", "归母净利润"),
        ("bs_total_assets", "总资产"),
        ("bs_total_hldr_eqy_exc_min_int", "归母权益"),
        ("cfs_net_cash_operating", "经营现金流"),
    ]

    print(f"  {'指标':<14}", end="")
    for _, row in stock.iterrows():
        print(f"  {row['quarter']:>10}", end="")
    print(f"  {'方向':>8}")
    print(f"  {'─' * 75}")

    for col, label in metrics:
        vals = stock[col].tolist()
        print(f"  {label:<14}", end="")
        for v in vals:
            print(f"  {_fmt(v):>10}", end="")
        # Direction
        if len(vals) >= 2 and all(v is not None and not (isinstance(v, float) and np.isnan(v)) for v in [vals[0], vals[-1]]):
            chg = (float(vals[-1]) / float(vals[0]) - 1) * 100
            arrow = "↗" if chg > 5 else ("↘" if chg < -5 else "→")
            print(f"  {arrow} {chg:+.0f}%", end="")
        print()

    # YoY table (same quarter last year comparison)
    qs = stock["quarter"].tolist()
    print(f"\n  同比增速 (%):")
    yoy_metrics = [("is_revenue", "营收"), ("is_n_income_attr_p", "净利润"), ("bs_total_assets", "总资产")]
    for col, label in yoy_metrics:
        print(f"  {label}:", end="")
        for current_q in qs:
            try:
                year = int(current_q[:4]); qnum = int(current_q[5])
                prev_q = f"{year - 1}q{qnum}"
                curr_row = stock[stock["quarter"] == current_q]
                prev_row = stock[stock["quarter"] == prev_q]
                if not curr_row.empty and not prev_row.empty:
                    cv = curr_row.iloc[0].get(col)
                    pv = prev_row.iloc[0].get(col)
                    if cv and pv and pv != 0:
                        yoy = (float(cv) / float(pv) - 1) * 100
                        print(f"  {current_q}: {yoy:+.1f}%", end="")
                    else:
                        print(f"  {current_q}: —", end="")
                else:
                    print(f"  {current_q}: —", end="")
            except (ValueError, IndexError):
                print(f"  {current_q}: —", end="")
        print()


# ── CSV export ─────────────────────────────────────────────────────────────

def export_stock_csv(symbol: str, output_path: str | None = None) -> str:
    """Export one stock's full financial data + ratios as a single wide CSV row."""
    df = _load_parquet(FINA_CACHE)
    indu = _load_parquet(INDU_CACHE)
    stock = df[df["symbol"] == symbol].sort_values("quarter")

    if stock.empty:
        raise ValueError(f"No data for {symbol}")

    stock_r = compute_ratios_df(stock)
    ind_map = get_industry_map(indu)
    ind_info = ind_map.get(symbol, {})

    # Build wide row: metadata + each quarter's raw fields + ratios
    row_data = {
        "symbol": symbol,
        "l1_name": ind_info.get("l1_name", ""),
        "l2_name": ind_info.get("l2_name", ""),
        "l3_name": ind_info.get("l3_name", ""),
        "n_quarters": len(stock),
        "quarter_range": f"{stock['quarter'].iloc[0]}→{stock['quarter'].iloc[-1]}",
    }

    # Latest quarter key metrics
    latest = stock_r.iloc[-1]
    for col in KEY_FIELDS:
        row_data[f"latest_{col}"] = latest.get(col) if col in stock_r.columns else None
    for rn, rfn in RATIOS:
        row_data[f"latest_{rn}"] = latest.get(rn) if rn in stock_r.columns else None

    # First quarter for growth computation
    if len(stock_r) >= 2:
        first = stock_r.iloc[0]
        for col in KEY_FIELDS:
            v_first = first.get(col) if col in stock_r.columns else None
            v_latest = latest.get(col) if col in stock_r.columns else None
            if v_first is not None and v_latest is not None and not np.isnan(v_first) and not np.isnan(v_latest) and v_first != 0:
                row_data[f"growth_{col}"] = (float(v_latest) / float(v_first) - 1) * 100
            else:
                row_data[f"growth_{col}"] = None

    row_df = pd.DataFrame([row_data])
    path = output_path or str(OUTPUT_DIR / f"stock_report_{symbol}.csv")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    row_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[ok] {path}", file=sys.stderr)
    return path


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Comprehensive single-stock financial analysis")
    p.add_argument("symbol", nargs="?", default=None, help="Stock symbol, e.g. 000001.SZ")
    p.add_argument("--csv", action="store_true", help="Export as wide CSV row")
    p.add_argument("--output", default=None, help="Output path")
    args = p.parse_args()

    if not args.symbol:
        print("Usage: python scripts/analyze_stock.py <symbol> [--csv]", file=sys.stderr)
        return 1

    if args.csv:
        export_stock_csv(args.symbol, args.output)
        return 0

    print_full_report(args.symbol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
