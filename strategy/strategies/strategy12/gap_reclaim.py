"""策略十二回测：昨日收盘涨停、今日低开未封涨停，开盘买、T+1 收盘清。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.costs import ENGINE_COMMISSION_RATE, SLIPPAGE_VALUE, STAMP_TAX_RATE
from strategy.factors.factor15 import GAP_MAX, GAP_MIN
from strategy.factors.factor18 import LD_OPEN_PANIC_MIN
from strategy.factors.factor21 import REQUIRE_YEST_OPENED, SKIP_YEST_IDX_RET
from strategy.open_break import TICK_SIZE, limit_down_state, limit_up_state
from strategy.strategies.strategy12.emotion_gate import load_ld_open_daily

_MYQUAN = Path(__file__).resolve().parents[3]
OUT = _MYQUAN / "backtest" / "strategy12_emotion_gate"
UNIV_PATH = _MYQUAN / "backtest" / "strategy3_first_board" / "zz1000_univ.parquet"
BAR_DIR = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
DATA_CACHE = _MYQUAN / "data_cache"

INITIAL = 1_000_000.0
MAX_POS = 3
MAX_ENTRIES_PER_DAY = 3
OOS_START = "2024-01-01"
TUNE_END = "2024-12-31"
BLIND_START = "2025-01-02"
LU_TOL = 0.012


def _limit_ratio(code: str) -> float:
    c = str(code).zfill(6)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def _norm_dates(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s)
    tz = getattr(out.dt, "tz", None)
    if tz is not None:
        out = out.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return out.dt.normalize()


def _bar_path(symbol: str) -> Path | None:
    for root in (BAR_DIR, DATA_CACHE):
        p = root / f"{symbol}_daily_qfq.parquet"
        if p.is_file():
            return p
    return None


def _scan_one(
    *,
    sym: str,
    code: str,
    name: str,
    path: Path,
    ld_map: dict[str, int],
    start_ts: pd.Timestamp,
) -> list[dict[str, Any]]:
    df = pd.read_parquet(path, columns=["date", "open", "high", "low", "close"])
    df["date"] = _norm_dates(df["date"])
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if len(df) < 40:
        return []
    prev = df["close"].shift(1)
    yest_prev = df["close"].shift(2)
    gap = df["open"] / prev - 1.0
    dstr = df["date"].dt.strftime("%Y-%m-%d")
    ld = dstr.map(ld_map)
    lim = _limit_ratio(code)
    yest_open = df["open"].shift(1)
    yest_high = df["high"].shift(1)
    yest_low = df["low"].shift(1)
    yest_ceil = yest_prev * (1.0 + lim)
    yest_lu = (prev >= yest_ceil * (1.0 - LU_TOL)) & (prev > yest_prev)
    open_ret = df["open"] / prev - 1.0
    lu_open = open_ret >= (lim - LU_TOL)
    nxt = df["date"].shift(-1)
    mask = (
        (df["date"] >= start_ts)
        & ld.notna()
        & (ld.astype(float) < float(LD_OPEN_PANIC_MIN))
        & yest_lu.fillna(False)
        & np.isfinite(gap)
        & (gap >= GAP_MIN)
        & (gap <= GAP_MAX)
        & (~lu_open.fillna(True))
        & nxt.notna()
        & (df["open"] > 0)
    )
    if not bool(mask.any()):
        return []
    hit = df.loc[mask]
    out: list[dict[str, Any]] = []
    for i in hit.index:
        g = float(gap.at[i])
        o = float(df.at[i, "open"])
        st = limit_up_state(
            prev_close=float(yest_prev.at[i]) if pd.notna(yest_prev.at[i]) else None,
            open_px=float(yest_open.at[i]),
            high_px=float(yest_high.at[i]),
            low_px=float(yest_low.at[i]),
            close_px=float(prev.at[i]),
            limit_up_pct=lim,
        )
        out.append(
            {
                "trade_date": str(dstr.at[i]),
                "symbol": sym,
                "code": code,
                "name": name,
                "gap": g,
                "gap_pct": g * 100.0,
                "ld_open": int(ld.at[i]),
                "yest_lu": True,
                "yest_locked": bool(st["locked"]),
                "yest_opened": bool(st["opened"]),
                "yest_open_at_limit": bool(st["open_at_limit"]),
                "today_lu_open": False,
                "rank_score": -g,
                "entry_px": o,
                "open": o,
                "entry": True,
            }
        )
    return out


def scan_signals(
    *,
    start: str = "20200102",
) -> pd.DataFrame:
    emo = load_ld_open_daily()
    ld_map = {
        str(r["date"]): int(r["mkt_ld_open"])
        for _, r in emo.iterrows()
        if pd.notna(r.get("mkt_ld_open"))
    }
    univ = pd.read_parquet(UNIV_PATH)
    start_ts = pd.Timestamp(start)
    rows: list[dict[str, Any]] = []
    n_ok = 0
    for i, u in univ.iterrows():
        sym = str(u["symbol"])
        code = str(u.get("code") or "")
        path = _bar_path(sym)
        if path is None:
            continue
        n_ok += 1
        rows.extend(
            _scan_one(
                sym=sym,
                code=code,
                name=str(u.get("name") or code),
                path=path,
                ld_map=ld_map,
                start_ts=start_ts,
            )
        )
        if n_ok % 400 == 0:
            print(f"  扫描进度 {n_ok} 只，候选 {len(rows)}")
    sig = pd.DataFrame(rows)
    if sig.empty:
        return sig
    idx_path = _MYQUAN / "backtest" / "strategy9_limit_down_emotion" / "emotion_index_merged.csv"
    if idx_path.is_file():
        idx = pd.read_csv(idx_path, usecols=lambda c: c in ("date", "ret_close"))
        idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
        idx = idx.sort_values("date")
        idx["yest_idx_ret"] = idx["ret_close"].shift(1)
        ret_map = dict(zip(idx["date"], idx["yest_idx_ret"]))
        sig["yest_idx_ret"] = sig["trade_date"].map(ret_map)
    sig = sig.sort_values(["trade_date", "rank_score", "symbol"], ascending=[True, False, True])
    return sig.reset_index(drop=True)


def filter_signals(
    sig: pd.DataFrame,
    *,
    require_opened: bool = False,
    drop_locked: bool = False,
    gap_min: float | None = None,
    gap_max: float | None = None,
    max_yest_idx_ret: float | None = None,
    rank_deepest: bool = True,
) -> pd.DataFrame:
    """调参用过滤。默认不改信号，由调用方显式打开开关。"""
    out = sig.copy()
    if out.empty:
        return out
    if require_opened and "yest_opened" in out.columns:
        out = out[out["yest_opened"] == True]  # noqa: E712
    if drop_locked and "yest_locked" in out.columns:
        out = out[out["yest_locked"] != True]  # noqa: E712
    if gap_min is not None:
        out = out[out["gap"] >= float(gap_min)]
    if gap_max is not None:
        out = out[out["gap"] <= float(gap_max)]
    if max_yest_idx_ret is not None and "yest_idx_ret" in out.columns:
        out = out[out["yest_idx_ret"].isna() | (out["yest_idx_ret"] > float(max_yest_idx_ret))]
    if rank_deepest:
        out["rank_score"] = -out["gap"].astype(float)
    else:
        out["rank_score"] = out["gap"].astype(float)
    if out.empty:
        return out
    return out.sort_values(
        ["trade_date", "rank_score", "symbol"], ascending=[True, False, True]
    ).reset_index(drop=True)


_BAR_CACHE: dict[str, pd.DataFrame] = {}


@dataclass
class _Pos:
    symbol: str
    code: str
    name: str
    shares: float
    entry_px: float
    buy_date: pd.Timestamp


def _bars(sym: str) -> pd.DataFrame:
    if sym not in _BAR_CACHE:
        p = _bar_path(sym)
        d = pd.read_parquet(p, columns=["date", "open", "high", "low", "close"])
        d["date"] = _norm_dates(d["date"])
        d = d.sort_values("date").reset_index(drop=True)
        d["prev"] = d["close"].shift(1)
        _BAR_CACHE[sym] = d
    return _BAR_CACHE[sym]


def run_portfolio(
    signals: pd.DataFrame,
    *,
    initial: float = INITIAL,
    max_pos: int = MAX_POS,
    max_entries: int = MAX_ENTRIES_PER_DAY,
    start: str = "2020-01-02",
    end: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    if signals.empty:
        empty = pd.DataFrame(columns=["date", "equity", "cash"])
        return empty, {"total_return_pct": 0.0, "n_trades": 0}, pd.DataFrame()

    def bars(sym: str) -> pd.DataFrame:
        return _bars(sym)

    cal = pd.to_datetime(sorted(load_ld_open_daily()["date"].unique()))
    cal = cal[cal >= pd.Timestamp(start)]
    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    by_day = {
        str(pd.Timestamp(d).date()): g
        for d, g in signals.groupby("trade_date")
    }
    cash = float(initial)
    positions: list[_Pos] = []
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    comm = ENGINE_COMMISSION_RATE
    slip = SLIPPAGE_VALUE
    stamp = STAMP_TAX_RATE

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        ds = str(dt.date())
        still: list[_Pos] = []
        for p in positions:
            b = bars(p.symbol)
            hit = b.index[b["date"] == dt]
            if len(hit) == 0:
                still.append(p)
                continue
            j = int(hit[0])
            oi, hi, li, ci = (
                float(b.at[j, "open"]),
                float(b.at[j, "high"]),
                float(b.at[j, "low"]),
                float(b.at[j, "close"]),
            )
            t1 = dt > p.buy_date
            if not t1:
                still.append(p)
                continue
            prev_c = float(b.at[j, "prev"]) if pd.notna(b.at[j, "prev"]) else ci
            lims = limit_down_state(
                prev_close=prev_c,
                open_px=oi,
                high_px=hi,
                low_px=li,
                close_px=ci,
                limit_down_pct=_limit_ratio(p.code),
                tick=TICK_SIZE,
            )
            if bool(lims["locked"]):
                still.append(p)
                continue
            sell_px = ci * (1 - slip)
            reason = "T+1收盘清仓"
            proceeds = p.shares * sell_px
            fee = proceeds * (comm + stamp)
            cash += proceeds - fee
            trades.append(
                {
                    "symbol": p.symbol,
                    "code": p.code,
                    "buy_date": str(p.buy_date.date()),
                    "sell_date": ds,
                    "buy_px": p.entry_px,
                    "sell_px": sell_px,
                    "ret_pct": (sell_px / p.entry_px - 1.0) * 100,
                    "reason": reason,
                }
            )
        positions = still

        free = max_pos - len(positions)
        if free > 0 and ds in by_day:
            cands = by_day[ds]
            held = {p.symbol for p in positions}
            cands = cands[~cands["symbol"].isin(held)].head(max_entries)
            nav = cash
            for p in positions:
                b = bars(p.symbol)
                hit = b.index[b["date"] == dt]
                if len(hit):
                    nav += p.shares * float(b.at[int(hit[0]), "close"])
            slot = nav / max_pos if max_pos else 0.0
            for _, r in cands.iterrows():
                if len(positions) >= max_pos:
                    break
                buy_px = float(r["entry_px"]) * (1 + slip)
                if buy_px <= 0 or cash < buy_px * 100:
                    continue
                budget = min(slot, cash) * 0.95
                shares = int(budget / buy_px / 100) * 100
                if shares < 100:
                    continue
                cost = shares * buy_px
                fee = cost * comm
                cash -= cost + fee
                positions.append(
                    _Pos(
                        symbol=str(r["symbol"]),
                        code=str(r["code"]),
                        name=str(r["name"]),
                        shares=float(shares),
                        entry_px=buy_px,
                        buy_date=dt,
                    )
                )

        mtm = cash
        for p in positions:
            b = bars(p.symbol)
            hit = b.index[b["date"] == dt]
            px = float(b.at[int(hit[0]), "close"]) if len(hit) else p.entry_px
            mtm += p.shares * px
        equity_rows.append({"date": ds, "equity": mtm, "cash": cash, "n_pos": len(positions)})

    eq = pd.DataFrame(equity_rows)
    tr = pd.DataFrame(trades)
    summary = _summarize(eq, tr, initial=initial)
    return eq, summary, tr


def _sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if len(s) < 20 or float(s.std()) <= 1e-12:
        return float("nan")
    return float(s.mean() / s.std() * np.sqrt(242))


def _mdd(eq: pd.Series) -> float:
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float((-dd.min()) * 100) if len(dd) else 0.0


def _summarize(eq: pd.DataFrame, tr: pd.DataFrame, *, initial: float) -> dict[str, Any]:
    if eq.empty:
        return {"total_return_pct": 0.0, "n_trades": 0}
    e = eq.copy()
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values("date")
    ret = e["equity"].pct_change().fillna(0.0)
    e0, e1 = float(e["equity"].iloc[0]), float(e["equity"].iloc[-1])
    # 用初始本金，避免首日已有仓把起点抬高
    total = (e1 / float(initial) - 1.0) * 100
    n = 0 if tr.empty else int(len(tr))
    win = float((tr["ret_pct"] > 0).mean() * 100) if n else float("nan")
    oos = e[e["date"] >= pd.Timestamp(OOS_START)]
    ins = e[e["date"] < pd.Timestamp(OOS_START)]
    def _leg(part: pd.DataFrame) -> dict[str, float]:
        if len(part) < 2:
            return {"ret": float("nan"), "mdd": float("nan"), "sharpe": float("nan")}
        r = part["equity"].pct_change().dropna()
        return {
            "ret": (float(part["equity"].iloc[-1]) / float(part["equity"].iloc[0]) - 1.0) * 100,
            "mdd": _mdd(part["equity"]),
            "sharpe": _sharpe(r),
        }
    is_m, oos_m = _leg(ins), _leg(oos)
    return {
        "entry": "open",
        "total_return_pct": total,
        "max_drawdown_pct": _mdd(e["equity"]),
        "sharpe_ratio": _sharpe(ret.iloc[1:]),
        "win_rate": win,
        "n_trades": n,
        "end_equity": e1,
        "is_return_pct": is_m["ret"],
        "is_mdd_pct": is_m["mdd"],
        "is_sharpe": is_m["sharpe"],
        "oos_return_pct": oos_m["ret"],
        "oos_mdd_pct": oos_m["mdd"],
        "oos_sharpe": oos_m["sharpe"],
        "oos_start": OOS_START,
        "passed": bool(
            is_m["ret"] == is_m["ret"]
            and is_m["ret"] > 0
            and (is_m["sharpe"] == is_m["sharpe"] and is_m["sharpe"] > 0)
            and oos_m["ret"] == oos_m["ret"]
            and oos_m["ret"] > 0
            and (oos_m["sharpe"] == oos_m["sharpe"] and oos_m["sharpe"] > 0)
            and oos_m["mdd"] < 40.0
        ),
    }


def run_gap_reclaim_backtest(
    *,
    verbose: bool = True,
    rescan: bool = False,
) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    sig_path = OUT / "signals.parquet"
    need = ("yest_opened", "yest_locked", "yest_idx_ret")
    if (not rescan) and sig_path.is_file():
        sig = pd.read_parquet(sig_path)
        if not all(c in sig.columns for c in need):
            sig = None
    else:
        sig = None
    if sig is None:
        if verbose:
            print(f"扫描信号 昨收涨停+今低开未封涨停  恐慌日(ld≥{LD_OPEN_PANIC_MIN})空仓  开盘买 T+1收盘清")
        sig = scan_signals()
        sig.to_parquet(sig_path, index=False)
    filt = filter_signals(
        sig,
        require_opened=REQUIRE_YEST_OPENED,
        max_yest_idx_ret=SKIP_YEST_IDX_RET,
    )
    if verbose:
        print(
            f"候选 {len(sig)} 条 → 过滤后 {len(filt)} 条 / "
            f"{filt['trade_date'].nunique() if len(filt) else 0} 日"
            f"（昨开板={REQUIRE_YEST_OPENED}  上证昨收门={SKIP_YEST_IDX_RET}）"
        )
    eq, summary, tr = run_portfolio(filt)
    eq.to_csv(OUT / "nav_daily.csv", index=False)
    if not tr.empty:
        tr.to_csv(OUT / "trades.csv", index=False)
    web = [
        {
            "entry": "open",
            "total_return_pct": summary.get("total_return_pct"),
            "max_drawdown_pct": summary.get("max_drawdown_pct"),
            "sharpe_ratio": summary.get("sharpe_ratio"),
            "win_rate": summary.get("win_rate"),
            "n_trades": summary.get("n_trades"),
        }
    ]
    (OUT / "summary.json").write_text(json.dumps(web, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "summary_detail.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "n_signals": int(len(sig)),
                "n_signals_filtered": int(len(filt)),
                "require_opened": REQUIRE_YEST_OPENED,
                "skip_yest_idx_ret": SKIP_YEST_IDX_RET,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_report(summary, n_sig=len(sig), n_filt=len(filt))
    if verbose:
        print(
            f"全样本 {summary.get('total_return_pct'):.1f}%  "
            f"OOS {summary.get('oos_return_pct'):.1f}%  "
            f"过关={summary.get('passed')}  笔数={summary.get('n_trades')}"
        )
    return {"summary": summary, "equity": eq, "trades": tr, "signals": filt}


def _write_report(summary: dict[str, Any], *, n_sig: int, n_filt: int) -> None:
    passed = "过关" if summary.get("passed") else "未过关"
    tune_path = OUT / "tune_result.json"
    tune = json.loads(tune_path.read_text(encoding="utf-8")) if tune_path.is_file() else {}
    wis = (tune.get("variants_is") or [])
    win = next((r for r in wis if r.get("id") == tune.get("winner_id")), None)
    blind = tune.get("blind") or {}
    lines = [
        "# 策略十二·涨停次日低开",
        "",
        "> 研究用途，非投资建议。不绑定凯盛/天通。v1–v5 已否决或被 v6 替换。",
        "",
        "## ITER_NOTE",
        "",
        "- op_type: event_universe_limit_up_next_gap",
        "- hypothesis: 真涨停且盘中开过板的次日低开更像获利回吐；大盘昨收大跌时低开是传染不是回档。",
        "- change: v6=昨开板 + 上证昨收≤-2% 空仓。调参窗 2020-01-02～2024-12-31，盲测 2025-01-02～今。",
        "- expected: 调参窗累计>0 且夏普>0；盲测累计>0、夏普>0、MDD<40% 才过关。",
        "",
        f"**结论：{passed}**（调参窗通过，盲测回撤超门槛）",
        "",
        "## 一字板",
        "",
        "- **今日**开盘涨停：不买（买不进）。",
        "- **卖出**：T+1 若一字跌停 locked 则不卖、顺延。",
        "- **昨日**：要求 `limit_up_state.opened`（触及涨停价且盘中打开）。全日一字锁定仅 21/4202；",
        "  未开板约一半候选其实从未触及涨停价（收盘容差 1.2% 过宽），开板过滤同时纠正了假涨停。",
        "",
        "## 规则（v6 冻结）",
        "",
        f"- 因子21：昨收涨停且曾开板，今日 gap ∈ [{GAP_MIN:.1%}, {GAP_MAX:.1%}] 且开盘未封涨停",
        f"- 因子18：低开开盘跌停家数 ≥ {LD_OPEN_PANIC_MIN} 的恐慌日空仓",
        f"- 上证昨收 ≤ {SKIP_YEST_IDX_RET:.0%}（开盘已知）空仓",
        "- 退出：T+1 收盘清仓；一字跌停无法卖则顺延",
        f"- 组合：{INITIAL:.0f} 本金，最多 {MAX_POS} 仓，每日最多 {MAX_ENTRIES_PER_DAY} 笔，按低开越深优先",
        "- 费用：佣金+杂费+印花+滑点（strategy.costs）",
        "",
        "## 调参 / 盲测（官方口径，本金各自 100 万）",
        "",
        "用户「2020-2025 调参、2025至今盲测」为避免 2025 重叠：调参截到 2024-12-31，盲测从 2025-01-02 起。选参只看调参窗。",
        "",
    ]
    if win:
        m = win["is"]
        lines += [
            "| 样本 | 区间 | 累计收益 | 最大回撤 | 夏普 | 笔数 |",
            "|------|------|----------|----------|------|------|",
            f"| 调参 | 2020-01-02～2024-12-31 | {m['ret_pct']:+.1f}% | {m['mdd_pct']:.1f}% | {m['sharpe']:.2f} | {m['n_trades']} |",
            f"| 盲测 | 2025-01-02～2026-08-28 | {blind.get('ret_pct', float('nan')):+.1f}% | {blind.get('mdd_pct', float('nan')):.1f}% | {blind.get('sharpe', float('nan')):.2f} | {blind.get('n_trades', 0)} |",
            "",
        ]
    lines += [
        "## 全样本（同一套 v6 规则、一条净值 2020→今）",
        "",
        "| 样本 | 累计收益 | 最大回撤 | 夏普 |",
        "|------|----------|----------|------|",
        f"| 全样本 | {summary.get('total_return_pct', float('nan')):.1f}% | {summary.get('max_drawdown_pct', float('nan')):.1f}% | {summary.get('sharpe_ratio', float('nan')):.2f} |",
        f"| 切分 IS <{OOS_START} | {summary.get('is_return_pct', float('nan')):.1f}% | {summary.get('is_mdd_pct', float('nan')):.1f}% | {summary.get('is_sharpe', float('nan')):.2f} |",
        f"| 切分 OOS ≥{OOS_START} | {summary.get('oos_return_pct', float('nan')):.1f}% | {summary.get('oos_mdd_pct', float('nan')):.1f}% | {summary.get('oos_sharpe', float('nan')):.2f} |",
        "",
        f"闭环 {summary.get('n_trades')} 笔，胜率 {summary.get('win_rate', float('nan')):.1f}%，原始信号 {n_sig} / 过滤后 {n_filt}。",
        "",
        "过关门槛：调参窗累计>0 且夏普>0，**并且**盲测累计>0、夏普>0、MDD<40%。",
        "本轮调参窗通过；盲测累计略正但回撤 55%，**未过关**（不在盲测窗上再调参）。",
        "",
        "## 2026 为什么差",
        "",
        "- 不是「没过滤今日一字涨停」。今日开盘涨停本来就不买。",
        "- 盲测内 2025 单笔均 +0.42%；2026 均 −0.11%，组合从 2026 年初约 134 万落到 7/30 的 73 万（相对盲测高点 −55%）。",
        "- 7 月主导：32 笔均 −3.03%。上证阴跌（约 4112→3764），因子18 的 `mkt_ld_open` 全月 0–2、从未≥4，恐慌门不触发。",
        "- 上证昨收≤−2% 门只能空出少数大阴次日；7/17 当日 T-1 只跌约 1.8%，当天仍会买。慢熊不是恐慌日模型。",
        "- 8 月 9 笔均 +10.6% 把年内单笔亏补回一部分，但高点回撤仍在。",
        "",
        "## 已否决 / 迭代",
        "",
        "| 轮次 | 规则 | 结果 |",
        "|------|------|------|",
        "| v1 | 因子18 恐慌日禁止凯盛/天通因子1 新开仓 | 样本内收益下降 |",
        "| v2 | 压力日低开 + 追开盘+2.5% + T+1 止损 | 全样本 -77.8% |",
        "| v3 | 压力日低开、开盘买、T+1 收盘清 | IS -21.8% |",
        "| v4 | 昨收跌停次日开板，恐慌日空仓 | 全样本 -42%，OOS -67% |",
        "| v5 | 昨收涨停次日低开，恐慌日空仓（无开板过滤） | 旧 OOS −23%、回撤 69% |",
        "| v6（当前） | 昨开板 + 上证昨收≤−2% 空仓 | 调参窗 +645%/夏普 1.23；盲测 +3.6%/回撤 55% |",
        "",
        "调参变体表见 `TUNE.md`。仅剔昨一字锁定几乎无效（21 笔）；要求开板才同时去掉假涨停。",
        "",
        "## 复现",
        "",
        "```bash",
        "python backtest/strategy12_emotion_gate/tune.py",
        "python backtest/strategy12_emotion_gate/run.py",
        "python -c \"from strategy import run_strategy12; run_strategy12()\"",
        "```",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = [
    "scan_signals",
    "filter_signals",
    "run_portfolio",
    "run_gap_reclaim_backtest",
    "OUT",
    "TUNE_END",
    "BLIND_START",
]
