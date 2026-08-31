"""天通股份：现行过门 vs 现行 + 前两日累计涨幅>5% 禁买。

研究对照，不改生产默认。区间 2025-01-01 → 今日。

A 现行：前日阴或小阳；禁前面双阳且跨日≥5%。
B 对照：A 全部保留，再加一条：前两日累计 close[T-1]/close[T-3]-1 > 5% 也禁买
      （与因子13 prior_2d_ret 同一口径；不要求两根都是阳）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.backtest import metric, monthly_returns_df  # noqa: E402
from strategy.config import TIANTONG  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    bar_shape,
    entry_filters_ok,
    entry_trigger_price,
)
from strategy.runner import run_open_break_backtest  # noqa: E402

START = "20250101"
WARMUP = "20241201"
PRIOR_2D = 0.05
OUT_DIR = Path(__file__).resolve().parent / "tiantong_gate_yin_2d"


def _ymd(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Shanghai")
    return t.strftime("%Y-%m-%d")


def _prior_2d_map(daily: pd.DataFrame) -> tuple[dict[str, bool], dict[str, float]]:
    """今日是否通过「前两日累计 ≤ 5%」。缺三根收盘时不额外禁买。"""
    closes = daily["close"].to_numpy(dtype=float)
    dates = [_ymd(d) for d in daily["date"]]
    allowed: dict[str, bool] = {}
    rets: dict[str, float] = {}
    for i, day in enumerate(dates):
        if i < 3:
            allowed[day] = True
            rets[day] = float("nan")
            continue
        c1 = float(closes[i - 1])
        c3 = float(closes[i - 3])
        if c3 <= 0:
            allowed[day] = True
            rets[day] = float("nan")
            continue
        ret = c1 / c3 - 1.0
        rets[day] = ret
        allowed[day] = ret <= PRIOR_2D + 1e-12
    return allowed, rets


def _stats(result, label: str) -> dict:
    m = result.metrics_df
    out = {
        "方案": label,
        "累计收益%": metric(m, "total_return_pct"),
        "总盈亏": metric(m, "total_pnl"),
        "最大回撤%": metric(m, "max_drawdown_pct"),
        "夏普": metric(m, "sharpe_ratio"),
        "闭环笔数": metric(m, "closed_trade_count"),
        "胜率%": metric(m, "win_rate"),
        "期末市值": metric(m, "end_market_value"),
    }
    if out["期末市值"] != out["期末市值"]:
        out["期末市值"] = 100_000.0 + out["总盈亏"]
    return out


def _buy_dates(result) -> list[str]:
    ed = result.executions_df
    if ed is None or ed.empty or "timestamp" not in ed.columns:
        return []
    side = ed["side"].astype(str).str.lower()
    buys = ed.loc[side.eq("buy")].copy()
    if buys.empty:
        return []
    ts = pd.to_datetime(buys["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai")
    return sorted(ts.dt.strftime("%Y-%m-%d").unique().tolist())


def _fmt(v: float, nd: int = 2) -> str:
    if v != v:
        return "-"
    return f"{v:,.{nd}f}"


def _gate_rows(
    daily: pd.DataFrame,
    *,
    entry_pct: float,
    prior_ok: dict[str, bool],
    prior_ret: dict[str, float],
) -> pd.DataFrame:
    opens = daily["open"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    highs = daily["high"].to_numpy(dtype=float)
    dates = [_ymd(d) for d in daily["date"]]
    rows: list[dict] = []
    for i, day in enumerate(dates):
        if i < 1:
            continue
        po, pc = float(opens[i - 1]), float(closes[i - 1])
        p2o = float(opens[i - 2]) if i >= 2 else None
        p2c = float(closes[i - 2]) if i >= 2 else None
        p2_shape = bar_shape(p2o, p2c) if p2o is not None and p2c is not None else ""
        cur = entry_filters_ok(
            po,
            pc,
            p2o,
            p2c,
            entry_pct=entry_pct,
            prev_entry_mode="yin_or_small_yang",
            ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
            double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        )
        two_ok = bool(prior_ok.get(day, True))
        var = bool(cur and two_ok)
        trig = float(highs[i]) + 1e-12 >= entry_trigger_price(
            float(opens[i]), entry_pct=entry_pct
        )
        ret2 = prior_ret.get(day, float("nan"))
        rows.append(
            {
                "date": day,
                "prev2_shape": p2_shape,
                "prev_shape": bar_shape(po, pc),
                "prior_2d_pct": None if ret2 != ret2 else round(ret2 * 100.0, 3),
                "current_ok": cur,
                "variant_ok": var,
                "prior_2d_ok": two_ok,
                "price_trigger": trig,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = TIANTONG.end_date
    entry_pct = float(TIANTONG.resolved_entry_pct())

    print(
        f"拉取 {TIANTONG.symbol_name}({TIANTONG.symbol}) "
        f"日线 {WARMUP} → {end}（回测从 {START}）..."
    )
    daily_full = fetch_daily(
        TIANTONG.symbol,
        WARMUP,
        end,
        cache_path=TIANTONG.daily_cache,
    )
    prior_ok, prior_ret = _prior_2d_map(daily_full)
    cut = pd.Timestamp("2025-01-01", tz="Asia/Shanghai")
    daily = daily_full.loc[daily_full["date"] >= cut].reset_index(drop=True)
    if daily.empty:
        raise SystemExit("切片后日线为空")

    print(
        f"回测日线: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}  n={len(daily)}"
    )

    cfg_a = replace(TIANTONG, start_date=START, end_date=end, report_path=None)
    cfg_b = replace(cfg_a, energy_allowed_by_date=dict(prior_ok))

    print("\n===== A 现行过门：阴/小阳 + 禁双阳跨日≥5%，±3% =====")
    r0 = run_open_break_backtest(cfg_a, daily)
    print("===== B 对照：现行 + 前两日累计>5%禁买，±3% =====")
    r1 = run_open_break_backtest(cfg_b, daily)

    s0 = _stats(r0, "现行")
    s1 = _stats(r1, "现行+前两日累计>5%禁")
    buys0 = _buy_dates(r0)
    buys1 = _buy_dates(r1)

    print("\n========== 天通股份 过门对照（2025-01-01 → 今）==========")
    print(
        "A 现行: 前日阴或小阳；禁前面双阳且跨日≥5%。"
        "B 对照: A 全部保留，再禁前两日累计 "
        f"close[T-1]/close[T-3]-1 > {PRIOR_2D*100:.0f}%。"
        "买卖价位同因子1：开盘±3%、仅止损、T+1。研究用途，非投资建议。"
    )
    keys = ["累计收益%", "总盈亏", "最大回撤%", "夏普", "闭环笔数", "胜率%", "期末市值"]
    print(f"{'指标':<12} {'现行 A':>16} {'对照 B':>16} {'差值(B-A)':>16}")
    for k in keys:
        a, b = s0[k], s1[k]
        diff = b - a if (a == a and b == b) else float("nan")
        nd = 4 if k in ("夏普", "累计收益%", "最大回撤%", "胜率%") else 2
        if k == "闭环笔数":
            nd = 0
        print(f"{k:<12} {_fmt(a, nd):>16} {_fmt(b, nd):>16} {_fmt(diff, nd):>16}")

    print(f"\n实际买入日 A={len(buys0)}  B={len(buys1)}")
    only_a = sorted(set(buys0) - set(buys1))
    only_b = sorted(set(buys1) - set(buys0))
    both = sorted(set(buys0) & set(buys1))
    print(f"  两边都买: {len(both)}")
    print(f"  仅现行买: {only_a or '无'}")
    print(f"  仅对照买: {only_b or '无'}")

    gates = _gate_rows(
        daily, entry_pct=entry_pct, prior_ok=prior_ok, prior_ret=prior_ret
    )
    n_cur = int(gates["current_ok"].sum())
    n_var = int(gates["variant_ok"].sum())
    extra = gates[gates["current_ok"] & ~gates["prior_2d_ok"]]
    trig_extra = extra[extra["price_trigger"]]
    print(
        f"\n过门日（不论是否触发买价）: 现行 {n_cur} / {len(gates)}，"
        f"对照 {n_var} / {len(gates)}，"
        f"现行过、前两日累计>5% 额外禁 {len(extra)} 日"
    )
    print(f"  其中当日最高价也过买点: {len(trig_extra)} 日")
    if not trig_extra.empty:
        show = trig_extra[
            [
                "date",
                "prev2_shape",
                "prev_shape",
                "prior_2d_pct",
                "current_ok",
                "variant_ok",
            ]
        ]
        print("\n--- 额外禁买且价格触发（最多 40）---")
        print(show.head(40).to_string(index=False))

    m0 = monthly_returns_df(r0, daily, initial_cash=cfg_a.initial_cash)
    m1 = monthly_returns_df(r1, daily, initial_cash=cfg_b.initial_cash)
    monthly = m0.rename(columns={"策略收益%": "现行收益%"}).merge(
        m1.rename(columns={"策略收益%": "对照收益%"})[["月份", "对照收益%"]],
        on="月份",
        how="outer",
    )
    if not monthly.empty:
        monthly["差值(B-A)"] = monthly["对照收益%"] - monthly["现行收益%"]

    payload = {
        "symbol": TIANTONG.symbol,
        "symbol_name": TIANTONG.symbol_name,
        "start": START,
        "end": end,
        "entry_pct": entry_pct,
        "prior_2d": PRIOR_2D,
        "prior_2d_def": "close[T-1] / close[T-3] - 1",
        "bars": int(len(daily)),
        "first_bar": _ymd(daily["date"].iloc[0]),
        "last_bar": _ymd(daily["date"].iloc[-1]),
        "A": s0,
        "B": s1,
        "buy_dates_A": buys0,
        "buy_dates_B": buys1,
        "only_A": only_a,
        "only_B": only_b,
        "gate_days_A": n_cur,
        "gate_days_B": n_var,
        "extra_ban": int(len(extra)),
        "extra_ban_and_trigger": int(len(trig_extra)),
        "disclaimer": "研究回测，非投资建议。",
    }
    cmp_path = OUT_DIR / "comparison.json"
    cmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    gates.to_csv(OUT_DIR / "gate_days.csv", index=False, encoding="utf-8-sig")
    if not monthly.empty:
        monthly.to_csv(OUT_DIR / "monthly.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"date": sorted(set(buys0) | set(buys1))}).assign(
        in_A=lambda d: d["date"].isin(buys0),
        in_B=lambda d: d["date"].isin(buys1),
    ).to_csv(OUT_DIR / "buy_dates.csv", index=False, encoding="utf-8-sig")

    print(f"\n产物: {cmp_path}")
    print(f"过门日 CSV: {OUT_DIR / 'gate_days.csv'}")
    if not monthly.empty:
        print(f"分月 CSV: {OUT_DIR / 'monthly.csv'}")

    better = "对照 B" if s1["累计收益%"] > s0["累计收益%"] else "现行 A"
    if abs(s1["累计收益%"] - s0["累计收益%"]) < 1e-9:
        better = "持平"
    print(
        f"\n结论: 对照相对现行 累计收益 {_fmt(s1['累计收益%'] - s0['累计收益%'])} 个百分点，"
        f"最大回撤 {_fmt(s1['最大回撤%'] - s0['最大回撤%'])} 个百分点，"
        f"闭环 {_fmt(s1['闭环笔数'] - s0['闭环笔数'], 0)} 笔。"
        f"累计收益更优: {better}。研究用途，非投资建议。"
    )


if __name__ == "__main__":
    main()
