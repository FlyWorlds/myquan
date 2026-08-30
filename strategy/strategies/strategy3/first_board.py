"""策略三·首板晋级：昨日首板 → 次日因子1开盘突破。

规则:
  · 宇宙: 中证1000（剔 ST/北交）
  · 首板: 当日收盘涨停，且前 5 个交易日均未收盘涨停；剔除首板日一字（locked）
  · 次日: 因子1 ±entry_pct 突破买入；前日为涨停不过滤阴/小阳
  · 不买: 一字涨停开盘、秒板（直线封板）、未触买点
  · 卖出: 因子1 开盘止损；一字跌停封单不卖
  · 组合: 100万、最多10仓、槽位净值/10
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import (  # noqa: E402
    TICK_SIZE,
    cannot_buy_limit_up,
    entry_trigger_price,
    is_miaoban_unbuyable,
    limit_down_state,
    limit_up_state,
    stop_trigger_price,
)
from backtest.universe_zz500_1000 import (  # noqa: E402
    CACHE_DIR as UNIV_CACHE,
    CSINDEX_CONS_URL,
    _to_symbol,
)

OUT = _MYQUAN / "backtest" / "strategy3_first_board"
SECOND_BOARD_BARS = _MYQUAN / "backtest" / "second_board" / "bars"
LU_TOL = 0.012
# 首板：涨停日前 N 个交易日均无收盘涨停（近五日未涨停）
FIRST_BOARD_LU_FREE_DAYS = 5
INITIAL = 1_000_000.0
MAX_POS = 1
MAX_ENTRIES_PER_DAY = 1
EXIT_MODE = "t1"  # t1=晋级日买、次日止损或收盘清；cont=因子1持有至止损
MAX_HOLD_DAYS = 3
TARGET_PCT = 0.95
LOT = 100
WORKERS = 8
ORIGIN = pd.Timestamp("2020-01-01")
GAP_MIN = -0.045
GAP_MAX = -0.003
MIN_VOL_RATIO = 1.4
REQUIRE_FB_OPENED = True
# first_board=首板+gap/量比；yesterday_lu=昨日收盘涨停全池（与盯盘一致）
POOL_MODE = "first_board"
# 情绪门槛：均取晋级日前一交易日（SENTIMENT_LAG=1），避免收盘统计前视
SENTIMENT_LAG = 1
MKT_LU_MIN: int | None = None
MKT_LU_MAX: int | None = None
MKT_LIANBAN_MIN: int | None = 2
MKT_MAX_HEIGHT_MIN: int | None = 2
MKT_MAX_HEIGHT_MAX: int | None = 5
MKT_LADDER_SCORE_MIN: int | None = None

_SENTIMENT: pd.DataFrame | None = None
_SENTIMENT_PREV: dict[str, str | None] = {}


def limit_ratio(code: str) -> float:
    c = str(code).zfill(6)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def load_zz1000(*, allow_network: bool = True) -> pd.DataFrame:
    cache = OUT / "zz1000_univ.parquet"
    if cache.is_file():
        return pd.read_parquet(cache)

    if not allow_network:
        raise RuntimeError("无本地 zz1000_univ.parquet 且已禁用网络拉取")

    url = CSINDEX_CONS_URL.format(code="000852")
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(3)
    df = pd.read_excel(io.BytesIO(r.content))
    code_col = next(
        c for c in df.columns if "成份券代码" in str(c) or "Constituent Code" in str(c)
    )
    name_col = next(
        c
        for c in df.columns
        if ("成份券名称" in str(c) or "Constituent Name" in str(c)) and "Eng" not in str(c)
    )
    rows = []
    for _, row in df.iterrows():
        c = str(row[code_col]).zfill(6)
        if c.startswith(("8", "4")):
            continue
        name = str(row[name_col]).strip()
        if "ST" in name.upper():
            continue
        rows.append({"code": c, "name": name, "symbol": _to_symbol(c)})
    out = pd.DataFrame(rows).drop_duplicates("code")
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def ensure_daily(univ: pd.DataFrame) -> None:
    UNIV_CACHE.mkdir(parents=True, exist_ok=True)
    missing = [
        r
        for _, r in univ.iterrows()
        if not (UNIV_CACHE / f"{r['symbol']}_daily_qfq.parquet").exists()
    ]
    print(f"缺日线: {len(missing)} / {len(univ)}")
    for i, r in enumerate(missing, 1):
        try:
            fetch_daily(
                r["symbol"],
                "20190101",
                pd.Timestamp.today().strftime("%Y%m%d"),
                cache_path=UNIV_CACHE / f"{r['symbol']}_daily_qfq.parquet",
            )
        except Exception as e:  # noqa: BLE001
            print(f"  fail {r['symbol']}: {e}")
        if i % 25 == 0:
            print(f"  拉取 {i}/{len(missing)}")


def _sentiment_cache_path() -> Path:
    return OUT / "mkt_sentiment_zz1000.parquet"


def _legacy_mkt_lu_cache_path() -> Path:
    return OUT / "mkt_lu_zz1000.parquet"


def _streak_from_lu(lu: np.ndarray) -> np.ndarray:
    streak = np.zeros(len(lu), dtype=int)
    for i in range(len(lu)):
        if lu[i]:
            streak[i] = (streak[i - 1] + 1) if i > 0 else 1
    return streak


def build_market_sentiment(univ: pd.DataFrame, *, rebuild: bool = False) -> pd.DataFrame:
    """按日统计宇宙情绪：涨停家数、连板梯队、最高板、梯度得分。"""
    cache = _sentiment_cache_path()
    if cache.exists() and not rebuild:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        return df.sort_values("date").reset_index(drop=True)

    lu_cnt: dict[pd.Timestamp, int] = {}
    lianban_cnt: dict[pd.Timestamp, int] = {}
    max_height: dict[pd.Timestamp, int] = {}
    ladder_score: dict[pd.Timestamp, int] = {}

    for i, row in enumerate(univ.itertuples(index=False), 1):
        daily = load_bars(row.symbol)
        if daily is None:
            continue
        dates = pd.DatetimeIndex(daily["date"])
        c = daily["close"].to_numpy(float)
        h = daily["high"].to_numpy(float)
        prev = np.roll(c, 1)
        prev[0] = np.nan
        lim = limit_ratio(row.code)
        lu = np.zeros(len(c), dtype=bool)
        for j in range(1, len(c)):
            pc = float(prev[j])
            if pc > 0:
                lu[j] = is_limit_up_close(pc, float(c[j]), float(h[j]), lim)
        streak = _streak_from_lu(lu)
        for j in range(1, len(c)):
            if not lu[j]:
                continue
            d = pd.Timestamp(dates[j]).normalize()
            st = int(streak[j])
            lu_cnt[d] = lu_cnt.get(d, 0) + 1
            if st >= 2:
                lianban_cnt[d] = lianban_cnt.get(d, 0) + 1
                ladder_score[d] = ladder_score.get(d, 0) + st
            max_height[d] = max(max_height.get(d, 0), st)
        if i % 100 == 0 or i == len(univ):
            print(f"  sentiment {i}/{len(univ)}")

    all_dates = sorted(set(lu_cnt) | set(max_height))
    rows = []
    for d in all_dates:
        rows.append(
            {
                "date": d,
                "mkt_lu": int(lu_cnt.get(d, 0)),
                "mkt_lianban": int(lianban_cnt.get(d, 0)),
                "mkt_max_height": int(max_height.get(d, 0)),
                "mkt_ladder_score": int(ladder_score.get(d, 0)),
            }
        )
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def build_mkt_lu_series(univ: pd.DataFrame, *, rebuild: bool = False) -> pd.Series:
    df = build_market_sentiment(univ, rebuild=rebuild)
    return df.set_index("date")["mkt_lu"].sort_index()


def _load_sentiment() -> pd.DataFrame:
    global _SENTIMENT, _SENTIMENT_PREV
    if _SENTIMENT is not None:
        return _SENTIMENT
    cache = _sentiment_cache_path()
    if not cache.is_file() and _legacy_mkt_lu_cache_path().is_file():
        legacy = pd.read_parquet(_legacy_mkt_lu_cache_path())
        legacy["mkt_lianban"] = 0
        legacy["mkt_max_height"] = 0
        legacy["mkt_ladder_score"] = 0
        legacy.to_parquet(cache, index=False)
    if not cache.is_file():
        _SENTIMENT = pd.DataFrame()
        _SENTIMENT_PREV = {}
        return _SENTIMENT
    df = pd.read_parquet(cache)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values("date").reset_index(drop=True)
    ds = [str(d.date()) for d in df["date"]]
    _SENTIMENT_PREV = {ds[i]: ds[i - 1] if i > 0 else None for i in range(len(ds))}
    _SENTIMENT = df.set_index("date")
    return _SENTIMENT


def _sentiment_ref_date(trade_date: str) -> str | None:
    d: str | None = trade_date
    for _ in range(max(SENTIMENT_LAG, 0)):
        if d is None:
            return None
        d = _SENTIMENT_PREV.get(d)
    return d


def sentiment_row(trade_date: str) -> tuple[str | None, dict[str, int | None]]:
    df = _load_sentiment()
    ref = _sentiment_ref_date(trade_date)
    if ref is None or df.empty:
        return None, {}
    ts = pd.Timestamp(ref).normalize()
    if ts not in df.index:
        return ref, {}
    row = df.loc[ts]
    return ref, {
        "sentiment_date": ref,
        "mkt_lu": int(row["mkt_lu"]),
        "mkt_lianban": int(row["mkt_lianban"]),
        "mkt_max_height": int(row["mkt_max_height"]),
        "mkt_ladder_score": int(row["mkt_ladder_score"]),
    }


def sentiment_passes(trade_date: str) -> tuple[bool, dict[str, int | str | None]]:
    ref, m = sentiment_row(trade_date)
    if ref is None or not m:
        no_gate = all(
            x is None
            for x in (
                MKT_LU_MIN,
                MKT_LU_MAX,
                MKT_LIANBAN_MIN,
                MKT_MAX_HEIGHT_MIN,
                MKT_MAX_HEIGHT_MAX,
                MKT_LADDER_SCORE_MIN,
            )
        )
        return no_gate, {**m, "sentiment_date": ref}

    lu = m.get("mkt_lu")
    lianban = m.get("mkt_lianban")
    height = m.get("mkt_max_height")
    ladder = m.get("mkt_ladder_score")

    if MKT_LU_MIN is not None and (lu is None or lu < MKT_LU_MIN):
        return False, m
    if MKT_LU_MAX is not None and (lu is None or lu > MKT_LU_MAX):
        return False, m
    if MKT_LIANBAN_MIN is not None and (lianban is None or lianban < MKT_LIANBAN_MIN):
        return False, m
    if MKT_MAX_HEIGHT_MIN is not None and (height is None or height < MKT_MAX_HEIGHT_MIN):
        return False, m
    if MKT_MAX_HEIGHT_MAX is not None and (height is None or height > MKT_MAX_HEIGHT_MAX):
        return False, m
    if MKT_LADDER_SCORE_MIN is not None and (ladder is None or ladder < MKT_LADDER_SCORE_MIN):
        return False, m
    return True, m


def get_mkt_lu_map() -> dict[str, int]:
    df = _load_sentiment()
    if df.empty:
        return {}
    return {str(pd.Timestamp(d).date()): int(v) for d, v in df["mkt_lu"].items()}


def mkt_lu_passes(trade_date: str) -> tuple[bool, int | None]:
    ok, m = sentiment_passes(trade_date)
    return ok, m.get("mkt_lu") if m else None


def load_bars(symbol: str) -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[d["date"] >= pd.Timestamp("2019-01-01")].reset_index(drop=True)
    return d if len(d) >= 40 else None


def is_limit_up_close(
    prev_close: float,
    close: float,
    high: float,
    lim: float,
) -> bool:
    if prev_close <= 0 or close <= 0:
        return False
    pct = close / prev_close - 1.0
    return pct >= lim - LU_TOL and close >= high * 0.995


def mark_first_board(
    lu: np.ndarray,
    *,
    lookback: int = FIRST_BOARD_LU_FREE_DAYS,
) -> np.ndarray:
    """首板掩码：lu[i] 且 lu[i-lookback:i] 全为 False。"""
    out = np.zeros(len(lu), dtype=bool)
    lb = max(int(lookback), 1)
    for i in range(lb, len(lu)):
        if lu[i] and not lu[i - lb : i].any():
            out[i] = True
    return out


def is_first_board_at(
    lu: np.ndarray,
    i: int,
    *,
    lookback: int = FIRST_BOARD_LU_FREE_DAYS,
) -> bool:
    lb = max(int(lookback), 1)
    if i < lb or not bool(lu[i]):
        return False
    return not lu[i - lb : i].any()


def process_symbol(task: dict) -> dict:
    symbol = task["symbol"]
    code = task["code"]
    name = task["name"]
    entry_pct = float(task["entry_pct"])
    out: dict[str, Any] = {
        "symbol": symbol,
        "code": code,
        "name": name,
        "signals": [],
        "ok": 0,
        "error": "",
    }
    daily = load_bars(symbol)
    if daily is None:
        out["error"] = "no_daily"
        return out

    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    vol = daily["volume"].to_numpy(float) if "volume" in daily.columns else np.ones(len(daily))
    prev = np.roll(c, 1)
    prev[0] = np.nan
    lim = limit_ratio(code)

    lu = np.zeros(len(c), dtype=bool)
    for i in range(1, len(c)):
        pc = float(prev[i])
        if pc > 0:
            lu[i] = is_limit_up_close(pc, float(c[i]), float(h[i]), lim)

    first_board = mark_first_board(lu)
    pool_mode = str(task.get("pool_mode") or POOL_MODE)

    for i in range(1, len(c) - 1):
        pc_fb = float(prev[i]) if np.isfinite(prev[i]) else 0.0
        st_fb = limit_up_state(
            prev_close=pc_fb if pc_fb > 0 else None,
            open_px=float(o[i]),
            high_px=float(h[i]),
            low_px=float(l[i]),
            close_px=float(c[i]),
            limit_up_pct=lim,
        )
        if pool_mode == "yesterday_lu":
            if not lu[i]:
                continue
        else:
            if not first_board[i]:
                continue
            # 首板日一字：晋级质量差，剔除
            if bool(st_fb["locked"]):
                continue
            if REQUIRE_FB_OPENED and not bool(st_fb["opened"]):
                continue

        j = i + 1
        if dates[j] < ORIGIN:
            continue

        oj, hj, lj, cj = float(o[j]), float(h[j]), float(l[j]), float(c[j])
        fb_close = float(c[i])
        if fb_close <= 0:
            continue
        gap = oj / fb_close - 1.0
        vwin = vol[max(0, i - 20) : i + 1]
        vol_ratio = float(vol[i]) / float(np.mean(vwin)) if len(vwin) and np.mean(vwin) > 0 else 1.0
        if pool_mode != "yesterday_lu":
            if vol_ratio < MIN_VOL_RATIO:
                continue
            if gap < GAP_MIN or gap > GAP_MAX:
                continue
        trade_ds = str(dates[j].date())
        sent_ok, sent = sentiment_passes(trade_ds)
        if not sent_ok:
            continue
        if pool_mode != "yesterday_lu":
            # 首板日秒板（直线封板）质量差，剔除
            if is_miaoban_unbuyable(
                prev_close=pc_fb if pc_fb > 0 else None,
                open_px=float(o[i]),
                high_px=float(h[i]),
                low_px=float(l[i]),
                close_px=float(c[i]),
                limit_up_pct=lim,
                entry_pct=entry_pct,
            ):
                continue

        pc_j = float(prev[j]) if np.isfinite(prev[j]) else 0.0
        if oj <= 0 or pc_j <= 0:
            continue

        reason = ""
        entry = False
        if cannot_buy_limit_up(
            prev_close=pc_j,
            open_px=oj,
            high_px=hj,
            low_px=lj,
            close_px=cj,
            limit_up_pct=lim,
        ):
            reason = "一字涨停开盘"
        elif is_miaoban_unbuyable(
            prev_close=pc_j,
            open_px=oj,
            high_px=hj,
            low_px=lj,
            close_px=cj,
            limit_up_pct=lim,
            entry_pct=entry_pct,
        ):
            reason = "秒板"
        else:
            buy_px = entry_trigger_price(oj, entry_pct=entry_pct)
            if hj + 1e-12 < buy_px:
                reason = "未触买点"
            else:
                entry = True
                reason = "买入"

        out["signals"].append(
            {
                "first_board_date": str(dates[i].date()),
                "trade_date": str(dates[j].date()),
                "symbol": symbol,
                "code": code,
                "name": name,
                "entry_pct": entry_pct,
                "entry": entry,
                "reason": reason,
                "buy_px": float(entry_trigger_price(oj, entry_pct=entry_pct))
                if oj > 0
                else np.nan,
                "buy_i": j,
                "fb_i": i,
                "fb_opened": bool(st_fb["opened"]),
                "gap_pct": round(gap * 100, 2),
                "vol_ratio": round(vol_ratio, 2),
                "sentiment_date": sent.get("sentiment_date"),
                "mkt_lu": sent.get("mkt_lu"),
                "mkt_lianban": sent.get("mkt_lianban"),
                "mkt_max_height": sent.get("mkt_max_height"),
                "mkt_ladder_score": sent.get("mkt_ladder_score"),
                "rank_score": round(
                    (2.0 if bool(st_fb["opened"]) else 0.0)
                    + min(vol_ratio, 5.0)
                    - abs(gap) * 10,
                    3,
                ),
            }
        )

    npz_path = OUT / "bars" / f"{symbol}.npz"
    sb_bar = SECOND_BOARD_BARS / f"{symbol}.npz"
    if not npz_path.exists() and not sb_bar.exists():
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            npz_path,
            dates=np.array([str(x.date()) for x in dates]),
            open=o,
            high=h,
            low=l,
            close=c,
            prev_close=prev,
            lim=np.array([lim]),
        )
    out["ok"] = 1
    return out


@dataclass
class Pos:
    symbol: str
    code: str
    name: str
    entry_pct: float
    shares: float
    entry_px: float
    buy_date: pd.Timestamp
    buy_i: int
    hold_days: int = 0


def _resolve_bar_path(sym: str) -> Path:
    for base in (OUT / "bars", SECOND_BOARD_BARS):
        p = base / f"{sym}.npz"
        if p.is_file():
            return p
    return OUT / "bars" / f"{sym}.npz"


def run_portfolio(signals: pd.DataFrame, *, entry_pct: float) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    sample = _resolve_bar_path(next(iter(signals["symbol"])) if len(signals) else "sh600000")
    if not sample.is_file():
        sample = next(SECOND_BOARD_BARS.glob("*.npz"))
    cal = pd.to_datetime(np.load(sample)["dates"])
    cal = cal[cal >= ORIGIN]

    bar_cache: dict[str, dict] = {}

    def bars(sym: str) -> dict:
        if sym not in bar_cache:
            p = _resolve_bar_path(sym)
            z = np.load(p, allow_pickle=True)
            dates = pd.to_datetime(z["dates"])
            bar_cache[sym] = {
                "dates": dates,
                "idx": {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
                "open": z["open"],
                "high": z["high"],
                "low": z["low"],
                "close": z["close"],
                "prev": z["prev_close"],
                "lim": float(z["lim"][0]),
            }
        return bar_cache[sym]

    entries = signals[signals["entry"] == True].copy()  # noqa: E712
    by_day = {d: g for d, g in entries.groupby("trade_date")}

    cash = INITIAL
    positions: list[Pos] = []
    equity_rows: list[dict] = []
    trades: list[dict] = []

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        ds = str(dt.date())

        still: list[Pos] = []
        for p in positions:
            b = bars(p.symbol)
            j = b["idx"].get(dt)
            if j is None:
                still.append(p)
                continue
            oi, hi, li, ci = (
                float(b["open"][j]),
                float(b["high"][j]),
                float(b["low"][j]),
                float(b["close"][j]),
            )
            stop_px = stop_trigger_price(oi, stop_pct=p.entry_pct)
            sold = False
            sell_px = None
            reason = ""
            p.hold_days += 1
            if EXIT_MODE == "t1" and j > p.buy_i:
                buy_dates = sorted(d for d in b["idx"] if d > p.buy_date)
                if not buy_dates:
                    still.append(p)
                    continue
                t1_date = buy_dates[0]
                if dt == t1_date:
                    if li <= stop_px + 1e-12:
                        prev_c = float(b["prev"][j]) if np.isfinite(b["prev"][j]) else ci
                        lims = limit_down_state(
                            prev_close=prev_c,
                            open_px=oi,
                            high_px=hi,
                            low_px=li,
                            close_px=ci,
                            limit_down_pct=b["lim"],
                            tick=TICK_SIZE,
                        )
                        if bool(lims["locked"]):
                            still.append(p)
                            continue
                        sell_px = float(
                            lims["limit_px"] if bool(lims["opened"]) else stop_px
                        ) * (1 - SLIP)
                        reason = "T+1止损"
                    else:
                        sell_px = ci * (1 - SLIP)
                        reason = "T+1收盘清仓"
                    sold = True
                elif dt > t1_date:
                    sell_px = ci * (1 - SLIP)
                    reason = "逾期清仓"
                    sold = True
                else:
                    still.append(p)
                    continue
            elif EXIT_MODE != "t1" and j > p.buy_i and li <= stop_px + 1e-12:
                prev_c = float(b["prev"][j]) if np.isfinite(b["prev"][j]) else ci
                lims = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=b["lim"],
                    tick=TICK_SIZE,
                )
                if bool(lims["locked"]):
                    still.append(p)
                    continue
                sell_px = float(lims["limit_px"] if bool(lims["opened"]) else stop_px) * (
                    1 - SLIP
                )
                reason = "因子1止损"
                sold = True
            elif (
                EXIT_MODE == "cont"
                and p.hold_days >= MAX_HOLD_DAYS
                and j > p.buy_i
            ):
                sell_px = ci * (1 - SLIP)
                reason = f"持有{MAX_HOLD_DAYS}日清仓"
                sold = True

            if sold and sell_px is not None:
                proceeds = p.shares * sell_px
                fee = proceeds * (COMMISSION + STAMP)
                cash += proceeds - fee
                trades.append(
                    {
                        "entry_pct": p.entry_pct,
                        "symbol": p.symbol,
                        "code": p.code,
                        "name": p.name,
                        "buy_date": str(p.buy_date.date()),
                        "sell_date": ds,
                        "buy_px": p.entry_px,
                        "sell_px": sell_px,
                        "ret_pct": (sell_px / p.entry_px - 1.0) * 100,
                        "reason": reason,
                    }
                )
            else:
                still.append(p)
        positions = still

        free = MAX_POS - len(positions)
        if free > 0 and ds in by_day:
            cands = by_day[ds]
            held = {p.symbol for p in positions}
            cands = cands[~cands["symbol"].isin(held)].sort_values(
                ["rank_score", "symbol"], ascending=[False, True]
            )
            if MAX_ENTRIES_PER_DAY > 0:
                cands = cands.head(MAX_ENTRIES_PER_DAY)
            nav = cash
            for p in positions:
                b = bars(p.symbol)
                j = b["idx"].get(dt)
                if j is not None:
                    nav += p.shares * float(b["close"][j])
                else:
                    nav += p.shares * p.entry_px
            alloc = nav / MAX_POS
            for _, row in cands.iterrows():
                if free <= 0 or cash < alloc * 0.5:
                    break
                sym = row["symbol"]
                b = bars(sym)
                j = b["idx"].get(dt)
                if j is None:
                    continue
                buy_px = float(row["buy_px"]) * (1 + SLIP)
                budget = min(cash * TARGET_PCT, alloc * TARGET_PCT)
                raw = math.floor(budget / (buy_px * LOT)) * LOT
                if raw < LOT:
                    continue
                cost = raw * buy_px
                fee = cost * COMMISSION
                if cost + fee > cash:
                    continue
                cash -= cost + fee
                positions.append(
                    Pos(
                        symbol=sym,
                        code=row["code"],
                        name=row["name"],
                        entry_pct=entry_pct,
                        shares=float(raw),
                        entry_px=buy_px,
                        buy_date=dt,
                        buy_i=j,
                    )
                )
                free -= 1

        nav = cash
        for p in positions:
            b = bars(p.symbol)
            j = b["idx"].get(dt)
            nav += p.shares * (
                float(b["close"][j]) if j is not None else p.entry_px
            )
        equity_rows.append(
            {"date": ds, "equity": nav, "n_pos": len(positions), "cash": cash}
        )

    eq = pd.DataFrame(equity_rows)
    eq["date"] = pd.to_datetime(eq["date"])
    e0, e1 = float(eq.equity.iloc[0]), float(eq.equity.iloc[-1])
    rets = eq.equity.pct_change().dropna()
    peak = eq.equity.cummax()
    max_dd = float(-(eq.equity / peak - 1).min()) * 100
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * math.sqrt(242))
        if len(rets) > 5 and rets.std(ddof=1) > 0
        else 0.0
    )
    tr = pd.DataFrame(trades)
    summary = {
        "entry_pct": entry_pct,
        "start": str(eq.date.iloc[0].date()),
        "end": str(eq.date.iloc[-1].date()),
        "total_return_pct": (e1 / e0 - 1) * 100,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "end_equity": e1,
        "n_trades": len(tr),
        "win_rate": float((tr.ret_pct > 0).mean()) if len(tr) else np.nan,
        "avg_trade_ret": float(tr.ret_pct.mean()) if len(tr) else np.nan,
        "avg_pos": float(eq.n_pos.mean()),
    }
    return eq, summary, tr


def _signal_cache_tag(entry_pct: float) -> str:
    tag = f"{entry_pct:.4f}".replace(".", "p")
    parts: list[str] = []
    if POOL_MODE == "yesterday_lu":
        parts.append("luall")
    if SENTIMENT_LAG:
        parts.append(f"lag{SENTIMENT_LAG}")
    if MKT_LU_MIN is not None or MKT_LU_MAX is not None:
        lo = MKT_LU_MIN if MKT_LU_MIN is not None else 0
        hi = MKT_LU_MAX if MKT_LU_MAX is not None else 999
        parts.append(f"lu{lo}_{hi}")
    if MKT_LIANBAN_MIN is not None:
        parts.append(f"lb{MKT_LIANBAN_MIN}")
    if MKT_MAX_HEIGHT_MIN is not None or MKT_MAX_HEIGHT_MAX is not None:
        lo = MKT_MAX_HEIGHT_MIN if MKT_MAX_HEIGHT_MIN is not None else 0
        hi = MKT_MAX_HEIGHT_MAX if MKT_MAX_HEIGHT_MAX is not None else 99
        parts.append(f"h{lo}_{hi}")
    if MKT_LADDER_SCORE_MIN is not None:
        parts.append(f"ls{MKT_LADDER_SCORE_MIN}")
    if parts:
        tag = f"{tag}_{'_'.join(parts)}"
    return tag


def _sentiment_cfg() -> dict[str, int | None | str]:
    return {
        "POOL_MODE": POOL_MODE,
        "MKT_LU_MIN": MKT_LU_MIN,
        "MKT_LU_MAX": MKT_LU_MAX,
        "MKT_LIANBAN_MIN": MKT_LIANBAN_MIN,
        "MKT_MAX_HEIGHT_MIN": MKT_MAX_HEIGHT_MIN,
        "MKT_MAX_HEIGHT_MAX": MKT_MAX_HEIGHT_MAX,
        "MKT_LADDER_SCORE_MIN": MKT_LADDER_SCORE_MIN,
        "SENTIMENT_LAG": SENTIMENT_LAG,
    }


def _init_worker_sentiment(cfg: dict[str, int | None | str]) -> None:
    global POOL_MODE, MKT_LU_MIN, MKT_LU_MAX, MKT_LIANBAN_MIN
    global MKT_MAX_HEIGHT_MIN, MKT_MAX_HEIGHT_MAX, MKT_LADDER_SCORE_MIN
    global SENTIMENT_LAG, _SENTIMENT, _SENTIMENT_PREV
    POOL_MODE = str(cfg.get("POOL_MODE") or "first_board")
    MKT_LU_MIN = cfg.get("MKT_LU_MIN")
    MKT_LU_MAX = cfg.get("MKT_LU_MAX")
    MKT_LIANBAN_MIN = cfg.get("MKT_LIANBAN_MIN")
    MKT_MAX_HEIGHT_MIN = cfg.get("MKT_MAX_HEIGHT_MIN")
    MKT_MAX_HEIGHT_MAX = cfg.get("MKT_MAX_HEIGHT_MAX")
    MKT_LADDER_SCORE_MIN = cfg.get("MKT_LADDER_SCORE_MIN")
    SENTIMENT_LAG = int(cfg.get("SENTIMENT_LAG") or 0)
    _SENTIMENT = None
    _SENTIMENT_PREV = {}
    _load_sentiment()


def build_signals(entry_pct: float, univ: pd.DataFrame, *, rebuild: bool = False) -> pd.DataFrame:
    tag = _signal_cache_tag(entry_pct)
    sig_cache = OUT / f"signals_{tag}.parquet"
    if sig_cache.exists() and not rebuild:
        return pd.read_parquet(sig_cache)

    global _SENTIMENT, _SENTIMENT_PREV
    _SENTIMENT = None
    _SENTIMENT_PREV = {}
    if not _sentiment_cache_path().is_file():
        build_market_sentiment(univ, rebuild=rebuild)
    _load_sentiment()

    tasks = [
        {**r, "entry_pct": entry_pct, "pool_mode": POOL_MODE}
        for r in univ.to_dict(orient="records")
    ]
    rows: list[dict] = []
    t0 = time.time()
    cfg = _sentiment_cfg()
    with ProcessPoolExecutor(
        max_workers=WORKERS,
        initializer=_init_worker_sentiment,
        initargs=(cfg,),
    ) as ex:
        futs = {ex.submit(process_symbol, t): t for t in tasks}
        done = 0
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            rows.extend(res.get("signals") or [])
            if done % 50 == 0 or done == len(tasks):
                print(f"  信号 thr={entry_pct*100:.1f}% {done}/{len(tasks)} ({time.time()-t0:.0f}s)")
    signals = pd.DataFrame(rows)
    signals.to_parquet(sig_cache, index=False)
    return signals


def run_first_board_promotion_backtest(
    *,
    start: str = "20200101",
    end: str | None = None,
    entry_pcts: tuple[float, ...] = (0.025, 0.03),
    initial_cash: float = INITIAL,
    max_positions: int = MAX_POS,
    max_hold_days: int = MAX_HOLD_DAYS,
    mkt_lu_min: int | None = MKT_LU_MIN,
    mkt_lu_max: int | None = MKT_LU_MAX,
    mkt_lianban_min: int | None = MKT_LIANBAN_MIN,
    mkt_max_height_min: int | None = MKT_MAX_HEIGHT_MIN,
    mkt_max_height_max: int | None = MKT_MAX_HEIGHT_MAX,
    mkt_ladder_score_min: int | None = MKT_LADDER_SCORE_MIN,
    sentiment_lag: int = SENTIMENT_LAG,
    pool_mode: str = POOL_MODE,
    rebuild_signals: bool = False,
) -> dict[str, Any]:
    """运行首板晋级组合回测（固定阈值，可多个）。"""
    global INITIAL, MAX_POS, MAX_HOLD_DAYS, POOL_MODE
    global MKT_LU_MIN, MKT_LU_MAX, MKT_LIANBAN_MIN
    global MKT_MAX_HEIGHT_MIN, MKT_MAX_HEIGHT_MAX, MKT_LADDER_SCORE_MIN
    global SENTIMENT_LAG, _SENTIMENT, _SENTIMENT_PREV
    POOL_MODE = str(pool_mode or "first_board")
    INITIAL = float(initial_cash)
    MAX_POS = int(max_positions)
    MAX_HOLD_DAYS = int(max_hold_days)
    MKT_LU_MIN = mkt_lu_min
    MKT_LU_MAX = mkt_lu_max
    MKT_LIANBAN_MIN = mkt_lianban_min
    MKT_MAX_HEIGHT_MIN = mkt_max_height_min
    MKT_MAX_HEIGHT_MAX = mkt_max_height_max
    MKT_LADDER_SCORE_MIN = mkt_ladder_score_min
    SENTIMENT_LAG = max(int(sentiment_lag), 0)
    _SENTIMENT = None
    _SENTIMENT_PREV = {}
    if rebuild_signals:
        for p in OUT.glob("signals_*.parquet"):
            p.unlink(missing_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    print("加载中证1000…")
    univ = load_zz1000()
    ensure_daily(univ)
    univ = univ[
        univ["symbol"].apply(
            lambda s: (UNIV_CACHE / f"{s}_daily_qfq.parquet").exists()
        )
    ].reset_index(drop=True)
    print(f"有日线 {len(univ)}")
    gates: list[str] = []
    if SENTIMENT_LAG:
        gates.append(f"T-{SENTIMENT_LAG}情绪")
    if MKT_LU_MIN is not None or MKT_LU_MAX is not None:
        gates.append(
            f"mkt_lu={MKT_LU_MIN if MKT_LU_MIN is not None else '—'}"
            f"～{MKT_LU_MAX if MKT_LU_MAX is not None else '—'}"
        )
    if MKT_LIANBAN_MIN is not None:
        gates.append(f"连板家数≥{MKT_LIANBAN_MIN}")
    if MKT_MAX_HEIGHT_MIN is not None or MKT_MAX_HEIGHT_MAX is not None:
        gates.append(
            f"最高板={MKT_MAX_HEIGHT_MIN if MKT_MAX_HEIGHT_MIN is not None else '—'}"
            f"～{MKT_MAX_HEIGHT_MAX if MKT_MAX_HEIGHT_MAX is not None else '—'}"
        )
    if MKT_LADDER_SCORE_MIN is not None:
        gates.append(f"梯度得分≥{MKT_LADDER_SCORE_MIN}")
    if gates:
        print("情绪门槛: " + " · ".join(gates))
    pool_label = "昨日涨停全池" if POOL_MODE == "yesterday_lu" else "首板晋级"
    print(f"股池: {pool_label}")
    build_market_sentiment(univ, rebuild=rebuild_signals)
    _load_sentiment()

    summaries = []
    for thr in entry_pcts:
        print(f"\n=== 阈值 ±{thr*100:.1f}% ===")
        signals = build_signals(thr, univ, rebuild=rebuild_signals)
        if start:
            signals = signals[signals["trade_date"] >= start[:4] + "-" + start[4:6] + "-" + start[6:8]]
        if end:
            signals = signals[signals["trade_date"] <= end[:4] + "-" + end[4:6] + "-" + end[6:8]]
        n_buy = int((signals["entry"] == True).sum()) if len(signals) else 0  # noqa: E712
        print(
            f"信号 {len(signals)} · 可买 {n_buy} · "
            f"一字 {(signals['reason']=='一字涨停开盘').sum() if len(signals) else 0} · "
            f"秒板 {(signals['reason']=='秒板').sum() if len(signals) else 0}"
        )
        eq, summary, tr = run_portfolio(signals, entry_pct=thr)
        summary["mkt_lu_min"] = MKT_LU_MIN
        summary["mkt_lu_max"] = MKT_LU_MAX
        summary["mkt_lianban_min"] = MKT_LIANBAN_MIN
        summary["mkt_max_height_min"] = MKT_MAX_HEIGHT_MIN
        summary["mkt_max_height_max"] = MKT_MAX_HEIGHT_MAX
        summary["mkt_ladder_score_min"] = MKT_LADDER_SCORE_MIN
        summary["sentiment_lag"] = SENTIMENT_LAG
        summary["pool_mode"] = POOL_MODE
        tag = _signal_cache_tag(thr)
        eq.to_csv(OUT / f"equity_{tag}.csv", index=False, encoding="utf-8-sig")
        tr.to_csv(OUT / f"trades_{tag}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summary)
        print(
            f"  收益 {summary['total_return_pct']:.1f}%  回撤 {summary['max_drawdown_pct']:.1f}%  "
            f"夏普 {summary['sharpe_ratio']:.2f}  胜率 {summary['win_rate']*100:.1f}%  "
            f"笔数 {summary['n_trades']}"
        )

    sum_df = pd.DataFrame(summaries)
    sum_df.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"summaries": summaries, "output_dir": str(OUT)}
