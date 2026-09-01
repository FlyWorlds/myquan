"""策略十三 · 纯因子1 ETF walk-forward 选票。

协议：
  · Cohort A（2023 前已上市）：IS 2023-01-02～2025-12-31 选参 → OOS 2025-01-02～今
  · Cohort B（2025 上市、2026 前）：IS 上市日～2025-12-31 选参 → OOS 2026-01-02～今
  · OOS 段按综合分（夏普/超额/收益/胜率）排名取 Top10

  python strategy/strategies/strategy13/run_etf_wf.py
  python strategy/strategies/strategy13/run_etf_wf.py --limit 80   # 调试
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy.strategies.strategy13.etf_lib import (  # noqa: E402
    END,
    WARM_START,
    assign_cohort,
    base_cfg,
    cohort_ok,
    discover_etfs,
    enrich_oos,
    fetch_etf_sina,
    param_jobs,
    score_is,
)
from strategy.strategies.strategy13.scoring import score_oos_rows  # noqa: E402

OUT = Path(__file__).resolve().parent / "etf_wf"
TOP_N = 10


def _fmt(v: float) -> str:
    return "—" if v != v else f"{v:.2f}"


def _report_md(ranked: list[dict[str, Any]], skipped: list[dict[str, str]], n_pool: int) -> str:
    lines = [
        "# 策略十三 · 纯因子1 ETF walk-forward Top10",
        "",
        "研究用途，不构成投资建议。",
        "",
        "## 协议",
        "",
        "| Cohort | 选参 IS | OOS 回测 |",
        "|--------|---------|----------|",
        "| A（2023前上市） | 2023-01-02～2025-12-31 | 2025-01-02～今 |",
        "| B（2025上市） | 上市日～2025-12-31 | 2026-01-02～今 |",
        "",
        "- 引擎：仅因子1；ETF 强制 T+1；印花 0；tick=0.001",
        "- IS 内择优参数；**排名只看 OOS 综合分**（夏普30%+超额30%+收益20%+胜率20%）",
        "",
        f"- 候选 {n_pool} 只 · 有效 {len(ranked)} 只 · 跳过 {len(skipped)} 只",
        "",
        "## Top10（OOS 综合分）",
        "",
        "| 排名 | 代码 | 名称 | Cohort | IS参数 | OOS收益% | OOS超额% | OOS夏普 | OOS胜率% | 综合分 |",
        "|-----:|------|------|:------:|--------|--------:|---------:|--------:|---------:|-------:|",
    ]
    for r in ranked[:TOP_N]:
        o = r["oos"]
        lines.append(
            f"| {r['oos_rank']} | {r['code']} | {r['name']} | {r['cohort']} | {r['label']} | "
            f"{_fmt(o['ret_pct'])} | {_fmt(o['excess_pct'])} | {_fmt(o['sharpe'])} | "
            f"{_fmt(r.get('oos_win_rate', float('nan')))} | {_fmt(r['composite_score'])} |"
        )
    if ranked:
        b = ranked[0]
        o = b["oos"]
        lines += [
            "",
            "## 推荐",
            "",
            f"OOS 综合第一：`{b['code']}` {b['name']}（cohort {b['cohort']}）",
            f"- 冻结参数 `{b['label']}`（买 {b['entry_pct']*100:g}% / 止 {b['stop_pct']*100:g}%）",
            f"- OOS：收益 {_fmt(o['ret_pct'])}%，超额 {_fmt(o['excess_pct'])}%，"
            f"夏普 {_fmt(o['sharpe'])}，胜率 {_fmt(b.get('oos_win_rate'))}%",
        ]
    if skipped:
        lines += ["", "## 跳过（节选）", ""]
        for s in skipped[:12]:
            lines.append(f"- `{s['code']}` {s['name']}：{s['reason']}")
    return "\n".join(lines) + "\n"


def _pool_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "symbol": row["symbol"],
        "cohort": row["cohort"],
        "label": row["label"],
        "entry_pct": row["entry_pct"],
        "stop_pct": row["stop_pct"],
        "prev_entry_mode": row["prev_entry_mode"],
        "oos_rank": row["oos_rank"],
        "composite_score": row["composite_score"],
        "oos": row["oos"],
        "is": row["is"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="仅跑前 N 只（调试）")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    universe = discover_etfs()
    if args.limit > 0:
        universe = universe[: args.limit]

    skipped: list[dict[str, str]] = []
    finalists: list[dict[str, Any]] = []
    param_rows: list[dict[str, Any]] = []

    print(f"ETF universe {len(universe)} · end={END}")

    for sym, code, name in universe:
        try:
            daily = fetch_etf_sina(sym, WARM_START, END.replace("-", ""))
        except Exception as exc:
            skipped.append({"code": code, "name": name, "reason": f"拉取失败: {exc}"})
            continue
        if daily is None or daily.empty:
            skipped.append({"code": code, "name": name, "reason": "无行情"})
            continue
        cohort_info = assign_cohort(daily)
        if cohort_info is None:
            skipped.append({"code": code, "name": name, "reason": "2026年后上市"})
            continue
        cohort, windows = cohort_info
        if not cohort_ok(daily, windows, cohort):
            skipped.append({"code": code, "name": name, "reason": f"cohort{cohort}样本不足"})
            continue
        trade_start = pd.Timestamp(daily["date"].iloc[0])
        if getattr(trade_start, "tz", None) is not None:
            trade_start = trade_start.tz_convert("Asia/Shanghai").tz_localize(None)
        base = base_cfg(sym, code, name, trade_start.strftime("%Y%m%d"))
        sym_rows: list[dict[str, Any]] = []
        for label, fn in param_jobs(base):
            try:
                row, _, _ = fn()
            except Exception as exc:
                row = {"label": label, "error": str(exc)}
            row.update({"symbol": sym, "code": code, "name": name, "cohort": cohort, "windows": windows})
            sym_rows.append(row)
            pr = {k: v for k, v in row.items() if k not in ("nav", "bh")}
            pr["is_score"] = score_is(row, windows) if "error" not in row else float("nan")
            param_rows.append(pr)
        viable = [r for r in sym_rows if "error" not in r and score_is(r, windows) > -1e8]
        if not viable:
            skipped.append({"code": code, "name": name, "reason": "IS无正超额参数"})
            continue
        best = max(viable, key=lambda r: score_is(r, windows))
        fin = enrich_oos(best, windows)
        fin["cohort"] = cohort
        fin["windows"] = windows
        fin["symbol"] = sym
        fin["code"] = code
        fin["name"] = name
        finalists.append(fin)
        o = fin["oos"]
        print(
            f"  {code} [{cohort}] {name[:10]:10s} {fin['label']:12s} "
            f"OOS ex={o['excess_pct']:+.1f}% sh={o['sharpe']:.2f}"
        )

    ranked = score_oos_rows(finalists)
    top10 = ranked[:TOP_N]

    summary = {
        "strategy": "strategy13",
        "end": END,
        "n_pool": len(universe),
        "n_finalists": len(finalists),
        "n_skipped": len(skipped),
        "scoring": "oos: sharpe30% + excess30% + ret20% + win_rate20%",
        "top10": [_pool_entry(r) for r in top10],
        "skipped_sample": skipped[:30],
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (OUT / "top10_pool.json").write_text(
        json.dumps([_pool_entry(r) for r in top10], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    pd.DataFrame(param_rows).to_csv(OUT / "param_sweep_all.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ranked).to_csv(OUT / "ranked_all.csv", index=False, encoding="utf-8-sig")
    (OUT / "report.md").write_text(_report_md(ranked, skipped, len(universe)), encoding="utf-8")
    print(f"\nWrote {OUT}/report.md · top10={[r['code'] for r in top10]}")


if __name__ == "__main__":
    main()
