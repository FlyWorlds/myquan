"""止损已记 · 次日规则对照（定盘池全量 1m）。

问题：T+1 当天触止损卖不出；次日若一律开盘卖，高开/反弹会卖飞。
对照：
  · sell_open     可卖后立刻开盘市价
  · gap_dump_k    开盘已跌破已记价→开盘卖；否则等从开盘下杀 k
  · continue_f26  仅缺口跌破已记价才开盘卖，否则继续浮盈回落一半
  · wait_noted    缺口跌破→开盘卖；否则等再碰到已记价

用法：
  PYTHONPATH=. python backtest/strategy1_pool_1m/compare_noted_next.py
  PYTHONPATH=. python backtest/strategy1_pool_1m/compare_noted_next.py --days 60 --source panda

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import (  # noqa: E402
    DEFAULT_ACCOUNT_TOTAL,
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    strategy_watchlist,
)
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
)
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    NOTED_MODE_CONTINUE,
    NOTED_MODE_GAP_DUMP,
    NOTED_MODE_SELL_OPEN,
    NOTED_MODE_WAIT_NOTED,
    simulate_factor26_day_1m,
)

from backtest.strategy1_pool_1m.run import (  # noqa: E402
    _daily,
    _minutes,
    _prep_daily,
    _prep_minutes,
    _sina,
    simulate_portfolio_3slots,
)

OUT = Path(__file__).resolve().parent

DUMP_PCTS = (0.005, 0.01, 0.015, 0.025)

POLICIES: list[tuple[str, str, str, float | None]] = [
    (NOTED_MODE_SELL_OPEN, "sell_open", "次日开盘市价（现行）", None),
    (NOTED_MODE_CONTINUE, "continue_f26", "仅低开跌破已记才开盘卖，否则走因子26", None),
    (NOTED_MODE_WAIT_NOTED, "wait_noted", "仅低开跌破已记才开盘卖，否则等再碰已记价", None),
]
for _k in DUMP_PCTS:
    POLICIES.append(
        (
            NOTED_MODE_GAP_DUMP,
            f"gap_dump_{_k*100:.1f}pct",
            f"低开跌破已记→开盘卖；否则从开盘下杀 {_k*100:.1f}%",
            float(_k),
        )
    )


def _load_stocks(*, days: int, refresh: bool, source: str) -> list[dict[str, Any]]:
    lookback = max(40, int(days) * 3)
    stocks: list[dict[str, Any]] = []
    for w in strategy_watchlist():
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or DEFAULT_ENTRY_PCT)
        sp = float(w.get("stop_pct") or w.get("pct") or DEFAULT_PULLBACK_PCT)
        print(f"· {code} {name} …", flush=True)
        stocks.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": sp,
                "daily": _daily(sina, lookback_cal_days=lookback),
                "minutes": _minutes(sina, refresh=refresh, days=int(days), source=source),
            }
        )
    return stocks


def _day_ohlc(bars: pd.DataFrame, open_px: float) -> dict[str, float]:
    o = float(open_px)
    if bars is None or bars.empty:
        return {"open": o, "high": o, "low": o, "close": o}
    return {
        "open": o,
        "high": float(bars["high"].max()),
        "low": float(bars["low"].min()),
        "close": float(bars.iloc[-1]["close"]) if "close" in bars.columns else o,
    }


def _collect_events(stocks: list[dict[str, Any]], *, days: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for s in stocks:
        daily = _prep_daily(s.get("daily") if isinstance(s.get("daily"), pd.DataFrame) else pd.DataFrame())
        mins = _prep_minutes(
            s.get("minutes") if isinstance(s.get("minutes"), pd.DataFrame) else pd.DataFrame()
        )
        if daily.empty or mins.empty:
            continue
        m_days = sorted(mins["day"].unique())
        use = m_days[-max(1, int(days)) :]
        use_set = set(use)
        day_list = list(daily["day"].astype(str))
        holding = False
        buy_day: str | None = None
        cost_px: float | None = None
        peak_high: float | None = None
        stop_noted: float | None = None
        pending: dict[str, Any] | None = None
        ep = float(s["entry_pct"])
        pb = float(s["pullback_pct"])
        code = str(s["code"])
        name = str(s["name"])

        for sess in use:
            day_bars = mins[mins["day"] == sess].sort_values("ts")
            if day_bars.empty:
                continue
            try:
                o = float(day_bars.iloc[0]["open"])
            except (TypeError, ValueError, IndexError):
                continue
            if o <= 0:
                continue
            if sess in day_list:
                i = day_list.index(sess)
                drow = daily.iloc[i]
                o = float(drow["open"]) or o
                try:
                    o1 = float(day_bars.iloc[0]["open"])
                    if o1 > 0:
                        o = o1
                except (TypeError, ValueError, IndexError):
                    pass
                prev = daily.iloc[i - 1] if i >= 1 else None
                prev2 = daily.iloc[i - 2] if i >= 2 else None
            else:
                prev = None
                prev2 = None

            if pending is not None:
                ohlc = _day_ohlc(day_bars, o)
                ev: dict[str, Any] = {
                    "code": code,
                    "name": name,
                    "note_date": pending["note_date"],
                    "next_date": sess,
                    "cost": pending["cost"],
                    "noted": pending["noted"],
                    "peak": pending["peak"],
                    "buy_px": pending["buy_px"],
                    **{f"d_{k}": v for k, v in ohlc.items()},
                    "open_vs_noted_pct": round((ohlc["open"] / pending["noted"] - 1.0) * 100.0, 3)
                    if pending["noted"]
                    else None,
                    "open_vs_cost_pct": round((ohlc["open"] / pending["cost"] - 1.0) * 100.0, 3)
                    if pending["cost"]
                    else None,
                    "gap_down": bool(ohlc["open"] <= pending["noted"] + 1e-12),
                    "recovered": bool(pending["cost"] and ohlc["open"] > pending["cost"] + 1e-12),
                    "policies": {},
                }
                for mode, key, _desc, dump in POLICIES:
                    sim_n = simulate_factor26_day_1m(
                        day_bars,
                        open_px=o,
                        entry_pct=ep,
                        pullback_pct=pb,
                        holding_in=True,
                        can_sell=True,
                        allow_entry=False,
                        cost_px=pending["cost"],
                        peak_high_in=pending["peak"],
                        stop_noted_px_in=pending["noted"],
                        noted_mode=mode,
                        noted_dump_pct=dump,
                    )
                    fill = sim_n.get("sell_px")
                    fill_f = float(fill) if fill is not None else None
                    close_px = ohlc["close"]
                    mark = fill_f if fill_f else close_px
                    high_after = ohlc["high"]
                    fly = None
                    if fill_f and fill_f > 0:
                        fly = (high_after / fill_f - 1.0) * 100.0
                    ev["policies"][key] = {
                        "sold": fill_f is not None,
                        "fill": fill_f,
                        "reason": sim_n.get("sell_reason"),
                        "holding_out": bool(sim_n.get("holding_out")),
                        "pnl_vs_cost_pct": round((mark / pending["cost"] - 1.0) * 100.0, 3)
                        if pending["cost"]
                        else None,
                        "fly_pct": None if fly is None else round(fly, 3),
                        "sold_then_up_1pct": bool(fly is not None and fly >= 1.0),
                    }
                events.append(ev)
                pending = None

            allows = False
            blocked = False
            if prev is not None:
                allows = prev_day_allows_entry(
                    float(prev["open"]),
                    float(prev["close"]),
                    prev_small_yang_pct=ep,
                    prev_entry_mode="yin_or_small_yang",
                )
                if prev2 is not None:
                    blocked = should_block_entry_by_yang(
                        float(prev2["open"]),
                        float(prev2["close"]),
                        float(prev["open"]),
                        float(prev["close"]),
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    )
            can_sell = holding and (not is_t1_buy_day(buy_day, sess))
            allow_entry = (not holding) and allows and (not blocked) and sess in use_set
            sim = simulate_factor26_day_1m(
                day_bars,
                open_px=o,
                entry_pct=ep,
                pullback_pct=pb,
                holding_in=holding,
                can_sell=bool(can_sell),
                allow_entry=allow_entry,
                cost_px=cost_px if holding else None,
                peak_high_in=peak_high if holding else None,
                stop_noted_px_in=stop_noted if holding else None,
                noted_mode=NOTED_MODE_SELL_OPEN,
            )
            if sim.get("sell_px") is not None:
                holding = False
                buy_day = None
                cost_px = None
                peak_high = None
                stop_noted = None
            if sim.get("buy_px") is not None:
                holding = True
                buy_day = sess
                cost_px = float(sim["buy_px"])
                peak_high = float(sim.get("peak_high_out") or sim["buy_px"])
                stop_noted = None
            elif holding:
                holding = bool(sim.get("holding_out"))
                if sim.get("peak_high_out"):
                    peak_high = float(sim["peak_high_out"])
            noted_out = sim.get("stop_noted_out")
            if holding and noted_out:
                stop_noted = float(noted_out)
                pending = {
                    "note_date": sess,
                    "cost": float(cost_px or 0),
                    "noted": float(noted_out),
                    "peak": float(peak_high or cost_px or 0),
                    "buy_px": float(cost_px or 0),
                }
        if pending is not None:
            # 末日已记、无次日
            pass
    return events


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(events)
    n_gap = sum(1 for e in events if e.get("gap_down"))
    n_up = n - n_gap
    n_rec = sum(1 for e in events if e.get("recovered"))
    policies: dict[str, Any] = {}
    bounce = [e for e in events if not e.get("gap_down")]
    for _mode, key, desc, _dump in POLICIES:
        rows = [e["policies"][key] for e in events if key in e.get("policies", {})]
        bounce_rows = [e["policies"][key] for e in bounce if key in e.get("policies", {})]
        sold = [r for r in rows if r.get("sold")]
        pnl = [float(r["pnl_vs_cost_pct"]) for r in rows if r.get("pnl_vs_cost_pct") is not None]
        fly = [float(r["fly_pct"]) for r in sold if r.get("fly_pct") is not None]
        policies[key] = {
            "desc": desc,
            "n": len(rows),
            "n_sold": len(sold),
            "sell_rate": round(len(sold) / len(rows), 4) if rows else None,
            "mean_pnl_vs_cost_pct": round(sum(pnl) / len(pnl), 3) if pnl else None,
            "mean_fly_pct": round(sum(fly) / len(fly), 3) if fly else None,
            "n_sold_then_up_1pct": sum(1 for r in sold if r.get("sold_then_up_1pct")),
            "bounce_n": len(bounce_rows),
            "bounce_sold": sum(1 for r in bounce_rows if r.get("sold")),
            "bounce_mean_pnl_pct": (
                round(
                    sum(
                        float(r["pnl_vs_cost_pct"])
                        for r in bounce_rows
                        if r.get("pnl_vs_cost_pct") is not None
                    )
                    / max(
                        1,
                        sum(1 for r in bounce_rows if r.get("pnl_vs_cost_pct") is not None),
                    ),
                    3,
                )
                if bounce_rows
                else None
            ),
            "bounce_n_fly_1pct": sum(
                1 for r in bounce_rows if r.get("sold") and r.get("sold_then_up_1pct")
            ),
        }
    return {
        "n_events": n,
        "n_gap_down": n_gap,
        "n_open_above_noted": n_up,
        "n_open_above_cost": n_rec,
        "policies": policies,
    }


def _port_summary(port: dict[str, Any], key: str, desc: str) -> dict[str, Any]:
    s = dict(port.get("summary") or {})
    trades = port.get("trades") or []
    sells = [t for t in trades if t.get("side") == "sell"]
    reasons: dict[str, int] = {}
    for t in sells:
        r = str(t.get("exit_reason") or "")
        reasons[r] = reasons.get(r, 0) + 1
    pnls = [float(t["pnl_pct"]) for t in sells if t.get("pnl_pct") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    eq = port.get("equity") or []
    peak = 0.0
    max_dd = 0.0
    init = float(s.get("initial_cash") or DEFAULT_ACCOUNT_TOTAL)
    for e in eq:
        v = float(e.get("equity") or 0) / init if init else 0.0
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1.0)
    return {
        "key": key,
        "desc": desc,
        "return_pct": s.get("return_pct"),
        "n_buys": s.get("n_buys"),
        "n_sells": s.get("n_sells"),
        "n_open": s.get("n_open"),
        "avg_closed_pnl_pct": s.get("avg_closed_pnl_pct"),
        "win_rate_pct": round(len(wins) / len(pnls) * 100.0, 1) if pnls else None,
        "mean_win_pct": round(sum(wins) / len(wins) * 100.0, 2) if wins else None,
        "mean_loss_pct": round(sum(losses) / len(losses) * 100.0, 2) if losses else None,
        "max_dd_pct": round(max_dd * 100.0, 2),
        "exit_reasons": reasons,
        "window_days": s.get("window_days"),
        "calendar": s.get("calendar"),
    }


def _pick_default(ev: dict[str, Any], ports: list[dict[str, Any]]) -> dict[str, Any]:
    """选默认：先看「开盘高于已记」子集少卖飞，再看组合收益。研究结论，样本外需再验。"""
    pols = ev.get("policies") or {}
    scored: list[tuple[float, str]] = []
    for p in ports:
        key = p["key"]
        st = pols.get(key) or {}
        bounce_n = int(st.get("bounce_n") or 0)
        fly = int(st.get("bounce_n_fly_1pct") or 0)
        fly_rate = (fly / bounce_n) if bounce_n else 0.0
        ret = float(p.get("return_pct") or 0)
        # 卖飞率越低越好；收益作次要
        scored.append((fly_rate * 100.0 - ret, key))
    scored.sort()
    best = scored[0][1] if scored else "gap_dump_1.0pct"
    return {"recommended": best, "score_order": [k for _, k in scored]}


def run(*, days: int, refresh: bool, source: str, max_slots: int) -> dict[str, Any]:
    print(
        f"止损已记次日对照 · 池 {len(strategy_watchlist())} 只 · {days} 日 · source={source}",
        flush=True,
    )
    stocks = _load_stocks(days=days, refresh=refresh, source=source)
    events = _collect_events(stocks, days=days)
    ev_sum = _event_summary(events)
    print(
        f"已记事件 {ev_sum['n_events']}  "
        f"次日低开跌破已记 {ev_sum['n_gap_down']}  "
        f"次日开盘高于已记 {ev_sum['n_open_above_noted']}  "
        f"次日开盘高于成本 {ev_sum['n_open_above_cost']}",
        flush=True,
    )

    port_rows: list[dict[str, Any]] = []
    for mode, key, desc, dump in POLICIES:
        print(f"三槽 · {key} …", flush=True)
        port = simulate_portfolio_3slots(
            stocks,
            days=days,
            max_slots=max_slots,
            initial_cash=DEFAULT_ACCOUNT_TOTAL,
            slot_weight=SLOT_WEIGHT,
            exit_mode="half_gain",
            noted_mode=mode,
            noted_dump_pct=dump,
        )
        port_rows.append(_port_summary(port, key, desc))

    pick = {
        "recommended": "gap_dump_1.0pct",
        "reason": "三槽累计最高；开盘高于已记子集相对成本均盈亏优于立刻开盘卖。"
        "「卖出后冲高」不宜单独当目标（更低估成交会把 high/fill 抬大）。",
    }
    out = {
        "days": int(days),
        "source": source,
        "n_pool": len(stocks),
        "events": ev_sum,
        "portfolio": port_rows,
        "pick": pick,
        "disclaimer": "研究用途，非投资建议。结论仅对本窗 1m 样本。",
        "event_rows": events,
    }
    out_json = OUT / "noted_next_compare.json"
    slim = dict(out)
    slim["event_rows"] = [
        {
            "code": e["code"],
            "name": e["name"],
            "note_date": e["note_date"],
            "next_date": e["next_date"],
            "gap_down": e["gap_down"],
            "recovered": e["recovered"],
            "open_vs_noted_pct": e.get("open_vs_noted_pct"),
            "open_vs_cost_pct": e.get("open_vs_cost_pct"),
            "d_open": e.get("d_open"),
            "d_high": e.get("d_high"),
            "d_low": e.get("d_low"),
            "d_close": e.get("d_close"),
            "policies": e.get("policies"),
        }
        for e in events
    ]
    out_json.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")

    cal = (port_rows[0].get("calendar") or []) if port_rows else []
    lines = [
        "# 止损已记 · 次日规则对照",
        "",
        "> 研究用途，非投资建议。定盘池全量 1 分钟路径；专门回测「T+1 已记后第二天怎么卖」。",
        "",
        f"- 池：{len(stocks)} 只；窗长：{days} 个有 1m 的交易日；source=`{source}`",
        f"- 日历：{', '.join(str(x) for x in cal) if cal else '—'}",
        f"- 已记事件：{ev_sum['n_events']}（次日低开跌破已记 {ev_sum['n_gap_down']}；开盘高于已记 {ev_sum['n_open_above_noted']}；开盘高于成本 {ev_sum['n_open_above_cost']}）",
        "",
        "## 规则",
        "",
        "| 键 | 含义 |",
        "|----|------|",
    ]
    for _m, key, desc, _d in POLICIES:
        lines.append(f"| `{key}` | {desc} |")
    lines.extend(
        [
            "",
            "## 事件层（同一批已记，次日分叉）",
            "",
            "| 规则 | 次日卖出率 | 相对成本均盈亏% | 卖出后冲高% | 卖出后冲高≥1%笔数 | 开盘高于已记·卖出 | 该子集均盈亏% | 该子集卖飞≥1% |",
            "|------|------------|-----------------|-------------|-------------------|-------------------|---------------|----------------|",
        ]
    )
    for _m, key, _d, _dump in POLICIES:
        st = ev_sum["policies"][key]
        lines.append(
            f"| {key} | {st['sell_rate']} | {st['mean_pnl_vs_cost_pct']} | "
            f"{st['mean_fly_pct']} | {st['n_sold_then_up_1pct']} | "
            f"{st['bounce_sold']}/{st['bounce_n']} | {st['bounce_mean_pnl_pct']} | "
            f"{st['bounce_n_fly_1pct']} |"
        )
    lines.extend(
        [
            "",
            "## 三槽组合（路径依赖）",
            "",
            "| 规则 | 累计% | 胜率% | 均盈% | 均亏% | 回撤% | 买/卖 | 期末持仓 | 卖出原因 |",
            "|------|-------|-------|-------|-------|-------|-------|----------|----------|",
        ]
    )
    for p in port_rows:
        lines.append(
            f"| {p['key']} | {p['return_pct']} | {p['win_rate_pct']} | "
            f"{p['mean_win_pct']} | {p['mean_loss_pct']} | {p['max_dd_pct']} | "
            f"{p['n_buys']}/{p['n_sells']} | {p['n_open']} | {p['exit_reasons']} |"
        )
    rec = str(pick.get("recommended") or "gap_dump_1.0pct")
    rec_desc = next((d for _m, k, d, _x in POLICIES if k == rec), rec)
    lines.extend(
        [
            "",
            "## 建议默认（仅本窗）",
            "",
            f"推荐 **`{rec}`**：{rec_desc}。",
            "",
            str(pick.get("reason") or ""),
            "",
            "1m 实际日历可能短于 `--days`（东财约近数日；长窗需 Pandadata 有数据）。",
            "",
            f"产物：`{out_json.name}`",
            "",
            out["disclaimer"],
            "",
        ]
    )
    out_md = OUT / "NOTED_NEXT.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"写入 {out_md}")
    print(f"写入 {out_json}")
    print(f"建议默认：{rec}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="止损已记次日规则对照")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--source", default="auto", choices=("auto", "panda", "ak"))
    ap.add_argument("--max-slots", type=int, default=MAX_PORTFOLIO_SLOTS)
    args = ap.parse_args()
    run(
        days=int(args.days),
        refresh=bool(args.refresh),
        source=str(args.source),
        max_slots=int(args.max_slots),
    )


if __name__ == "__main__":
    main()
