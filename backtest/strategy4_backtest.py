"""策略四回测：累计评分可买 Top20 × 因子1 开盘突破（中证500+1000）。

规则对齐 strategy4.pool：
  · 评分月 M 的 cum2020 截面分 → 交易月 M+1 使用（无前瞻）
  · 每日：已持仓票不进 Top20；买入前置未过不进 Top20
  · 仅对当日可买 Top20 内、空仓触开盘突破者开仓；有仓按开盘止损
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)
from strategy.strategies._unreg_s4.pool import (  # noqa: E402
    POOL_DEFAULTS,
    score_universe,
)

PATHS = _MYQUAN / "backtest" / "factor1_monthly_top3" / "paths"
METRICS = Path(POOL_DEFAULTS["metrics_path"])
OUT = _MYQUAN / "backtest" / "strategy4_out"

INITIAL_CASH = 1_000_000.0
MAX_POS = 10
LOT = 100
TARGET_PCT = 0.95
ORIGIN = pd.Timestamp("2020-02-01")


def _thr_key(thr: float) -> str:
    return str(thr).replace(".", "_")


def build_monthly_ranks(score_mode: str = "cum2020") -> dict[str, pd.DataFrame]:
    """score_month -> ranked DataFrame(symbol, thr, score, ...). 交易用 score_month+1。"""
    m = pd.read_parquet(METRICS)
    ok = f"{score_mode}_ok"
    ex = f"{score_mode}_excess_return_pct"
    sh = f"{score_mode}_sharpe_ratio"
    ret = f"{score_mode}_total_return_pct"
    dd = f"{score_mode}_dd_improve_pct"
    sub = m[m[ok] == 1].copy()
    w_ex = float(POOL_DEFAULTS["w_excess"])
    w_sh = float(POOL_DEFAULTS["w_sharpe"])
    w_ret = float(POOL_DEFAULTS["w_return"])
    w_dd = float(POOL_DEFAULTS["w_dd"])

    out: dict[str, pd.DataFrame] = {}
    for month, g0 in sub.groupby("score_month"):
        best_rows = []
        for _, g in g0.groupby("symbol"):
            g = g.copy()
            for col in (ex, sh, dd, ret):
                v = g[col].astype(float)
                if v.nunique() <= 1 or float(v.std(ddof=0) or 0) == 0:
                    g[f"r_{col}"] = 0.5
                else:
                    g[f"r_{col}"] = (v - v.min()) / (v.max() - v.min())
            g["thr_score"] = (
                5.0 * g[f"r_{ex}"]
                + 3.0 * g[f"r_{sh}"]
                + 2.0 * g[f"r_{dd}"]
                + 1.0 * g[f"r_{ret}"]
            )
            best_rows.append(g.loc[g["thr_score"].idxmax()])
        best = pd.DataFrame(best_rows)
        best["excess"] = best[ex].astype(float)
        best["sharpe"] = best[sh].astype(float)
        best["total_return"] = best[ret].astype(float)
        best["dd_improve"] = best[dd].astype(float)
        scored = score_universe(best, w_excess=w_ex, w_sharpe=w_sh, w_return=w_ret, w_dd=w_dd)
        scored["thr"] = scored["threshold_pct"].astype(float)
        # 只要有 path 的票
        scored = scored[scored["symbol"].map(lambda s: (PATHS / f"{s}.npz").exists())].copy()
        scored["raw_rank"] = np.arange(1, len(scored) + 1)
        out[str(month)] = scored.reset_index(drop=True)
    return out


@dataclass
class Pos:
    symbol: str
    thr: float
    shares: float
    buy_i: int
    entry_px: float


class PathBook:
    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def get(self, symbol: str) -> dict | None:
        if symbol in self._cache:
            return self._cache[symbol]
        p = PATHS / f"{symbol}.npz"
        if not p.exists():
            self._cache[symbol] = None  # type: ignore
            return None
        z = np.load(p, allow_pickle=True)
        dates = pd.to_datetime(z["dates"])
        date_to_i = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}
        pack = {"dates": dates, "date_to_i": date_to_i, "z": z}
        self._cache[symbol] = pack
        return pack

    def bar(self, symbol: str, thr: float, dt: pd.Timestamp):
        pack = self.get(symbol)
        if pack is None:
            return None
        j = pack["date_to_i"].get(pd.Timestamp(dt).normalize())
        if j is None:
            return None
        k = _thr_key(float(thr))
        z = pack["z"]
        try:
            return (
                j,
                float(z[f"open_{k}"][j]),
                float(z[f"high_{k}"][j]),
                float(z[f"low_{k}"][j]),
                float(z[f"close_{k}"][j]),
            )
        except KeyError:
            return None


def entry_ok_at(book: PathBook, symbol: str, thr: float, dt: pd.Timestamp) -> bool:
    pack = book.get(symbol)
    if pack is None:
        return False
    j = pack["date_to_i"].get(pd.Timestamp(dt).normalize())
    if j is None or j < 2:
        return False
    k = _thr_key(float(thr))
    z = pack["z"]
    try:
        o = z[f"open_{k}"]
        c = z[f"close_{k}"]
    except KeyError:
        return False
    po, pc = float(o[j - 1]), float(c[j - 1])
    allows = prev_day_allows_entry(
        po, pc, prev_small_yang_pct=float(thr), prev_entry_mode="yin_or_small_yang"
    )
    if not allows:
        return False
    blocked = should_block_entry_by_yang(
        float(o[j - 2]),
        float(c[j - 2]),
        po,
        pc,
        tick=TICK_SIZE,
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    )
    return not blocked


def day_pool(
    ranked: pd.DataFrame,
    book: PathBook,
    held: set[str],
    dt: pd.Timestamp,
    top_n: int,
) -> list[dict]:
    """当日可买 TopN：非持仓 + 买入前置通过，按评分序。"""
    picks: list[dict] = []
    for _, r in ranked.iterrows():
        if len(picks) >= top_n:
            break
        sym = str(r["symbol"])
        if sym in held:
            continue
        thr = float(r["thr"])
        if not entry_ok_at(book, sym, thr, dt):
            continue
        picks.append({"symbol": sym, "thr": thr, "score": float(r["score"]), "raw_rank": int(r["raw_rank"])})
    return picks


def run_backtest(
    *,
    score_mode: str = "cum2020",
    top_n: int = 20,
    max_pos: int = MAX_POS,
    initial_cash: float = INITIAL_CASH,
    slip: float = SLIP,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    t0 = time.time()
    print("构建月度评分排名…")
    by_score = build_monthly_ranks(score_mode)
    trade_ranked: dict[str, pd.DataFrame] = {}
    for sm, df in by_score.items():
        trade_m = str(pd.Period(sm, freq="M") + 1)
        trade_ranked[trade_m] = df
    print(f"  评分月 {len(by_score)} → 交易月 {len(trade_ranked)} ({time.time()-t0:.1f}s)")

    sample = next(PATHS.glob("*.npz"))
    cal = pd.to_datetime(np.load(sample)["dates"])
    cal = [pd.Timestamp(d).normalize() for d in cal if pd.Timestamp(d).normalize() >= ORIGIN]

    book = PathBook()
    cash = float(initial_cash)
    positions: list[Pos] = []
    equity_rows: list[dict] = []
    trades: list[dict] = []

    for di, dt in enumerate(cal):
        trade_m = str(dt.to_period("M"))
        ranked = trade_ranked.get(trade_m)
        held = {p.symbol for p in positions}

        # 1) 止损
        still: list[Pos] = []
        for pos in positions:
            b = book.bar(pos.symbol, pos.thr, dt)
            if b is None:
                still.append(pos)
                continue
            j, oi, hi, li, ci = b
            stop_px = stop_trigger_price(oi, stop_pct=pos.thr)
            if j > pos.buy_i and li <= stop_px + 1e-12:
                pack = book.get(pos.symbol)
                prev_c = ci
                assert pack is not None
                prev_keys = [d for d in pack["date_to_i"] if d < dt]
                if prev_keys:
                    pj = pack["date_to_i"][max(prev_keys)]
                    k = _thr_key(pos.thr)
                    prev_c = float(pack["z"][f"close_{k}"][pj])
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=TICK_SIZE,
                )
                if bool(lim["locked"]):
                    still.append(pos)
                    continue
                sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                sell_px *= 1.0 - slip
                proceeds = pos.shares * sell_px
                fee = proceeds * (COMMISSION + STAMP)
                cash += proceeds - fee
                trades.append(
                    {
                        "date": dt.date().isoformat(),
                        "symbol": pos.symbol,
                        "side": "sell",
                        "px": sell_px,
                        "shares": pos.shares,
                        "thr": pos.thr,
                    }
                )
            else:
                still.append(pos)
        positions = still
        held = {p.symbol for p in positions}

        # 2) 可买池 + 开仓
        if ranked is not None and len(positions) < max_pos:
            pool = day_pool(ranked, book, held, dt, top_n)
            free = max_pos - len(positions)
            # 按池顺序尝试买入
            for item in pool:
                if free <= 0:
                    break
                if item["symbol"] in held:
                    continue
                b = book.bar(item["symbol"], item["thr"], dt)
                if b is None:
                    continue
                j, oi, hi, li, ci = b
                if oi <= 0:
                    continue
                buy_px = entry_trigger_price(oi, entry_pct=item["thr"])
                if hi + 1e-12 < buy_px:
                    continue
                px = buy_px * (1.0 + slip)
                # 剩余现金 / 剩余槽位
                slot_budget = cash / free * TARGET_PCT
                raw = math.floor(slot_budget / (px * LOT)) * LOT
                if raw < LOT:
                    continue
                cost = raw * px
                fee = cost * COMMISSION
                if cost + fee > cash:
                    continue
                cash -= cost + fee
                positions.append(
                    Pos(
                        symbol=item["symbol"],
                        thr=item["thr"],
                        shares=float(raw),
                        buy_i=j,
                        entry_px=px,
                    )
                )
                held.add(item["symbol"])
                free -= 1
                trades.append(
                    {
                        "date": dt.date().isoformat(),
                        "symbol": item["symbol"],
                        "side": "buy",
                        "px": px,
                        "shares": float(raw),
                        "thr": item["thr"],
                        "pool_score": item["score"],
                        "raw_rank": item["raw_rank"],
                    }
                )

        # 3) 盯市
        equity = cash
        for pos in positions:
            b = book.bar(pos.symbol, pos.thr, dt)
            if b is None:
                equity += pos.shares * pos.entry_px
            else:
                equity += pos.shares * b[4]
        equity_rows.append(
            {
                "date": dt,
                "equity": equity,
                "cash": cash,
                "n_pos": len(positions),
            }
        )
        if (di + 1) % 250 == 0:
            print(f"  {dt.date()} equity={equity:,.0f} pos={len(positions)} ({time.time()-t0:.0f}s)")

    eq = pd.DataFrame(equity_rows)
    tr = pd.DataFrame(trades)
    e = eq.set_index("date")["equity"].astype(float)
    rets = e.pct_change().dropna()
    dd = (e / e.cummax() - 1.0).min()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(242)) if len(rets) > 2 and rets.std() > 0 else 0.0
    summary = {
        "start": str(e.index.min().date()),
        "end": str(e.index.max().date()),
        "n_days": int(len(e)),
        "initial_cash": initial_cash,
        "total_return_pct": float(e.iloc[-1] / initial_cash - 1) * 100,
        "max_drawdown_pct": float(-dd) * 100,
        "sharpe": sharpe,
        "end_equity": float(e.iloc[-1]),
        "n_buys": int((tr["side"] == "buy").sum()) if not tr.empty else 0,
        "n_sells": int((tr["side"] == "sell").sum()) if not tr.empty else 0,
        "top_n": top_n,
        "max_pos": max_pos,
        "score_mode": score_mode,
        "slip": slip,
    }

    # 分年链式
    yearly_rows = []
    years = e.index.year if e.index.tz is None else e.index.tz_convert(None).year
    for y, g in e.groupby(years):
        prev = e[e.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else initial_cash
        yearly_rows.append(
            {
                "year": int(y),
                "return_pct": float(g.iloc[-1] / base - 1) * 100,
                "max_dd_pct": float(-(g / g.cummax() - 1).min()) * 100,
            }
        )
    yearly = pd.DataFrame(yearly_rows)

    # 独立年重置
    reset_rows = []
    for y in sorted(set(int(x) for x in years)):
        mask = eq["date"].dt.year == y
        if y == 2020:
            mask &= eq["date"] >= ORIGIN
        sub_cal = [pd.Timestamp(d).normalize() for d in eq.loc[mask, "date"]]
        if len(sub_cal) < 20:
            continue
        # 简化：用链式分年近似独立年成本太高；从连续权益切段不重置仓位
        # 真正重置：单独再跑会很慢。这里用「该年首末权益相对」之外，
        # 另给「假设每年初现金=initial、仅统计该年买卖」— 用链式即可先交，再补重置。
        pass

    summary["yearly"] = yearly
    return eq, tr, summary


def _yearly_reset(
    *,
    score_mode: str,
    top_n: int,
    max_pos: int,
    capital: float,
    slip: float,
) -> pd.DataFrame:
    """每年本金重置独立回测（较慢但口径清晰）。"""
    rows = []
    for y in range(2020, 2027):
        start = ORIGIN if y == 2020 else pd.Timestamp(f"{y}-01-01")
        end = pd.Timestamp(f"{y}-12-31")
        # 临时改 ORIGIN 窗口：直接调用内部循环太重，复制精简版
        eq, tr, sm = _run_window(
            start=start,
            end=end,
            score_mode=score_mode,
            top_n=top_n,
            max_pos=max_pos,
            initial_cash=capital,
            slip=slip,
        )
        if eq.empty:
            continue
        rows.append(
            {
                "year": y,
                "ret_pct_reset": sm["total_return_pct"],
                "dd_pct": sm["max_drawdown_pct"],
                "n_buys": sm["n_buys"],
                "end_equity": sm["end_equity"],
            }
        )
        print(f"  reset {y}: {sm['total_return_pct']:+.1f}% dd={sm['max_drawdown_pct']:.1f}%")
    return pd.DataFrame(rows)


def _run_window(
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    score_mode: str,
    top_n: int,
    max_pos: int,
    initial_cash: float,
    slip: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    by_score = getattr(_run_window, "_ranks", None)
    if by_score is None:
        by_score = build_monthly_ranks(score_mode)
        _run_window._ranks = by_score  # type: ignore[attr-defined]
    trade_ranked = {str(pd.Period(sm, freq="M") + 1): df for sm, df in by_score.items()}

    sample = next(PATHS.glob("*.npz"))
    cal = pd.to_datetime(np.load(sample)["dates"])
    cal = [
        pd.Timestamp(d).normalize()
        for d in cal
        if start <= pd.Timestamp(d).normalize() <= end
    ]
    book = PathBook()
    cash = float(initial_cash)
    positions: list[Pos] = []
    equity_rows: list[dict] = []
    trades: list[dict] = []

    for dt in cal:
        trade_m = str(dt.to_period("M"))
        ranked = trade_ranked.get(trade_m)
        still = []
        for pos in positions:
            b = book.bar(pos.symbol, pos.thr, dt)
            if b is None:
                still.append(pos)
                continue
            j, oi, hi, li, ci = b
            stop_px = stop_trigger_price(oi, stop_pct=pos.thr)
            if j > pos.buy_i and li <= stop_px + 1e-12:
                pack = book.get(pos.symbol)
                prev_c = ci
                if pack is not None:
                    prev_keys = [d for d in pack["date_to_i"] if d < dt]
                    if prev_keys:
                        pj = pack["date_to_i"][max(prev_keys)]
                        k = _thr_key(pos.thr)
                        prev_c = float(pack["z"][f"close_{k}"][pj])
                lim = limit_down_state(
                    prev_close=prev_c, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                    limit_down_pct=0.10, tick=TICK_SIZE,
                )
                if bool(lim["locked"]):
                    still.append(pos)
                    continue
                sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px) * (1.0 - slip)
                cash += pos.shares * sell_px - pos.shares * sell_px * (COMMISSION + STAMP)
                trades.append({"date": dt, "side": "sell", "symbol": pos.symbol})
            else:
                still.append(pos)
        positions = still
        held = {p.symbol for p in positions}
        if ranked is not None and len(positions) < max_pos:
            pool = day_pool(ranked, book, held, dt, top_n)
            free = max_pos - len(positions)
            for item in pool:
                if free <= 0:
                    break
                if item["symbol"] in held:
                    continue
                b = book.bar(item["symbol"], item["thr"], dt)
                if b is None:
                    continue
                j, oi, hi, li, ci = b
                if oi <= 0:
                    continue
                buy_px = entry_trigger_price(oi, entry_pct=item["thr"])
                if hi + 1e-12 < buy_px:
                    continue
                px = buy_px * (1.0 + slip)
                slot_budget = cash / free * TARGET_PCT
                raw = math.floor(slot_budget / (px * LOT)) * LOT
                if raw < LOT:
                    continue
                cost = raw * px
                fee = cost * COMMISSION
                if cost + fee > cash:
                    continue
                cash -= cost + fee
                positions.append(Pos(item["symbol"], item["thr"], float(raw), j, px))
                held.add(item["symbol"])
                free -= 1
                trades.append({"date": dt, "side": "buy", "symbol": item["symbol"]})
        equity = cash
        for pos in positions:
            b = book.bar(pos.symbol, pos.thr, dt)
            equity += pos.shares * (b[4] if b else pos.entry_px)
        equity_rows.append({"date": dt, "equity": equity})

    eq = pd.DataFrame(equity_rows)
    if eq.empty:
        return eq, pd.DataFrame(), {"total_return_pct": 0, "max_drawdown_pct": 0, "n_buys": 0, "end_equity": initial_cash}
    e = eq.set_index("date")["equity"].astype(float)
    dd = float(-(e / e.cummax() - 1).min()) * 100
    tr = pd.DataFrame(trades)
    return eq, tr, {
        "total_return_pct": float(e.iloc[-1] / initial_cash - 1) * 100,
        "max_drawdown_pct": dd,
        "n_buys": int((tr["side"] == "buy").sum()) if not tr.empty else 0,
        "end_equity": float(e.iloc[-1]),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== 策略四回测（含滑点 0.1%）===")
    eq, tr, sm = run_backtest(slip=0.001)
    yearly = sm.pop("yearly")
    print("\n摘要:")
    for k, v in sm.items():
        print(f"  {k}: {v}")
    print("\n分年(链式):")
    print(yearly.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    eq.to_csv(OUT / "backtest_equity.csv", index=False, encoding="utf-8-sig")
    tr.to_csv(OUT / "backtest_trades.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT / "backtest_yearly.csv", index=False, encoding="utf-8-sig")

    print("\n=== 每年本金重置（仍 100 万/年）===")
    reset = _yearly_reset(
        score_mode="cum2020", top_n=20, max_pos=MAX_POS, capital=INITIAL_CASH, slip=0.001
    )
    reset.to_csv(OUT / "backtest_yearly_reset.csv", index=False, encoding="utf-8-sig")
    if not reset.empty:
        print(reset.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        print(
            f"算术年均 {reset['ret_pct_reset'].mean():.1f}% | "
            f"累计盈亏(不复利) {(reset['ret_pct_reset']/100*INITIAL_CASH).sum():,.0f}"
        )

    (OUT / "backtest_summary.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in sm.items())
        + "\n\n"
        + yearly.to_string(index=False)
        + "\n\nreset:\n"
        + reset.to_string(index=False),
        encoding="utf-8",
    )
    print(f"\n产物: {OUT}")


if __name__ == "__main__":
    main()
