#!/usr/bin/env python3
"""策略十二：仅用 2020–2024 调参，冻结后再盲测 2025 至今。

窗口解释：用户写「2020-2025 调参、2025至今盲测」。为避免 2025 重叠，
调参 = 2020-01-02～2024-12-31，盲测 = 2025-01-02～数据末日。
禁止用盲测窗选参。研究用途，非投资建议。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy12.gap_reclaim import (  # noqa: E402
    BLIND_START,
    INITIAL,
    OUT,
    TUNE_END,
    _mdd,
    _sharpe,
    filter_signals,
    run_portfolio,
    scan_signals,
)

TUNE_START = "2020-01-02"
IS_EXIT_PAD = "2025-01-15"  # 让 2024 年末仓能 T+1 平，指标仍截到 TUNE_END
MIN_IS_TRADES = 150

VARIANTS: list[dict[str, Any]] = [
    {"id": "v5_baseline", "label": "v5 基线（不过滤昨开板）", "require_opened": False, "max_pos": 3},
    {"id": "opened", "label": "要求昨涨停曾开板", "require_opened": True, "max_pos": 3},
    {"id": "drop_locked", "label": "仅剔昨一字锁定", "drop_locked": True, "max_pos": 3},
    {
        "id": "opened_pos2",
        "label": "昨开板 + 最多 2 仓",
        "require_opened": True,
        "max_pos": 2,
        "max_entries": 2,
    },
    {
        "id": "opened_pos1",
        "label": "昨开板 + 最多 1 仓",
        "require_opened": True,
        "max_pos": 1,
        "max_entries": 1,
    },
    {
        "id": "opened_skip_idx2",
        "label": "昨开板 + 上证昨收≤−2% 空仓",
        "require_opened": True,
        "max_yest_idx_ret": -0.02,
        "max_pos": 3,
    },
    {
        "id": "opened_skip_idx3",
        "label": "昨开板 + 上证昨收≤−3% 空仓",
        "require_opened": True,
        "max_yest_idx_ret": -0.03,
        "max_pos": 3,
    },
    {
        "id": "opened_gap_deep",
        "label": "昨开板 + 低开带收窄到 [−4.5%, −0.8%]",
        "require_opened": True,
        "gap_max": -0.008,
        "max_pos": 3,
    },
]


def _load_or_scan(*, force: bool, verbose: bool) -> pd.DataFrame:
    path = OUT / "signals.parquet"
    need = ("yest_opened", "yest_locked", "yest_idx_ret")
    if (not force) and path.is_file():
        sig = pd.read_parquet(path)
        if all(c in sig.columns for c in need):
            if verbose:
                print(f"复用信号 {len(sig)} 条  {path}")
            return sig
        if verbose:
            print("已有 parquet 缺一字/指数字段，重扫")
    if verbose:
        print("扫描全宇宙信号（含昨开板/一字锁定）…")
    sig = scan_signals()
    OUT.mkdir(parents=True, exist_ok=True)
    sig.to_parquet(path, index=False)
    if verbose:
        print(f"候选 {len(sig)} 条 / {sig['trade_date'].nunique() if len(sig) else 0} 日")
    return sig


def _metrics(eq: pd.DataFrame, tr: pd.DataFrame, *, initial: float, end: str | None = None) -> dict[str, Any]:
    if eq.empty:
        return {
            "ret_pct": 0.0,
            "mdd_pct": 0.0,
            "sharpe": float("nan"),
            "n_trades": 0,
            "win_rate": float("nan"),
            "end_equity": float(initial),
        }
    e = eq.copy()
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values("date")
    if end:
        e = e[e["date"] <= pd.Timestamp(end)]
    if e.empty:
        return {
            "ret_pct": 0.0,
            "mdd_pct": 0.0,
            "sharpe": float("nan"),
            "n_trades": 0,
            "win_rate": float("nan"),
            "end_equity": float(initial),
        }
    e0, e1 = float(initial), float(e["equity"].iloc[-1])
    r = e["equity"].pct_change().dropna()
    n = 0 if tr.empty else int(len(tr))
    if n and end and "sell_date" in tr.columns:
        tr_w = tr[pd.to_datetime(tr["sell_date"]) <= pd.Timestamp(end)]
        n = int(len(tr_w))
        win = float((tr_w["ret_pct"] > 0).mean() * 100) if n else float("nan")
    else:
        win = float((tr["ret_pct"] > 0).mean() * 100) if n else float("nan")
    return {
        "ret_pct": (e1 / e0 - 1.0) * 100,
        "mdd_pct": _mdd(e["equity"]),
        "sharpe": _sharpe(r),
        "n_trades": n,
        "win_rate": win,
        "end_equity": e1,
    }


def _apply_variant(sig: pd.DataFrame, v: dict[str, Any]) -> pd.DataFrame:
    keys = ("require_opened", "drop_locked", "gap_min", "gap_max", "max_yest_idx_ret", "rank_deepest")
    kw = {k: v[k] for k in keys if k in v}
    return filter_signals(sig, **kw)


def _pick(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok = []
    for r in rows:
        sh = r["is"]["sharpe"]
        if r["is"]["n_trades"] < MIN_IS_TRADES:
            continue
        if not (r["is"]["ret_pct"] == r["is"]["ret_pct"] and r["is"]["ret_pct"] > 0):
            continue
        if not (sh == sh and sh > 0):
            continue
        ok.append(r)
    if not ok:
        return None
    ok.sort(key=lambda x: (float(x["is"]["sharpe"]), float(x["is"]["ret_pct"])), reverse=True)
    return ok[0]


def _year_break(tr: pd.DataFrame) -> list[dict[str, Any]]:
    if tr.empty:
        return []
    t = tr.copy()
    t["y"] = pd.to_datetime(t["buy_date"]).dt.year
    out = []
    for y, g in t.groupby("y"):
        out.append(
            {
                "year": int(y),
                "n": int(len(g)),
                "mean_ret": float(g["ret_pct"].mean()),
                "sum_ret": float(g["ret_pct"].sum()),
                "win": float((g["ret_pct"] > 0).mean() * 100),
            }
        )
    return out


def _month_break(tr: pd.DataFrame, year: int) -> list[dict[str, Any]]:
    if tr.empty:
        return []
    t = tr.copy()
    t["dt"] = pd.to_datetime(t["buy_date"])
    t = t[t["dt"].dt.year == year]
    out = []
    for m, g in t.groupby(t["dt"].dt.month):
        out.append(
            {
                "month": int(m),
                "n": int(len(g)),
                "mean_ret": float(g["ret_pct"].mean()),
                "sum_ret": float(g["ret_pct"].sum()),
                "win": float((g["ret_pct"] > 0).mean() * 100),
            }
        )
    return out


def main() -> None:
    force = "--rescan" in sys.argv
    quiet = "--quiet" in sys.argv
    verbose = not quiet
    sig = _load_or_scan(force=force, verbose=verbose)

    n_opened = int(sig["yest_opened"].sum()) if "yest_opened" in sig.columns else -1
    n_locked = int(sig["yest_locked"].sum()) if "yest_locked" in sig.columns else -1
    if verbose:
        print(f"一字诊断：昨开板 {n_opened}/{len(sig)}  昨锁定 {n_locked}/{len(sig)}")

    sig_is = sig[sig["trade_date"] <= TUNE_END].copy()
    sig_blind = sig[sig["trade_date"] >= BLIND_START].copy()

    rows: list[dict[str, Any]] = []
    for v in VARIANTS:
        filt = _apply_variant(sig_is, v)
        max_pos = int(v.get("max_pos", 3))
        max_entries = int(v.get("max_entries", max_pos))
        if verbose:
            print(f"IS  {v['id']:20s}  信号 {len(filt):5d}  pos={max_pos}")
        eq, _, tr = run_portfolio(
            filt,
            initial=INITIAL,
            max_pos=max_pos,
            max_entries=max_entries,
            start=TUNE_START,
            end=IS_EXIT_PAD,
        )
        met = _metrics(eq, tr, initial=INITIAL, end=TUNE_END)
        rows.append(
            {
                "id": v["id"],
                "label": v["label"],
                "params": {k: v[k] for k in v if k not in ("id", "label")},
                "n_signals_is": int(len(filt)),
                "is": met,
            }
        )
        if verbose:
            print(
                f"     收益 {met['ret_pct']:+7.1f}%  夏普 {met['sharpe']:.3f}  "
                f"回撤 {met['mdd_pct']:.1f}%  笔数 {met['n_trades']}"
            )

    winner = _pick(rows)
    pick_note = "按 IS 夏普（收益>0、夏普>0、笔数≥150）选取；未见盲测窗。"
    if winner is None:
        pick_note = "无变体满足 IS 门槛，冻结 v5 基线仅作对照。"
        winner = next(r for r in rows if r["id"] == "v5_baseline")

    if verbose:
        print(f"冻结：{winner['id']}  {winner['label']}")
        print("开始盲测（选参已冻结）…")

    wv = next(x for x in VARIANTS if x["id"] == winner["id"])
    filt_b = _apply_variant(sig_blind, wv)
    eq_b, _, tr_b = run_portfolio(
        filt_b,
        initial=INITIAL,
        max_pos=int(wv.get("max_pos", 3)),
        max_entries=int(wv.get("max_entries", wv.get("max_pos", 3))),
        start=BLIND_START,
        end=None,
    )
    blind = _metrics(eq_b, tr_b, initial=INITIAL)
    y2026 = _month_break(tr_b, 2026)
    years = _year_break(tr_b)

    passed_blind = bool(
        blind["ret_pct"] == blind["ret_pct"]
        and blind["ret_pct"] > 0
        and (blind["sharpe"] == blind["sharpe"] and blind["sharpe"] > 0)
        and blind["mdd_pct"] < 40.0
    )

    payload = {
        "tune_window": [TUNE_START, TUNE_END],
        "blind_window": [BLIND_START, "data_end"],
        "selection": pick_note,
        "n_signals_all": int(len(sig)),
        "yest_opened": n_opened,
        "yest_locked": n_locked,
        "variants_is": rows,
        "winner_id": winner["id"],
        "winner_label": winner["label"],
        "winner_params": winner["params"],
        "blind": blind,
        "blind_passed": passed_blind,
        "blind_by_year": years,
        "blind_2026_by_month": y2026,
        "n_signals_blind": int(len(filt_b)),
        "disclaimer": "研究用途，非投资建议。",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tune_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    eq_b.to_csv(OUT / "nav_blind.csv", index=False)
    if not tr_b.empty:
        tr_b.to_csv(OUT / "trades_blind.csv", index=False)

    lines = [
        "# 策略十二 调参（2020–2024）与盲测（2025 至今）",
        "",
        "> 研究用途，非投资建议。调参窗与盲测窗不重叠。",
        "",
        f"- 调参：{TUNE_START} ～ {TUNE_END}（用户「2020-2025 调参」去掉与盲测重叠的 2025）",
        f"- 盲测：{BLIND_START} ～ 数据末日；本金独立 {INITIAL:.0f}",
        f"- 选参：{pick_note}",
        f"- 冻结：**{winner['id']}** {winner['label']}",
        "",
        "## 调参窗结果",
        "",
        "| 变体 | 累计收益 | 夏普 | 回撤 | 笔数 |",
        "|------|----------|------|------|------|",
    ]
    for r in rows:
        m = r["is"]
        mark = " ←冻结" if r["id"] == winner["id"] else ""
        lines.append(
            f"| {r['label']} | {m['ret_pct']:+.1f}% | {m['sharpe']:.2f} | "
            f"{m['mdd_pct']:.1f}% | {m['n_trades']}{mark} |"
        )
    lines += [
        "",
        "## 盲测（冻结后一次）",
        "",
        f"- 累计 {blind['ret_pct']:+.1f}%  夏普 {blind['sharpe']:.2f}  "
        f"回撤 {blind['mdd_pct']:.1f}%  笔数 {blind['n_trades']}  "
        f"胜率 {blind['win_rate']:.1f}%",
        f"- 过关（累计>0 且夏普>0 且回撤<40%）：{'是' if passed_blind else '否'}",
        "",
        "### 盲测分年",
        "",
        "| 年 | 笔数 | 均收益 | 合计 | 胜率 |",
        "|----|------|--------|------|------|",
    ]
    for y in years:
        lines.append(
            f"| {y['year']} | {y['n']} | {y['mean_ret']:+.2f}% | {y['sum_ret']:+.1f} | {y['win']:.1f}% |"
        )
    if y2026:
        lines += [
            "",
            "### 2026 分月（盲测内）",
            "",
            "| 月 | 笔数 | 均收益 | 合计 | 胜率 |",
            "|----|------|--------|------|------|",
        ]
        for m in y2026:
            lines.append(
                f"| {m['month']} | {m['n']} | {m['mean_ret']:+.2f}% | {m['sum_ret']:+.1f} | {m['win']:.1f}% |"
            )
    (OUT / "TUNE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if verbose:
        print(json.dumps({"winner": winner["id"], "blind": blind, "passed": passed_blind}, ensure_ascii=False, default=str))
        print(f"写入 {OUT / 'tune_result.json'}")


if __name__ == "__main__":
    main()
