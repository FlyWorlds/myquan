"""策略八·题材联动：当日涨停定题材 → 题材成分股当日因子1 ±阈值。

规则:
  · 宇宙: 中证1000
  · 题材: 通达信概念（离线 tdx_members_index.json）
  · 因子14: **当日**同题材涨停同伴数 theme_lu_count ≥ N
  · 股池: 热题材内成分股（默认排除当日已涨停的龙头，买联动票）
  · 买卖: **当日**开盘 ±entry_pct 突破即买；T+1 止损/收盘清
  · 情绪: T-1 连板梯度（与策略三同源）

回测说明: 日线用「当日收盘涨停池」定题材，同日 high 触达买点；与盯盘「盘中涨停→题材→阈值买」近似。
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.strategies.strategy8.concept_index import (  # noqa: E402
    load_concept_maps,
    theme_lu_stats,
)
from strategy.strategies.strategy3 import first_board as s3  # noqa: E402

OUT = _MYQUAN / "backtest" / "strategy8_theme_linkage"
SENTIMENT_CACHE = _MYQUAN / "backtest" / "strategy3_first_board" / "mkt_sentiment_zz1000.parquet"
UNIV_CACHE = s3.UNIV_CACHE
INITIAL = 1_000_000.0
MAX_POS = 10
MAX_ENTRIES_PER_DAY = 1
ORIGIN = pd.Timestamp("2020-01-01")
MIN_THEME_LU = 3
WORKERS = 8
# members=热题材全部成分；linkage=排除当日涨停龙头；lu_theme=仅当日涨停且在同题材内
POOL_MODE = "linkage"
GAP_MIN = -0.045
GAP_MAX = 0.03
APPLY_GAP_FILTER = False
MIN_VOL_RATIO = 0.0
MAX_VOL_RATIO = 99.0
THEME_LU_MAX: int | None = 9
SENTIMENT_LAG = 1
MKT_LU_MIN: int | None = None
MKT_LU_MAX: int | None = None
MKT_LIANBAN_MIN: int | None = 2
MKT_MAX_HEIGHT_MIN: int | None = 2
MKT_MAX_HEIGHT_MAX: int | None = 5
MKT_LADDER_SCORE_MIN: int | None = None

_DAILY_LU: dict[str, set[str]] = {}
_CODE_CONCEPTS: dict[str, list[str]] = {}
_CONCEPT_CODES: dict[str, list[str]] = {}


def _sync_sentiment_globals() -> None:
    s3.SENTIMENT_LAG = SENTIMENT_LAG
    s3.MKT_LU_MIN = MKT_LU_MIN
    s3.MKT_LU_MAX = MKT_LU_MAX
    s3.MKT_LIANBAN_MIN = MKT_LIANBAN_MIN
    s3.MKT_MAX_HEIGHT_MIN = MKT_MAX_HEIGHT_MIN
    s3.MKT_MAX_HEIGHT_MAX = MKT_MAX_HEIGHT_MAX
    s3.MKT_LADDER_SCORE_MIN = MKT_LADDER_SCORE_MIN
    s3.OUT = SENTIMENT_CACHE.parent
    s3._SENTIMENT = None
    s3._SENTIMENT_PREV = {}


def build_daily_lu_map(univ: pd.DataFrame) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for _, row in univ.iterrows():
        daily = s3.load_bars(row.symbol)
        if daily is None:
            continue
        dates = pd.DatetimeIndex(daily["date"])
        c = daily["close"].to_numpy(float)
        h = daily["high"].to_numpy(float)
        prev = np.roll(c, 1)
        prev[0] = np.nan
        lim = s3.limit_ratio(row.code)
        for k in range(1, len(c)):
            pc = float(prev[k])
            if pc <= 0:
                continue
            if s3.is_limit_up_close(pc, float(c[k]), float(h[k]), lim):
                ds = str(dates[k].date())
                out.setdefault(ds, set()).add(str(row.code).zfill(6))
    return out


def _rank_score(*, theme_lu: int, gap_pct: float, vol_ratio: float, pool_tag: str) -> float:
    score = min(theme_lu, 9) * 2.0
    if pool_tag == "题材联动":
        score += 2.0
    if -4.5 <= float(gap_pct) <= 0.0:
        score += 1.5
    if 1.2 <= vol_ratio <= 2.5:
        score += 1.0
    return round(score, 3)


def _passes_quality_filters(*, gap_pct: float, vol_ratio: float, theme_lu: int) -> bool:
    if THEME_LU_MAX is not None and theme_lu > THEME_LU_MAX:
        return False
    if MIN_VOL_RATIO > 0 and vol_ratio < MIN_VOL_RATIO:
        return False
    if MAX_VOL_RATIO < 99 and vol_ratio > MAX_VOL_RATIO:
        return False
    if APPLY_GAP_FILTER:
        g = float(gap_pct) / 100.0
        return GAP_MIN <= g <= GAP_MAX
    return True


def _pool_ok(*, in_today_lu: bool, theme_lu: int, pool_mode: str) -> tuple[bool, str]:
    if theme_lu < MIN_THEME_LU:
        return False, ""
    if pool_mode == "lu_theme":
        return (in_today_lu, "当日涨停") if in_today_lu else (False, "")
    if pool_mode == "linkage":
        return (not in_today_lu, "题材联动") if not in_today_lu else (False, "")
    return True, "题材成分"


def process_symbol(task: dict) -> dict:
    symbol = task["symbol"]
    code = str(task["code"]).zfill(6)
    name = task["name"]
    entry_pct = float(task["entry_pct"])
    pool_mode = str(task.get("pool_mode") or POOL_MODE)
    out: dict[str, Any] = {
        "symbol": symbol,
        "code": code,
        "name": name,
        "signals": [],
        "ok": 0,
        "error": "",
    }
    daily = s3.load_bars(symbol)
    if daily is None:
        out["error"] = "no_daily"
        return out

    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    vol = daily["volume"].to_numpy(float) if "volume" in daily.columns else np.ones(len(daily))
    prev = np.roll(c, 1)
    prev[0] = np.nan
    lim = s3.limit_ratio(code)

    lu = np.zeros(len(c), dtype=bool)
    for k in range(1, len(c)):
        pc = float(prev[k])
        if pc > 0:
            lu[k] = s3.is_limit_up_close(pc, float(c[k]), float(h[k]), lim)

    for j in range(1, len(c)):
        if dates[j] < ORIGIN:
            continue
        trade_ds = str(dates[j].date())
        lu_set = _DAILY_LU.get(trade_ds, set())
        theme_lu, theme_name, theme_members = theme_lu_stats(
            code,
            lu_set,
            code_to_concepts=_CODE_CONCEPTS,
            concept_to_codes=_CONCEPT_CODES,
        )
        ok_pool, pool_tag = _pool_ok(
            in_today_lu=bool(lu[j]),
            theme_lu=theme_lu,
            pool_mode=pool_mode,
        )
        if not ok_pool:
            continue

        sent_ok, sent = s3.sentiment_passes(trade_ds)
        if not sent_ok:
            continue

        oj, hj, lj, cj = float(o[j]), float(h[j]), float(l[j]), float(c[j])
        pc_j = float(prev[j]) if np.isfinite(prev[j]) else 0.0
        if oj <= 0 or pc_j <= 0:
            continue

        vwin = vol[max(0, j - 20) : j + 1]
        vol_ratio = float(vol[j]) / float(np.mean(vwin)) if len(vwin) and np.mean(vwin) > 0 else 1.0
        gap_pct = round((oj / pc_j - 1.0) * 100, 2)
        if not _passes_quality_filters(gap_pct=gap_pct, vol_ratio=vol_ratio, theme_lu=theme_lu):
            continue

        reason = ""
        entry = False
        if s3.cannot_buy_limit_up(
            prev_close=pc_j,
            open_px=oj,
            high_px=hj,
            low_px=lj,
            close_px=cj,
            limit_up_pct=lim,
        ):
            reason = "一字涨停开盘"
        elif s3.is_miaoban_unbuyable(
            prev_close=pc_j,
            open_px=oj,
            high_px=hj,
            low_px=lj,
            close_px=cj,
            limit_up_pct=lim,
            entry_pct=entry_pct,
        ):
            reason = "秒板"
        else:
            buy_px = s3.entry_trigger_price(oj, entry_pct=entry_pct)
            if hj + 1e-12 < buy_px:
                reason = "未触买点"
            else:
                entry = True
                reason = "买入"

        out["signals"].append(
            {
                "theme_date": trade_ds,
                "trade_date": trade_ds,
                "symbol": symbol,
                "code": code,
                "name": name,
                "entry_pct": entry_pct,
                "entry": entry,
                "reason": reason,
                "pool_tag": pool_tag,
                "theme_name": theme_name,
                "theme_lu_count": theme_lu,
                "theme_members": theme_members,
                "today_lu": bool(lu[j]),
                "buy_px": float(s3.entry_trigger_price(oj, entry_pct=entry_pct)) if oj > 0 else np.nan,
                "buy_i": j,
                "gap_pct": gap_pct,
                "vol_ratio": round(vol_ratio, 2),
                "sentiment_date": sent.get("sentiment_date"),
                "mkt_lu": sent.get("mkt_lu"),
                "mkt_lianban": sent.get("mkt_lianban"),
                "mkt_max_height": sent.get("mkt_max_height"),
                "rank_score": _rank_score(
                    theme_lu=theme_lu,
                    gap_pct=gap_pct,
                    vol_ratio=vol_ratio,
                    pool_tag=pool_tag,
                ),
            }
        )

    npz_path = OUT / "bars" / f"{symbol}.npz"
    if not npz_path.exists():
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            npz_path,
            dates=np.array([str(x.date()) for x in dates]),
            open=o,
            high=h,
            low=l,
            close=c,
            prev_close=prev,
            lim=np.array([lim]),
        )
    out["ok"] = 1
    return out


def _signal_cache_tag(entry_pct: float) -> str:
    tag = f"{entry_pct:.4f}".replace(".", "p")
    parts = ["td0", f"tm{MIN_THEME_LU}", POOL_MODE]
    if APPLY_GAP_FILTER:
        parts.append("gapf")
    if MIN_VOL_RATIO > 0:
        parts.append(f"vr{MIN_VOL_RATIO:.1f}".replace(".", "p"))
    if THEME_LU_MAX is not None:
        parts.append(f"tmax{THEME_LU_MAX}")
    if SENTIMENT_LAG:
        parts.append(f"lag{SENTIMENT_LAG}")
    if MKT_LIANBAN_MIN is not None:
        parts.append(f"lb{MKT_LIANBAN_MIN}")
    if MKT_MAX_HEIGHT_MIN is not None or MKT_MAX_HEIGHT_MAX is not None:
        lo = MKT_MAX_HEIGHT_MIN if MKT_MAX_HEIGHT_MIN is not None else 0
        hi = MKT_MAX_HEIGHT_MAX if MKT_MAX_HEIGHT_MAX is not None else 99
        parts.append(f"h{lo}_{hi}")
    return f"{tag}_{'_'.join(parts)}"


def _init_worker(cfg: dict[str, Any]) -> None:
    global POOL_MODE, MIN_THEME_LU, SENTIMENT_LAG
    global MKT_LU_MIN, MKT_LU_MAX, MKT_LIANBAN_MIN
    global MKT_MAX_HEIGHT_MIN, MKT_MAX_HEIGHT_MAX, MKT_LADDER_SCORE_MIN
    global APPLY_GAP_FILTER, MIN_VOL_RATIO, MAX_VOL_RATIO, THEME_LU_MAX
    global _DAILY_LU, _CODE_CONCEPTS, _CONCEPT_CODES
    POOL_MODE = str(cfg.get("POOL_MODE") or "linkage")
    MIN_THEME_LU = int(cfg.get("MIN_THEME_LU") or 3)
    APPLY_GAP_FILTER = bool(cfg.get("APPLY_GAP_FILTER", False))
    MIN_VOL_RATIO = float(cfg.get("MIN_VOL_RATIO") or 0.0)
    MAX_VOL_RATIO = float(cfg.get("MAX_VOL_RATIO") or 99.0)
    THEME_LU_MAX = cfg.get("THEME_LU_MAX")
    SENTIMENT_LAG = int(cfg.get("SENTIMENT_LAG") or 1)
    MKT_LU_MIN = cfg.get("MKT_LU_MIN")
    MKT_LU_MAX = cfg.get("MKT_LU_MAX")
    MKT_LIANBAN_MIN = cfg.get("MKT_LIANBAN_MIN")
    MKT_MAX_HEIGHT_MIN = cfg.get("MKT_MAX_HEIGHT_MIN")
    MKT_MAX_HEIGHT_MAX = cfg.get("MKT_MAX_HEIGHT_MAX")
    MKT_LADDER_SCORE_MIN = cfg.get("MKT_LADDER_SCORE_MIN")
    _DAILY_LU = cfg["daily_lu"]
    _CODE_CONCEPTS = cfg["code_concepts"]
    _CONCEPT_CODES = cfg["concept_codes"]
    _sync_sentiment_globals()
    s3._load_sentiment()


def build_signals(entry_pct: float, univ: pd.DataFrame, *, rebuild: bool = False) -> pd.DataFrame:
    tag = _signal_cache_tag(entry_pct)
    sig_cache = OUT / f"signals_{tag}.parquet"
    if sig_cache.exists() and not rebuild:
        return pd.read_parquet(sig_cache)

    codes = tuple(sorted(str(c).zfill(6) for c in univ["code"]))
    code_concepts, concept_codes = load_concept_maps(codes)
    print(f"  概念映射: {len(concept_codes)} 题材 · {len(code_concepts)} 成分股")
    daily_lu = build_daily_lu_map(univ)
    cfg = {
        "POOL_MODE": POOL_MODE,
        "MIN_THEME_LU": MIN_THEME_LU,
        "APPLY_GAP_FILTER": APPLY_GAP_FILTER,
        "MIN_VOL_RATIO": MIN_VOL_RATIO,
        "MAX_VOL_RATIO": MAX_VOL_RATIO,
        "THEME_LU_MAX": THEME_LU_MAX,
        "SENTIMENT_LAG": SENTIMENT_LAG,
        "MKT_LU_MIN": MKT_LU_MIN,
        "MKT_LU_MAX": MKT_LU_MAX,
        "MKT_LIANBAN_MIN": MKT_LIANBAN_MIN,
        "MKT_MAX_HEIGHT_MIN": MKT_MAX_HEIGHT_MIN,
        "MKT_MAX_HEIGHT_MAX": MKT_MAX_HEIGHT_MAX,
        "MKT_LADDER_SCORE_MIN": MKT_LADDER_SCORE_MIN,
        "daily_lu": daily_lu,
        "code_concepts": code_concepts,
        "concept_codes": concept_codes,
    }
    tasks = [{**r, "entry_pct": entry_pct, "pool_mode": POOL_MODE} for r in univ.to_dict(orient="records")]
    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, initializer=_init_worker, initargs=(cfg,)) as ex:
        futs = {ex.submit(process_symbol, t): t for t in tasks}
        done = 0
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            rows.extend(res.get("signals") or [])
            if done % 100 == 0 or done == len(tasks):
                print(f"  信号 thr={entry_pct*100:.1f}% {done}/{len(tasks)} ({time.time()-t0:.0f}s)")
    signals = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(sig_cache, index=False)
    return signals


def _rebase_summary(
    eq: pd.DataFrame,
    tr: pd.DataFrame,
    summary: dict[str, Any],
    *,
    start: str | None,
) -> dict[str, Any]:
    if not start or eq.empty:
        return summary
    start_ds = start[:4] + "-" + start[4:6] + "-" + start[6:8]
    eq2 = eq[eq["date"] >= pd.Timestamp(start_ds)]
    if len(eq2) < 2:
        return summary
    e0, e1 = float(eq2["equity"].iloc[0]), float(eq2["equity"].iloc[-1])
    rets = eq2["equity"].pct_change().dropna()
    peak = eq2["equity"].cummax()
    max_dd = float(-(eq2["equity"] / peak - 1).min()) * 100
    import math

    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * math.sqrt(242))
        if len(rets) > 5 and rets.std(ddof=1) > 0
        else 0.0
    )
    tr2 = tr[tr["buy_date"] >= start_ds] if len(tr) else tr
    wins = tr2[tr2["ret_pct"] > 0] if len(tr2) else tr2
    out = dict(summary)
    out["start"] = str(eq2["date"].iloc[0].date())
    out["end"] = str(eq2["date"].iloc[-1].date())
    out["total_return_pct"] = (e1 / e0 - 1.0) * 100
    out["end_equity"] = e1
    out["max_drawdown_pct"] = max_dd
    out["sharpe_ratio"] = sharpe
    out["n_trades"] = int(len(tr2))
    out["win_rate"] = float(len(wins) / len(tr2)) if len(tr2) else 0.0
    out["avg_trade_ret"] = float(tr2["ret_pct"].mean()) if len(tr2) else 0.0
    return out


def run_portfolio(signals: pd.DataFrame, *, entry_pct: float) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    old_out = s3.OUT
    old_max = s3.MAX_POS
    old_daily = s3.MAX_ENTRIES_PER_DAY
    old_init = s3.INITIAL
    s3.OUT = OUT
    s3.MAX_POS = MAX_POS
    s3.MAX_ENTRIES_PER_DAY = MAX_ENTRIES_PER_DAY
    s3.INITIAL = INITIAL
    try:
        return s3.run_portfolio(signals, entry_pct=entry_pct)
    finally:
        s3.OUT = old_out
        s3.MAX_POS = old_max
        s3.MAX_ENTRIES_PER_DAY = old_daily
        s3.INITIAL = old_init


def run_theme_linkage_backtest(
    *,
    start: str = "20250101",
    end: str | None = None,
    entry_pcts: tuple[float, ...] = (0.025, 0.03),
    initial_cash: float = INITIAL,
    max_positions: int = MAX_POS,
    min_theme_lu: int = MIN_THEME_LU,
    pool_mode: str = POOL_MODE,
    apply_gap_filter: bool = APPLY_GAP_FILTER,
    min_vol_ratio: float = MIN_VOL_RATIO,
    max_vol_ratio: float = MAX_VOL_RATIO,
    theme_lu_max: int | None = THEME_LU_MAX,
    mkt_lianban_min: int | None = MKT_LIANBAN_MIN,
    mkt_max_height_min: int | None = MKT_MAX_HEIGHT_MIN,
    mkt_max_height_max: int | None = MKT_MAX_HEIGHT_MAX,
    sentiment_lag: int = SENTIMENT_LAG,
    rebuild_signals: bool = False,
) -> dict[str, Any]:
    global INITIAL, MAX_POS, MIN_THEME_LU, POOL_MODE
    global APPLY_GAP_FILTER, MIN_VOL_RATIO, MAX_VOL_RATIO, THEME_LU_MAX
    global MKT_LIANBAN_MIN, MKT_MAX_HEIGHT_MIN, MKT_MAX_HEIGHT_MAX, SENTIMENT_LAG
    INITIAL = float(initial_cash)
    MAX_POS = int(max_positions)
    MIN_THEME_LU = int(min_theme_lu)
    POOL_MODE = str(pool_mode or "linkage")
    APPLY_GAP_FILTER = bool(apply_gap_filter)
    MIN_VOL_RATIO = float(min_vol_ratio)
    MAX_VOL_RATIO = float(max_vol_ratio)
    THEME_LU_MAX = theme_lu_max
    MKT_LIANBAN_MIN = mkt_lianban_min
    MKT_MAX_HEIGHT_MIN = mkt_max_height_min
    MKT_MAX_HEIGHT_MAX = mkt_max_height_max
    SENTIMENT_LAG = max(int(sentiment_lag), 0)
    _sync_sentiment_globals()
    OUT.mkdir(parents=True, exist_ok=True)

    if rebuild_signals:
        for p in OUT.glob("signals_*.parquet"):
            p.unlink(missing_ok=True)

    print("加载中证1000…")
    univ = s3.load_zz1000()
    s3.ensure_daily(univ)
    univ = univ[
        univ["symbol"].apply(lambda s: (UNIV_CACHE / f"{s}_daily_qfq.parquet").exists())
    ].reset_index(drop=True)
    print(f"有日线 {len(univ)}")

    if not SENTIMENT_CACHE.is_file():
        s3.build_market_sentiment(univ, rebuild=False)
    s3._load_sentiment()

    pool_label = {
        "members": "热题材成分",
        "linkage": "题材联动（非当日涨停）",
        "lu_theme": "当日涨停+同题材",
    }.get(POOL_MODE, POOL_MODE)
    print(f"股池: {pool_label} · 当日涨停定题材≥{MIN_THEME_LU} · 当日阈值买 · T-{SENTIMENT_LAG}情绪")

    summaries = []
    for thr in entry_pcts:
        print(f"\n=== 阈值 ±{thr*100:.1f}% ===")
        signals = build_signals(thr, univ, rebuild=rebuild_signals)
        if start:
            signals = signals[signals["trade_date"] >= start[:4] + "-" + start[4:6] + "-" + start[6:8]]
        if end:
            signals = signals[signals["trade_date"] <= end[:4] + "-" + end[4:6] + "-" + end[6:8]]
        n_buy = int((signals["entry"] == True).sum()) if len(signals) else 0  # noqa: E712
        print(f"信号 {len(signals)} · 可买 {n_buy} · 题材 {signals['theme_name'].nunique() if len(signals) else 0}")
        eq, summary, tr = run_portfolio(signals, entry_pct=thr)
        summary = _rebase_summary(eq, tr, summary, start=start)
        summary["min_theme_lu"] = MIN_THEME_LU
        summary["pool_mode"] = POOL_MODE
        summary["theme_same_day"] = True
        summary["apply_gap_filter"] = APPLY_GAP_FILTER
        summary["sentiment_lag"] = SENTIMENT_LAG
        summary["mkt_lianban_min"] = MKT_LIANBAN_MIN
        summary["mkt_max_height_min"] = MKT_MAX_HEIGHT_MIN
        summary["mkt_max_height_max"] = MKT_MAX_HEIGHT_MAX
        tag = _signal_cache_tag(thr)
        eq.to_csv(OUT / f"equity_{tag}.csv", index=False, encoding="utf-8-sig")
        tr.to_csv(OUT / f"trades_{tag}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summary)
        print(
            f"  收益 {summary['total_return_pct']:.1f}%  回撤 {summary['max_drawdown_pct']:.1f}%  "
            f"夏普 {summary['sharpe_ratio']:.2f}  胜率 {summary['win_rate']*100:.1f}%  "
            f"笔数 {summary['n_trades']}"
        )

    sum_df = pd.DataFrame(summaries)
    sum_df.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"summaries": summaries, "output_dir": str(OUT)}
