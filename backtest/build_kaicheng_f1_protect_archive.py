#!/usr/bin/env python3
"""凯盛因子1：防护/让利逐段档案（同窗口对齐、含项目成本、默认不累加）。

口径（按研究约定固定）：
1. 时间：上笔卖日收盘 → 本笔卖日收盘为整段窗口。策略过滤空仓，仍与整段持有比较。
2. 价格：持有=窗口收盘涨跌；策略=同窗口权益涨跌（相对持有不动）。
3. 成本：沿用本项目回测费用，已含在权益曲线。
4. 比例：持有跌 20%、策略亏 10% → 20:10；默认不累加总盈亏比。

用法：
  python backtest/build_kaicheng_f1_protect_archive.py
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy import KAICHENG, run_open_break  # noqa: E402
from dataclasses import replace  # noqa: E402

OUT = Path(__file__).resolve().parent / "kaicheng_f1_protect_archive_2020"


def _tz_day_index(s: pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(s)
    if idx.tz is None:
        idx = idx.tz_localize("Asia/Shanghai")
    else:
        idx = idx.tz_convert("Asia/Shanghai")
    return idx.normalize()


def _pair_trips(orders: pd.DataFrame) -> list[tuple[pd.Series, pd.Series]]:
    buys: list[pd.Series] = []
    trips: list[tuple[pd.Series, pd.Series]] = []
    for _, r in orders.iterrows():
        if r["side"] == "buy":
            buys.append(r)
        elif r["side"] == "sell" and buys:
            trips.append((buys.pop(0), r))
    return trips


def _ratio(hold_pct: float, strat_pct: float) -> tuple[str, str]:
    if hold_pct < 0:
        kind = "下跌"
        h = abs(hold_pct)
        if strat_pct < 0:
            ratio = f"{h:.1f}:{abs(strat_pct):.1f}"
        elif strat_pct > 0:
            ratio = f"{h:.1f}:0(策略反赚{strat_pct:.1f})"
        else:
            ratio = f"{h:.1f}:0"
        return kind, ratio
    if hold_pct > 0:
        kind = "上涨"
        h = abs(hold_pct)
        if strat_pct > 0:
            ratio = f"{h:.1f}:{abs(strat_pct):.1f}"
        elif strat_pct < 0:
            ratio = f"{h:.1f}:0(策略反亏{strat_pct:.1f})"
        else:
            ratio = f"{h:.1f}:0"
        return kind, ratio
    return "平盘", "0:0"


def build(force_daily_refresh: bool = False) -> Path:
    cfg = replace(
        KAICHENG,
        start_date="20200101",
        end_date=datetime.now().strftime("%Y%m%d"),
    )
    result, daily = run_open_break(
        cfg,
        show_report=False,
        verbose=False,
        force_daily_refresh=force_daily_refresh,
    )

    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["day"] = _tz_day_index(d["date"])
    close_map = d.set_index("day")["close"].astype(float).sort_index()

    eq = result.equity_curve.sort_index()
    eq.index = _tz_day_index(eq.index)
    eq_day = eq.groupby(level=0).last()

    orders = result.orders_df.copy()
    orders = orders[orders["status"] == "filled"].copy()
    orders["ts"] = pd.to_datetime(orders["updated_at"])
    orders["day"] = _tz_day_index(orders["ts"])
    orders = orders.sort_values("ts")
    trips = _pair_trips(orders)

    rows: list[dict] = []
    for i in range(1, len(trips)):
        b, s = trips[i]
        t0 = trips[i - 1][1]["day"]
        t1 = s["day"]
        c0 = float(close_map.asof(t0))
        c1 = float(close_map.asof(t1))
        e0 = float(eq_day.asof(t0))
        e1 = float(eq_day.asof(t1))
        if c0 <= 0 or e0 <= 0:
            continue

        hold_pct = (c1 / c0 - 1.0) * 100.0
        strat_pct = (e1 / e0 - 1.0) * 100.0
        kind, ratio = _ratio(hold_pct, strat_pct)

        segs = []
        for bb, ss in trips:
            if t0 < ss["day"] <= t1:
                segs.append(
                    {
                        "买日": bb["day"].strftime("%Y-%m-%d"),
                        "卖日": ss["day"].strftime("%Y-%m-%d"),
                        "买价": round(float(bb["avg_price"]), 4),
                        "卖价": round(float(ss["avg_price"]), 4),
                        "单笔%": round(
                            (float(ss["avg_price"]) / float(bb["avg_price"]) - 1) * 100, 2
                        ),
                    }
                )

        rows.append(
            {
                "段序": i,
                "类型": kind,
                "区间起": t0.strftime("%Y-%m-%d"),
                "区间止": t1.strftime("%Y-%m-%d"),
                "持有%_收盘": round(hold_pct, 2),
                "策略%_同窗口权益含成本": round(strat_pct, 2),
                "比例_持有对策略": ratio,
                "本段策略笔数": len(segs),
                "本段明细": json.dumps(segs, ensure_ascii=False),
                "起点收盘": round(c0, 4),
                "终点收盘": round(c1, 4),
                "起点权益": round(e0, 2),
                "终点权益": round(e1, 2),
                "年份": int(t1.year),
            }
        )

    arch = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    arch.to_csv(OUT / "segments.csv", index=False)
    arch[arch["类型"] == "下跌"].to_csv(OUT / "down_segments.csv", index=False)
    arch[arch["类型"] == "上涨"].to_csv(OUT / "up_segments.csv", index=False)

    meta = {
        "标的": "凯盛科技 sh600552",
        "策略": "因子1 开盘±2.5%",
        "样本": f"{arch['区间起'].iloc[0]} → {arch['区间止'].iloc[-1]}",
        "段数": int(len(arch)),
        "下跌段": int((arch["类型"] == "下跌").sum()),
        "上涨段": int((arch["类型"] == "上涨").sum()),
        "口径": {
            "窗口": "上笔卖日收盘 → 本笔卖日收盘（整段时间；策略过滤空仓仍与整段持有比）",
            "持有": "窗口收盘价涨跌幅（持有不动）",
            "策略": "同窗口权益涨跌幅；项目费用已含",
            "比例": "持有跌20、策略亏10 → 20:10；本版不累加",
        },
        "成本假设": {
            "commission_rate": cfg.commission_rate,
            "misc_fee_rate": cfg.misc_fee_rate,
            "stamp_tax_rate": cfg.stamp_tax_rate,
            "slippage_value": cfg.slippage_value,
        },
    }
    (OUT / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md: list[str] = [
        "# 凯盛科技 · 因子1 防护/让利逐段档案",
        "",
        "## 口径（已固定）",
        "",
        "1. **时间**：上笔卖日收盘 → 本笔卖日收盘。策略过滤空仓，仍与整段持有比较。",
        "2. **价格**：持有=窗口收盘；策略=同窗口权益（相对持有不动）。",
        "3. **成本**：项目回测费用已含在策略权益。",
        "4. **先不累加**：只保留逐段 `持有:策略` 比例。",
        "",
        f"- 样本：`{meta['样本']}`",
        f"- 段数：{meta['段数']}（下跌 {meta['下跌段']} / 上涨 {meta['上涨段']}）",
        (
            f"- 费用：佣金 {cfg.commission_rate}，杂费 {cfg.misc_fee_rate}，"
            f"印花税 {cfg.stamp_tax_rate}，滑点 {cfg.slippage_value}"
        ),
        "",
        "比例读法：下跌 20%、策略亏 10% → **20:10（2:1）**。",
        "",
        "---",
        "",
        "## 下跌段（持有为负）",
        "",
        "| # | 区间 | 持有% | 策略% | 比例 | 笔数 |",
        "|---:|---|---:|---:|---|---:|",
    ]
    down = arch[arch["类型"] == "下跌"].sort_values("持有%_收盘")
    for _, r in down.iterrows():
        md.append(
            f"| {r['段序']} | {r['区间起']}→{r['区间止']} | {r['持有%_收盘']:.2f} | "
            f"{r['策略%_同窗口权益含成本']:.2f} | {r['比例_持有对策略']} | {r['本段策略笔数']} |"
        )

    md += [
        "",
        "## 上涨段（持有为正）",
        "",
        "| # | 区间 | 持有% | 策略% | 比例 | 笔数 |",
        "|---:|---|---:|---:|---|---:|",
    ]
    up = arch[arch["类型"] == "上涨"].sort_values("持有%_收盘", ascending=False)
    for _, r in up.iterrows():
        md.append(
            f"| {r['段序']} | {r['区间起']}→{r['区间止']} | {r['持有%_收盘']:.2f} | "
            f"{r['策略%_同窗口权益含成本']:.2f} | {r['比例_持有对策略']} | {r['本段策略笔数']} |"
        )

    md += [
        "",
        "## 文件",
        "",
        "- `segments.csv` / `down_segments.csv` / `up_segments.csv`",
        "- `meta.json`",
        "",
        "本档案仅供研究参考，不构成投资建议。",
    ]
    (OUT / "ARCHIVE.md").write_text("\n".join(md), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    path = build(force_daily_refresh="--refresh" in sys.argv)
    print(f"已生成: {path}")
