"""凯盛科技：现行仅止损 vs 连止损2次后跳过第3次买入、第4次才买（循环）。"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402


def _stats(result, label: str) -> dict:
    m = result.metrics_df
    td = result.trades_df
    out = {
        "方案": label,
        "累计收益%": metric(m, "total_return_pct"),
        "总盈亏": metric(m, "total_pnl"),
        "最大回撤%": metric(m, "max_drawdown_pct"),
        "夏普": metric(m, "sharpe_ratio"),
        "闭环笔数": metric(m, "closed_trade_count"),
        "胜率%": metric(m, "win_rate"),
        "单笔最大收益%": float("nan"),
        "单笔最大净盈亏": float("nan"),
    }
    for key in ("final_equity", "ending_value", "end_equity", "equity"):
        if key in m.index:
            out["期末权益"] = metric(m, key)
            break
    else:
        out["期末权益"] = 100_000.0 + out["总盈亏"]
    if td is not None and not td.empty and "return_pct" in td.columns:
        out["单笔最大收益%"] = float(td["return_pct"].max())
        if "net_pnl" in td.columns:
            out["单笔最大净盈亏"] = float(td["net_pnl"].max())
    return out


def _fmt(v: float, nd: int = 2) -> str:
    if v != v:  # NaN
        return "-"
    return f"{v:,.{nd}f}"


def main() -> None:
    base = replace(KAICHENG, start_date="20200101")
    skip = replace(base, skip_buy_after_consec_stops=2)

    print("===== A 现行策略（仅止损，每次买点都买）=====")
    r0, d0 = run_open_break(base, show_report=False, verbose=False)
    print("===== B 连止损2次 → 跳过第3次买入 → 第4次才买（循环）=====")
    r1, d1 = run_open_break(skip, show_report=False, verbose=False)

    s0 = _stats(r0, "现行")
    s1 = _stats(r1, "跳买")
    print("\n========== 凯盛科技对比（2020-01-01 → 今）==========")
    print(f"日线: {d0['date'].iloc[0]} → {d0['date'].iloc[-1]}  n={len(d0)}")
    print(
        "B规则: 价格条件同现行(开盘±2.5%、前日阴/小阳、禁双阳跨日≥5%、仅止损)；"
        "连续2次止损后，下一次策略买点跳过，再下一次买点才买入；循环。"
    )
    keys = [
        "累计收益%",
        "总盈亏",
        "最大回撤%",
        "夏普",
        "闭环笔数",
        "胜率%",
        "单笔最大收益%",
        "单笔最大净盈亏",
        "期末权益",
    ]
    print(f"{'指标':<14} {'现行策略':>16} {'连止损跳买':>16} {'差值(B-A)':>18}")
    for k in keys:
        a, b = s0[k], s1[k]
        diff = b - a if (a == a and b == b) else float("nan")
        nd = 4 if "夏普" in k else 2
        print(f"{k:<14} {_fmt(a, nd):>16} {_fmt(b, nd):>16} {_fmt(diff, nd):>18}")

    better = "连止损跳买" if s1["累计收益%"] > s0["累计收益%"] else "现行策略"
    if abs(s1["累计收益%"] - s0["累计收益%"]) < 1e-9:
        better = "持平"
    print(
        f"\n结论: 连止损跳买累计收益 {_fmt(s1['累计收益%'] - s0['累计收益%'])} 个百分点"
        f"（相对现行）；胜率 {_fmt(s1['胜率%'] - s0['胜率%'])} pct；"
        f"闭环少 {_fmt(s0['闭环笔数'] - s1['闭环笔数'], 0)} 笔。"
        f"累计收益更优: {better}。"
    )


if __name__ == "__main__":
    main()
