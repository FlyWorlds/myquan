"""589680：2025 选参窗候选阈值 → 冻结后全期 / 2026 对照。

不重新用 2026 选参；只把 IS 正超额方案拿到全期与 2026 上看。
研究用途，不构成投资建议。
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from backtest.kczz_etf_589680_s1_pre2026.run_walkforward import (  # noqa: E402
    CASH,
    CODE,
    NAME,
    SELECT_END,
    START,
    SYMBOL,
    _rank,
    _run_f1,
    _run_f1_asym,
    _stats,
    apply_best_cfg,
    base_cfg,
    build_jobs,
    holdings_table,
    monthly_excess_rows,
    run_best_full,
)
from strategy.data import fetch_daily  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _MYQUAN / "data_cache" / "sh589680_daily_qfq.parquet"


def _oos_2026(result: Any, daily: pd.DataFrame) -> dict[str, float]:
    from backtest.kczz_etf_589680_s1_pre2026.run_walkforward import _prepare_eq_close

    eq, close = _prepare_eq_close(result, daily)
    eq_2026 = eq[eq.index.year >= 2026]
    close_2026 = close[close.index.year >= 2026]
    if len(eq_2026) < 2 or len(close_2026) < 2:
        return {}
    eq_pre = eq[eq.index.year < 2026]
    px_pre = close[close.index.year < 2026]
    base_eq = float(eq_pre.iloc[-1]) if len(eq_pre) else CASH
    base_px = float(px_pre.iloc[-1]) if len(px_pre) else float(close_2026.iloc[0])
    strat = (float(eq_2026.iloc[-1]) / base_eq - 1.0) * 100.0
    bh = (float(close_2026.iloc[-1]) / base_px - 1.0) * 100.0
    peak = eq_2026.cummax()
    dd = float((eq_2026 / peak - 1.0).min() * 100.0)
    return {
        "2026策略%": round(strat, 2),
        "2026持有%": round(bh, 2),
        "2026超额%": round(strat - bh, 2),
        "2026回撤%": round(dd, 2),
    }


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.today().strftime("%Y%m%d")
    try:
        daily0 = fetch_daily(SYMBOL, START, today, cache_path=CACHE, force_refresh=False)
    except Exception:
        daily0 = pd.read_parquet(CACHE)
    d0 = str(pd.to_datetime(daily0["date"]).min().date())
    d1 = str(pd.to_datetime(daily0["date"]).max().date())
    print(f"日线 {len(daily0)} · {d0}→{d1}")

    # 1) 重跑 IS，取正超额方案
    select_base = base_cfg(end_date=SELECT_END)
    is_rows: list[dict[str, Any]] = []
    is_art: dict[str, tuple[Any, pd.DataFrame]] = {}
    for name, fn in build_jobs(select_base):
        print(f"  IS {name} ...", flush=True)
        row, r, d = fn()
        is_art[name] = (r, d)
        clean = {k: v for k, v in row.items() if k != "_cfg"}
        clean["_cfg_json"] = json.dumps(row["_cfg"], ensure_ascii=False)
        is_rows.append(clean)
    is_ranked = _rank(pd.DataFrame(is_rows))
    pos = is_ranked[is_ranked["累计超额%"] > 0].copy()
    print(f"IS 正超额方案: {len(pos)} / {len(is_ranked)}")

    # 额外对照：盯盘现行 买2.5/止3.5（若已在网格则不重复）
    extra = []
    if not (pos["方案"] == "F1买2.5/止3.5").any():
        extra.append("F1买2.5/止3.5")

    # 2) 冻结跑全期
    compare_rows = []
    monthly_by = {}
    holdings_by = {}
    for _, is_row in pos.iterrows():
        name = str(is_row["方案"])
        cfg = json.loads(str(is_row["_cfg_json"]))
        print(f"  FULL {name} ...", flush=True)
        result, daily = run_best_full(cfg, end_date=today)
        full = _stats(result, daily, name)
        oos = _oos_2026(result, daily)
        monthly = monthly_excess_rows(result, daily, label=NAME, initial_cash=CASH)
        hold = holdings_table(result, daily)
        monthly_by[name] = monthly
        holdings_by[name] = hold
        m2026 = monthly[monthly["月份"].astype(str).str.startswith("2026")]
        compare_rows.append(
            {
                "方案": name,
                "买入%": round(float(cfg.get("entry_pct") or cfg["threshold_pct"]) * 100, 1),
                "止损%": round(float(cfg.get("stop_pct") or cfg["threshold_pct"]) * 100, 1),
                "隔日跳买": bool(cfg.get("skip_buy_after_overnight_stop")),
                "IS超额%": float(is_row["累计超额%"]),
                "IS夏普": float(is_row["夏普"]),
                "全期策略%": float(full["累计策略%"]),
                "全期持有%": float(full["累计平权%"]),
                "全期超额%": float(full["累计超额%"]),
                "全期回撤%": float(full["策略回撤%"]),
                "全期夏普": float(full["夏普"]),
                "闭环": int(full["闭环"]),
                **oos,
                "2026超额月胜率%": round(
                    float((m2026["超额%"] > 0).mean() * 100) if len(m2026) else 0.0, 1
                ),
                "_cfg_json": json.dumps(cfg, ensure_ascii=False),
            }
        )

    cmp = pd.DataFrame(compare_rows)
    # 排序：先看 2026 超额，再看全期超额（仅展示，不据此改「无前视最优」）
    cmp_view = cmp.sort_values(
        ["2026超额%", "全期超额%", "IS超额%"], ascending=False
    ).reset_index(drop=True)
    cmp_view.drop(columns=["_cfg_json"]).to_csv(
        DIR / "threshold_compare_full_2026.csv", index=False, encoding="utf-8-sig"
    )

    # 按 2026 超额最好的方案展开分月（研究对照；标注为「2026观察最优」非无前视）
    best_2026_name = str(cmp_view.iloc[0]["方案"])
    best_is_name = str(pos.iloc[0]["方案"])
    m_best = monthly_by[best_2026_name]
    m_is = monthly_by[best_is_name]
    m2026_best = m_best[m_best["月份"].astype(str).str.startswith("2026")].copy()
    m2026_is = m_is[m_is["月份"].astype(str).str.startswith("2026")].copy()
    m2026_best.to_csv(DIR / "monthly_2026_best_by_oos.csv", index=False, encoding="utf-8-sig")
    m2026_is.to_csv(DIR / "monthly_2026_is_winner.csv", index=False, encoding="utf-8-sig")
    holdings_by[best_2026_name].to_csv(
        DIR / "holdings_2026_best_by_oos.csv", index=False, encoding="utf-8-sig"
    )

    summary = {
        "区间": f"{d0} → {d1}",
        "说明": "阈值均在2025选参窗生成；2026列为样本外观察，不用于改选",
        "无前视IS最优": best_is_name,
        "2026观察超额最高": best_2026_name,
        "对照表": cmp_view.drop(columns=["_cfg_json"]).to_dict(orient="records"),
        "IS最优_2026": cmp_view[cmp_view["方案"] == best_is_name]
        .drop(columns=["_cfg_json"])
        .iloc[0]
        .to_dict(),
        "OOS观察最优_2026": cmp_view.iloc[0].drop(labels=["_cfg_json"]).to_dict(),
    }
    (DIR / "threshold_compare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 589680 改阈值对照：IS 候选冻结 → 全期 / 2026",
        "",
        "> 研究回测。所有阈值仅用 2025 选参；2026 只作样本外观察，**不据此改选**。",
        "",
        f"- 无前视 IS 最优：`{best_is_name}`",
        f"- 2026 超额观察最高：`{best_2026_name}`（仅对照）",
        "",
        "## 候选对照",
        "",
        cmp_view.drop(columns=["_cfg_json"]).to_markdown(index=False),
        "",
        f"## 2026 分月 · IS 最优（{best_is_name}）",
        "",
        m2026_is.to_markdown(index=False),
        "",
        f"## 2026 分月 · OOS 观察最优（{best_2026_name}）",
        "",
        m2026_best.to_markdown(index=False),
        "",
        f"## 持仓 · OOS 观察最优（{best_2026_name}）",
        "",
        holdings_by[best_2026_name].to_markdown(index=False),
        "",
    ]
    (DIR / "threshold_compare_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n========== 对照 ==========")
    print(cmp_view.drop(columns=["_cfg_json"]).to_string(index=False))
    print(f"\nIS最优: {best_is_name}")
    print(f"2026观察最优: {best_2026_name}")
    print(f"产出: {DIR}")


if __name__ == "__main__":
    main()
