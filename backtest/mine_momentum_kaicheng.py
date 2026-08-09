"""凯盛科技：挖掘因子4动量参数，目标夏普≥1.5。"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.momentum_sim import simulate_momentum  # noqa: E402


def _grid() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for n in (20, 30, 40, 50, 60, 80, 90, 120):
        out.append(("dist_hl", {"n": n, "enter": 1.0, "exit": 0.0}))
        out.append(("dist_hl", {"n": n, "enter": 2.0, "exit": -1.0}))
        out.append(("dist_hl", {"n": n, "enter": 5.0, "exit": 0.0}))
        out.append(("roc", {"n": n, "buffer": 0.0}))
        out.append(("roc", {"n": n, "buffer": 0.03}))
        out.append(("ma", {"n": n, "buffer": 0.0}))
        out.append(("breakout", {"n": n, "deadband": 0.05}))
        out.append(("up_ratio", {"n": n, "thresh": 0.55, "exit_thresh": 0.45}))
        for ma_n in (40, 60, 90, 120):
            out.append(("roc_ma", {"n": n, "ma_n": ma_n, "buffer": 0.0}))
            out.append(("dist_ma", {"n": n, "ma_n": ma_n, "enter": 1.0, "exit": 0.0}))
            out.append(("dist_ma", {"n": n, "ma_n": ma_n, "enter": 3.0, "exit": -1.0}))
    for fast, slow in itertools.product((5, 8, 10, 12, 15), (20, 30, 40, 60)):
        if fast >= slow:
            continue
        out.append(("dual_ma", {"fast": fast, "slow": slow, "buffer": 0.0}))
        for n in (40, 60, 90):
            out.append(
                (
                    "dual_dist",
                    {
                        "fast": fast,
                        "slow": slow,
                        "n": n,
                        "enter": 1.0,
                        "exit": 0.0,
                    },
                )
            )
    for m, k in itertools.product((5, 6, 8, 10), (8, 12, 20)):
        out.append(("alpha022", {"m": m, "k": k, "buffer": 0.0}))
        out.append(("alpha022", {"m": m, "k": k, "buffer": 0.005}))
    return out


def _run_grid(daily, cfg, label: str) -> list[dict]:
    rows = []
    for kind, params in _grid():
        m = simulate_momentum(
            daily,
            kind=kind,
            params=params,
            initial_cash=cfg.initial_cash,
            target_pct=cfg.target_pct,
            commission_rate=cfg.commission_rate,
            stamp_tax_rate=cfg.stamp_tax_rate,
            slippage_value=cfg.slippage_value,
            lot_size=cfg.lot_size,
        )
        rows.append({"kind": kind, "params": params, "window": label, **m})
    rows.sort(key=lambda r: (r["sharpe"], r["total_return"]), reverse=True)
    return rows


def main() -> None:
    cfg = KAICHENG
    daily_full = fetch_daily(
        cfg.symbol,
        cfg.start_date,
        cfg.end_date,
        cache_path=cfg.daily_cache,
    )
    windows = {
        "2020+": daily_full,
        "2022+": daily_full[daily_full["date"] >= "2022-01-01"].reset_index(drop=True),
        "2023+": daily_full[daily_full["date"] >= "2023-01-01"].reset_index(drop=True),
        "2024+": daily_full[daily_full["date"] >= "2024-01-01"].reset_index(drop=True),
    }
    best_overall = None
    for label, daily in windows.items():
        if len(daily) < 80:
            continue
        print(f"\n===== 窗口 {label}  bars={len(daily)} =====")
        rows = _run_grid(daily, cfg, label)
        for i, r in enumerate(rows[:8], 1):
            print(
                f"{i:2d}. sharpe={r['sharpe']:.3f} ret={r['total_return']*100:7.2f}% "
                f"dd={r['max_dd']*100:5.2f}% trades={r['trades']:.0f} "
                f"{r['kind']} {r['params']}"
            )
        good = [r for r in rows if r["sharpe"] >= 1.5]
        print(f"夏普≥1.5: {len(good)} / {len(rows)}")
        cand = good[0] if good else rows[0]
        # 优先：全样本且夏普≥1.5；否则取各窗最高夏普
        if best_overall is None:
            best_overall = cand
        else:
            # 偏好全样本达标；否则更高夏普
            def score(r):
                bonus = 0.5 if r["window"] == "2020+" and r["sharpe"] >= 1.5 else 0.0
                bonus += 0.2 if r["window"] == "2020+" else 0.0
                return r["sharpe"] + bonus

            if score(cand) > score(best_overall):
                best_overall = cand

    assert best_overall is not None
    print(
        f"\nBEST: window={best_overall['window']} {best_overall['kind']} "
        f"{best_overall['params']} sharpe={best_overall['sharpe']:.4f}"
    )
    out = Path(__file__).with_name("_momentum_mine_best.txt")
    out.write_text(
        f"kind={best_overall['kind']}\n"
        f"params={best_overall['params']!r}\n"
        f"window={best_overall['window']}\n"
        f"sharpe={best_overall['sharpe']:.6f}\n"
        f"ret={best_overall['total_return']:.6f}\n"
        f"dd={best_overall['max_dd']:.6f}\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
