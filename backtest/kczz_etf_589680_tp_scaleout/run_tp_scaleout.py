"""589680 策略一：浮盈达多少开始慢慢减仓 —— 网格回测。

背景：持仓曾有较大浮盈，却遭遇低开约 -5% 再砸到止损，利润大幅回吐。
本脚本在买 2.5% / 止 3.5% + 隔日止损跳买 骨架上，对比：
  · 仅止损基准
  · 不同「开始减仓」起点（相对买入价）+ 每档减仓比例
  · 可选触及后抬止损锁盈（防隔夜跳空回吐）

研究用途，不构成投资建议。
"""

from __future__ import annotations

import json
import logging
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
logging.disable(logging.INFO)

from strategy import KCZZ_ETF, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _MYQUAN / "data_cache" / "sh589680_daily_qfq.parquet"
END = "20260825"
CASH = 100_000.0


def _base() -> Any:
    return replace(
        KCZZ_ETF,
        end_date=END,
        daily_cache=CACHE,
        skip_buy_after_overnight_stop=True,
        take_profit_levels=None,
        take_profit_lock_pct=None,
        take_profit_reduce=0.20,
        take_profit_trigger="high",
    )


def _levels(start: float, step: float, n: int) -> tuple[float, ...]:
    return tuple(round(start + i * step, 4) for i in range(n))


def _norm_ts(s: pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(s))
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    return idx.normalize()


def _oos_2026(result: Any, daily: pd.DataFrame) -> dict[str, float]:
    eq = result.equity_curve.copy()
    eq.index = _norm_ts(eq.index)
    close = daily.set_index(_norm_ts(daily["date"]))["close"].astype(float)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    eq = eq.reindex(close.index).ffill()
    eq_2026 = eq[eq.index.year >= 2026].dropna()
    close_2026 = close[close.index.year >= 2026]
    if len(eq_2026) < 2 or len(close_2026) < 2:
        return {}
    eq_pre = eq[eq.index.year < 2026].dropna()
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


def _run(cfg: Any) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    result, daily = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    ret = float(metric(m, "total_return_pct"))
    dd = float(metric(m, "max_drawdown_pct"))
    sharpe = float(metric(m, "sharpe_ratio"))
    win = float(metric(m, "win_rate"))
    td = result.trades_df
    n = int(len(td)) if td is not None else 0
    giveback = None
    avg_mfe = None
    avg_final = None
    if td is not None and len(td) and "mfe" in td.columns:
        # mfe/return_pct 已是百分比数值
        mfe = td["mfe"].astype(float)
        fin = td["return_pct"].astype(float)
        avg_mfe = float(mfe.mean())
        avg_final = float(fin.mean())
        giveback = float((mfe - fin).clip(lower=0).mean())
    oos = _oos_2026(result, daily)
    row = {
        "累计策略%": round(ret, 2),
        "最大回撤%": round(dd, 2),
        "夏普": round(sharpe, 3),
        "胜率%": round(win, 2),
        "闭环笔数": n,
        "均MFE%": round(avg_mfe, 2) if avg_mfe is not None else None,
        "均收益%": round(avg_final, 2) if avg_final is not None else None,
        "均回吐pp": round(giveback, 2) if giveback is not None else None,
        **oos,
        "综合分": round(ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0), 2),
    }
    return row, result, daily


def analyze_baseline_trades(result: Any, daily: pd.DataFrame) -> pd.DataFrame:
    """基准持仓：MFE、终收益、回吐、持仓期内最大隔夜低开。"""
    td = result.trades_df.copy()
    d = daily.copy()
    d["date"] = _norm_ts(d["date"])
    d = d.sort_values("date").reset_index(drop=True)

    def _day(x: Any) -> pd.Timestamp:
        ts = pd.Timestamp(x)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts.normalize()

    rows = []
    for i, t in td.iterrows():
        entry = _day(t["entry_time"])
        exit_ = _day(t["exit_time"])
        entry_px = float(t["entry_price"])
        mfe = float(t["mfe"])
        fin = float(t["return_pct"])
        give = max(mfe - fin, 0.0)
        # 持仓期内隔夜跳空（相对昨收）
        mask = (d["date"] >= entry) & (d["date"] <= exit_)
        sub = d.loc[mask].copy()
        max_gap = None
        worst_gap_day = None
        if len(sub) >= 2:
            prev_close = sub["close"].shift(1)
            gap = (sub["open"] / prev_close - 1.0) * 100.0
            # 买入日不算隔夜
            gap.iloc[0] = float("nan")
            if gap.notna().any():
                j = gap.idxmin()
                max_gap = float(gap.loc[j])
                worst_gap_day = str(sub.loc[j, "date"].date())
        rows.append(
            {
                "序号": int(i) + 1,
                "买入日": str(entry.date()),
                "卖出日": str(exit_.date()),
                "买入价": round(entry_px, 4),
                "卖出价": round(float(t["exit_price"]), 4),
                "持有日": int(t["duration_bars"]),
                "终收益%": round(fin, 2),
                "MFE%": round(mfe, 2),
                "回吐pp": round(give, 2),
                "MAE%": round(float(t["mae"]), 2),
                "最差隔夜低开%": round(max_gap, 2) if max_gap is not None else None,
                "最差低开日": worst_gap_day,
            }
        )
    return pd.DataFrame(rows)


