"""对照三槽交割单与 1 分钟 K：核对买卖时刻、价格、半仓/全清/回落。

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_LADDER_FULL_PCT,
    DEFAULT_LADDER_HALF_PCT,
    DEFAULT_PULLBACK_PCT,
    cost_hard_stop_px,
    eval_multi_tp_bar,
    ladder_target_price,
    lot_half_shares,
)

CACHE = _ROOT / "backtest" / "strategy1_pool_1m" / "cache_1m"
HERE = Path(__file__).resolve().parent


def _sina(code: str) -> str:
    c = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    return f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}"


def _code(raw: str) -> str:
    return "".join(ch for ch in str(raw) if ch.isdigit()).zfill(6)[-6:]


def load_trades(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["code"] = _code(r.get("code") or "")
        r["side"] = str(r.get("side") or "").lower()
        r["ts"] = pd.Timestamp(r.get("ts") or r.get("date") or "")
        r["px"] = float(r.get("px") or 0)
        r["shares"] = int(float(r.get("shares") or 0))
        r["exit_reason"] = str(r.get("exit_reason") or "")
    return rows


def load_minutes(code: str) -> pd.DataFrame:
    p = CACHE / f"{_sina(code)}_1m.parquet"
    if not p.is_file():
        return pd.DataFrame()
    m = pd.read_parquet(p)
    m["ts"] = pd.to_datetime(m["ts"])
    if getattr(m["ts"].dt, "tz", None) is not None:
        m["ts"] = m["ts"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    m = m.dropna(subset=["open", "high", "low", "close"])
    m = m[(m["high"] > 0) & (m["low"] > 0)].sort_values("ts")
    m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
    return m


def _day_open(mins: pd.DataFrame, day: str) -> float:
    d = mins[mins["day"] == day]
    if d.empty:
        return 0.0
    return float(d.iloc[0]["open"])


def replay_lot(
    mins: pd.DataFrame,
    *,
    cost: float,
    buy_ts: pd.Timestamp,
    shares0: int,
    last_day: str | None = None,
) -> list[dict[str, Any]]:
    """从买入分钟起用 eval_multi_tp_bar 重放，得到应有卖点。"""
    bars = mins[mins["ts"] >= buy_ts].copy()
    if last_day:
        bars = bars[bars["day"] <= last_day]
    peak = float(cost)
    stage = 0
    shares = int(shares0)
    buy_day = str(buy_ts)[:10]
    buy_day_peak = float(cost)
    hits: list[dict[str, Any]] = []
    for _, row in bars.iterrows():
        ts = pd.Timestamp(row["ts"])
        day = str(ts)[:10]
        can_sell = day != buy_day
        if day == buy_day:
            buy_day_peak = max(buy_day_peak, float(row["high"]))
        # 买入日盘中最高未到 3% → 次日武装 T1 峰值回落
        armed = bool(can_sell and (buy_day_peak / cost - 1.0) < 0.03 - 1e-12)
        ev = eval_multi_tp_bar(
            bar_open=float(row["open"]),
            bar_high=float(row["high"]),
            bar_low=float(row["low"]),
            cost_px=float(cost),
            peak_before=peak,
            shares=shares,
            tp_stage=stage,
            can_sell=can_sell,
            overnight_armed=armed,
            day_open=_day_open(mins, day) or float(row["open"]),
        )
        peak = float(ev.get("peak_after") or peak)
        act = ev.get("action") or {}
        if can_sell and act.get("kind") in {"full", "half"}:
            sell_n = int(act.get("shares") or 0)
            hits.append(
                {
                    "ts": ts,
                    "kind": act.get("kind"),
                    "reason": act.get("reason"),
                    "fill_px": float(act.get("fill_px") or 0),
                    "shares": sell_n,
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "open": float(row["open"]),
                }
            )
            if act.get("kind") == "half":
                shares = max(0, shares - sell_n)
                stage = 1
            else:
                shares = 0
                break
    return hits


def group_lots(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_code[t["code"]].append(t)
    lots: list[dict[str, Any]] = []
    for code, rows in by_code.items():
        rows = sorted(rows, key=lambda x: x["ts"])
        open_lot: dict[str, Any] | None = None
        for t in rows:
            if t["side"] == "buy":
                if open_lot and int(open_lot["remain"]) > 0:
                    lots.append(open_lot)
                open_lot = {
                    "code": code,
                    "name": t.get("name") or code,
                    "buy_ts": t["ts"],
                    "buy_px": t["px"],
                    "shares0": t["shares"],
                    "remain": t["shares"],
                    "sells": [],
                }
            elif t["side"] == "sell" and open_lot:
                open_lot["sells"].append(t)
                open_lot["remain"] = int(open_lot["remain"]) - int(t["shares"])
                if open_lot["remain"] <= 0:
                    lots.append(open_lot)
                    open_lot = None
        if open_lot:
            lots.append(open_lot)
    return lots


def check_lot(lot: dict[str, Any], mins: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    code = lot["code"]
    if mins.empty:
        issues.append(f"{code} 无 1m 缓存")
        return issues
    buy_ts = lot["buy_ts"]
    cost = float(lot["buy_px"])
    shares0 = int(lot["shares0"])
    bar = mins[mins["ts"] == buy_ts]
    if bar.empty:
        # 允许差 1 分钟（排队补买 trigger_ts）
        near = mins[(mins["ts"] >= buy_ts - pd.Timedelta(minutes=2)) & (mins["ts"] <= buy_ts + pd.Timedelta(minutes=2))]
        if near.empty:
            issues.append(f"{code} 买时 {buy_ts} 附近无 1m")
    else:
        h = float(bar.iloc[0]["high"])
        o = float(bar.iloc[0]["open"])
        day = str(buy_ts)[:10]
        day_o = _day_open(mins, day) or o
        # 开盘突破：当日高应已过阈值；买价应接近阈值或当根高/开
        if h + 1e-9 < cost * 0.99:
            issues.append(f"{code} 买价 {cost} 高于当根高 {h}")
        if day_o > 0 and cost < day_o - 1e-9:
            issues.append(f"{code} 买价 {cost} 低于今开 {day_o}")

    expected = replay_lot(mins, cost=cost, buy_ts=buy_ts, shares0=shares0)
    actual = [
        {
            "ts": s["ts"],
            "reason": s["exit_reason"],
            "px": s["px"],
            "shares": s["shares"],
        }
        for s in lot["sells"]
    ]
    if len(actual) != len(expected) and lot["remain"] <= 0:
        issues.append(
            f"{code} {buy_ts} 卖笔数 交割{len(actual)} vs 1m重放{len(expected)} "
            f"实={[ (str(a['ts'])[11:16], a['reason']) for a in actual ]} "
            f"应={[ (str(e['ts'])[11:16], e['reason']) for e in expected ]}"
        )
    n = min(len(actual), len(expected))
    for i in range(n):
        a, e = actual[i], expected[i]
        if abs((a["ts"] - e["ts"]).total_seconds()) > 60:
            issues.append(
                f"{code} 第{i+1}笔时刻 交割{a['ts']} vs 1m {e['ts']} reason={a['reason']}/{e['reason']}"
            )
        if a["reason"] and e["reason"] and a["reason"] != e["reason"]:
            issues.append(
                f"{code} 第{i+1}笔原因 交割{a['reason']} vs 1m {e['reason']}"
            )
        if abs(float(a["px"]) - float(e["fill_px"])) > 0.02 + 1e-9:
            issues.append(
                f"{code} 第{i+1}笔价 交割{a['px']} vs 1m {e['fill_px']}"
            )
        if int(a["shares"]) != int(e["shares"]):
            issues.append(
                f"{code} 第{i+1}笔股数 交割{a['shares']} vs 1m {e['shares']}"
            )
    # 半仓后必须还能再卖或仍持剩余
    for s in lot["sells"]:
        if s["exit_reason"] == "ladder_half_10":
            half = lot_half_shares(shares0)
            if int(s["shares"]) != half and shares0 >= 200:
                issues.append(f"{code} 10% 半仓股数 {s['shares']} 期望 {half}（整仓{shares0}）")
            later = [x for x in lot["sells"] if x["ts"] > s["ts"]]
            if not later and lot["remain"] <= 0:
                issues.append(f"{code} 10% 半仓后交割已无剩余却未记第二笔")
            if later and later[0]["exit_reason"] == "ladder_half_10":
                issues.append(f"{code} 半仓后又打了一次 10%（应走 15% 或峰值回落全平）")
            if later and later[0]["exit_reason"] not in {
                "peak_pullback_clear",
                "ladder_full_15",
                "hard_from_cost",
            }:
                # 允许硬保护；不允许再 half
                if later[0]["exit_reason"] == "ladder_half_10":
                    pass
    # 未平仓：检查是否漏卖
    if lot["remain"] > 0 and expected:
        e = expected[0]
        if str(e["ts"])[:10] <= str(mins["ts"].max())[:10]:
            issues.append(f"{code} 交割仍持仓 {lot['remain']} 但 1m 重放应在 {e['ts']} {e['reason']}")
    return issues


def plot_lot(lot: dict[str, Any], mins: pd.DataFrame, out: Path) -> Path | None:
    if mins.empty:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception:
        return None

    buy_ts = lot["buy_ts"]
    day0 = str(buy_ts)[:10]
    last_sell = lot["sells"][-1]["ts"] if lot["sells"] else mins["ts"].max()
    win = mins[(mins["ts"] >= pd.Timestamp(day0) - pd.Timedelta(hours=1)) & (mins["ts"] <= last_sell + pd.Timedelta(minutes=30))]
    if win.empty:
        win = mins[mins["day"] >= day0].head(400)
    if win.empty:
        return None

    fig, ax = plt.subplots(figsize=(12, 5.2))
    xs = mdates.date2num(win["ts"].tolist())
    width = 0.0005
    for x, (_, r) in zip(xs, win.iterrows()):
        o, h, lo, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        color = "#d14" if c < o else "#2a8"
        ax.vlines(x, lo, h, color=color, linewidth=0.8)
        ax.add_line(
            plt.Line2D([x - width, x + width], [o, o], color=color, linewidth=1.4)
        )
        ax.add_line(
            plt.Line2D([x - width, x + width], [c, c], color=color, linewidth=1.4)
        )
        ax.vlines(x, min(o, c), max(o, c), color=color, linewidth=2.2)

    cost = float(lot["buy_px"])
    ax.axhline(cost, color="#888", ls="--", lw=0.8, label=f"成本 {cost:.2f}")
    ax.axhline(
        ladder_target_price(cost, gain_pct=DEFAULT_LADDER_HALF_PCT),
        color="#c90",
        ls=":",
        lw=0.8,
        label="10%",
    )
    ax.axhline(
        ladder_target_price(cost, gain_pct=DEFAULT_LADDER_FULL_PCT),
        color="#06c",
        ls=":",
        lw=0.8,
        label="15%",
    )
    ax.axhline(
        cost_hard_stop_px(cost, hard_pct=DEFAULT_PULLBACK_PCT),
        color="#a33",
        ls=":",
        lw=0.8,
        label="硬保护",
    )
    ax.scatter(
        [mdates.date2num(buy_ts)],
        [cost],
        marker="^",
        s=80,
        c="#06c",
        zorder=5,
        label="买",
    )
    for s in lot["sells"]:
        ax.scatter(
            [mdates.date2num(s["ts"])],
            [s["px"]],
            marker="v",
            s=80,
            c="#d14",
            zorder=5,
        )
        ax.annotate(
            f"{s['exit_reason'] or 'sell'}\\n{s['shares']}@{s['px']}",
            (mdates.date2num(s["ts"]), s["px"]),
            textcoords="offset points",
            xytext=(6, 8),
            fontsize=8,
            color="#d14",
        )
    ax.set_title(
        f"{lot['code']} {lot['name']}  买 {buy_ts} @{cost:.2f} ×{lot['shares0']}"
        + (f"  余{lot['remain']}" if lot["remain"] > 0 else "  已平")
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def write_report(
    *,
    lots: list[dict[str, Any]],
    issues: list[str],
    images: list[Path],
    equity: list[dict[str, Any]] | None,
    out_md: Path,
    tag: str,
) -> None:
    lines = [
        f"# 交割单 × 1 分钟 K 核对 · {tag}",
        "",
        "> 研究用途，非投资建议。对照 `eval_multi_tp_bar` 从买入分钟重放，检查时刻/价格/半仓股数/剩余全平。",
        "",
        "## 结论",
        "",
    ]
    if issues:
        lines.append(f"发现 **{len(issues)}** 条需人工看的差异：")
        lines.append("")
        for it in issues:
            lines.append(f"- {it}")
    else:
        lines.append("交割卖点与 1m 重放在时刻（±1 分钟）、原因、价格（±0.02）、半仓股数上对齐。")
        lines.append("")
        lines.append("仍须注意（规则内，不是漏单）：")
        lines.append("- 买入当日 T+1 不卖；浮盈未到 3% 记到次日峰值回落 2.5%；已过 3% 次日走中段。")
        lines.append("- 10% 只减半；未到 15% 则最高点回落 2% 把该股剩余全平。")
        lines.append("- 短窗 5 日不能当策略期望。")
    lines.extend(["", "## 回合一览", "", "| 代码 | 名称 | 买时 | 成本 | 股 | 卖出 | 余股 |", "|------|------|------|------|----|------|------|"])
    for lot in lots:
        sells = "；".join(
            f"{str(s['ts'])[5:16]} {s['exit_reason']} {s['shares']}@{s['px']}"
            for s in lot["sells"]
        ) or "—"
        lines.append(
            f"| {lot['code']} | {lot['name']} | {lot['buy_ts']} | {lot['buy_px']} | "
            f"{lot['shares0']} | {sells} | {lot['remain']} |"
        )
    if equity:
        lines.extend(["", "## 日末权益", "", "| 日期 | 权益 | 现金 | 持仓 | 累计% |", "|------|------|------|------|-------|"])
        for r in equity:
            lines.append(
                f"| {r.get('date')} | {r.get('equity')} | {r.get('cash')} | "
                f"{r.get('codes')} | {r.get('ret_pct')} |"
            )
    if images:
        lines.extend(["", "## 1 分钟 K（买卖标注）", ""])
        for p in images:
            rel = p.name
            lines.append(f"![{rel}]({rel})")
            lines.append("")
    lines.extend(["", "研究用途，非投资建议。", ""])
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="_week202609")
    ap.add_argument("--pool-dir", default=str(HERE))
    args = ap.parse_args(argv)
    tag = str(args.tag).strip()
    file_stem = f"_{tag}" if tag else ""
    pool_dir = Path(args.pool_dir)
    trades_p = pool_dir / f"portfolio_trades{file_stem}.csv"
    eq_p = pool_dir / f"portfolio_equity{file_stem}.csv"
    if not trades_p.is_file():
        raise SystemExit(f"没有 {trades_p}")
    trades = load_trades(trades_p)
    equity = list(csv.DictReader(eq_p.open(encoding="utf-8"))) if eq_p.is_file() else []
    lots = group_lots(trades)
    issues: list[str] = []
    images: list[Path] = []
    img_dir = pool_dir / f"audit_k{file_stem}"
    for lot in lots:
        mins = load_minutes(lot["code"])
        issues.extend(check_lot(lot, mins))
        fn = f"{lot['code']}_{str(lot['buy_ts'])[:10].replace('-', '')}.png"
        p = plot_lot(lot, mins, img_dir / fn)
        if p:
            images.append(p)
    out_md = pool_dir / f"AUDIT_1M_AUTO{file_stem}.md"
    write_report(lots=lots, issues=issues, images=images, equity=equity, out_md=out_md, tag=tag)
    print(f"回合 {len(lots)} · 差异 {len(issues)} · 图 {len(images)}")
    print(f"写入 {out_md}")
    for it in issues:
        print(" !", it)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
