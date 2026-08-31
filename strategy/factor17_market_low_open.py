"""因子17：大盘低开 — 指数 gap / 收盘 / 次日表现 + 全市场实体阳比例。

口径：
  · 大盘低开：上证指数开盘相对昨收 gap% < 0
  · **实体阳线**（收阳家数）：close > open（相对开盘收红），与相对昨收涨跌无关
    例：昨收 100，开盘 95（-5%），收盘 96（相对昨收 -4%）→ 仍计为阳线
  · 按低开幅度分桶统计：当日收盘、次日开盘/收盘、简易买卖情景胜率

研究用途，不构成投资建议。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.data import fetch_daily, fetch_index_daily

FACTOR_ID = "factor17"
FACTOR_NAME = "因子17·大盘低开"

DEFAULT_INDEX = "sh000001"
DEFAULT_START = "20150101"

OUT_DIR = Path(__file__).resolve().parents[1] / "backtest" / "factor17_market_low_open"
BREADTH_CACHE = OUT_DIR / "yang_breadth_zz1000.parquet"

# (标签, 下界, 上界)  gap% 左闭右开，仅 gap < 0
GAP_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("微跌(-0.5~0%)", -0.5, 0.0),
    ("低开(-1~-0.5%)", -1.0, -0.5),
    ("低开(-2~-1%)", -2.0, -1.0),
    ("低开(-3~-2%)", -3.0, -2.0),
    ("大幅(-5~-3%)", -5.0, -3.0),
    ("急跌(<-5%)", -99.0, -5.0),
)

DEFAULT_PARAMS: dict[str, Any] = {
    "index_symbol": DEFAULT_INDEX,
    "start": DEFAULT_START,
    "low_open_only": True,
    "yang_definition": "close_gt_open",
    "breadth_universe": "zz1000",
}


def factor17_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
  因子17 · 大盘低开（指数 + 实体阳家数比例）
================================================================================
指数：{p.get('index_symbol', DEFAULT_INDEX)}（默认上证指数）
低开：开盘相对昨收 gap% < 0
实体阳：close > open（相对开盘收红；可与相对昨收仍下跌并存）
广度池：中证1000成分（可缓存 {BREADTH_CACHE.name}）
分桶：{', '.join(b[0] for b in GAP_BUCKETS)}
输出：各桶样本数、指数当日/次日收益、实体阳比例、低开日买卖情景统计
研究用途，不构成投资建议。
================================================================================
""".strip()


def is_intraday_yang(open_px: float, close_px: float) -> bool:
    """实体阳线：收盘 > 开盘（用户口径）。"""
    return float(close_px) > float(open_px)


def assign_gap_bucket(gap_pct: float) -> str | None:
    g = float(gap_pct)
    if g >= 0:
        return None
    for label, lo, hi in GAP_BUCKETS:
        if lo <= g < hi:
            return label
    return GAP_BUCKETS[-1][0]


def prepare_index_features(index_df: pd.DataFrame) -> pd.DataFrame:
    """为指数日线附加 gap、日内、次日字段。"""
    d = index_df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.sort_values("date").reset_index(drop=True)
    d["prev_close"] = d["close"].shift(1)
    d = d.dropna(subset=["prev_close"])
    d["gap_pct"] = (d["open"] / d["prev_close"] - 1.0) * 100.0
    d["intraday_pct"] = (d["close"] / d["open"] - 1.0) * 100.0
    d["day_ret_pct"] = (d["close"] / d["prev_close"] - 1.0) * 100.0
    d["intraday_yang"] = d["close"] > d["open"]
    d["close_up_vs_prev"] = d["close"] > d["prev_close"]

    d["next_open"] = d["open"].shift(-1)
    d["next_close"] = d["close"].shift(-1)
    d["next_gap_vs_today_close_pct"] = (d["next_open"] / d["close"] - 1.0) * 100.0
    d["next_intraday_pct"] = (d["next_close"] / d["next_open"] - 1.0) * 100.0
    d["next_day_total_pct"] = (d["next_close"] / d["close"] - 1.0) * 100.0
    d["next_open_vs_prev_pct"] = (d["next_open"] / d["prev_close"] - 1.0) * 100.0

    # 低开日买卖情景（百分数收益）
    d["ret_buy_open_sell_close"] = d["intraday_pct"]
    d["ret_buy_close_sell_next_open"] = d["next_gap_vs_today_close_pct"]
    d["ret_buy_close_sell_next_close"] = d["next_day_total_pct"]
    d["ret_buy_open_sell_next_close"] = (d["next_close"] / d["open"] - 1.0) * 100.0

    d["gap_bucket"] = d["gap_pct"].map(assign_gap_bucket)
    return d


