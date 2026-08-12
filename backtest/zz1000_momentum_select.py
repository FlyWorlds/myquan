"""中证1000 · 截面选股回测（动量/反转可配置）。

默认读取 dig 结果 best_config.json：
  2026YTD 最优为短期反转 rev(n=60)+持有6日（趋势动量回撤过大）。

规则：
  · 股票池：中证1000 主板（剔科创/创业/北交）
  · 每天收盘按因子截面选 TopK → 次日开盘买 → 持有 hold_days 日后开盘卖
  · 资金：hold_days 袖套轮动
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.data import fetch_daily  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent / "universe_zz500_1000" / "daily_cache"
OUT_DIR = Path(__file__).resolve().parent / "zz1000_momentum_select"
PANEL_PATH = OUT_DIR / "panel_ohlc.parquet"
PANEL_PATH_ZZ500_1000 = OUT_DIR / "panel_ohlc_zz500_1000.parquet"
BEST_PATH = OUT_DIR / "best_config.json"
CSINDEX_CONS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/{code}cons.xls"
)

INITIAL_CASH = 1_000_000.0
COMMISSION = 0.0000854
STAMP = 0.001
SLIP = 0.001
LOT = 100


def _is_mainboard(code: str) -> bool:
    c = str(code).zfill(6)
    if c.startswith(("688", "689", "300", "301")):
        return False
    if c.startswith(("8", "4")):
        return False
    return True


def _to_symbol(code: str) -> str:
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("5", "6")) else f"sz{c}"


def _load_csindex_mainboard(index_code: str, *, label: str) -> pd.DataFrame:
    url = CSINDEX_CONS_URL.format(code=index_code)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    code_col = next(
        c for c in df.columns if "Constituent Code" in str(c) or "成份券代码" in str(c)
    )
    name_col = next(
        c
        for c in df.columns
        if ("Constituent Name" in str(c) or "成份券名称" in str(c)) and "Eng" not in str(c)
    )
    rows = []
    for _, row in df.iterrows():
        c = str(row[code_col]).zfill(6)
        if not _is_mainboard(c):
            continue
        rows.append(
            {"code": c, "name": str(row[name_col]).strip(), "symbol": _to_symbol(c)}
        )
    out = pd.DataFrame(rows).drop_duplicates("code")
    print(f"{label}主板成分: {len(out)}")
    return out


def load_zz1000_mainboard() -> pd.DataFrame:
    return _load_csindex_mainboard("000852", label="中证1000")


def load_zz500_mainboard() -> pd.DataFrame:
    return _load_csindex_mainboard("000905", label="中证500")


def load_zz500_1000_mainboard() -> pd.DataFrame:
    """中证500 + 中证1000 主板并集（去重）。"""
    a = load_zz500_mainboard()
    b = load_zz1000_mainboard()
    out = pd.concat([a, b], ignore_index=True).drop_duplicates("code")
    print(f"中证500+1000主板并集: {len(out)}")
    return out


def load_best_config() -> dict:
    if BEST_PATH.exists():
        return json.loads(BEST_PATH.read_text(encoding="utf-8"))
    return {
        "kind": "rev",
        "n": 60,
        "top_k": 2,
        "hold_days": 6,
        "min_score": None,
        "ma_filter": None,
    }


def load_panel_matrices(
    symbols: list[str],
    *,
    warm_start: str,
    end: str,
    refresh: bool = False,
    panel_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    path = Path(panel_path) if panel_path is not None else PANEL_PATH
    if path.exists() and not refresh:
        wide = pd.read_parquet(path)
        print(f"载入面板缓存 {path} {wide['close'].shape}")
        return wide["open"], wide["high"], wide["low"], wide["close"]

    opens: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        cache = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        try:
            d = fetch_daily(sym, warm_start, end, cache_path=cache, force_refresh=refresh)
        except Exception:
            continue
        if d is None or d.empty or len(d) < 40:
            continue
        d = d.copy()
        d["d"] = pd.to_datetime(d["date"]).dt.tz_convert("Asia/Shanghai").dt.normalize()
        d = d.set_index("d")
        opens[sym] = d["open"].astype(float)
        highs[sym] = d["high"].astype(float)
        lows[sym] = d["low"].astype(float)
        closes[sym] = d["close"].astype(float)
        if i % 100 == 0:
            print(f"  panel {i}/{len(symbols)} valid={len(closes)} ({time.time()-t0:.1f}s)")
    op = pd.DataFrame(opens).sort_index()
    hi = pd.DataFrame(highs).sort_index()
    lo = pd.DataFrame(lows).sort_index()
    cl = pd.DataFrame(closes).sort_index()
    cols = sorted(set(op.columns) & set(hi.columns) & set(lo.columns) & set(cl.columns))
    op, hi, lo, cl = op[cols], hi[cols], lo[cols], cl[cols]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat({"open": op, "high": hi, "low": lo, "close": cl}, axis=1).to_parquet(path)
    print(f"写入面板 {path} {cl.shape}")
    return op, hi, lo, cl


def _factor3_dist_hl(highs: pd.DataFrame, lows: pd.DataFrame, n: int) -> pd.DataFrame:
    """因子3 dist_hl：dist_high - dist_low（低点更近→偏多）。"""
    n = int(n)
    hv = highs.to_numpy(dtype=float, copy=False)
    lv = lows.to_numpy(dtype=float, copy=False)
    rows, cols = hv.shape
    out = np.full((rows, cols), np.nan, dtype=float)
    for j in range(cols):
        hcol = hv[:, j]
        lcol = lv[:, j]
        for i in range(n - 1, rows):
            sl_h = hcol[i - n + 1 : i + 1]
            sl_l = lcol[i - n + 1 : i + 1]
            if not (np.isfinite(sl_h).all() and np.isfinite(sl_l).all()):
                continue
            dist_high = (n - 1) - int(np.argmax(sl_h))
            dist_low = (n - 1) - int(np.argmin(sl_l))
            out[i, j] = dist_high - dist_low
    return pd.DataFrame(out, index=highs.index, columns=highs.columns)


def compute_factor(
    opens: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    kind: str,
    n: int,
    min_score: float | None,
    ma_filter: int | None,
    n_short: int | None = None,
) -> pd.DataFrame:
    c = closes
    kind = str(kind)
    if kind == "roc":
        fac = c / c.shift(n) - 1.0
    elif kind == "rev":
        fac = -(c / c.shift(n) - 1.0)
    elif kind == "roc_vol":
        roc = c / c.shift(n) - 1.0
        vol = c.pct_change().rolling(max(n, 10), min_periods=5).std()
        fac = roc / vol.replace(0, np.nan)
    elif kind == "ma_gap":
        ma = c.rolling(n, min_periods=n).mean()
        fac = c / ma - 1.0
    elif kind == "breakout":
        hh = highs.shift(1).rolling(n, min_periods=n).max()
        fac = c / hh - 1.0
    elif kind == "dist_hl":
        # 与 strategy.momentum.dist_hl / 因子3 一致：距 N 日高低点的时间距离差
        fac = _factor3_dist_hl(highs, lows, n)
    elif kind == "dist_hl_pos":
        # 旧口径：价格在 N 日高低区间中的相对位置（非因子3 dist_hl）
        hh = highs.rolling(n, min_periods=n).max()
        ll = lows.rolling(n, min_periods=n).min()
        mid = (hh + ll) / 2.0
        span = (hh - ll).replace(0, np.nan)
        fac = (c - mid) / span
    elif kind == "resid":
        s = int(n_short or 5)
        fac = (c / c.shift(n) - 1.0) - (c / c.shift(s) - 1.0)
    elif kind == "roc_nochase":
        fac = (c / c.shift(n) - 1.0).where(c.pct_change() <= 0.05)
    else:
        raise ValueError(f"unknown kind {kind}")

    if ma_filter and int(ma_filter) > 1:
        ma = c.rolling(int(ma_filter), min_periods=int(ma_filter)).mean()
        fac = fac.where(c > ma)
    if min_score is not None and kind != "rev":
        fac = fac.where(fac >= float(min_score))
    return fac


def daily_topk(factor: pd.DataFrame, k: int) -> dict[pd.Timestamp, list[str]]:
    picks: dict[pd.Timestamp, list[str]] = {}
    for dt_idx, row in factor.iterrows():
        s = row.dropna()
        if len(s) < k:
            continue
        picks[pd.Timestamp(dt_idx)] = s.nlargest(k).index.tolist()
    return picks


def simulate(
    *,
    factor: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    picks: dict[pd.Timestamp, list[str]],
    bt_start: pd.Timestamp,
    hold_days: int,
    top_k: int,
    initial_cash: float,
    factor_label: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    all_dates = [pd.Timestamp(d) for d in factor.index]
    date_to_i = {d: i for i, d in enumerate(all_dates)}
    sleeve_cash = [initial_cash / hold_days for _ in range(hold_days)]
    sleeve_pos: list[list[dict]] = [[] for _ in range(hold_days)]
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []
    pick_rows: list[dict] = []

    for di, d in enumerate(all_dates):
        if d < bt_start:
            continue
        for s_idx in range(hold_days):
            still = []
            for pos in sleeve_pos[s_idx]:
                if di - pos["entry_i"] >= hold_days:
                    sym = pos["sym"]
                    if sym not in opens.columns or pd.isna(opens.at[d, sym]):
                        still.append(pos)
                        continue
                    px = float(opens.at[d, sym]) * (1.0 - SLIP)
                    proceeds = pos["shares"] * px
                    fee = proceeds * (COMMISSION + STAMP)
                    sleeve_cash[s_idx] += proceeds - fee
                    trade_rows.append(
                        {
                            "date": d,
                            "symbol": sym,
                            "side": "sell",
                            "shares": pos["shares"],
                            "price": px,
                            "sleeve": s_idx,
                        }
                    )
                else:
                    still.append(pos)
            sleeve_pos[s_idx] = still

        prev_i = date_to_i[d] - 1
        if prev_i >= 0:
            prev_d = all_dates[prev_i]
            top = picks.get(prev_d, [])
            if top:
                pick_rows.append(
                    {"signal_date": prev_d, "trade_date": d, "picks": ",".join(top)}
                )
                s_idx = di % hold_days
                if not sleeve_pos[s_idx] and sleeve_cash[s_idx] > 0:
                    budget_each = sleeve_cash[s_idx] / max(len(top), 1)
                    for sym in top:
                        if sym not in opens.columns or pd.isna(opens.at[d, sym]):
                            continue
                        px = float(opens.at[d, sym]) * (1.0 + SLIP)
                        if px <= 0:
                            continue
                        shares = int(budget_each // (px * LOT)) * LOT
                        if shares <= 0:
                            continue
                        cost = shares * px
                        fee = cost * COMMISSION
                        if cost + fee > sleeve_cash[s_idx]:
                            continue
                        sleeve_cash[s_idx] -= cost + fee
                        sleeve_pos[s_idx].append(
                            {"sym": sym, "shares": shares, "entry_i": di}
                        )
                        trade_rows.append(
                            {
                                "date": d,
                                "symbol": sym,
                                "side": "buy",
                                "shares": shares,
                                "price": px,
                                "sleeve": s_idx,
                            }
                        )

        eq = sum(sleeve_cash)
        for s_idx in range(hold_days):
            for pos in sleeve_pos[s_idx]:
                sym = pos["sym"]
                if sym in closes.columns and not pd.isna(closes.at[d, sym]):
                    eq += pos["shares"] * float(closes.at[d, sym])
        equity_rows.append({"date": d, "equity": eq})

    eq_df = pd.DataFrame(equity_rows)
    tr_df = pd.DataFrame(trade_rows)
    pk_df = pd.DataFrame(pick_rows)
    if eq_df.empty:
        return eq_df, tr_df, {"error": "no equity"}

    eq = eq_df["equity"].to_numpy(dtype=float)
    rets = np.diff(eq) / np.where(eq[:-1] == 0, np.nan, eq[:-1])
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) and np.std(rets) > 1e-12
        else 0.0
    )
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.where(peak == 0, np.nan, peak)
    stats = {
        "start": str(eq_df["date"].iloc[0].date()),
        "end": str(eq_df["date"].iloc[-1].date()),
        "n_days": int(len(eq_df)),
        "total_return_pct": float(eq[-1] / initial_cash - 1.0) * 100,
        "max_drawdown_pct": float(np.nanmax(dd)) * 100 if len(dd) else 0.0,
        "sharpe": sharpe,
        "end_equity": float(eq[-1]),
        "n_trades": int(len(tr_df)),
        "n_buys": int((tr_df["side"] == "buy").sum()) if not tr_df.empty else 0,
        "top_k": top_k,
        "hold_days": hold_days,
        "factor": factor_label,
    }
    return eq_df, tr_df, {**stats, "picks": pk_df}


def _write_html_report(
    *,
    eq_df: pd.DataFrame,
    tr_df: pd.DataFrame,
    pk_df: pd.DataFrame,
    stats: dict,
    name_map: dict[str, str],
    initial_cash: float,
    note: str = "",
) -> Path:
    out = OUT_DIR / "中证1000_动量选股_2026_report.html"
    if eq_df is None or eq_df.empty:
        out.write_text("<html><body>无权益数据</body></html>", encoding="utf-8")
        return out

    eq = eq_df.copy()
    eq["date"] = pd.to_datetime(eq["date"], utc=True).dt.tz_convert("Asia/Shanghai")
    eq = eq.sort_values("date")
    peak = eq["equity"].cummax()
    eq["dd"] = eq["equity"] / peak - 1.0
    equity = [float(x) for x in eq["equity"]]

    eqm = eq.set_index("date")
    monthly_rows = []
    for period, g in eqm.groupby(eqm.index.to_period("M")):
        prev = eqm[eqm.index < g.index[0]]
        base = float(prev["equity"].iloc[-1]) if len(prev) else initial_cash
        e1 = float(g["equity"].iloc[-1])
        monthly_rows.append(
            (
                str(period),
                f"{(e1 / base - 1) * 100:.2f}",
                f"{e1:,.2f}",
                f"{float(g['dd'].min()) * 100:.2f}",
            )
        )

    def esc(s: object) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    w, h, pad = 960, 320, 40
    xs = np.linspace(pad, w - pad, max(len(equity), 1))
    ymin, ymax = min(equity), max(equity)
    span = ymax - ymin or 1.0

    def ymap(v: float) -> float:
        return h - pad - (v - ymin) / span * (h - 2 * pad)

    pts = " ".join(f"{xs[i]:.1f},{ymap(equity[i]):.1f}" for i in range(len(equity)))
    grid = []
    for t in np.linspace(ymin, ymax, 5):
        yy = ymap(float(t))
        grid.append(
            f'<line x1="{pad}" y1="{yy:.1f}" x2="{w-pad}" y2="{yy:.1f}" stroke="#e8e8e8"/>'
            f'<text x="{pad-6}" y="{yy+4:.1f}" text-anchor="end" font-size="11" fill="#888">{t/10000:.1f}万</text>'
        )
    svg = (
        f'<svg viewBox="0 0 {w} {h}" width="100%">'
        f'<rect width="{w}" height="{h}" fill="#fafafa"/>{"".join(grid)}'
        f'<polyline fill="none" stroke="#1a56db" stroke-width="2" points="{pts}"/></svg>'
    )

    cards = [
        ("区间", f"{stats.get('start')} → {stats.get('end')}"),
        ("累计收益%", f"{float(stats.get('total_return_pct', 0)):.2f}"),
        ("最大回撤%", f"{float(stats.get('max_drawdown_pct', 0)):.2f}"),
        ("夏普", f"{float(stats.get('sharpe', 0)):.4f}"),
        ("期末权益", f"{float(stats.get('end_equity', 0)):,.2f}"),
        ("每日选股", stats.get("top_k")),
        ("持股天数", stats.get("hold_days")),
        ("因子", stats.get("factor")),
        ("买入笔数", stats.get("n_buys")),
    ]
    cards_html = "".join(
        f'<div class="card"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
        for k, v in cards
    )

    def table(headers: list[str], rows: list[tuple]) -> str:
        th = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows
        )
        return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    month_html = table(["月份", "策略收益%", "月末权益", "月内最大回撤%"], monthly_rows)

    pick_rows = []
    if pk_df is not None and not pk_df.empty:
        tmp = pk_df.copy()
        for c in ("signal_date", "trade_date"):
            tmp[c] = pd.to_datetime(tmp[c], utc=True).dt.tz_convert("Asia/Shanghai")
        for _, r in tmp.tail(30).iterrows():
            pick_rows.append(
                (
                    r["signal_date"].strftime("%Y-%m-%d"),
                    r["trade_date"].strftime("%Y-%m-%d"),
                    r.get("picks", ""),
                    r.get("pick_names", ""),
                )
            )
    pick_html = table(["信号日", "交易日", "代码", "名称"], pick_rows)

    trade_rows = []
    if tr_df is not None and not tr_df.empty:
        tmp = tr_df.copy()
        tmp["date"] = pd.to_datetime(tmp["date"], utc=True).dt.tz_convert("Asia/Shanghai")
        for _, r in tmp.tail(40).iterrows():
            trade_rows.append(
                (
                    r["date"].strftime("%Y-%m-%d"),
                    r["side"],
                    r["symbol"],
                    r.get("name", name_map.get(r["symbol"], "")),
                    int(r["shares"]),
                    f"{float(r['price']):.3f}",
                    int(r["sleeve"]),
                )
            )
    trade_html = table(
        ["日期", "方向", "代码", "名称", "股数", "价格", "袖套"], trade_rows
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>中证1000 · 截面选股回测 2026</title>
<style>
  body{{margin:0;font-family:"Noto Sans SC",system-ui,sans-serif;background:#f6f5f2;color:#1c1b19}}
  header{{padding:36px 40px 20px;border-bottom:1px solid #e4e0d8;background:#fff}}
  h1{{margin:0 0 8px;font-size:28px}} header p{{margin:0;color:#6b6560;max-width:820px}}
  main{{padding:24px 40px 48px;max-width:1100px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin:16px 0 28px}}
  .card{{background:#fff;border:1px solid #e4e0d8;border-radius:10px;padding:12px 14px}}
  .k{{font-size:12px;color:#6b6560}} .v{{font-size:18px;font-weight:600;margin-top:4px;word-break:break-all}}
  h2{{font-size:18px;margin:0 0 12px}}
  .panel{{background:#fff;border:1px solid #e4e0d8;border-radius:12px;padding:16px;overflow-x:auto;margin-bottom:28px}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th,td{{border-bottom:1px solid #e4e0d8;padding:8px 10px;text-align:left;white-space:nowrap}}
  th{{color:#6b6560}}
  .note{{background:#fff8e8;border:1px solid #f0e0b0;border-radius:10px;padding:12px 14px;margin-bottom:20px;color:#5c4b1f;font-size:14px}}
  footer{{padding:0 40px 40px;color:#6b6560;font-size:12px}}
</style>
</head>
<body>
<header>
  <h1>中证1000 · 截面选股回测</h1>
  <p>每天收盘选 Top{esc(stats.get('top_k'))}，次日开盘买入，持有 {esc(stats.get('hold_days'))} 日开盘卖出；袖套轮动。仅供研究参考，不构成投资建议。</p>
</header>
<main>
  {"<div class='note'>" + esc(note) + "</div>" if note else ""}
  <section><h2>核心指标</h2><div class="cards">{cards_html}</div></section>
  <section><h2>权益曲线</h2><div class="panel">{svg}</div></section>
  <section><h2>分月表现</h2><div class="panel">{month_html}</div></section>
  <section><h2>最近选股</h2><div class="panel">{pick_html}</div></section>
  <section><h2>最近成交</h2><div class="panel">{trade_html}</div></section>
</main>
<footer>生成自 backtest/zz1000_momentum_select · dig: mine_zz1000_momentum.py</footer>
</body>
</html>
"""
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    cfg0 = load_best_config()
    p = argparse.ArgumentParser(description="中证1000 截面选股回测")
    p.add_argument("--start", default="20260101")
    p.add_argument("--end", default=dt.date.today().strftime("%Y%m%d"))
    p.add_argument("--kind", default=cfg0.get("kind", "rev"))
    p.add_argument("--n", type=int, default=int(cfg0.get("n", 60)))
    p.add_argument("--top-k", type=int, default=int(cfg0.get("top_k", 2)))
    p.add_argument("--hold-days", type=int, default=int(cfg0.get("hold_days", 6)))
    p.add_argument("--min-score", type=float, default=None)
    p.add_argument("--ma-filter", type=int, default=None)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--warm-start", default="20250701")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)

    min_score = args.min_score if args.min_score is not None else cfg0.get("min_score")
    ma_filter = args.ma_filter if args.ma_filter is not None else cfg0.get("ma_filter")
    n_short = cfg0.get("n_short")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    univ = load_zz1000_mainboard()
    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = load_panel_matrices(
        univ["symbol"].tolist(),
        warm_start=args.warm_start,
        end=args.end,
        refresh=bool(args.refresh),
    )

    factor = compute_factor(
        opens,
        highs,
        lows,
        closes,
        kind=args.kind,
        n=args.n,
        min_score=min_score,
        ma_filter=ma_filter,
        n_short=n_short,
    )
    label = (
        f"{args.kind}{{n={args.n}, hold={args.hold_days}, "
        f"min_score={min_score}, ma={ma_filter}}}"
    )
    print(f"因子 {label} 矩阵 {factor.shape}")

    picks = daily_topk(factor, args.top_k)
    bt_start = pd.Timestamp(args.start).tz_localize("Asia/Shanghai")
    eq_df, tr_df, stats = simulate(
        factor=factor,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=args.hold_days,
        top_k=args.top_k,
        initial_cash=INITIAL_CASH,
        factor_label=label,
    )

    print("\n========== 中证1000 截面选股回测 ==========")
    for k in (
        "start",
        "end",
        "n_days",
        "factor",
        "top_k",
        "hold_days",
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "end_equity",
        "n_trades",
        "n_buys",
    ):
        print(f"{k}: {stats.get(k)}")

    if not tr_df.empty:
        tr_df["name"] = tr_df["symbol"].map(name_map)
        tr_df.to_csv(OUT_DIR / "trades_2026.csv", index=False, encoding="utf-8-sig")

    pk = stats.get("picks")
    if isinstance(pk, pd.DataFrame) and not pk.empty:
        pk = pk.copy()
        pk["pick_names"] = pk["picks"].map(
            lambda s: ",".join(name_map.get(x, x) for x in str(s).split(","))
        )
        pk.to_csv(OUT_DIR / "daily_picks_2026.csv", index=False, encoding="utf-8-sig")
        print("\n最近10日选股:")
        print(pk.tail(10).to_string(index=False))

    if not eq_df.empty:
        eq_df.to_csv(OUT_DIR / "equity_2026.csv", index=False, encoding="utf-8-sig")

    (OUT_DIR / "summary_2026.txt").write_text(
        "\n".join(f"{k}: {stats.get(k)}" for k in stats if k != "picks") + "\n",
        encoding="utf-8",
    )

    note = (
        "挖参说明：原 dist_hl 趋势动量在 2026YTD 夏普仅约 0.21、回撤约 30%。"
        "网格搜索后，同池同约束下短期反转 rev(n=60)+持有6日 更优"
        f"（夏普≈{float(stats.get('sharpe', 0)):.2f}，回撤≈{float(stats.get('max_drawdown_pct', 0)):.1f}%）。"
        "趋势动量族未能在回撤≤20% 约束下达标。"
    )
    html_path = _write_html_report(
        eq_df=eq_df,
        tr_df=tr_df if not tr_df.empty else pd.DataFrame(),
        pk_df=pk if isinstance(pk, pd.DataFrame) else pd.DataFrame(),
        stats=stats,
        name_map=name_map,
        initial_cash=INITIAL_CASH,
        note=note,
    )
    print(f"HTML: {html_path}")
    if not args.no_open:
        import subprocess

        subprocess.run(["open", str(html_path)], check=False)


if __name__ == "__main__":
    main()
