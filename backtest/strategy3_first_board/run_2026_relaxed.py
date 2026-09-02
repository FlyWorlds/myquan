"""策略3 · 2026 年窗口 · 情绪门槛放宽对照。

默认：连板≥2、最高板 2～5
放宽：连板≥1、最高板 2～8 / 2～10 / 仅连板≥1

  python backtest/strategy3_first_board/run_2026_relaxed.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy3.first_board import (  # noqa: E402
    OUT,
    run_first_board_promotion_backtest,
)

START = "20260101"
END = "20260831"
OUT_SUB = OUT / "y2026_relaxed"

CONFIGS: list[dict] = [
    {
        "id": "default_lb2_h2_5",
        "label": "默认·连板≥2·最高板2～5",
        "mkt_lianban_min": 2,
        "mkt_max_height_min": 2,
        "mkt_max_height_max": 5,
    },
    {
        "id": "relax_lb1_h2_8",
        "label": "放宽·连板≥1·最高板2～8",
        "mkt_lianban_min": 1,
        "mkt_max_height_min": 2,
        "mkt_max_height_max": 8,
    },
    {
        "id": "relax_lb1_h2_10",
        "label": "放宽·连板≥1·最高板2～10",
        "mkt_lianban_min": 1,
        "mkt_max_height_min": 2,
        "mkt_max_height_max": 10,
    },
    {
        "id": "relax_lb1_only",
        "label": "更宽·仅连板≥1（不限最高板）",
        "mkt_lianban_min": 1,
        "mkt_max_height_min": None,
        "mkt_max_height_max": None,
    },
]


def _slice_2026(eq: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    e = eq.copy()
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values("date")
    y = e[e["date"].between("2026-01-01", "2026-08-31")].reset_index(drop=True)
    if len(y) < 2:
        return y, {"ret_pct": float("nan"), "mdd_pct": float("nan"), "aug_pct": float("nan")}
    nav0 = float(y["equity"].iloc[0])
    y = y.copy()
    y["nav"] = y["equity"] / nav0
    ret = float(y["nav"].iloc[-1] - 1.0) * 100.0
    peak = y["nav"].cummax()
    mdd = float((y["nav"] / peak - 1.0).min()) * 100.0
    aug = y[y["date"].between("2026-08-01", "2026-08-31")]
    if len(aug) >= 2:
        # 用 7 月末净值作 MoM；若无则用 8/1
        before = y[y["date"] <= "2026-07-31"]
        base = float(before["nav"].iloc[-1]) if len(before) else float(aug["nav"].iloc[0])
        aug_pct = float(aug["nav"].iloc[-1] / base - 1.0) * 100.0
        aug_cal = float(aug["nav"].iloc[-1] / float(aug["nav"].iloc[0]) - 1.0) * 100.0
    else:
        aug_pct = float("nan")
        aug_cal = float("nan")
    return y, {
        "ret_pct": ret,
        "mdd_pct": mdd,
        "aug_mom_pct": aug_pct,
        "aug_cal_pct": aug_cal,
        "n_days": len(y),
    }


def _monthly(nav: pd.DataFrame) -> pd.DataFrame:
    s = nav.set_index("date")["nav"].sort_index()
    m = s.resample("ME").last().dropna()
    out = pd.DataFrame({"month": m.index.strftime("%Y-%m"), "nav": m.values})
    out["ret_pct"] = out["nav"].pct_change() * 100.0
    return out


def main() -> None:
    OUT_SUB.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for cfg in CONFIGS:
        print("\n" + "=" * 60)
        print(cfg["label"])
        print("=" * 60)
        result = run_first_board_promotion_backtest(
            start=START,
            end=END,
            entry_pcts=(0.025, 0.03),
            pool_mode="first_board",
            mkt_lianban_min=cfg["mkt_lianban_min"],
            mkt_max_height_min=cfg["mkt_max_height_min"],
            mkt_max_height_max=cfg["mkt_max_height_max"],
            mkt_lu_min=None,
            mkt_lu_max=None,
            rebuild_signals=True,
        )
        for s in result["summaries"]:
            thr = float(s["entry_pct"])
            tag = (
                f"{thr:.4f}".replace("0.", "0p")
            )
            # find equity file written by run
            # tag format from _signal_cache_tag
            from strategy.strategies.strategy3 import first_board as fb

            fb.MKT_LIANBAN_MIN = cfg["mkt_lianban_min"]
            fb.MKT_MAX_HEIGHT_MIN = cfg["mkt_max_height_min"]
            fb.MKT_MAX_HEIGHT_MAX = cfg["mkt_max_height_max"]
            fb.MKT_LU_MIN = None
            fb.MKT_LU_MAX = None
            fb.SENTIMENT_LAG = 1
            eq_tag = fb._signal_cache_tag(thr)
            eq_path = OUT / f"equity_{eq_tag}.csv"
            tr_path = OUT / f"trades_{eq_tag}.csv"
            eq = pd.read_csv(eq_path)
            y26, m26 = _slice_2026(eq)
            y26.to_csv(OUT_SUB / f"equity_{cfg['id']}_{eq_tag}.csv", index=False)
            monthly = _monthly(y26)
            monthly.to_csv(OUT_SUB / f"monthly_{cfg['id']}_{eq_tag}.csv", index=False)
            tr = pd.read_csv(tr_path, parse_dates=["buy_date", "sell_date"])
            tr26 = tr[
                (tr["buy_date"].between("2026-01-01", "2026-08-31"))
                | (tr["sell_date"].between("2026-01-01", "2026-08-31"))
            ]
            tr26.to_csv(OUT_SUB / f"trades_{cfg['id']}_{eq_tag}.csv", index=False)
            aug_tr = tr26[
                (tr26["buy_date"].between("2026-08-01", "2026-08-31"))
                | (tr26["sell_date"].between("2026-08-01", "2026-08-31"))
            ]
            row = {
                "config": cfg["id"],
                "label": cfg["label"],
                "entry_pct": thr,
                "y2026_ret_pct": round(m26["ret_pct"], 2),
                "y2026_mdd_pct": round(m26["mdd_pct"], 2),
                "aug_mom_pct": round(m26["aug_mom_pct"], 2),
                "aug_cal_pct": round(m26["aug_cal_pct"], 2),
                "n_trades_2026": int(len(tr26)),
                "n_trades_aug": int(len(aug_tr)),
                "win_rate_2026": round(float((tr26["ret_pct"] > 0).mean() * 100), 1)
                if len(tr26)
                else None,
            }
            rows.append(row)
            print(
                f"  ±{thr*100:.1f}% | 2026收益 {row['y2026_ret_pct']:+.2f}% | "
                f"回撤 {row['y2026_mdd_pct']:.2f}% | 8月MoM {row['aug_mom_pct']:+.2f}% | "
                f"笔数 {row['n_trades_2026']}（8月{row['n_trades_aug']}）"
            )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_SUB / "compare.csv", index=False)
    (OUT_SUB / "compare.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = [
        "# 策略三 · 2026 窗口 · 情绪放宽对照",
        "",
        f"- 区间：{START} → {END}（首板晋级 · 中证1000）",
        "- 执行：晋级日因子1 突破买，T+1 止损或收盘清；单槽",
        "- 情绪：T-1；下表对比默认 vs 放宽",
        "",
        "| 配置 | 阈值 | 2026收益% | 回撤% | 8月MoM% | 8月日历% | 笔数 | 8月笔数 | 胜率% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| {r['label']} | ±{r['entry_pct']*100:.1f}% | {r['y2026_ret_pct']:+.2f} | "
            f"{r['y2026_mdd_pct']:.2f} | {r['aug_mom_pct']:+.2f} | {r['aug_cal_pct']:+.2f} | "
            f"{r['n_trades_2026']} | {r['n_trades_aug']} | {r['win_rate_2026']} |"
        )
    md += [
        "",
        "## 说明",
        "",
        "- 2026 收益：自 2026-01-02 净值归一后算到 8/31。",
        "- 8月MoM：7月末 → 8月末；8月日历：8/1 → 8/31。",
        "- 研究口径，不构成投资建议。",
    ]
    (OUT_SUB / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n报告 → {OUT_SUB / 'report.md'}")


if __name__ == "__main__":
    main()
