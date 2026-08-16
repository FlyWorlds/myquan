"""``ma_crossover_signal`` skill — fast/slow MA crossover for one symbol.

Fast vs slow MA (SMA or EMA), current trend state, the most-recent golden/death
cross (date + bars ago), MA gap and price bias (乖离率). Cross detection is by the
SIGN CHANGE of (fast − slow), so a stale cross is reported with its real date
rather than masked by the current ordering.

Cross-market via our own ``panda_data`` (A 股) / ``tqx_data`` (港股 / 美股)
endpoints. Self-contained (same principle as the sibling analysis skills).
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_HK_SUFFIX = ".HK"
_US_SUFFIXES = (".NB", ".US", ".NY")
_CN_SUFFIXES = (".SH", ".SZ", ".BJ")
_FIELDS = ["open", "close", "high", "low", "volume", "pre_close"]


def _resolve_market(code: str, declared: str) -> str | None:
    m = (declared or "auto").strip().lower()
    if m in ("cn", "hk", "us"):
        return m
    if m and m != "auto":
        return None
    u = code.upper()
    if u.endswith(_HK_SUFFIX):
        return "hk"
    if u.endswith(_US_SUFFIXES):
        return "us"
    if u.endswith(_CN_SUFFIXES):
        return "cn"
    if re.fullmatch(r"\d{6}", u):
        return "cn"
    return None


def _to_us_symbol(code: str) -> str:
    u = code.upper()
    for suf in (".US", ".NY"):
        if u.endswith(suf):
            return code[: -len(suf)] + ".NB"
    return code


def _fetch_daily(code: str, market: str, start_date: str, end_date: str):
    if market == "cn":
        import panda_data  # type: ignore[import-untyped]

        return panda_data.get_market_data(
            symbol=[code],
            start_date=start_date,
            end_date=end_date,
            type="stock",
            fields=_FIELDS,
        )
    if market == "hk":
        import tqx_data  # type: ignore[import-untyped]

        return tqx_data.get_hk_daily(
            symbol=[code], start_date=start_date, end_date=end_date, fields=_FIELDS
        )
    import tqx_data  # type: ignore[import-untyped]

    return tqx_data.get_us_daily(
        symbol=[_to_us_symbol(code)],
        start_date=start_date,
        end_date=end_date,
        fields=_FIELDS + ["amount"],
    )


def _clean_close_frame(df):
    """DataFrame with columns date(str) + close(float), ascending, NaN dropped."""
    import pandas as pd  # noqa: PLC0415

    if df is None or not hasattr(df, "empty") or df.empty:
        return None
    if "close" not in df.columns:
        return None
    work = df.copy()
    if "date" in work.columns:
        work = work.sort_values("date")
        dates = work["date"].astype(str).tolist()
    else:
        dates = [str(i) for i in range(len(work))]
    close = pd.to_numeric(work["close"], errors="coerce")
    out = pd.DataFrame({"date": dates, "close": close.values}).dropna(subset=["close"])
    out = out.reset_index(drop=True)
    return out


def _finite(x, n: int = 6):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, n)


def _moving_average(series, period: int, ma_type: str):
    if ma_type == "ema":
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    return series.rolling(window=period, min_periods=period).mean()


def _default_window(lookback_days: int, slow_period: int, end_date: str) -> tuple[str, str]:
    end = end_date.strip() if end_date else date.today().strftime("%Y%m%d")
    try:
        end_dt = date(int(end[0:4]), int(end[4:6]), int(end[6:8]))
    except (ValueError, IndexError):
        end_dt = date.today()
        end = end_dt.strftime("%Y%m%d")
    # Ensure enough rows for slow MA + some crossover history.
    target = max(lookback_days, int(slow_period * 2.5) + 10)
    buffer_days = int(target * 1.6) + 15
    start = (end_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
    return start, end


async def run(
    stock_code: str,
    market: str = "auto",
    fast_period: int = 5,
    slow_period: int = 20,
    ma_type: str = "sma",
    start_date: str = "",
    end_date: str = "",
    lookback_days: int = 120,
    max_signals: int = 5,
) -> str:
    try:
        code = (stock_code or "").strip()
        if not code:
            return "Error: stock_code 不能为空"
        if not _SYMBOL_RE.match(code):
            return (
                f"Error: 非法 stock_code={code!r}: 只允许字母/数字/`.`/`_`/`-`。"
                "示例: A 股 `600519`；港股 `0700.HK`；美股 `AAPL.NB`。"
            )

        resolved = _resolve_market(code, market)
        if resolved not in ("cn", "hk", "us"):
            return (
                f"Error: market={market!r} 不合法且无法从 stock_code 推断市场。"
                "请显式传 `cn`/`hk`/`us`，或给 stock_code 加 .HK / .NB 后缀。"
            )

        try:
            fast = max(int(fast_period), 1)
            slow = max(int(slow_period), 2)
        except (TypeError, ValueError):
            return f"Error: fast_period/slow_period 不是合法整数 ({fast_period!r}/{slow_period!r})"
        if fast >= slow:
            return f"Error: fast_period({fast}) 必须小于 slow_period({slow})。"

        mtype = (ma_type or "sma").strip().lower()
        if mtype not in ("sma", "ema"):
            return f"Error: ma_type={ma_type!r} 不合法，只支持 'sma' / 'ema'。"

        try:
            lookback = max(int(lookback_days), slow)
        except (TypeError, ValueError):
            lookback = 120
        try:
            n_signals = max(int(max_signals), 1)
        except (TypeError, ValueError):
            n_signals = 5

        start = start_date.strip() if start_date else ""
        end = end_date.strip() if end_date else ""
        if not start:
            start, end = _default_window(lookback, slow, end)
        elif not end:
            end = date.today().strftime("%Y%m%d")

        try:
            df = _fetch_daily(code, resolved, start, end)
        except ImportError as exc:
            pkg = "panda_data" if resolved == "cn" else "tqx_data"
            return f"Error: 数据源 {pkg} 未安装/不可用: {exc}"
        except Exception as exc:
            return f"Error: 获取日线失败 (market={resolved}, symbol={code}): {exc}"

        frame = _clean_close_frame(df)
        if frame is None or frame.shape[0] < slow:
            got = 0 if frame is None else int(frame.shape[0])
            return (
                f"Error: {code} 在 {start}~{end} 内收盘价样本不足（得到 {got} 条，"
                f"至少需要 slow_period={slow} 条才能算慢均线）。请放宽日期区间。"
            )

        close = frame["close"].astype(float)
        fast_ma = _moving_average(close, fast, mtype)
        slow_ma = _moving_average(close, slow, mtype)

        valid = fast_ma.notna() & slow_ma.notna()
        diff = (fast_ma - slow_ma)[valid]
        idxs = diff.index.tolist()

        # Detect crossovers by sign change of (fast - slow).
        signals: list[dict] = []
        prev = None
        for i in idxs:
            cur = float(diff.loc[i])
            if prev is not None:
                p_sign = 1 if prev > 0 else (-1 if prev < 0 else 0)
                c_sign = 1 if cur > 0 else (-1 if cur < 0 else 0)
                if p_sign <= 0 and c_sign > 0:
                    signals.append({"type": "golden", "pos": int(i)})
                elif p_sign >= 0 and c_sign < 0:
                    signals.append({"type": "death", "pos": int(i)})
            prev = cur

        last_pos = frame.index[-1]
        last_close = float(close.iloc[-1])
        last_fast = float(fast_ma.iloc[-1]) if fast_ma.notna().iloc[-1] else None
        last_slow = float(slow_ma.iloc[-1]) if slow_ma.notna().iloc[-1] else None

        state = None
        ma_gap_pct = None
        price_bias_pct = None
        if last_fast is not None and last_slow is not None:
            state = "bullish" if last_fast >= last_slow else "bearish"
            if last_slow != 0:
                ma_gap_pct = (last_fast - last_slow) / last_slow
                price_bias_pct = (last_close - last_slow) / last_slow

        last_cross = None
        if signals:
            s = signals[-1]
            pos = s["pos"]
            last_cross = {
                "type": s["type"],
                "date": str(frame.loc[pos, "date"]),
                "bars_ago": int(last_pos - pos),
                "close": _finite(float(frame.loc[pos, "close"])),
            }

        recent = [
            {
                "type": s["type"],
                "date": str(frame.loc[s["pos"], "date"]),
                "close": _finite(float(frame.loc[s["pos"], "close"])),
            }
            for s in signals[-n_signals:]
        ]

        result = {
            "stock_code": code,
            "market": resolved,
            "start_date": start,
            "end_date": end,
            "observations": int(frame.shape[0]),
            "ma_type": mtype,
            "fast_period": fast,
            "slow_period": slow,
            "last_close": _finite(last_close),
            "fast_ma": _finite(last_fast),
            "slow_ma": _finite(last_slow),
            "state": state,
            "ma_gap_pct": _finite(ma_gap_pct),
            "price_bias_pct": _finite(price_bias_pct),
            "last_cross": last_cross,
            "recent_signals": recent,
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error("[skill ma_crossover_signal] error=%s", exc, exc_info=True)
        return f"Error: {type(exc).__name__}: {exc}"


if __name__ == "__main__":
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="ma_crossover_signal skill — standalone runner")
    ap.add_argument("stock_code")
    ap.add_argument("--market", default="auto", choices=["auto", "cn", "hk", "us"])
    ap.add_argument("--fast-period", type=int, default=5)
    ap.add_argument("--slow-period", type=int, default=20)
    ap.add_argument("--ma-type", default="sma", choices=["sma", "ema"])
    ap.add_argument("--start-date", default="")
    ap.add_argument("--end-date", default="")
    ap.add_argument("--lookback-days", type=int, default=120)
    ap.add_argument("--max-signals", type=int, default=5)
    a = ap.parse_args()
    print(asyncio.run(run(a.stock_code, a.market, a.fast_period, a.slow_period,
                          a.ma_type, a.start_date, a.end_date, a.lookback_days, a.max_signals)))
