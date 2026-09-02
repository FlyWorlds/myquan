"""策略十三回测：S1 质量带周频轮动 · 重点看 2026-08。

  python backtest/strategy13_weekly_rotate/run.py
  python backtest/strategy13_weekly_rotate/run.py --start 20260101 --end 20260831
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.s1_weekly_rotate import run_s1_weekly_rotate, s1_weekly_rules_text  # noqa: E402

OUT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20250102")
    ap.add_argument("--end", default="20260831")
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--mom-n", type=int, default=20)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print(s1_weekly_rules_text({"top_k": args.top_k, "mom_n": args.mom_n}))
    print(f"\n回测 {args.start} → {args.end} · Top{args.top_k} · mom{args.mom_n}")

    res = run_s1_weekly_rotate(
        start=args.start,
        end=args.end,
        top_k=args.top_k,
        mom_n=args.mom_n,
    )
    res.nav.to_csv(OUT / "nav_daily.csv", header=["nav"])
    res.daily_ret.to_csv(OUT / "daily_ret.csv", header=["ret"])
    res.weekly_picks.to_csv(OUT / "weekly_picks.csv", index=False)
    res.monthly.to_csv(OUT / "monthly.csv", index=False)

    # 2026-08 明细
    aug_nav = res.nav.loc["2026-08-01":"2026-08-31"]
    aug_ret = res.daily_ret.loc["2026-08-01":"2026-08-31"]
    aug_weeks = res.weekly_picks[
        (res.weekly_picks["hold_week"] >= "2026-08-01")
        & (res.weekly_picks["hold_week"] <= "2026-08-31")
    ]
    aug_pct = float("nan")
    if len(aug_nav) >= 2:
        aug_pct = float(aug_nav.iloc[-1] / aug_nav.iloc[0] - 1.0) * 100.0

    summary = {
        "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
        "strategy": "strategy13 · S1质量带周频轮动",
        "window": [args.start, args.end],
        "params": res.config,
        "stats": res.stats,
        "fill_stats": res.fill_stats,
        "aug_2026": {
            "ret_pct": aug_pct,
            "n_days": int(len(aug_ret)),
            "n_weeks": int(len(aug_weeks)),
            "avg_kept": float(aug_weeks["n_kept"].mean()) if len(aug_weeks) else None,
            "avg_turn": float(aug_weeks["turn"].mean()) if len(aug_weeks) else None,
        },
        "note": "研究口径（含换手成本）；重叠票不强制换出；非投资建议",
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    md = [
        "# 策略十三 · S1质量带周频轮动",
        "",
        f"- 生成：{summary['generated']}",
        f"- 区间：{args.start} → {args.end}",
        f"- TopK={args.top_k} · mom={args.mom_n} · 重叠留仓 · 含换手成本",
        "",
        "## 全区间",
        "",
        f"- 收益：{res.stats.get('ret_pct', float('nan')):+.2f}%",
        f"- 夏普：{res.stats.get('sharpe', float('nan')):.2f}",
        f"- 回撤：{res.stats.get('mdd_pct', float('nan')):.2f}%",
        f"- 周均换手：{res.stats.get('avg_week_turn', float('nan')):.2%} · 周均留仓 {res.stats.get('avg_kept', float('nan')):.1f} 只",
        "",
        "## 2026年8月",
        "",
        f"- **收益：{aug_pct:+.2f}%**（{len(aug_ret)} 个交易日）",
        f"- 周数：{len(aug_weeks)} · 周均留仓 {summary['aug_2026']['avg_kept']} · 周均换手 {summary['aug_2026']['avg_turn']}",
        "",
        "### 8月周名单",
        "",
        "| 信号日 | 持有周 | 留仓 | 新进 | 换出 | 换手 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in aug_weeks.itertuples(index=False):
        md.append(
            f"| {r.signal_date} | {r.hold_week} | {r.n_kept} | {r.n_added} | {r.n_dropped} | {r.turn:.0%} |"
        )
    md += [
        "",
        "## 月度收益",
        "",
        "| 月 | 收益% |",
        "|---|---:|",
    ]
    for r in res.monthly.dropna(subset=["ret_pct"]).itertuples(index=False):
        md.append(f"| {r.month} | {r.ret_pct:+.2f} |")
    md += [
        "",
        "## 说明",
        "",
        "- 参考策略一：13A 质量带宇宙；执行改为周频动量 Top20 等权。",
        "- 仍在名单内的票不强制换出（部分不换）；仅对换出/新进部分计换手成本。",
        "- 研究模拟，不构成投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")

    print("\n=== 结果 ===")
    print(
        f"全区间 {res.stats.get('ret_pct', float('nan')):+.2f}% | "
        f"夏普 {res.stats.get('sharpe', float('nan')):.2f} | "
        f"回撤 {res.stats.get('mdd_pct', float('nan')):.2f}%"
    )
    print(f"2026-08 收益：{aug_pct:+.2f}%")
    print(f"报告 → {OUT / 'report.md'}")


if __name__ == "__main__":
    main()