def _agg_row(g: pd.DataFrame) -> dict[str, Any]:
    def _mean(col: str) -> float | None:
        if col not in g.columns:
            return None
        s = pd.to_numeric(g[col], errors="coerce").dropna()
        return round(float(s.mean()), 3) if len(s) else None

    def _win(col: str) -> float | None:
        if col not in g.columns:
            return None
        s = pd.to_numeric(g[col], errors="coerce").dropna()
        return round(float((s > 0).mean() * 100.0), 1) if len(s) else None

    out: dict[str, Any] = {
        "n_days": int(len(g)),
        "idx_gap_pct_mean": _mean("gap_pct"),
        "idx_intraday_pct_mean": _mean("intraday_pct"),
        "idx_day_ret_mean": _mean("day_ret_pct"),
        "idx_intraday_yang_pct": round(float(g["intraday_yang"].mean() * 100), 1)
        if "intraday_yang" in g.columns and len(g)
        else None,
        "idx_next_open_vs_close_mean": _mean("next_gap_vs_today_close_pct"),
        "idx_next_intraday_mean": _mean("next_intraday_pct"),
        "idx_next_total_mean": _mean("next_day_total_pct"),
        "stock_yang_ratio_mean": _mean("yang_ratio"),
        "ret_open_close_win_pct": _win("ret_buy_open_sell_close"),
        "ret_open_close_mean": _mean("ret_buy_open_sell_close"),
        "ret_close_next_open_win_pct": _win("ret_buy_close_sell_next_open"),
        "ret_close_next_open_mean": _mean("ret_buy_close_sell_next_open"),
        "ret_close_next_close_win_pct": _win("ret_buy_close_sell_next_close"),
        "ret_close_next_close_mean": _mean("ret_buy_close_sell_next_close"),
        "ret_open_next_close_win_pct": _win("ret_buy_open_sell_next_close"),
        "ret_open_next_close_mean": _mean("ret_buy_open_sell_next_close"),
    }
    return out


def summarize_by_gap_bucket(
    feat: pd.DataFrame,
    *,
    low_open_only: bool = True,
) -> pd.DataFrame:
    d = feat.copy()
    if low_open_only:
        d = d[d["gap_pct"] < 0].copy()
    d = d.dropna(subset=["gap_bucket"])
    rows: list[dict[str, Any]] = []
    for label, _, _ in GAP_BUCKETS:
        g = d[d["gap_bucket"] == label]
        if g.empty:
            continue
        rows.append({"bucket": label, **_agg_row(g)})
    return pd.DataFrame(rows)


def build_yang_breadth_daily(
    *,
    start: str,
    end: str,
    max_stocks: int | None = None,
    workers: int = 8,
    cache_path: Path = BREADTH_CACHE,
    force: bool = False,
) -> pd.DataFrame:
    """中证1000成分：按日统计实体阳家数比例（close>open）。"""
    if cache_path.is_file() and not force:
        cached = pd.read_parquet(cache_path)
        cached["date"] = pd.to_datetime(cached["date"]).dt.normalize()
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        sub = cached[(cached["date"] >= s) & (cached["date"] <= e)]
        if not sub.empty:
            return sub.reset_index(drop=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from strategy.strategies.strategy3.first_board import load_zz1000

    univ = load_zz1000()
    if max_stocks is not None and max_stocks > 0:
        univ = univ.head(int(max_stocks))

    def _one(sym: str) -> pd.DataFrame | None:
        try:
            df = fetch_daily(sym, start, end)
        except Exception:
            return None
        if df is None or df.empty:
            return None
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        out["yang"] = out["close"] > out["open"]
        return out[["date", "yang"]]

    frames: list[pd.DataFrame] = []
    symbols = univ["symbol"].dropna().astype(str).tolist()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, s): s for s in symbols}
        for fut in as_completed(futs):
            part = fut.result()
            if part is not None and not part.empty:
                frames.append(part)

    if not frames:
        return pd.DataFrame(columns=["date", "yang_ratio", "n_yang", "n_stocks"])

    panel = pd.concat(frames, ignore_index=True)
    agg = (
        panel.groupby("date", as_index=False)
        .agg(n_yang=("yang", "sum"), n_stocks=("yang", "count"))
        .sort_values("date")
    )
    agg["yang_ratio"] = agg["n_yang"] / agg["n_stocks"].replace(0, np.nan)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(cache_path, index=False)
    return agg.reset_index(drop=True)


