"""两段选股：沪深300+中证500+中证1000 动量 Top20 → 第二因子收到 5 只 → 策略1。

不用 26 只契合池。事先 4 组（含一段动量 Top5），2025 至今验证。

  python strategy/strategies/strategy4/run_two_stage.py
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
from strategy.config import KAICHENG, TIANTONG  # noqa: E402
from strategy.s1_price_select import (  # noqa: E402
    weekly_mom_gate_from_close,
    weekly_two_stage_gate,
)
from strategy.strategies.strategy4.portfolio import (  # noqa: E402
    active_nav,
    load_daily,
    run_one,
    window_metrics,
)
from strategy.strategies.strategy4.run_mom_universe import (  # noqa: E402
    _year_from_prior,
    mom_bh_nav,
)

OUT = Path(__file__).resolve().parent / "two_stage"
PANEL_500_1000 = (
    _MYQUAN
    / "backtest"
    / "zz1000_momentum_select"
    / "panel_ohlc_zz500_1000.parquet"
)
ABC_CACHE = _MYQUAN / "backtest" / "universe_abc" / "daily_cache"
ABC_RESULTS = _MYQUAN / "backtest" / "universe_abc" / "results.csv"
COMBINED_PANEL = OUT / "panel_hs300_zz500_1000.parquet"
REPORT_FROM = "2025-01-02"
STAGE1_K = 20
STAGE2_K = 5
N_TRIALS = 4


def _bar_index(s) -> pd.DatetimeIndex:
    if hasattr(s, "dt"):
        idx = pd.to_datetime(s)
        if getattr(idx.dt, "tz", None) is not None:
            idx = idx.dt.tz_localize(None)
        return pd.DatetimeIndex(idx).normalize()
    idx = pd.to_datetime(s)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return pd.DatetimeIndex(idx).normalize()


def _wide_from_abc(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    closes, highs = {}, {}
    for sym in symbols:
        path = ABC_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        if d.empty or "close" not in d.columns:
            continue
        idx = _bar_index(d["date"])
        closes[sym] = pd.Series(pd.to_numeric(d["close"], errors="coerce").to_numpy(), index=idx)
        highs[sym] = pd.Series(pd.to_numeric(d["high"], errors="coerce").to_numpy(), index=idx)
    return pd.DataFrame(closes).sort_index(), pd.DataFrame(highs).sort_index()


def _wide_ohlc_from_abc(symbols: list[str]) -> dict[str, pd.DataFrame]:
    buckets: dict[str, dict[str, pd.Series]] = {k: {} for k in ("open", "high", "low", "close")}
    for sym in symbols:
        path = ABC_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        if d.empty or "close" not in d.columns:
            continue
        idx = _bar_index(d["date"])
        for col in ("open", "high", "low", "close"):
            if col not in d.columns:
                continue
            buckets[col][sym] = pd.Series(
                pd.to_numeric(d[col], errors="coerce").to_numpy(), index=idx
            )
    return {k: pd.DataFrame(v).sort_index() for k, v in buckets.items()}


COMBINED_OHLC = OUT / "panel_hs300_zz500_1000_ohlc.parquet"


def load_combined_ohlc() -> dict[str, pd.DataFrame]:
    """沪深300+中证500/1000 的 open/high/low/close。当前成分，有幸存者偏差。"""
    if COMBINED_OHLC.exists():
        wide = pd.read_parquet(COMBINED_OHLC)
        return {k: wide[k].copy() for k in ("open", "high", "low", "close") if k in wide.columns}
    wide = pd.read_parquet(PANEL_500_1000)
    frames = {}
    for col in ("open", "high", "low", "close"):
        part = wide[col].copy()
        part.index = _bar_index(part.index.to_series())
        frames[col] = part
    abc = pd.read_csv(ABC_RESULTS)
    hs = sorted({str(s).lower() for s in abc.loc[abc["index"] == "沪深300", "symbol"]})
    extra = _wide_ohlc_from_abc(hs)
    out = {}
    for col in ("open", "high", "low", "close"):
        out[col] = frames[col].join(extra.get(col, pd.DataFrame()), how="outer")
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(out, axis=1).to_parquet(COMBINED_OHLC)
    print(f"写入 OHLC 合并面板 {out['close'].shape}")
    return out


def load_combined_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """沪深300（abc 缓存）+ 中证500/1000 主板面板。当前成分，有幸存者偏差。"""
    if COMBINED_PANEL.exists():
        wide = pd.read_parquet(COMBINED_PANEL)
        return wide["close"].copy(), wide["high"].copy()
    wide = pd.read_parquet(PANEL_500_1000)
    c500 = wide["close"].copy()
    h500 = wide["high"].copy()
    c500.index = _bar_index(c500.index.to_series())
    h500.index = _bar_index(h500.index.to_series())
    abc = pd.read_csv(ABC_RESULTS)
    hs = sorted({str(s).lower() for s in abc.loc[abc["index"] == "沪深300", "symbol"]})
    c300, h300 = _wide_from_abc(hs)
    close = c500.join(c300, how="outer")
    high = h500.join(h300, how="outer")
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat({"close": close, "high": high}, axis=1).to_parquet(COMBINED_PANEL)
    print(f"写入合并面板 {close.shape}")
    return close, high


def _meta(sym: str) -> dict:
    code = sym[2:]
    return {
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


def _selected(gate: dict[str, dict[str, bool]], start: str) -> set[str]:
    return {
        sym
        for sym, mp in gate.items()
        if any(d >= start and v for d, v in mp.items())
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, high = load_combined_panel()
    print(f"宇宙 {close.shape[1]} 只（沪深300+中证500+中证1000，非契合池）")

    variants = {
        "mom_top5": weekly_mom_gate_from_close(close, mom_n=20, k=5),
        "mom20_near5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="near_high"
        ),
        "mom20_persist5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="persist"
        ),
        "mom20_noclimax5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="not_climax"
        ),
    }
    labels = {
        "mom_top5": "一段：周频动量 Top5",
        "mom20_near5": "两段：动量Top20 → 近高 Top5",
        "mom20_persist5": "两段：动量Top20 → 上涨日占比 Top5",
        "mom20_noclimax5": "两段：动量Top20 → 未拉直 Top5",
    }

    union: set[str] = set()
    for gate in variants.values():
        union |= _selected(gate, REPORT_FROM)
    print(f"2025 起四套名单并集 {len(union)} 只")

    dailies = {}
    for sym in sorted(union):
        daily = load_daily(sym)
        if daily is not None:
            dailies[sym] = daily
    print(f"有日线 {len(dailies)}")

    books = {}
    rows = []
    for vid, gate in variants.items():
        print(f"== {vid} ==")
        s1 = {}
        need = [s for s in dailies if any(
            d >= REPORT_FROM and v for d, v in (gate.get(s) or {}).items()
        )]
        for i, sym in enumerate(need, 1):
            if i % 40 == 0 or i == 1:
                print(f"  {i}/{len(need)} {sym}")
            s1[sym] = run_one(_meta(sym), dailies[sym], s9=False, allowed=gate.get(sym))
        nav = active_nav({s: r["nav"] for s, r in s1.items()}, gate)
        bh = mom_bh_nav(close, gate)
        books[vid] = nav
        books[f"{vid}_bh"] = bh
        m = window_metrics(nav, start=REPORT_FROM)
        mb = window_metrics(bh, start=REPORT_FROM)
        sl = nav[nav.index >= pd.Timestamp(REPORT_FROM)]
        rows.append(
            {
                "id": vid,
                "label": labels[vid],
                "s1_ret": round(m["ret_pct"], 2),
                "s1_sharpe": round(m["sharpe"], 3),
                "s1_mdd": round(m["mdd_pct"], 2),
                "s1_y2025": round(_year_from_prior(sl, 2025), 2),
                "s1_y2026": round(_year_from_prior(sl, 2026), 2),
                "bh_ret": round(mb["ret_pct"], 2),
                "bh_sharpe": round(mb["sharpe"], 3),
                "n_trades": int(sum(r["n_trades"] for r in s1.values())),
            }
        )

    p2 = {}
    for cfg in (KAICHENG, TIANTONG):
        daily = load_daily(cfg.symbol)
        if daily is None:
            continue
        p2[cfg.symbol] = run_one(
            {
                "code": cfg.em_symbol,
                "symbol": cfg.symbol,
                "name": cfg.symbol_name,
                "entry_pct": cfg.resolved_entry_pct(),
                "stop_pct": cfg.resolved_stop_pct(),
                "tick": cfg.tick,
                "t0": False,
                "limit_down_pct": cfg.limit_down_pct,
                "stamp_tax_rate": cfg.stamp_tax_rate,
            },
            daily,
            s9=False,
            allowed=None,
        )
    nav_p2 = active_nav({s: r["nav"] for s, r in p2.items()}, None)
    mp = window_metrics(nav_p2, start=REPORT_FROM)
    slp = nav_p2[nav_p2.index >= pd.Timestamp(REPORT_FROM)]
    rows.append(
        {
            "id": "s1_pinned2",
            "label": "对照：策略1 仅凯盛+天通",
            "s1_ret": round(mp["ret_pct"], 2),
            "s1_sharpe": round(mp["sharpe"], 3),
            "s1_mdd": round(mp["mdd_pct"], 2),
            "s1_y2025": round(_year_from_prior(slp, 2025), 2),
            "s1_y2026": round(_year_from_prior(slp, 2026), 2),
            "bh_ret": float("nan"),
            "bh_sharpe": float("nan"),
            "n_trades": int(sum(r["n_trades"] for r in p2.values())),
        }
    )
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "summary.csv", index=False)
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# 两段选股：动量池 → 5 只 → 策略1",
                "",
                "研究回测，不构成投资建议。不用 26 只契合池。",
                "",
                f"- 宇宙：沪深300+中证500+中证1000 共 {close.shape[1]} 只（当前成分缓存，有幸存者偏差）",
                f"- 一段：周频 20 日动量 Top{STAGE1_K}；二段收到 {STAGE2_K} 只",
                f"- 事先 {N_TRIALS} 组（含一段动量 Top5），未在 2025 上再搜参数",
                "- 交易：策略1 仅止损，统一 ±2.5%",
                f"- 区间：{REPORT_FROM} 起",
                "",
                table.to_markdown(index=False),
                "",
                "本报告仅供研究参考，不构成投资建议。",
            ]
        ),
        encoding="utf-8",
    )
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
