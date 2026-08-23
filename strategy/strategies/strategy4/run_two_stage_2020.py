"""两段选股 / 近高等权持有：2020 至今。

  python strategy/strategies/strategy4/run_two_stage_2020.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.config import KAICHENG, TIANTONG  # noqa: E402
from strategy.s1_price_select import (  # noqa: E402
    weekly_mom_gate_from_close,
    weekly_two_stage_gate,
)
from strategy.strategies.strategy4.portfolio import (  # noqa: E402
    active_nav,
    load_daily,
    run_one,
    window_metrics,
)
from strategy.strategies.strategy4.run_mom_universe import (  # noqa: E402
    _year_from_prior,
    mom_bh_nav,
)
from strategy.strategies.strategy4.run_two_stage import (  # noqa: E402
    STAGE1_K,
    STAGE2_K,
    _meta,
    _selected,
    load_combined_panel,
)

OUT = Path(__file__).resolve().parent / "two_stage" / "from_2020"
REPORT_FROM = "2020-01-02"
S1_START = "20200102"
S1_SLICE = "2019-01-01"


def _year_table(navs: dict[str, pd.Series], years: range) -> pd.DataFrame:
    rows = []
    for year in years:
        row = {"year": year}
        for name, nav in navs.items():
            sl = nav[nav.index >= pd.Timestamp(REPORT_FROM)]
            row[name] = round(_year_from_prior(sl, year), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _monthly(nav: pd.Series) -> dict[str, float]:
    sl = nav[nav.index >= pd.Timestamp(REPORT_FROM)].dropna()
    if sl.empty:
        return {}
    sl = sl / float(sl.iloc[0])
    return {
        m.strftime("%Y-%m"): round(float(v), 4) for m, v in sl.resample("ME").last().items()
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, high = load_combined_panel()
    print(f"宇宙 {close.shape[1]} 只，区间 {REPORT_FROM} 起")

    variants = {
        "mom_top5": weekly_mom_gate_from_close(close, mom_n=20, k=5),
        "mom20_near5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="near_high"
        ),
        "mom20_persist5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="persist"
        ),
        "mom20_noclimax5": weekly_two_stage_gate(
            close, high, stage1_k=STAGE1_K, stage2_k=STAGE2_K, stage2="not_climax"
        ),
    }
    labels = {
        "mom_top5": "一段动量 Top5 等权持有",
        "mom20_near5": "近高 Top5 等权持有",
        "mom20_persist5": "上涨日占比 Top5 等权持有",
        "mom20_noclimax5": "未拉直 Top5 等权持有",
        "univ_ew": "宇宙 1249 只等权",
        "s1_near5": "策略1 · 近高名单",
        "s1_pinned2": "策略1 · 凯盛+天通",
    }

    books: dict[str, pd.Series] = {}
    rows = []
    for vid, gate in variants.items():
        bh = mom_bh_nav(close, gate)
        books[vid] = bh
        m = window_metrics(bh, start=REPORT_FROM)
        m_is = window_metrics(bh, start=REPORT_FROM, end="2023-12-31")
        m_oos = window_metrics(bh, start="2024-01-02")
        sl = bh[bh.index >= pd.Timestamp(REPORT_FROM)]
        n_sel = len(_selected(gate, REPORT_FROM))
        rows.append(
            {
                "id": vid,
                "label": labels[vid],
                "ret": round(m["ret_pct"], 2),
                "ann": round(m["ann_pct"], 2),
                "sharpe": round(m["sharpe"], 3),
                "mdd": round(m["mdd_pct"], 2),
                "is_2020_2023": round(m_is["ret_pct"], 2),
                "oos_2024": round(m_oos["ret_pct"], 2),
                "n_names": n_sel,
            }
        )
        print(f"{vid} BH {m['ret_pct']:.1f}% 夏普 {m['sharpe']:.2f} 回撤 {m['mdd_pct']:.1f}% 名单 {n_sel}")

    ew = close.pct_change().mean(axis=1)
    ew_nav = (1.0 + ew).cumprod()
    if len(ew_nav):
        ew_nav.iloc[0] = 1.0
    books["univ_ew"] = ew_nav
    m = window_metrics(ew_nav, start=REPORT_FROM)
    rows.append(
        {
            "id": "univ_ew",
            "label": labels["univ_ew"],
            "ret": round(m["ret_pct"], 2),
            "ann": round(m["ann_pct"], 2),
            "sharpe": round(m["sharpe"], 3),
            "mdd": round(m["mdd_pct"], 2),
            "is_2020_2023": round(
                window_metrics(ew_nav, start=REPORT_FROM, end="2023-12-31")["ret_pct"], 2
            ),
            "oos_2024": round(window_metrics(ew_nav, start="2024-01-02")["ret_pct"], 2),
            "n_names": int(close.shape[1]),
        }
    )

    near_gate = variants["mom20_near5"]
    need = _selected(near_gate, REPORT_FROM)
    print(f"近高 2020 起并集 {len(need)}，跑策略1")
    s1 = {}
    for i, sym in enumerate(sorted(need), 1):
        daily = load_daily(sym)
        if daily is None:
            continue
        if i % 80 == 0 or i == 1:
            print(f"  {i}/{len(need)} {sym}")
        s1[sym] = run_one(
            _meta(sym),
            daily,
            s9=False,
            allowed=near_gate.get(sym),
            start_date=S1_START,
            slice_from=S1_SLICE,
        )
    if s1:
        nav_s1 = active_nav({s: r["nav"] for s, r in s1.items()}, near_gate)
        books["s1_near5"] = nav_s1
        m = window_metrics(nav_s1, start=REPORT_FROM)
        rows.append(
            {
                "id": "s1_near5",
                "label": labels["s1_near5"],
                "ret": round(m["ret_pct"], 2),
                "ann": round(m["ann_pct"], 2),
                "sharpe": round(m["sharpe"], 3),
                "mdd": round(m["mdd_pct"], 2),
                "is_2020_2023": round(
                    window_metrics(nav_s1, start=REPORT_FROM, end="2023-12-31")["ret_pct"],
                    2,
                ),
                "oos_2024": round(window_metrics(nav_s1, start="2024-01-02")["ret_pct"], 2),
                "n_names": len(s1),
            }
        )
        print(f"s1_near5 {m['ret_pct']:.1f}%")

    p2 = {}
    for cfg in (KAICHENG, TIANTONG):
        daily = load_daily(cfg.symbol)
        if daily is None:
            continue
        p2[cfg.symbol] = run_one(
            {
                "code": cfg.em_symbol,
                "symbol": cfg.symbol,
                "name": cfg.symbol_name,
                "entry_pct": cfg.resolved_entry_pct(),
                "stop_pct": cfg.resolved_stop_pct(),
                "tick": cfg.tick,
                "t0": False,
                "limit_down_pct": cfg.limit_down_pct,
                "stamp_tax_rate": cfg.stamp_tax_rate,
            },
            daily,
            s9=False,
            allowed=None,
            start_date=S1_START,
            slice_from=S1_SLICE,
        )
    nav_p2 = active_nav({s: r["nav"] for s, r in p2.items()}, None)
    books["s1_pinned2"] = nav_p2
    m = window_metrics(nav_p2, start=REPORT_FROM)
    rows.append(
        {
            "id": "s1_pinned2",
            "label": labels["s1_pinned2"],
            "ret": round(m["ret_pct"], 2),
            "ann": round(m["ann_pct"], 2),
            "sharpe": round(m["sharpe"], 3),
            "mdd": round(m["mdd_pct"], 2),
            "is_2020_2023": round(
                window_metrics(nav_p2, start=REPORT_FROM, end="2023-12-31")["ret_pct"], 2
            ),
            "oos_2024": round(window_metrics(nav_p2, start="2024-01-02")["ret_pct"], 2),
            "n_names": len(p2),
        }
    )
    print(f"s1_pinned2 {m['ret_pct']:.1f}%")

    table = pd.DataFrame(rows)
    years = _year_table(
        {k: books[k] for k in books},
        range(2020, 2027),
    )
    monthly = {k: _monthly(v) for k, v in books.items()}
    table.to_csv(OUT / "summary.csv", index=False)
    years.to_csv(OUT / "yearly.csv", index=False)
    (OUT / "nav_monthly.json").write_text(
        json.dumps(monthly, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# 两段选股 2020 至今",
                "",
                "研究回测，不构成投资建议。不用 26 只契合池。",
                "",
                f"- 宇宙：沪深300+中证500+中证1000 共 {close.shape[1]} 只（当前成分，有幸存者偏差）",
                f"- 区间：{REPORT_FROM} 起；样本内 2020–2023，样本外 2024 起",
                "- 近高：周频动量 Top20 → 贴近 20 日高点 Top5，下一周等权持有（无费用）",
                "- 策略1：仅止损，统一 ±2.5%（置顶两票用各自阈值）",
                "",
                table.to_markdown(index=False),
                "",
                "## 分年（%）",
                "",
                years.to_markdown(index=False),
                "",
                "本报告仅供研究参考，不构成投资建议。",
            ]
        ),
        encoding="utf-8",
    )
    print(table.to_string(index=False))
    print(years.to_string(index=False))


if __name__ == "__main__":
    main()