def merge_index_and_breadth(
    index_feat: pd.DataFrame,
    breadth: pd.DataFrame | None,
) -> pd.DataFrame:
    d = index_feat.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    if breadth is None or breadth.empty:
        d["yang_ratio"] = np.nan
        return d
    b = breadth.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None).dt.normalize()
    return d.merge(b[["date", "yang_ratio", "n_yang", "n_stocks"]], on="date", how="left")


def trading_hints(bucket_stats: pd.DataFrame) -> list[dict[str, str]]:
    """基于历史均收益给出研究向提示（非交易指令）。"""
    hints: list[dict[str, str]] = []
    if bucket_stats.empty:
        return hints
    # 全样本低开日合并
    total_n = int(bucket_stats["n_days"].sum())
    if total_n < 30:
        hints.append(
            {
                "level": "warn",
                "text": f"低开样本仅 {total_n} 日，统计仅供参考。",
            }
        )

    def _weighted_mean(col: str) -> float | None:
        if col not in bucket_stats.columns:
            return None
        w = bucket_stats["n_days"].astype(float)
        v = pd.to_numeric(bucket_stats[col], errors="coerce")
        m = (v * w).sum() / w.sum() if w.sum() > 0 else np.nan
        return float(m) if m == m else None

    scenarios = [
        ("低开日开盘买入、当日收盘卖出", "ret_open_close_mean", "ret_open_close_win_pct"),
        ("低开日收盘买入、次日开盘卖出", "ret_close_next_open_mean", "ret_close_next_open_win_pct"),
        ("低开日收盘买入、次日收盘卖出", "ret_close_next_close_mean", "ret_close_next_close_win_pct"),
        ("低开日开盘买入、次日收盘卖出", "ret_open_next_close_mean", "ret_open_next_close_win_pct"),
    ]
    ranked: list[tuple[str, float, float | None]] = []
    for name, mcol, wcol in scenarios:
        mu = _weighted_mean(mcol)
        wr = _weighted_mean(wcol)
        if mu is not None:
            ranked.append((name, mu, wr))
    ranked.sort(key=lambda x: x[1], reverse=True)
    if ranked:
        best = ranked[0]
        wr_txt = f"{best[2]:.1f}" if best[2] is not None else "-"
        hints.append(
            {
                "level": "info",
                "text": (
                    f"历史低开日加权表现最佳情景：{best[0]}，"
                    f"均收益 {best[1]:+.2f}%，胜率约 {wr_txt}%。"
                ),
            }
        )
        if len(ranked) > 1 and ranked[0][1] > 0 and ranked[-1][1] < 0:
            wr_last = (
                f"{ranked[-1][2]:.1f}" if ranked[-1][2] is not None else "-"
            )
            hints.append(
                {
                    "level": "info",
                    "text": (
                        f"对比：{ranked[-1][0]} 均收益 {ranked[-1][1]:+.2f}%"
                        f"（胜率约 {wr_last}%），"
                        "低开日不宜盲目抄底/追涨，需分桶看待。"
                    ),
                }
            )
    yang_mean = _weighted_mean("stock_yang_ratio_mean")
    if yang_mean is not None and yang_mean == yang_mean and yang_mean > 0:
        hints.append(
            {
                "level": "info",
                "text": (
                    f"低开日中证1000实体阳（close>open）家数比例均值约 {yang_mean*100:.1f}%；"
                    "指数常收红（close>open）不等于多数个股相对昨收上涨。"
                ),
            }
        )
    return hints


