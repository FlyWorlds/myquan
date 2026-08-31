"""策略九·低开跌停情绪：统计中证1000 宇宙每日「低开且开盘即跌停」家数，对照大盘当日涨跌。

规则口径（2020→今，研究用途）：
  · 宇宙：中证1000（剔 ST / 北交），与策略三情绪统计同源
  · 低开：开盘价 < 昨收
  · 开盘即跌停：开盘价落在跌停价容差内（主板 10% / 科创创业 20%）
  · 大盘：默认上证指数 sh000001 收盘相对昨收涨跌幅
  · 情绪阶段：按历史分位划分 平静 / 正常 / 恐慌（家数越少越平静）
  · 方向预测：恐慌→当日收跌（顺势）；平静→当日收涨（顺势）；正常→样本内多数类
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.open_break import TICK_SIZE, limit_down_price  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
from strategy.strategies.strategy3 import first_board as s3  # noqa: E402
from strategy.strategies.strategy9.sentiment_phase import (  # noqa: E402
    LD_OPEN_CALM_MAX,
    LD_OPEN_PANIC_MIN,
    classify_ld_open_phase,
)

OUT = _MYQUAN / "backtest" / "strategy9_limit_down_emotion"
ORIGIN = pd.Timestamp("2020-01-01")
INDEX_SYMBOL = "sh000001"
INDEX_NAME = "上证指数"


def _sentiment_cache_path() -> Path:
    return OUT / "mkt_ld_open_zz1000.parquet"


def is_gap_down_limit_down_open(
    prev_close: float,
    open_px: float,
    *,
    limit_ratio: float,
    tick: float = TICK_SIZE,
) -> bool:
    """低开且开盘价在跌停价（一字跌停开盘）。"""
    if prev_close <= 0 or open_px <= 0:
        return False
    if float(open_px) >= float(prev_close):
        return False
    ld_px = limit_down_price(prev_close, limit_down_pct=limit_ratio, tick=tick)
    if ld_px is None:
        return False
    tol = max(float(tick) * 0.51, 1e-8)
    return abs(float(open_px) - float(ld_px)) <= tol


def ensure_daily_parallel(univ: pd.DataFrame, *, workers: int = 8) -> None:
    """并行补齐宇宙日线缓存（复用 strategy3 缓存路径）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    UNIV_CACHE.mkdir(parents=True, exist_ok=True)
    missing = [
        r
        for _, r in univ.iterrows()
        if not (UNIV_CACHE / f"{r['symbol']}_daily_qfq.parquet").exists()
    ]
    print(f"缺日线: {len(missing)} / {len(univ)}")
    if not missing:
        return

    def _one(row: Any) -> tuple[str, str | None]:
        from strategy.data import fetch_daily

        try:
            fetch_daily(
                row.symbol,
                "20190101",
                pd.Timestamp.today().strftime("%Y%m%d"),
                cache_path=UNIV_CACHE / f"{row.symbol}_daily_qfq.parquet",
            )
            return row.symbol, None
        except Exception as exc:  # noqa: BLE001
            return row.symbol, str(exc)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {pool.submit(_one, r): r for r in missing}
        for fut in as_completed(futures):
            sym, err = fut.result()
            done += 1
            if err:
                print(f"  fail {sym}: {err}")
            if done % 25 == 0 or done == len(missing):
                print(f"  拉取 {done}/{len(missing)}")


def build_mkt_ld_open_series(
    univ: pd.DataFrame,
    *,
    rebuild: bool = False,
) -> pd.DataFrame:
    """按日统计「低开开盘即跌停」家数。"""
    cache = _sentiment_cache_path()
    if cache.is_file() and not rebuild:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        return df.sort_values("date").reset_index(drop=True)

    cnt: dict[pd.Timestamp, int] = {}
    all_dates: set[pd.Timestamp] = set()
    for i, row in enumerate(univ.itertuples(index=False), 1):
        daily = s3.load_bars(row.symbol)
        if daily is None or len(daily) < 2:
            continue
        lim = s3.limit_ratio(row.code)
        dates = pd.DatetimeIndex(daily["date"])
        o = daily["open"].to_numpy(float)
        prev_c = daily["close"].shift(1).to_numpy(float)
        for j in range(1, len(daily)):
            d = pd.Timestamp(dates[j]).normalize()
            if d < ORIGIN:
                continue
            all_dates.add(d)
            pc = float(prev_c[j])
            if pc <= 0:
                continue
            if is_gap_down_limit_down_open(pc, float(o[j]), limit_ratio=lim):
                cnt[d] = cnt.get(d, 0) + 1
        if i % 100 == 0 or i == len(univ):
            print(f"  ld_open {i}/{len(univ)}")

    rows = [
        {"date": d, "mkt_ld_open": int(cnt.get(d, 0))}
        for d in sorted(all_dates)
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["date", "mkt_ld_open"])
    else:
        df = df.sort_values("date").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def load_index_daily(
    *,
    start: str = "20191201",
    end: str | None = None,
    symbol: str = INDEX_SYMBOL,
) -> pd.DataFrame:
    """拉取指数日线（收盘涨跌用于验证当日走势）。"""
    import akshare as ak

    end_s = end or pd.Timestamp.today().strftime("%Y%m%d")
    cache = OUT / f"{symbol}_daily.parquet"
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end_s)

    if cache.is_file():
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        if df["date"].max() >= end_ts - pd.Timedelta(days=5):
            sub = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]
            if not sub.empty:
                return sub.sort_values("date").reset_index(drop=True)

    code = str(symbol).strip().lower()
    if not code.startswith(("sh", "sz")):
        raise ValueError(f"仅支持 sh/sz 指数代码: {symbol}")
    try:
        raw = ak.stock_zh_index_daily(symbol=code)
    except Exception as exc:
        raise RuntimeError(f"指数日线拉取失败: {symbol} {start}~{end_s}") from exc
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"]).dt.tz_localize(None).dt.normalize()
    for col in ("open", "high", "low", "close"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["open", "close"]).sort_values("date")
    raw = raw[(raw["date"] >= start_ts) & (raw["date"] <= end_ts)]
    raw["symbol"] = code
    raw.to_parquet(cache, index=False)
    return raw.reset_index(drop=True)


