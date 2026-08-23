"""中证500+1000 主板 · 周频动量筛选，不用 26 只契合池。

  python strategy/strategies/strategy4/run_mom_universe.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from holdingStocks.watch_config import limit_down_pct_of  # noqa: E402
from strategy.costs import stamp_tax_for_code  # noqa: E402
from strategy.s1_price_select import weekly_mom_gate_from_close  # noqa: E402
from strategy.strategies.strategy4.bindings import MOM_TOP_K, MOM_VALUE_COL  # noqa: E402
from strategy.strategies.strategy4.portfolio import (  # noqa: E402
    PINNED,
    TRADE_START,
    active_nav,
    load_daily,
    run_one,
    window_metrics,
)
from strategy.config import KAICHENG, TIANTONG  # noqa: E402

OUT = Path(__file__).resolve().parent / "mom_universe"
PANEL = (
    _MYQUAN
    / "backtest"
    / "zz1000_momentum_select"
    / "panel_ohlc_zz500_1000.parquet"
)
REPORT_FROM = "2025-01-02"
K = MOM_TOP_K
MOM_N = 20


def _year_from_prior(nav: pd.Series, year: int) -> float:
    s = nav.dropna().sort_index()
    prev = s[s.index.year < year]
    this = s[s.index.year == year]
    if this.empty:
        return float("nan")
    start = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
    if start <= 0:
        return float("nan")
    return (float(this.iloc[-1]) / start - 1.0) * 100.0


def mom_bh_nav(close: pd.DataFrame, gate: dict[str, dict[str, bool]]) -> pd.Series:
    c = close.copy()
    idx = pd.to_datetime(c.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    c.index = pd.DatetimeIndex(idx).normalize()
    rets = c.pct_change()
    out = []
    for ts, row in rets.iterrows():
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        names = [col for col in rets.columns if bool((gate.get(col) or {}).get(key, False))]
        names = [n for n in names if pd.notna(row.get(n))]
        out.append(float(row[names].mean()) if names else 0.0)
    nav = (1.0 + pd.Series(out, index=rets.index)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wide = pd.read_parquet(PANEL)
    close = wide["close"].copy()
    print(f"动量宇宙 {close.shape[1]} 只（中证500+1000 主板面板，非契合池）")
    gate = weekly_mom_gate_from_close(close, mom_n=MOM_N, k=K)
    days = sorted({d for mp in gate.values() for d in mp if d >= REPORT_FROM})
    selected = {
        sym
        for sym, mp in gate.items()
        if any(mp.get(d) for d in days)
    }
    print(f"2025 起周频 {MOM_VALUE_COL} Top{K} 曾入选 {len(selected)} 只")

    metas = {}
    dailies = {}
    for sym in sorted(selected):
        daily = load_daily(sym)
        if daily is None:
            continue
        code = sym[2:]
        dailies[sym] = daily
        metas[sym] = {
            "code": code,
            "symbol": sym,
            "name": sym,
            "entry_pct": 0.025,
            "stop_pct": 0.025,
            "tick": 0.01,
            "t0": False,
            "limit_down_pct": float(limit_down_pct_of(code)),
            "stamp_tax_rate": stamp_tax_for_code(code),
        }

    s1, s9 = {}, {}
    for i, (sym, daily) in enumerate(dailies.items(), 1):
        if i % 20 == 0 or i == 1:
            print(f"  backtest {i}/{len(dailies)} {sym}")
        s1[sym] = run_one(metas[sym], daily, s9=False, allowed=gate.get(sym))
        s9[sym] = run_one(metas[sym], daily, s9=True, allowed=gate.get(sym))

    nav_s1 = active_nav({s: r["nav"] for s, r in s1.items()}, gate)
    nav_s9 = active_nav({s: r["nav"] for s, r in s9.items()}, gate)
    nav_bh = mom_bh_nav(close, gate)

    # 两票策略1 对照：统一 2.5%/3.0% 仅止损，不用契合池
    p2 = {}
    for cfg in (KAICHENG, TIANTONG):
        daily = load_daily(cfg.symbol)
        if daily is None:
            continue
        meta = {
            "code": cfg.em_symbol,
            "symbol": cfg.symbol,
            "name": cfg.symbol_name,
            "entry_pct": cfg.resolved_entry_pct(),
            "stop_pct": cfg.resolved_stop_pct(),
            "tick": cfg.tick,
            "t0": False,
            "limit_down_pct": cfg.limit_down_pct,
            "stamp_tax_rate": cfg.stamp_tax_rate,
        }
        p2[cfg.symbol] = run_one(meta, daily, s9=False, allowed=None)
    nav_p2 = active_nav({s: r["nav"] for s, r in p2.items()}, None)

    books = {
        "s1_mom_top5": nav_s1,
        "s9_mom_top5": nav_s9,
        "bh_mom_top5": nav_bh,
        "s1_pinned2": nav_p2,
    }
    rows = []
    for vid, nav in books.items():
        m = window_metrics(nav, start=REPORT_FROM)
        sl = nav[nav.index >= pd.Timestamp(REPORT_FROM)]
        rows.append(
            {
                "id": vid,
                "ret_2025_now": round(m["ret_pct"], 2),
                "ann_pct": round(m["ann_pct"], 2),
                "sharpe": round(m["sharpe"], 3),
                "mdd_pct": round(m["mdd_pct"], 2),
                "y2025": round(_year_from_prior(sl, 2025), 2),
                "y2026": round(_year_from_prior(sl, 2026), 2),
                "start": m.get("start"),
                "end": m.get("end"),
            }
        )
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "summary.csv", index=False)
    (OUT / "selected_2025.json").write_text(
        json.dumps(sorted(dailies), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    month = {}
    for vid, nav in books.items():
        m = nav.copy()
        m.index = pd.to_datetime(m.index)
        m = m[m.index >= pd.Timestamp(REPORT_FROM)]
        if m.empty:
            continue
        m = m / float(m.iloc[0])
        month[vid] = {
            str(k.date())[:7]: float(v)
            for k, v in m.resample("ME").last().dropna().items()
        }
    (OUT / "nav_monthly.json").write_text(
        json.dumps({"k": K, "mom_n": MOM_N, "n_selected": len(dailies), "nav": month}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 周频动量筛选（中证500+1000 主板，非 26 只契合池）",
        "",
        "研究回测，不构成投资建议。",
        "",
        f"- 宇宙：面板 {close.shape[1]} 只中证500+1000 主板（当前成分缓存，有幸存者偏差）",
        f"- 筛选：T 收盘 {MOM_N} 日动量，本周最后交易日 Top{K}，下一周才开仓",
        "- 策略1：仅止损，统一 ±2.5%，无因子4、无止盈、不用契合池阈值",
        "- 策略9：同一名单上加因子4 + 20%昨高全清",
        "- 对照：动量 Top5 等权持有；策略1 凯盛+天通（置顶票，不是拟合池）",
        f"- 2025 起曾入选 {len(dailies)} 只；区间 {REPORT_FROM}～缓存末日",
        "",
        table.to_markdown(index=False),
        "",
        "本报告仅供研究参考，不构成投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(table.to_string(index=False))
    print("selected", len(dailies))


if __name__ == "__main__":
    main()