def factor17_signal(
    *,
    start: str = DEFAULT_START,
    end: str | None = None,
    index_symbol: str = DEFAULT_INDEX,
    with_breadth: bool = True,
    breadth_max_stocks: int | None = None,
    breadth_force: bool = False,
    params: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """因子17 主入口：拉指数 + 可选广度 → 分桶统计 + 买卖提示。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    end = end or pd.Timestamp.today().strftime("%Y%m%d")

    idx = fetch_index_daily(index_symbol, start, end)
    feat = prepare_index_features(idx)

    breadth: pd.DataFrame | None = None
    breadth_note = ""
    if with_breadth:
        try:
            breadth = build_yang_breadth_daily(
                start=start,
                end=end,
                max_stocks=breadth_max_stocks,
                force=breadth_force,
            )
            breadth_note = f"广度：中证1000，{len(breadth)} 个交易日"
        except Exception as exc:
            breadth_note = f"广度未生成（{type(exc).__name__}: {exc}）"

    merged = merge_index_and_breadth(feat, breadth)
    bucket_stats = summarize_by_gap_bucket(merged, low_open_only=bool(p.get("low_open_only", True)))
    hints = trading_hints(bucket_stats)

    low_open_days = merged[merged["gap_pct"] < 0].copy()
    latest: dict[str, Any] | None = None
    if not low_open_days.empty:
        row = low_open_days.iloc[-1]
        latest = {
            "date": str(row["date"].date()),
            "gap_pct": round(float(row["gap_pct"]), 2),
            "bucket": row.get("gap_bucket"),
            "index_intraday_pct": round(float(row["intraday_pct"]), 2),
            "index_day_ret_pct": round(float(row["day_ret_pct"]), 2),
            "index_intraday_yang": bool(row["intraday_yang"]),
            "yang_ratio": None
            if pd.isna(row.get("yang_ratio"))
            else round(float(row["yang_ratio"]) * 100, 1),
        }

    return {
        "factor_id": FACTOR_ID,
        "params": p,
        "index_symbol": index_symbol,
        "start": start,
        "end": end,
        "breadth_note": breadth_note,
        "bucket_stats": bucket_stats,
        "hints": hints,
        "latest_low_open": latest,
        "rules_text": factor17_rules_text(p),
        "n_index_days": int(len(feat)),
        "n_low_open_days": int((feat["gap_pct"] < 0).sum()),
    }


def build_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {FACTOR_NAME} 报告",
        "",
        f"- 指数：`{result.get('index_symbol')}`",
        f"- 区间：{result.get('start')} → {result.get('end')}",
        f"- 指数交易日：{result.get('n_index_days')} · 低开日：{result.get('n_low_open_days')}",
        f"- {result.get('breadth_note', '')}",
        "",
        "## 口径",
        "",
        "- **大盘低开**：开盘相对昨收 gap% < 0",
        "- **实体阳**：close > open（相对开盘收红；可与相对昨收仍跌并存）",
        "- **收阳家数比例**：广度池内实体阳股票数 / 总股票数",
        "",
        "## 分桶统计（低开日）",
        "",
    ]
    stats: pd.DataFrame = result.get("bucket_stats")  # type: ignore[assignment]
    if stats is not None and not stats.empty:
        lines.append(
            "| 桶 | 样本 | 均gap% | 当日日内% | 当日涨跌% | 指数实体阳% | "
            "实体阳家数% | 次日开盘gap% | 次日日内% | 次日总% | "
            "开买收卖均% | 胜率% | 收买次开均% | 胜率% |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in stats.iterrows():
            lines.append(
                f"| {r['bucket']} | {int(r['n_days'])} | "
                f"{r.get('idx_gap_pct_mean', '-')} | {r.get('idx_intraday_pct_mean', '-')} | "
                f"{r.get('idx_day_ret_mean', '-')} | {r.get('idx_intraday_yang_pct', '-')} | "
                f"{_pct(r.get('stock_yang_ratio_mean'))} | "
                f"{r.get('idx_next_open_vs_close_mean', '-')} | {r.get('idx_next_intraday_mean', '-')} | "
                f"{r.get('idx_next_total_mean', '-')} | "
                f"{r.get('ret_open_close_mean', '-')} | {r.get('ret_open_close_win_pct', '-')} | "
                f"{r.get('ret_close_next_open_mean', '-')} | {r.get('ret_close_next_open_win_pct', '-')} |"
            )
    else:
        lines.append("_无低开样本_")

    lines += ["", "## 研究提示", ""]
    for h in result.get("hints") or []:
        lines.append(f"- {h.get('text', '')}")

    lat = result.get("latest_low_open")
    if lat:
        lines += [
            "",
            "## 最近一次大盘低开",
            "",
            f"- 日期：{lat.get('date')} · 桶：{lat.get('bucket')}",
            f"- 指数 gap：{lat.get('gap_pct')}% · 日内：{lat.get('index_intraday_pct')}% · "
            f"全日：{lat.get('index_day_ret_pct')}%",
            f"- 指数实体阳：{'是' if lat.get('index_intraday_yang') else '否'} · "
            f"成分实体阳比例：{lat.get('yang_ratio', '-')}%",
        ]

    lines += [
        "",
        "本报告基于历史统计，不构成任何投资建议。",
        "",
    ]
    return "\n".join(lines)


def _pct(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if x != x:
        return "-"
    return f"{x*100:.1f}"
