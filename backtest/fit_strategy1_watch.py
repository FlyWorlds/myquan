"""策略一 · 盯盘池拟合度分析（按个股阈值）。

口径（与 universe_zz500_1000 一致）：
  · 夏普 ≥ 1.0 且 策略收益 > 买入持有 → 拟合通过
  · 买点=今日开盘；前日阴/小阳；仅止损；T+1
  · 个股阈值：盯盘 watch_config._WATCH_PCT（天通±3%、凯盛±2.5%、其余默认±2.5%）

用法：
  cd backtest && python fit_strategy1_watch.py
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
import warnings
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

from holdingStocks.watch_config import WATCHLIST  # noqa: E402
from strategy import BacktestConfig, run_open_break_backtest  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "universe_zz500_1000"
OUT_CSV = OUT_DIR / "fit_watch_per_pct.csv"
OUT_TXT = OUT_DIR / "fit_watch_per_pct_summary.txt"
START_DATE = "20200101"
INITIAL_CASH = 100_000.0
SHARPE_MIN = 1.0
CACHE_DIR = _MYQUAN / "data_cache"

# README 旧表对照（全池统一 ±2.5% 快照）
_OLD_NOTE = {
    "600330": "旧统一±2.5% 约夏普1.009 / 策略+573%",
    "600552": "旧统一±2.5% 约夏普1.222 / 策略+984%",
}


def _bh_stats(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    if daily is None or daily.empty or "close" not in daily.columns:
        return None, None
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if closes.empty:
        return None, None
    c0, c1 = float(closes.iloc[0]), float(closes.iloc[-1])
    if c0 <= 0:
        return None, None
    bh_ret = (c1 / c0 - 1.0) * 100.0
    peak = closes.cummax()
    dd = (closes / peak - 1.0) * 100.0
    bh_dd = float(-dd.min()) if not dd.empty else None
    return bh_ret, bh_dd


def _index_of(code: str) -> str:
    # 粗分：与 README 表一致的已知归属；其余标未知
    zz500 = {"001389", "002335", "600105"}
    if code in zz500:
        return "中证500"
    return "中证1000"


def run_one(item: dict) -> dict:
    code = str(item["code"]).zfill(6)
    name = str(item["name"])
    pct = float(item.get("pct") or 0.025)
    symbol = str(item["sina"])
    end_date = dt.date.today().strftime("%Y%m%d")
    cache = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    row: dict = {
        "code": code,
        "name": name,
        "symbol": symbol,
        "index": _index_of(code),
        "threshold_pct": pct,
        "阈值%": round(pct * 100.0, 1),
        "ok": 0,
        "拟合": "否",
        "error": "",
    }
    try:
        cfg = BacktestConfig(
            symbol=symbol,
            symbol_name=name,
            em_symbol=code,
            threshold_pct=pct,
            start_date=START_DATE,
            end_date=end_date,
            initial_cash=INITIAL_CASH,
            entry_ref="today_open",
            prev_entry_mode="yin_or_small_yang",
            daily_cache=cache,
            report_path=None,
        )
        daily = fetch_daily(
            cfg.symbol,
            cfg.start_date,
            cfg.end_date,
            cache_path=cfg.daily_cache,
        )
        if daily is None or daily.empty or len(daily) < 60:
            row["error"] = f"日线不足({0 if daily is None else len(daily)})"
            return row
        result = run_open_break_backtest(cfg, daily)
        m = result.metrics_df
        strat = float(metric(m, "total_return_pct"))
        dd = float(metric(m, "max_drawdown_pct"))
        sharpe = float(metric(m, "sharpe_ratio"))
        win = float(metric(m, "win_rate"))
        n_tr = int(metric(m, "closed_trade_count"))
        pf = float(metric(m, "profit_factor"))
        bh_ret, bh_dd = _bh_stats(daily)
        excess = None if bh_ret is None else strat - float(bh_ret)
        fit = (sharpe >= SHARPE_MIN) and (excess is not None and excess > 0)
        row.update(
            {
                "策略收益%": round(strat, 2),
                "持有收益%": None if bh_ret is None else round(float(bh_ret), 2),
                "超额%": None if excess is None else round(float(excess), 2),
                "策略回撤%": round(dd, 2),
                "持有回撤%": None if bh_dd is None else round(float(bh_dd), 2),
                "夏普": round(sharpe, 3),
                "胜率%": round(win, 2),
                "闭环": n_tr,
                "利润因子": round(pf, 3),
                "ok": 1,
                "拟合": "是" if fit else "否",
                "n_bars": len(daily),
            }
        )
        return row
    except Exception as e:  # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {e}"
        return row


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    print(
        f"策略一拟合度 · 盯盘池 {len(WATCHLIST)} 只 | "
        f"{START_DATE}→今 | 夏普≥{SHARPE_MIN} 且超额>0"
    )
    for i, item in enumerate(WATCHLIST, 1):
        print(
            f"  [{i}/{len(WATCHLIST)}] {item['code']} {item['name']} "
            f"±{float(item['pct'])*100:.1f}% ...",
            flush=True,
        )
        row = run_one(item)
        rows.append(row)
        if row.get("ok"):
            print(
                f"    夏普{row['夏普']} 策略{row['策略收益%']}% "
                f"持有{row['持有收益%']}% 超额{row['超额%']}% "
                f"回撤{row['策略回撤%']}% 拟合={row['拟合']}"
            )
        else:
            print(f"    FAIL {row.get('error')}")

    df = pd.DataFrame(rows)
    if not df.empty and "夏普" in df.columns:
        df = df.sort_values("夏普", ascending=False, na_position="last")
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    fit_n = int((df["拟合"] == "是").sum()) if "拟合" in df.columns else 0
    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        "策略: 策略一·因子1（开盘突破仅止损）",
        "个股阈值: 天通±3.0% / 凯盛±2.5% / 其余默认±2.5%",
        f"区间: {START_DATE} → 今",
        f"筛选: 夏普≥{SHARPE_MIN} 且 策略收益>买入持有",
        f"盯盘池: {len(df)}  拟合通过: {fit_n}",
        "",
        "按夏普降序:",
    ]
    for _, r in df.iterrows():
        if int(r.get("ok") or 0) != 1:
            lines.append(f"  {r['code']} {r['name']} FAIL {r.get('error')}")
            continue
        note = _OLD_NOTE.get(str(r["code"]), "")
        lines.append(
            f"  {r['code']} {r['name']} ±{r['阈值%']}% | "
            f"夏普{r['夏普']} 策略{r['策略收益%']}% 持有{r['持有收益%']}% "
            f"超额{r['超额%']}% 回撤{r['策略回撤%']}% 拟合={r['拟合']}"
            + (f"  # {note}" if note else "")
        )

    lines.append("")
    lines.append("焦点对照:")
    for code in ("600552", "600330"):
        sub = df[df["code"] == code]
        if sub.empty:
            continue
        r = sub.iloc[0]
        lines.append(
            f"  {r['name']}: ±{r['阈值%']}% → 夏普{r['夏普']} / "
            f"策略{r['策略收益%']}% / 超额{r['超额%']}% / 拟合={r['拟合']}"
        )

    text = "\n".join(lines) + "\n"
    OUT_TXT.write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"CSV: {OUT_CSV}")
    print(f"TXT: {OUT_TXT}")


if __name__ == "__main__":
    main()
