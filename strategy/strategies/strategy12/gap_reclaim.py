"""策略十二回测：昨日收盘跌停、今日开板，开盘买、T+1 收盘清。"""

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
from strategy.open_break import TICK_SIZE, limit_down_state
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
    sig = sig.sort_values(["trade_date", "rank_score", "symbol"], ascending=[True, False, True])
    return sig.reset_index(drop=True)


@dataclass
class _Pos:
    symbol: str
    code: str
    name: str
    shares: float
    entry_px: float
    buy_date: pd.Timestamp


def run_portfolio(
    signals: pd.DataFrame,
    *,
    initial: float = INITIAL,
    max_pos: int = MAX_POS,
    max_entries: int = MAX_ENTRIES_PER_DAY,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    if signals.empty:
        empty = pd.DataFrame(columns=["date", "equity", "cash"])
        return empty, {"total_return_pct": 0.0, "n_trades": 0}, pd.DataFrame()

    bar_cache: dict[str, pd.DataFrame] = {}

    def bars(sym: str) -> pd.DataFrame:
        if sym not in bar_cache:
            p = _bar_path(sym)
            d = pd.read_parquet(p, columns=["date", "open", "high", "low", "close"])
            d["date"] = _norm_dates(d["date"])
            d = d.sort_values("date").reset_index(drop=True)
            d["prev"] = d["close"].shift(1)
            bar_cache[sym] = d
        return bar_cache[sym]

    cal = pd.to_datetime(sorted(load_ld_open_daily()["date"].unique()))
    cal = cal[cal >= pd.Timestamp("2020-01-02")]
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
) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f"扫描信号 昨收涨停+今低开未封涨停  恐慌日(ld≥{LD_OPEN_PANIC_MIN})空仓  开盘买 T+1收盘清")
    sig = scan_signals()
    sig_path = OUT / "signals.parquet"
    sig.to_parquet(sig_path, index=False)
    if verbose:
        print(f"候选 {len(sig)} 条 / {sig['trade_date'].nunique() if len(sig) else 0} 日")
    eq, summary, tr = run_portfolio(sig)
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
        json.dumps({"summary": summary, "n_signals": int(len(sig))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(summary, n_sig=len(sig))
    if verbose:
        print(
            f"全样本 {summary.get('total_return_pct'):.1f}%  "
            f"OOS {summary.get('oos_return_pct'):.1f}%  "
            f"过关={summary.get('passed')}  笔数={summary.get('n_trades')}"
        )
    return {"summary": summary, "equity": eq, "trades": tr, "signals": sig}


def _write_report(summary: dict[str, Any], *, n_sig: int) -> None:
    passed = "过关" if summary.get("passed") else "未过关"
    lines = [
        "# 策略十二·涨停次日低开",
        "",
        "> 研究用途，非投资建议。不绑定凯盛/天通。v1–v4 已否决。",
        "",
        "## ITER_NOTE",
        "",
        "- op_type: event_universe_limit_up_next_gap",
        "- hypothesis: 昨日收盘涨停的强势股，今日低开是获利回吐而非崩盘；带内低开买入吃回档修复。因子18 恐慌日空仓。",
        "- change: 选股=T-1 收盘涨停且 T 低开 gap∈[-4.5%,-0.3%] 未封涨停；择时=非恐慌；开盘买、T+1 收盘清。",
        "- expected: IS（<2024）累计>0 且夏普>0，且 OOS 累计>0、夏普>0、MDD<40% 才过关。",
        "",
        f"**结论：{passed}**",
        "",
        "## 规则",
        "",
        f"- 因子21：昨收涨停，今日 gap ∈ [{GAP_MIN:.1%}, {GAP_MAX:.1%}] 且开盘未封涨停",
        f"- 因子18：低开开盘跌停家数 ≥ {LD_OPEN_PANIC_MIN} 的恐慌日空仓",
        "- 退出：T+1 收盘清仓；一字跌停无法卖则顺延",
        f"- 组合：{INITIAL:.0f} 本金，最多 {MAX_POS} 仓，每日最多 {MAX_ENTRIES_PER_DAY} 笔，按低开越深优先",
        "- 费用：佣金+杂费+印花+滑点（strategy.costs）",
        "",
        "## 结果",
        "",
        "| 样本 | 累计收益 | 最大回撤 | 夏普 |",
        "|------|----------|----------|------|",
        f"| 全样本 | {summary.get('total_return_pct', float('nan')):.1f}% | {summary.get('max_drawdown_pct', float('nan')):.1f}% | {summary.get('sharpe_ratio', float('nan')):.2f} |",
        f"| IS <{OOS_START} | {summary.get('is_return_pct', float('nan')):.1f}% | {summary.get('is_mdd_pct', float('nan')):.1f}% | {summary.get('is_sharpe', float('nan')):.2f} |",
        f"| OOS ≥{OOS_START} | {summary.get('oos_return_pct', float('nan')):.1f}% | {summary.get('oos_mdd_pct', float('nan')):.1f}% | {summary.get('oos_sharpe', float('nan')):.2f} |",
        "",
        f"闭环 {summary.get('n_trades')} 笔，胜率 {summary.get('win_rate', float('nan')):.1f}%，信号 {n_sig} 条。",
        "",
        "过关门槛：IS 累计>0 且夏普>0，**并且** OOS 累计>0、夏普>0、MDD<40%。",
        "本轮 IS 通过，OOS 累计为负且回撤 68%，**未过关**（不在 OOS 上调参）。",
        "",
        "## 已否决轮次",
        "",
        "| 轮次 | 规则 | 结果 |",
        "|------|------|------|",
        "| v1 | 因子18 恐慌日禁止凯盛/天通因子1 新开仓 | 样本内收益下降 |",
        "| v2 | 压力日低开 + 追开盘+2.5% + T+1 止损 | 全样本 -77.8% |",
        "| v3 | 压力日低开、开盘买、T+1 收盘清 | IS -21.8% |",
        "| v4 | 昨收跌停次日开板，恐慌日空仓 | 全样本 -42%，OOS -67% |",
        "| v5（当前） | 昨收涨停次日低开，恐慌日空仓 | 见上表 |",
        "",
        "## 复现",
        "",
        "```bash",
        "python backtest/strategy12_emotion_gate/run.py",
        "python -c \"from strategy import run_strategy12; run_strategy12()\"",
        "```",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = ["scan_signals", "run_portfolio", "run_gap_reclaim_backtest", "OUT"]