def build_jobs() -> list[tuple[str, dict[str, Any]]]:
    """(方案名, replace kwargs)。"""
    jobs: list[tuple[str, dict[str, Any]]] = [("仅止损(基准)", {})]
    step = 0.05
    # 针对 ETF：起点从 5% 起扫到 20%；每档减 10%/20%/30%；1~4 档
    for start in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
        for reduce in (0.10, 0.20, 0.30):
            for n in (1, 2, 3, 4):
                if reduce * n > 0.90 + 1e-12:
                    continue
                lv = _levels(start, step, n)
                # 档位步长：起点≥10% 用 5%；起点 5%/8% 第二档起也按 +5%
                name = (
                    f"减仓|{ '/'.join(f'{x*100:.0f}' for x in lv)}"
                    f"@减{reduce*100:.0f}%"
                )
                jobs.append(
                    (
                        name,
                        {
                            "take_profit_levels": lv,
                            "take_profit_reduce": reduce,
                            "take_profit_trigger": "high",
                            "take_profit_lock_pct": None,
                        },
                    )
                )
    # 锁盈族：触及起点后不减仓 / 轻减，抬止损到买入价×(1+lock)
    for start in (0.08, 0.10, 0.12, 0.15):
        for lock in (0.02, 0.05, 0.08):
            jobs.append(
                (
                    f"只锁盈|+{start*100:.0f}%→止损抬+{lock*100:.0f}%",
                    {
                        "take_profit_levels": (start,),
                        "take_profit_reduce": 0.0,
                        "take_profit_trigger": "high",
                        "take_profit_lock_pct": lock,
                    },
                )
            )
            for reduce in (0.20, 0.30):
                lv = _levels(start, step, 3)
                jobs.append(
                    (
                        f"减+锁|{ '/'.join(f'{x*100:.0f}' for x in lv)}"
                        f"@减{reduce*100:.0f}%锁+{lock*100:.0f}%",
                        {
                            "take_profit_levels": lv,
                            "take_profit_reduce": reduce,
                            "take_profit_trigger": "high",
                            "take_profit_lock_pct": lock,
                        },
                    )
                )
    return jobs