def _predict_direction(ld_open: int | None, *, calm_max: int, panic_min: int) -> str:
    """根据低开跌停家数预测当日大盘收盘方向（相对昨收）。"""
    if ld_open is None:
        return "flat"
    n = int(ld_open)
    if n >= panic_min:
        return "down"
    if n <= calm_max:
        return "up"
    return "down"  # 正常区间样本内收跌略多，顺势偏空


def analyze_emotion_vs_index(
    emotion: pd.DataFrame,
    index: pd.DataFrame,
    *,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """合并情绪与指数，标注实际涨跌与预测。"""
    emo = emotion.copy()
    emo["date"] = pd.to_datetime(emo["date"]).dt.normalize()
    idx = index.copy()
    idx["date"] = pd.to_datetime(idx["date"]).dt.normalize()
    idx["prev_close"] = idx["close"].shift(1)
    idx["ret_close"] = idx["close"] / idx["prev_close"] - 1.0
    idx["ret_open"] = idx["close"] / idx["open"] - 1.0
    idx["actual"] = np.where(idx["ret_close"] > 0, "up", np.where(idx["ret_close"] < 0, "down", "flat"))

    merged = emo.merge(
        idx[["date", "open", "close", "prev_close", "ret_close", "ret_open", "actual"]],
        on="date",
        how="inner",
    )
    if start is not None:
        merged = merged[merged["date"] >= start].copy()
    merged["phase"] = merged["mkt_ld_open"].apply(
        lambda x: classify_ld_open_phase(int(x) if pd.notna(x) else None)["ldPhase"]
    )
    merged["phase_label"] = merged["mkt_ld_open"].apply(
        lambda x: classify_ld_open_phase(int(x) if pd.notna(x) else None)["ldPhaseLabel"]
    )
    merged["predict"] = merged["mkt_ld_open"].apply(
        lambda x: _predict_direction(
            int(x) if pd.notna(x) else None,
            calm_max=LD_OPEN_CALM_MAX,
            panic_min=LD_OPEN_PANIC_MIN,
        )
    )
    merged["hit"] = merged["predict"] == merged["actual"]
    merged["hit"] = merged["hit"] & merged["actual"].isin(("up", "down"))
    return merged.sort_values("date").reset_index(drop=True)


def _phase_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase, g in df.groupby("phase", dropna=False):
        if g.empty:
            continue
        up_pct = float((g["actual"] == "up").mean()) if len(g) else 0.0
        rows.append(
            {
                "phase": phase,
                "days": int(len(g)),
                "avg_ld_open": float(g["mkt_ld_open"].mean()),
                "avg_ret_close_pct": float(g["ret_close"].mean() * 100),
                "up_ratio_pct": round(up_pct * 100, 2),
                "predict_hit_pct": round(float(g["hit"].mean()) * 100, 2) if len(g) else 0.0,
            }
        )
    return rows


def _write_report(
    df: pd.DataFrame,
    *,
    start: str,
    end: str,
    summary: dict[str, Any],
) -> Path:
    report = OUT / "REPORT.md"
    phase_lines = []
    for row in summary.get("phase_stats", []):
        phase_lines.append(
            f"| {row['phase']} | {row['days']} | {row['avg_ld_open']:.1f} | "
            f"{row['avg_ret_close_pct']:+.2f}% | {row['up_ratio_pct']:.1f}% | "
            f"{row['predict_hit_pct']:.1f}% |"
        )
    body = f"""# 策略九·低开跌停情绪研究报告

> 研究用途，非投资建议。区间 {start}～{end}，宇宙中证1000，大盘参照{INDEX_NAME}。

## 口径

- **低开开盘即跌停**：开盘 < 昨收，且开盘价在跌停价容差内
- **情绪阶段**：平静 ≤{LD_OPEN_CALM_MAX} · 正常 {LD_OPEN_CALM_MAX + 1}～{LD_OPEN_PANIC_MIN - 1} · 恐慌 ≥{LD_OPEN_PANIC_MIN}
- **预测规则**：恐慌→收跌；平静→收涨；正常→收跌（样本内顺势）

## 全样本

| 指标 | 数值 |
|------|------|
| 交易日 | {summary.get('trade_days', 0)} |
| 平均低开跌停家数 | {summary.get('avg_ld_open', 0):.2f} |
| 预测命中率（涨跌二分类） | {summary.get('hit_rate_pct', 0):.2f}% |
| 恐慌日占比 | {summary.get('panic_day_pct', 0):.2f}% |
| 平静日占比 | {summary.get('calm_day_pct', 0):.2f}% |

## 分阶段

| 阶段 | 天数 | 均家数 | 均涨跌幅 | 收涨占比 | 预测命中 |
|------|------|--------|----------|----------|----------|
{chr(10).join(phase_lines) if phase_lines else '| — | — | — | — | — | — |'}

## 产物

- `mkt_ld_open_zz1000.parquet` — 日度家数
- `emotion_index_merged.csv` — 合并明细
- `summary.json` — 汇总指标
"""
    report.write_text(body, encoding="utf-8")
    return report


def run_limit_down_emotion_backtest(
    *,
    start: str = "20200101",
    end: str | None = None,
    index_symbol: str = INDEX_SYMBOL,
    rebuild: bool = False,
    allow_network: bool = True,
    max_stocks: int | None = None,
    workers: int = 8,
) -> dict[str, Any]:
    """构建情绪序列并对照大盘当日涨跌。"""
    end_s = end or pd.Timestamp.today().strftime("%Y%m%d")
    start_ts = pd.Timestamp(start)
    OUT.mkdir(parents=True, exist_ok=True)

    print("加载中证1000 宇宙…")
    univ = s3.load_zz1000(allow_network=allow_network)
    if max_stocks is not None and max_stocks > 0:
        univ = univ.head(int(max_stocks)).copy()
        print(f"宇宙截断为前 {len(univ)} 只（max_stocks={max_stocks}）")
    else:
        print(f"宇宙 {len(univ)} 只")

    if rebuild or not _sentiment_cache_path().is_file():
        if allow_network:
            print("确保成分股日线缓存…")
            ensure_daily_parallel(univ, workers=workers)
        else:
            s3.ensure_daily(univ)

    print("统计低开开盘跌停家数…")
    emotion = build_mkt_ld_open_series(univ, rebuild=rebuild)

    print(f"拉取{INDEX_NAME} {index_symbol}…")
    index = load_index_daily(start="20191201", end=end_s, symbol=index_symbol)

    merged = analyze_emotion_vs_index(emotion, index, start=start_ts)
    merged = merged[merged["date"] <= pd.Timestamp(end_s)]

    trade_df = merged[merged["actual"].isin(("up", "down"))].copy()
    hit_rate = float(trade_df["hit"].mean()) if len(trade_df) else 0.0
    phase_stats = _phase_stats(trade_df)

    summary: dict[str, Any] = {
        "strategy": "strategy9",
        "start": start,
        "end": end_s,
        "universe": "zz1000",
        "index": index_symbol,
        "index_name": INDEX_NAME,
        "ld_open_calm_max": LD_OPEN_CALM_MAX,
        "ld_open_panic_min": LD_OPEN_PANIC_MIN,
        "trade_days": int(len(trade_df)),
        "avg_ld_open": float(trade_df["mkt_ld_open"].mean()) if len(trade_df) else 0.0,
        "hit_rate_pct": round(hit_rate * 100, 2),
        "max_stocks": max_stocks,
        "workers": workers,
        "panic_day_pct": round(
            float((trade_df["phase"] == "panic").mean()) * 100, 2
        )
        if len(trade_df)
        else 0.0,
        "calm_day_pct": round(
            float((trade_df["phase"] == "calm").mean()) * 100, 2
        )
        if len(trade_df)
        else 0.0,
        "phase_stats": phase_stats,
    }

    merged.to_csv(OUT / "emotion_index_merged.csv", index=False)
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = _write_report(merged, start=start, end=end_s, summary=summary)

    print(f"\n区间 {start}～{end_s} · 交易日 {summary['trade_days']}")
    print(f"平均低开跌停家数 {summary['avg_ld_open']:.2f}")
    print(f"预测命中率 {summary['hit_rate_pct']:.2f}%")
    for row in phase_stats:
        print(
            f"  [{row['phase']}] n={row['days']} avg_ld={row['avg_ld_open']:.1f} "
            f"ret={row['avg_ret_close_pct']:+.2f}% up={row['up_ratio_pct']:.1f}% "
            f"hit={row['predict_hit_pct']:.1f}%"
        )
    print(f"报告: {report}")

    return {"summary": summary, "merged": merged, "emotion": emotion, "report": str(report)}
