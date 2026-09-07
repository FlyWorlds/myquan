"""策略一定盘池 · 近 7 交易日 1 分钟路径回测。

选股/过滤：日线（前日阴/小阳、双阳禁买）；组合回撤看因子2 预警（不注资）。
成交：池内票近 7 日用 1 分钟 path-dependent（开盘突破/攻击波买 + 回落波止损）。

用法：
  PYTHONPATH=. python backtest/strategy1_pool_1m/run.py
  PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --days 7 --refresh

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.data import fetch_daily  # noqa: E402
from strategy.dd_alert import derive_thresholds, format_rules  # noqa: E402
from strategy.minute import pull_akshare_1m  # noqa: E402
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    replay_factor26_1m,
)

OUT = Path(__file__).resolve().parent
CACHE = OUT / "cache_1m"
CACHE.mkdir(parents=True, exist_ok=True)


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}"


def _em(code: str) -> str:
    return str(code).zfill(6)


def _load_pool() -> list[dict]:
    from holdingStocks.watch_config import strategy_watchlist

    return list(strategy_watchlist())


def _daily(sina: str, lookback_cal_days: int = 40) -> pd.DataFrame:
    end = pd.Timestamp.now().strftime("%Y%m%d")
    start = (pd.Timestamp.now() - pd.Timedelta(days=lookback_cal_days)).strftime(
        "%Y%m%d"
    )
    try:
        return fetch_daily(sina, start, end)
    except Exception as e:  # noqa: BLE001
        print(f"  日线失败 {sina}: {e}")
        return pd.DataFrame()


def _minutes(sina: str, *, refresh: bool) -> pd.DataFrame:
    path = CACHE / f"{sina}_1m.parquet"
    if path.exists() and not refresh:
        try:
            df = pd.read_parquet(path)
            if not df.empty and "ts" in df.columns:
                return df
        except Exception:  # noqa: BLE001
            pass
    em = _em(sina[2:] if len(sina) >= 8 else sina)
    try:
        df = pull_akshare_1m(em_symbol=em, sina_symbol=sina, adjust="")
    except Exception as e:  # noqa: BLE001
        print(f"  1m 失败 {sina}: {e}")
        df = pd.DataFrame()
    if not df.empty:
        try:
            df.to_parquet(path, index=False)
        except Exception:  # noqa: BLE001
            pass
    return df


def _trade_pnl(trades: list[dict]) -> tuple[float | None, int]:
    """简单成对买→卖收益（未计费）；未平仓不算。"""
    buy_px = None
    rets: list[float] = []
    for t in trades:
        if t.get("side") == "buy":
            buy_px = float(t["px"])
        elif t.get("side") == "sell" and buy_px and buy_px > 0:
            rets.append(float(t["px"]) / buy_px - 1.0)
            buy_px = None
    if not rets:
        return None, 0
    # 连乘
    nav = 1.0
    for r in rets:
        nav *= 1.0 + r
    return nav - 1.0, len(rets)


def run(*, days: int = 7, refresh: bool = False, entry_pct: float | None = None) -> dict:
    entry = float(entry_pct if entry_pct is not None else DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    pool = _load_pool()
    rows: list[dict] = []
    print(f"定盘池 {len(pool)} 只 · 近 {days} 交易日 1m 路径 · entry/pb={entry*100:.1f}%")

    for w in pool:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        sp = float(w.get("stop_pct") or w.get("pct") or pb)
        print(f"· {code} {name} …", flush=True)
        daily = _daily(sina)
        mins = _minutes(sina, refresh=refresh)
        rep = replay_factor26_1m(
            daily,
            mins,
            entry_pct=ep,
            pullback_pct=sp,
            last_n_days=int(days),
        )
        pnl, n_round = _trade_pnl(list(rep.get("trades") or []))
        rows.append(
            {
                "code": code,
                "name": name,
                "sina": sina,
                "entry_pct": ep,
                "pullback_pct": sp,
                "days_used": rep.get("days_used"),
                "holding": bool(rep.get("holding")),
                "n_trades": len(rep.get("trades") or []),
                "n_rounds": n_round,
                "pnl_pct": None if pnl is None else round(pnl * 100.0, 2),
                "last_side": rep.get("last_trigger_side"),
                "last_px": rep.get("last_trigger_px"),
                "last_date": (
                    str(rep.get("last_trigger_date"))[:10]
                    if rep.get("last_trigger_date") is not None
                    else None
                ),
                "trades": rep.get("trades") or [],
            }
        )

    df = pd.DataFrame(rows)
    # 等权已平仓回合收益（有 pnl 的票）
    finished = df[df["pnl_pct"].notna()]
    eq_pnl = float(finished["pnl_pct"].mean()) if len(finished) else None
    if eq_pnl is not None:
        eq_pnl = round(eq_pnl, 2)
    # 因子2：用等权合成粗净值（仅有完整回合的票）
    f2_note = "样本过短，回撤预警仅作阈值展示"
    th = derive_thresholds()
    summary = {
        "window_days": int(days),
        "n_pool": len(pool),
        "n_with_rounds": int(len(finished)),
        "equal_weight_pnl_pct": eq_pnl,
        "factor2_alert": th.as_dict(),
        "factor2_label": th.label(),
        "factor2_rules": format_rules(th),
        "factor2_note": f2_note,
        "disclaimer": "研究用途，非投资建议；1m 约近数日；未计费/滑点。",
    }

    out_csv = OUT / "pool_1m_7d.csv"
    out_json = OUT / "pool_1m_7d.json"
    out_md = OUT / "REPORT.md"
    df.drop(columns=["trades"], errors="ignore").to_csv(out_csv, index=False)
    out_json.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    lines = [
        "# 策略一定盘池 · 近 7 日 1 分钟路径回测",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 规则",
        "",
        "- **选股/过滤**：日线（前日阴/小阳、双阳禁买）；因子2 回撤仅预警阈值，不注资",
        "- **成交**：池内票近 N 交易日 **1 分钟** path-dependent（买=开盘突破或攻击波；卖=分时最高回落）",
        f"- 窗长：{days} 交易日；默认阈值 ±{entry*100:.1f}%",
        "",
        "## 摘要",
        "",
        f"- 池子：{summary['n_pool']} 只；有完整买卖回合：{summary['n_with_rounds']}",
        f"- 等权已平仓收益：{eq_pnl if eq_pnl is not None else '—'}%",
        f"- 因子2：{summary['factor2_label']}",
        "",
        "## 个股",
        "",
        "| 代码 | 名称 | 天数 | 成交笔数 | 回合 | 收益% | 持有 | 末次 |",
        "|------|------|------|----------|------|-------|------|------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['code']} | {r['name']} | {r['days_used']} | {r['n_trades']} | "
            f"{r['n_rounds']} | {r['pnl_pct'] if r['pnl_pct'] is not None else '—'} | "
            f"{'Y' if r['holding'] else ''} | {r['last_side'] or ''} |"
        )
    lines.extend(
        [
            "",
            f"产物：`{out_csv.name}` / `{out_json.name}`",
            "",
            summary["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n写入 {out_csv}")
    print(f"写入 {out_md}")
    if eq_pnl is not None:
        print(f"等权已平仓收益 {eq_pnl:.2f}%（{len(finished)} 只）")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="策略一定盘池 7 日 1m 回测")
    ap.add_argument("--days", type=int, default=7, help="近 N 个有 1m 的交易日")
    ap.add_argument("--refresh", action="store_true", help="强制重拉 1m")
    ap.add_argument("--entry-pct", type=float, default=None)
    args = ap.parse_args()
    run(days=int(args.days), refresh=bool(args.refresh), entry_pct=args.entry_pct)


if __name__ == "__main__":
    main()