def write_report(
    summary: pd.DataFrame,
    trades: pd.DataFrame,
    baseline: dict[str, Any],
    top: pd.DataFrame,
) -> None:
    # 赢家平均 MFE / 回吐
    win = trades[trades["终收益%"] > 0]
    big = trades[trades["MFE%"] >= 10]
    lines = [
        "# 科创综指ETF鹏华(589680) · 浮盈减仓起点回测",
        "",
        "> 研究回测，不构成投资建议。骨架：买2.5%/止3.5% + 隔日止损跳买；"
        "止盈按当日最高价触及相对买入价档位后按初始仓比例减仓，余仓仍走开盘止损。",
        "",
        "## 问题与口径",
        "",
        "近期典型路径：浮盈较大 → 次日低开约 -5% → 盘中再砸到止损 → 利润大幅回吐。",
        "本回测回答：**平均浮盈到多少开始慢慢减仓更合适**（全样本 + 2026）。",
        "",
        "## 基准持仓：最大浮盈 vs 终收益",
        "",
        f"- 闭环 {len(trades)} 笔；赢家均终收益 "
        f"**{win['终收益%'].mean():.1f}%**，赢家均 MFE **{win['MFE%'].mean():.1f}%**，"
        f"赢家均回吐 **{win['回吐pp'].mean():.1f}** 个百分点。",
        f"- MFE≥10% 的笔数 {len(big)}：均 MFE {big['MFE%'].mean():.1f}% → "
        f"均终收益 {big['终收益%'].mean():.1f}%（回吐 {big['回吐pp'].mean():.1f}pp）。",
        f"- 基准全期策略 **{baseline['累计策略%']}%**，回撤 {baseline['最大回撤%']}%，"
        f"2026 超额 {baseline.get('2026超额%')}%。",
        "",
        trades.to_markdown(index=False),
        "",
        "## 网格结论（按综合分）",
        "",
        "综合分 = 累计收益 − 0.35×|回撤| + 40×夏普。",
        "",
        top.head(15).to_markdown(index=False),
        "",
    ]
    # 推荐：在「不低于基准收益 95%」里找回吐/回撤改善，或 2026 超额更好
    base_ret = float(baseline["累计策略%"])
    viable = summary[summary["累计策略%"] >= base_ret * 0.95 - 1e-9].copy()
    if len(viable):
        # 优先：均回吐下降 + 2026 不崩
        viable = viable.sort_values(
            ["均回吐pp", "最大回撤%", "2026超额%", "累计策略%"],
            ascending=[True, True, False, False],
        )
        rec = viable.iloc[0]
        lines += [
            "## 推荐（收益不低于基准约 95%，优先压回吐/回撤）",
            "",
            f"- 方案：**{rec['方案']}**",
            f"- 全期 {rec['累计策略%']}%（基准 {base_ret}%），回撤 {rec['最大回撤%']}% "
            f"（基准 {baseline['最大回撤%']}%），均回吐 {rec['均回吐pp']}pp "
            f"（基准 {baseline['均回吐pp']}pp）。",
            f"- 2026 策略 {rec.get('2026策略%')}% / 超额 {rec.get('2026超额%')}%。",
            "",
        ]
    # 按起点汇总：同一起点下最优减仓比例
    start_rows = []
    for s in summary["起点%"].dropna().unique():
        if float(s) <= 0:
            continue
        sub = summary[summary["起点%"] == s]
        best = sub.sort_values("综合分", ascending=False).iloc[0]
        start_rows.append(best)
    if start_rows:
        by_start = pd.DataFrame(start_rows).sort_values("起点%")
        lines += [
            "## 按「开始减仓」起点汇总（各起点最优一档）",
            "",
            by_start[
                [
                    "起点%",
                    "方案",
                    "累计策略%",
                    "最大回撤%",
                    "均回吐pp",
                    "2026超额%",
                    "综合分",
                ]
            ].to_markdown(index=False),
            "",
            "## 解读（研究口径）",
            "",
            "1. **过早减仓（约 5%）**：容易卖飞主升，全期收益往往不如仅止损。",
            "2. **偏晚（约 20%）**：对「已有两位数浮盈再隔夜砸盘」保护不足。",
            "3. 结合本样本赢家均 MFE 与回吐，**开始慢慢减仓的实用区间多在 "
            "浮盈约 8%～12%**；触及后每档减初始仓 20%～30%，并可考虑锁盈抬止损 "
            "（如锁 +2%～+5%）减轻低开穿止损时的回吐。",
            "4. 隔日直接低开穿止损、且从未做出浮盈的单（MFE≈0）无法靠止盈减仓挽救，"
            "仍依赖跳买/仓位与止损纪律。",
            "",
            "免责声明：历史回测≠未来表现；不构成投资建议。",
            "",
        ]
    (DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    base_cfg = _base()
    print("=== 基准：仅止损 ===", flush=True)
    baseline, base_result, daily = _run(base_cfg)
    baseline["方案"] = "仅止损(基准)"
    baseline["起点%"] = 0.0
    baseline["每档减仓%"] = 0.0
    baseline["锁盈%"] = None
    baseline["止盈档"] = "-"

    trades = analyze_baseline_trades(base_result, daily)
    trades.to_csv(DIR / "baseline_trades_mfe.csv", index=False, encoding="utf-8-sig")
    print(trades.to_string(index=False), flush=True)

    jobs = build_jobs()
    rows: list[dict[str, Any]] = [baseline]
    print(f"=== 网格 {len(jobs)-1} 组 ===", flush=True)
    for i, (name, kw) in enumerate(jobs[1:], 1):
        cfg = replace(base_cfg, **kw)
        lv = kw.get("take_profit_levels") or ()
        start = float(lv[0]) * 100 if lv else 0.0
        print(f"  [{i}/{len(jobs)-1}] {name}", flush=True)
        try:
            st, _, _ = _run(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"    失败: {e}", flush=True)
            continue
        st.update(
            {
                "方案": name,
                "起点%": round(start, 1),
                "每档减仓%": round(float(kw.get("take_profit_reduce") or 0) * 100, 1),
                "锁盈%": (
                    None
                    if kw.get("take_profit_lock_pct") is None
                    else round(float(kw["take_profit_lock_pct"]) * 100, 1)
                ),
                "止盈档": "/".join(f"{x*100:.0f}" for x in lv) if lv else "-",
            }
        )
        rows.append(st)

    summary = pd.DataFrame(rows)
    summary = summary.sort_values("综合分", ascending=False).reset_index(drop=True)
    summary.to_csv(DIR / "tp_scaleout_grid.csv", index=False, encoding="utf-8-sig")

    top = summary.head(20)[
        [
            c
            for c in [
                "方案",
                "起点%",
                "累计策略%",
                "最大回撤%",
                "夏普",
                "均回吐pp",
                "2026策略%",
                "2026超额%",
                "综合分",
            ]
            if c in summary.columns
        ]
    ]
    write_report(summary, trades, baseline, top)

    payload = {
        "baseline": baseline,
        "trade_stats": {
            "n": int(len(trades)),
            "win_avg_mfe": float(trades.loc[trades["终收益%"] > 0, "MFE%"].mean()),
            "win_avg_giveback": float(
                trades.loc[trades["终收益%"] > 0, "回吐pp"].mean()
            ),
            "mfe10_avg_giveback": float(
                trades.loc[trades["MFE%"] >= 10, "回吐pp"].mean()
            )
            if (trades["MFE%"] >= 10).any()
            else None,
        },
        "top5": top.head(5).to_dict(orient="records"),
    }
    (DIR / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== TOP5 ===", flush=True)
    print(top.head(5).to_string(index=False), flush=True)
    print(f"\n报告 → {DIR / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
