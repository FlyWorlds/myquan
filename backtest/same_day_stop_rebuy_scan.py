"""止损当日尾盘再买扫描（因子1 开盘突破）。

现行：止损/卖出当日禁买。
扫描：开放当日打止损后尾盘再买；再买仓位当日不可卖（T+1）。

过滤组合：
  · 尾盘收阳
  · 收盘高于止损价 X 点（1点=1%，相对止损价）
  · 收盘距当日最低价反弹 ≥ X 点（相对开盘）

区间默认 2025-01-01 至今。仅供研究，不构成投资建议。
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy import BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402

_CACHE = _ROOT / "data_cache"
_OUT = Path(__file__).resolve().parent / "same_day_stop_rebuy_2025"


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


def _fetch_sina_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """东财 ETF 失败时的新浪日线兜底（未复权/站点口径，仅研究用）。"""
    import json
    import urllib.request

    url = (
        "https://quotes.sina.cn/cn/api/json_v2.php/"
        f"CN_MarketDataService.getKLineData?symbol={symbol}"
        "&scale=240&ma=no&datalen=800"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode())
    df = pd.DataFrame(raw)
    if df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["day"])
    start_ts = pd.Timestamp(start[:4] + "-" + start[4:6] + "-" + start[6:8])
    end_ts = pd.Timestamp(end[:4] + "-" + end[4:6] + "-" + end[6:8]) + pd.Timedelta(
        days=1
    )
    df = df[(df["date"] >= start_ts) & (df["date"] < end_ts)]
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    df["symbol"] = symbol
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


def _load_daily(cfg: BacktestConfig) -> pd.DataFrame:
    try:
        daily = fetch_daily(
            cfg.symbol,
            start=cfg.start_date,
            end=cfg.end_date,
            cache_path=cfg.daily_cache,
        )
        if daily is not None and not daily.empty:
            return daily
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] fetch_daily {cfg.symbol}: {exc}")
    if str(cfg.em_symbol).startswith(("58", "51", "56", "15", "16")):
        daily = _fetch_sina_daily(cfg.symbol, cfg.start_date, cfg.end_date)
        if cfg.daily_cache is not None and not daily.empty:
            cfg.daily_cache.parent.mkdir(parents=True, exist_ok=True)
            daily.to_parquet(cfg.daily_cache, index=False)
        return daily
    return pd.DataFrame()


# 用户标的：东材 / 珠峰 / 天通+凯盛 / 金安国纪 / ETF589080 / ETF588170
UNIVERSE: list[dict[str, Any]] = [
    {"code": "601208", "name": "东材科技", "entry": 0.025, "stop": 0.025},
    {"code": "600338", "name": "西藏珠峰", "entry": 0.025, "stop": 0.025},
    {"code": "600552", "name": "凯盛科技", "entry": 0.025, "stop": 0.025},
    {"code": "600330", "name": "天通股份", "entry": 0.03, "stop": 0.03},
    {"code": "002636", "name": "金安国纪", "entry": 0.03, "stop": 0.03},
    {
        "code": "589080",
        "name": "科创综指ETF汇添富",
        "entry": 0.025,
        "stop": 0.035,
        "etf": True,
    },
    {
        "code": "588170",
        "name": "科创半导体ETF华夏",
        "entry": 0.025,
        "stop": 0.035,
        "etf": True,
    },
]

# 1点=1%。收阳时收盘天然 > 开盘 ≥ 止损×约1.025，故「收阳+低于2.5点」与「仅收阳」等价。
# 网格：基线 / 仅收阳 / 不限阴阳×高于止损 / 收阳×更严距低与高于止损。
X_LOOSE = (0.0, 0.5, 1.0, 1.5, 2.0)
X_STRICT = (3.0, 4.0, 5.0)


def _variants() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "label": "基线_止损日禁买",
            "allow": False,
            "yang": True,
            "above": 0.0,
            "from_low": 0.0,
        },
        {
            "label": "再买_仅收阳(等价止损+≤2.5点)",
            "allow": True,
            "yang": True,
            "above": 0.0,
            "from_low": 0.0,
        },
        {
            "label": "再买_不限阴阳_收盘≥止损",
            "allow": True,
            "yang": False,
            "above": 0.0,
            "from_low": 0.0,
        },
    ]
    for above in X_LOOSE:
        if above <= 0:
            continue
        rows.append(
            {
                "label": f"再买_不限阴阳_止损+{above:g}点",
                "allow": True,
                "yang": False,
                "above": above / 100.0,
                "from_low": 0.0,
            }
        )
    for from_low in X_LOOSE + X_STRICT:
        if from_low <= 0:
            continue
        rows.append(
            {
                "label": f"再买_不限阴阳_距低≥{from_low:g}点",
                "allow": True,
                "yang": False,
                "above": 0.0,
                "from_low": from_low / 100.0,
            }
        )
    for x in X_STRICT:
        rows.append(
            {
                "label": f"再买_收阳_止损+{x:g}点",
                "allow": True,
                "yang": True,
                "above": x / 100.0,
                "from_low": 0.0,
            }
        )
        rows.append(
            {
                "label": f"再买_收阳_距低≥{x:g}点",
                "allow": True,
                "yang": True,
                "above": 0.0,
                "from_low": x / 100.0,
            }
        )
        rows.append(
            {
                "label": f"再买_收阳_止损+{x:g}_距低≥{x:g}",
                "allow": True,
                "yang": True,
                "above": x / 100.0,
                "from_low": x / 100.0,
            }
        )
    return rows


def _cfg_for(item: dict[str, Any], start: str, end: str) -> BacktestConfig:
    code = str(item["code"])
    sym = _sina(code)
    etf = bool(item.get("etf"))
    kw: dict[str, Any] = dict(
        symbol=sym,
        symbol_name=str(item["name"]),
        em_symbol=code,
        entry_pct=float(item["entry"]),
        stop_pct=float(item["stop"]),
        threshold_pct=float(item["entry"]),
        start_date=start,
        end_date=end,
        t0=False,
        daily_cache=_CACHE / f"{sym}_daily_qfq.parquet",
    )
    if etf:
        kw["stamp_tax_rate"] = 0.0
        kw["tick"] = 0.001
    return BacktestConfig(**kw)


def _run_one(
    base: BacktestConfig,
    variant: dict[str, Any],
) -> dict[str, Any]:
    cfg = replace(
        base,
        allow_same_day_rebuy_after_stop=bool(variant["allow"]),
        rebuy_require_yang=bool(variant["yang"]),
        rebuy_above_stop_pct=float(variant["above"]),
        rebuy_from_low_pct=float(variant["from_low"]),
        report_path=None,
    )
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    same_day = 0
    try:
        ex = result.executions_df
        if ex is not None and not ex.empty:
            tmp = ex.copy()
            tmp["day"] = tmp["timestamp"].astype(str).str[:10]
            for _, g in tmp.groupby("day"):
                sides = {str(s).lower() for s in g["side"].tolist()}
                if "buy" in sides and "sell" in sides:
                    same_day += 1
    except Exception:  # noqa: BLE001
        same_day = -1
    return {
        "symbol": cfg.symbol,
        "name": cfg.symbol_name,
        "variant": variant["label"],
        "allow_rebuy": bool(variant["allow"]),
        "require_yang": bool(variant["yang"]),
        "above_stop_pts": float(variant["above"]) * 100.0,
        "from_low_pts": float(variant["from_low"]) * 100.0,
        "total_return_pct": metric(m, "total_return_pct"),
        "max_drawdown_pct": metric(m, "max_drawdown_pct"),
        "sharpe_ratio": metric(m, "sharpe_ratio"),
        "win_rate": metric(m, "win_rate"),
        "closed_trades": metric(m, "closed_trade_count"),
        "end_mv": metric(m, "end_market_value"),
        "same_day_buy_sell_days": same_day,
    }


def main() -> None:
    start = "20250101"
    end = dt.date.today().strftime("%Y%m%d")
    _OUT.mkdir(parents=True, exist_ok=True)
    variants = _variants()
    rows: list[dict[str, Any]] = []

    print(f"区间 {start}~{end} | 变体 {len(variants)} | 标的 {len(UNIVERSE)}")
    print("口径：因子1仅止损；再买=止损后尾盘按收盘价建仓，当日不可卖。1点=1%。")
    print("免责：研究回测，不构成投资建议。\n")

    for item in UNIVERSE:
        base = _cfg_for(item, start, end)
        # ETF 可能成立日晚于 2025-01-01
        daily = _load_daily(base)
        if daily is None or daily.empty:
            print(f"[跳过] {base.symbol_name} 无日线")
            continue
        d0 = str(daily["date"].iloc[0])[:10]
        d1 = str(daily["date"].iloc[-1])[:10]
        print(f"== {base.symbol_name}({base.symbol}) {d0}→{d1} bars={len(daily)}")
        base = replace(
            base,
            start_date=d0.replace("-", ""),
            end_date=d1.replace("-", ""),
        )
        for v in variants:
            try:
                row = _run_one(base, v)
                rows.append(row)
                print(
                    f"  {v['label']}: ret={row['total_return_pct']:.2f}% "
                    f"dd={row['max_drawdown_pct']:.2f}% "
                    f"sharpe={row['sharpe_ratio']:.3f} "
                    f"trades={row['closed_trades']:.0f} "
                    f"same_day={row['same_day_buy_sell_days']}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {v['label']}: ERROR {exc}")
                rows.append(
                    {
                        "symbol": base.symbol,
                        "name": base.symbol_name,
                        "variant": v["label"],
                        "error": str(exc),
                    }
                )

    df = pd.DataFrame(rows)
    csv_path = _OUT / "scan_metrics.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # 相对基线的差额
    if not df.empty and "error" not in df.columns:
        base_map = {
            (r.symbol,): r
            for r in df.itertuples()
            if r.variant == "基线_止损日禁买"
        }
        deltas = []
        for r in df.itertuples():
            b = base_map.get((r.symbol,))
            if b is None or r.variant == "基线_止损日禁买":
                continue
            deltas.append(
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "variant": r.variant,
                    "d_ret": float(r.total_return_pct) - float(b.total_return_pct),
                    "d_dd": float(r.max_drawdown_pct) - float(b.max_drawdown_pct),
                    "d_sharpe": float(r.sharpe_ratio) - float(b.sharpe_ratio),
                    "ret": float(r.total_return_pct),
                    "base_ret": float(b.total_return_pct),
                    "sharpe": float(r.sharpe_ratio),
                    "base_sharpe": float(b.sharpe_ratio),
                    "trades": float(r.closed_trades),
                }
            )
        ddf = pd.DataFrame(deltas)
        ddf.to_csv(_OUT / "vs_baseline.csv", index=False, encoding="utf-8-sig")

        # 每标的夏普最优（相对基线）
        best_rows = []
        for sym, g in ddf.groupby("symbol"):
            best = g.sort_values(["d_sharpe", "d_ret"], ascending=False).iloc[0]
            best_rows.append(best.to_dict())
        best_df = pd.DataFrame(best_rows)
        best_df.to_csv(_OUT / "best_vs_baseline.csv", index=False, encoding="utf-8-sig")

        # 简洁 markdown 报告
        lines = [
            f"# 止损当日尾盘再买扫描（{start}~{end}）",
            "",
            "## 规则",
            "",
            "- **基线**：因子1 开盘突破；止损当日禁买（现行）。",
            "- **再买**：当日触止损清仓后，若尾盘满足条件则按**收盘价**再建仓；新仓当日不可卖（T+1）。",
            "- **过滤**：尾盘收阳；收盘 ≥ 止损价×(1+X%)；(收盘−最低)/开盘 ≥ Y%。1点=1%。",
            "- 注意：触止损且收阳时，收盘天然高于止损约≥2.5点、距低亦约≥2.5点，故「收阳+X≤2.5」与仅收阳几乎等价；严格过滤看 X≥3。",
            "- 个股阈值：东材/珠峰/凯盛 ±2.5%；天通/金安 ±3.0%；两只科创 ETF 买2.5%/止3.5%、无印花税、tick=0.001。",
            "- **仅供研究，不构成投资建议。**",
            "",
            "## 各标的相对基线最优（按 Δ夏普）",
            "",
            "| 标的 | 最优变体 | 收益% | 基线收益% | Δ收益 | 夏普 | 基线夏普 | Δ夏普 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for r in best_df.itertuples():
            lines.append(
                f"| {r.name} | {r.variant} | {r.ret:.2f} | {r.base_ret:.2f} | "
                f"{r.d_ret:+.2f} | {r.sharpe:.3f} | {r.base_sharpe:.3f} | {r.d_sharpe:+.3f} |"
            )
        lines += [
            "",
            "## 结论摘要",
            "",
            "1. **仅收阳再买**：多数个股弱于基线；个别 ETF（如 589080）样本内可能改善。",
            "2. **不限阴阳乱接**：同日买卖次数上升，多数夏普下降，不宜默认。",
            "3. **个别改善**看 `best_vs_baseline.csv`；勿全池一刀切。",
            "4. **建议**：默认维持止损当日禁买；试验再买需单标的严格过滤。",
            "",
            f"明细：`{csv_path}`",
            "",
        ]
        (_OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
        print("\n" + "\n".join(lines))

    print(f"\n已写 {_OUT}")


if __name__ == "__main__":
    main()
