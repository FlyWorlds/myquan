"""盯盘实时行情：东财 SSE 推送 + 新浪批量快照兜底；本地 WebSocket 出站。"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.akq_math import price_chg_pct
import pandas as pd
import requests

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# 东财 SSE 字段：现价/开/高/低/昨收（fltt=2 时为真实价格）
_EM_FIELDS = "f43,f44,f45,f46,f60,f57,f58,f170,f168"
_EM_SSE_URLS = (
    "https://2.push2.eastmoney.com/api/qt/stock/sse",
    "https://push2.eastmoney.com/api/qt/stock/sse",
    "https://push2delay.eastmoney.com/api/qt/stock/sse",
)
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "text/event-stream",
}
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}

# 超过此时长没有 SSE tick / 新浪批量成功，视为外网行情中断（午休无成交仍会走新浪兜底）。
QUOTE_STALE_AFTER_SEC = 40.0


def sina_to_secid(sina: str) -> str:
    s = str(sina or "").strip().lower()
    if s.startswith("sh"):
        return f"1.{s[2:]}"
    if s.startswith("sz"):
        return f"0.{s[2:]}"
    if s.startswith(("6", "5", "9")):
        return f"1.{s}"
    return f"0.{s}"


def _fnum(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _quote_session_and_clock(ts: Any) -> tuple[str, str]:
    """行情戳 → (YYYY-MM-DD, HH:MM:SS)；缺失部分返回空串。"""
    s = str(ts or "").strip().replace("T", " ", 1)
    if len(s) >= 19 and s[4:5] == "-" and s[10:11] == " ":
        return s[:10], s[11:19]
    if len(s) >= 8 and s[2:3] == ":":
        return "", s[:8]
    return "", ""


def _open_is_final(ts: Any) -> bool:
    """9:25 开盘价核定后才允许该快照成为交易基准。"""
    _session, clock = _quote_session_and_clock(ts)
    return bool(clock and clock >= "09:25:00")


def _continuous_quote(ts: Any) -> bool:
    _session, clock = _quote_session_and_clock(ts)
    return ("09:30:00" <= clock <= "11:30:00") or (
        "13:00:00" <= clock < "15:00:00"
    )


def _open_result_only(ts: Any) -> bool:
    _session, clock = _quote_session_and_clock(ts)
    return "09:25:00" <= clock < "09:30:00"


def _auction_lock_quote(ts: Any) -> bool:
    """9:20–9:25 不可撤单竞价：只记独立路径，不进正式 OHLC。"""
    _session, clock = _quote_session_and_clock(ts)
    return "09:20:00" <= clock < "09:25:00"


@dataclass
class QuoteSnapshot:
    sina: str
    session: str
    open: float
    high: float
    low: float
    last: float
    prev_close: float | None
    day_chg_pct: float | None
    last_ts: str
    source: str = "seed"
    open_finalized: bool = False
    auction_baseline: float | None = None
    auction_high: float | None = None
    auction_low: float | None = None
    auction_ts: str = ""
    day_bars: Any = field(default=None, repr=False)

    def as_quote_dict(self) -> dict[str, Any]:
        bars = self.day_bars
        if bars is None:
            bars = pd.DataFrame()
        return {
            "session": self.session,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "last": float(self.last),
            "prev_close": None
            if self.prev_close is None
            else float(self.prev_close),
            "day_chg_pct": self.day_chg_pct,
            "last_ts": self.last_ts,
            "_day_bars": bars,
            "_quote_source": self.source,
            "_open_finalized": bool(self.open_finalized),
            # 兼容 session_open_usable：9:15–9:25 的指示价绝不能算买点。
            "_preopen_baseline": not bool(self.open_finalized),
            "_auction_baseline": self.auction_baseline,
            "_auction_high": self.auction_high,
            "_auction_low": self.auction_low,
            "_auction_ts": self.auction_ts or None,
        }


class QuoteHub:
    """线程安全的当日 OHLC 状态。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._quotes: dict[str, QuoteSnapshot] = {}
        self.updated = threading.Event()
        self._gen = 0
        self.sse_ok = False
        self.sse_last_ok_ts = 0.0
        self.quote_last_ok_ts = 0.0
        self.quote_last_ok_clock = ""
        self.source_last_ok: dict[str, tuple[float, str]] = {}

    def mark_quote_ok(self, source: str = "") -> None:
        """任意外网行情成功（SSE tick 或新浪批量）都刷新，供顶栏判断断网。"""
        now = time.time()
        clock = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.quote_last_ok_ts = now
        self.quote_last_ok_clock = clock
        src = str(source or "unknown").strip() or "unknown"
        self.source_last_ok[src] = (now, clock)
        if source in ("em_sse", "sse", ""):
            self.sse_ok = True
            self.sse_last_ok_ts = now

    def mark_sse_ok(self) -> None:
        self.mark_quote_ok("em_sse")

    def mark_sse_down(self) -> None:
        self.sse_ok = False

    def sse_healthy(self, *, max_age_sec: float = 15.0) -> bool:
        if not self.sse_ok:
            return False
        return (time.time() - self.sse_last_ok_ts) <= max_age_sec

    def quote_health(self, *, max_age_sec: float = QUOTE_STALE_AFTER_SEC) -> dict[str, Any]:
        last = float(self.quote_last_ok_ts or 0.0)
        had = last > 0
        age = (time.time() - last) if had else None
        ok = bool(had and age is not None and age <= float(max_age_sec))
        source_ages = {
            src: {
                "at": clock,
                "ageSec": round(time.time() - ts, 1),
                "ok": (time.time() - ts) <= float(max_age_sec),
            }
            for src, (ts, clock) in sorted(self.source_last_ok.items())
        }
        return {
            "feedOk": ok,
            "quoteStale": bool(had and not ok),
            "quoteAt": self.quote_last_ok_clock or None,
            "quoteAgeSec": None if age is None else round(age, 1),
            "dataSources": sorted(self.source_last_ok.keys()),
            "sourceAges": source_ages,
        }

    def seed_from_quote(self, sina: str, quote: dict[str, Any]) -> None:
        sina = str(sina).lower()
        snap = QuoteSnapshot(
            sina=sina,
            session=str(quote.get("session") or datetime.now().strftime("%Y-%m-%d")),
            open=float(quote["open"]),
            high=float(quote["high"]),
            low=float(quote["low"]),
            last=float(quote["last"]),
            prev_close=None
            if quote.get("prev_close") is None
            else float(quote["prev_close"]),
            day_chg_pct=quote.get("day_chg_pct"),
            last_ts=str(quote.get("last_ts") or ""),
            source="seed",
            open_finalized=bool(
                quote.get("_open_finalized")
                if quote.get("_open_finalized") is not None
                else _open_is_final(quote.get("last_ts"))
            ),
            auction_baseline=quote.get("_auction_baseline"),
            auction_high=quote.get("_auction_high"),
            auction_low=quote.get("_auction_low"),
            auction_ts=str(quote.get("_auction_ts") or ""),
            day_bars=quote.get("_day_bars"),
        )
        self._absorb_auction_path(
            snap,
            last=float(quote.get("last") or 0),
            last_ts=str(quote.get("last_ts") or ""),
        )
        with self._lock:
            self._quotes[sina] = snap
            self._gen += 1
            self.updated.set()

    def apply_tick(
        self,
        sina: str,
        *,
        last: float | None = None,
        high: float | None = None,
        low: float | None = None,
        open_px: float | None = None,
        prev_close: float | None = None,
        last_ts: str | None = None,
        source: str = "tick",
    ) -> bool:
        sina = str(sina).lower()
        tick_ts = str(last_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        tick_session, _tick_clock = _quote_session_and_clock(tick_ts)
        tick_open_final = _open_is_final(tick_ts)
        tick_continuous = _continuous_quote(tick_ts)
        tick_open_result = _open_result_only(tick_ts)
        with self._lock:
            cur = self._quotes.get(sina)
            if cur is None or (
                tick_session
                and str(cur.session or "")[:10]
                and tick_session != str(cur.session)[:10]
            ):
                if last is None or last <= 0:
                    return False
                o = float(open_px or last)
                # 竞价阶段不继承供应商累计 high/low；午休/收盘冷启动仍保留当日 OHLC。
                if tick_open_final and not tick_open_result:
                    h = max(float(high or last), float(last), o)
                    l0 = float(low or last)
                    l = min(l0, float(last), o) if l0 > 0 else min(float(last), o)
                else:
                    h = max(o, float(last))
                    l = min(o, float(last))
                pc = prev_close
                chg = price_chg_pct(last, pc)
                self._quotes[sina] = QuoteSnapshot(
                    sina=sina,
                    session=tick_session or datetime.now().strftime("%Y-%m-%d"),
                    open=o,
                    high=max(h, float(last)),
                    low=min(l, float(last)) if l > 0 else float(last),
                    last=float(last),
                    prev_close=pc,
                    day_chg_pct=chg,
                    last_ts=tick_ts,
                    source=source,
                    open_finalized=tick_open_final,
                )
                self._absorb_auction_path(
                    self._quotes[sina],
                    last=float(last),
                    last_ts=tick_ts,
                )
                self._gen += 1
                self.updated.set()
                return True

            changed = False
            # 关键边界：首次收到 9:25+ 快照时，整段重置 OHLC，彻底丢弃
            # 9:15–9:25 的竞价指示 open/high/low；不能只改 last。
            if tick_open_final and not cur.open_finalized:
                o = float(open_px or last or 0)
                px = float(last or o)
                if o <= 0 or px <= 0:
                    return False
                cur.open = o
                cur.last = px
                cur.high = max(o, px)
                cur.low = min(o, px)
                cur.open_finalized = True
                changed = True
            elif tick_open_final and open_px is not None and open_px > 0:
                # 正式开盘价晚到/来源切换时允许纠正；旧实现 cur.open>0 后永不更新，
                # 正是本次 18.35/59.97 错买的根因。
                if abs(cur.open - float(open_px)) > 1e-9:
                    cur.open = float(open_px)
                    changed = True
                    if tick_open_result:
                        cur.high = max(cur.open, float(last or cur.last))
                        cur.low = min(cur.open, float(last or cur.last))
            elif open_px is not None and open_px > 0 and cur.open <= 0:
                cur.open = float(open_px)
                changed = True
            if prev_close is not None and prev_close > 0:
                if cur.prev_close is None or abs(cur.prev_close - prev_close) > 1e-9:
                    cur.prev_close = float(prev_close)
                    changed = True
            if last is not None and last > 0 and abs(cur.last - last) > 1e-9:
                cur.last = float(last)
                changed = True
            if tick_open_result and cur.open_finalized:
                # 9:25–9:30 只有核定开盘结果，没有连续竞价路径。
                cur.high = max(cur.open, cur.last)
                cur.low = min(cur.open, cur.last)
            elif high is not None and high > 0:
                nh = max(cur.high, float(high), cur.last)
                if nh > cur.high + 1e-12:
                    cur.high = nh
                    changed = True
            elif last is not None and last > 0 and last > cur.high:
                cur.high = float(last)
                changed = True
            if tick_open_result and cur.open_finalized:
                pass
            elif low is not None and low > 0:
                nl = min(cur.low, float(low), cur.last) if cur.low > 0 else float(low)
                if cur.low <= 0 or nl < cur.low - 1e-12:
                    cur.low = nl
                    changed = True
            elif last is not None and last > 0 and (cur.low <= 0 or last < cur.low):
                cur.low = float(last)
                changed = True
            if last_ts:
                cur.last_ts = tick_ts
            if tick_session:
                cur.session = tick_session
            if cur.prev_close is not None and cur.last > 0:
                cur.day_chg_pct = price_chg_pct(cur.last, cur.prev_close)
            cur.source = source
            if self._absorb_auction_path(cur, last=last, last_ts=tick_ts):
                changed = True
            if changed:
                self._gen += 1
                self.updated.set()
            return changed

    @staticmethod
    def _absorb_auction_path(
        snap: QuoteSnapshot,
        *,
        last: float | None,
        last_ts: str,
    ) -> bool:
        """9:20–9:25 指示现价写入独立路径；9:25 重置 OHLC 时不得擦掉。"""
        if not _auction_lock_quote(last_ts):
            return False
        try:
            px = float(last or 0)
        except (TypeError, ValueError):
            return False
        if px <= 0:
            return False
        changed = False
        if snap.auction_baseline is None or float(snap.auction_baseline) <= 0:
            snap.auction_baseline = round(px, 4)
            snap.auction_high = round(px, 4)
            snap.auction_low = round(px, 4)
            changed = True
        else:
            high0 = float(snap.auction_high or px)
            low0 = float(snap.auction_low or px)
            if px > high0 + 1e-12:
                snap.auction_high = round(px, 4)
                changed = True
            if px < low0 - 1e-12:
                snap.auction_low = round(px, 4)
                changed = True
        if str(snap.auction_ts or "") != str(last_ts):
            snap.auction_ts = str(last_ts)
            changed = True
        return changed

    def get_quote(self, sina: str) -> dict[str, Any] | None:
        sina = str(sina).lower()
        with self._lock:
            snap = self._quotes.get(sina)
            if snap is None:
                return None
            return snap.as_quote_dict()

    def wait_update(self, timeout: float | None = None) -> bool:
        ok = self.updated.wait(timeout=timeout)
        if ok:
            self.updated.clear()
        return ok

    def generation(self) -> int:
        with self._lock:
            return self._gen


def _parse_em_payload(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text or text in ("{}", "null"):
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    data = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(data, dict):
        if isinstance(obj, dict) and "f43" in obj:
            data = obj
        else:
            return None
    return data


def _em_tick_from_data(data: dict[str, Any]) -> dict[str, float | None]:
    # fltt=2 → 真实价格
    return {
        "last": _fnum(data.get("f43")),
        "high": _fnum(data.get("f44")),
        "low": _fnum(data.get("f45")),
        "open": _fnum(data.get("f46")),
        "prev_close": _fnum(data.get("f60")),
    }


class EastmoneySseFeed:
    """单标的东财 SSE；断线指数退避重连。"""

    def __init__(
        self,
        hub: QuoteHub,
        sina: str,
        *,
        stop: threading.Event,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.hub = hub
        self.sina = sina.lower()
        self.secid = sina_to_secid(sina)
        self.stop = stop
        self.on_log = on_log or (lambda _m: None)

    def run(self) -> None:
        backoff = 1.0
        url_i = 0
        while not self.stop.is_set():
            url = _EM_SSE_URLS[url_i % len(_EM_SSE_URLS)]
            url_i += 1
            try:
                self._stream_once(url)
                backoff = 1.0
            except Exception as e:  # noqa: BLE001
                self.hub.mark_sse_down()
                self.on_log(f"SSE {self.sina} 断开: {e}")
                if self.stop.wait(backoff):
                    break
                backoff = min(30.0, backoff * 1.8)

    def _stream_once(self, url: str) -> None:
        params = {
            "fields": _EM_FIELDS,
            "mpi": "1000",
            "invt": "2",
            "fltt": "2",
            "secid": self.secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "dect": "1",
        }
        with requests.get(
            url,
            params=params,
            headers=_EM_HEADERS,
            stream=True,
            timeout=(8, 60),
        ) as resp:
            resp.raise_for_status()
            self.on_log(f"SSE 已连接 {self.sina} via {url.split('/')[2]}")
            buf = ""
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if self.stop.is_set():
                    break
                if not chunk:
                    continue
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", "ignore")
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip("\r")
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        data = _parse_em_payload(payload)
                        if not data:
                            continue
                        tick = _em_tick_from_data(data)
                        last = tick["last"]
                        prev = tick["prev_close"]
                        # 盘前东财现价常为 0，用昨收垫上，否则 SSE 已连也 seed 不进 hub
                        if last is None or last <= 0:
                            if prev is None or prev <= 0:
                                continue
                            last = prev
                        open_px = tick["open"]
                        if open_px is None or open_px <= 0:
                            open_px = last
                        self.hub.mark_sse_ok()
                        self.hub.apply_tick(
                            self.sina,
                            last=last,
                            high=tick["high"],
                            low=tick["low"],
                            open_px=open_px,
                            prev_close=prev,
                            last_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            source="em_sse",
                        )


def fill_preopen_ohlc(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    last_px: float,
    bid: float = 0.0,
    ask: float = 0.0,
    prev_close: float = 0.0,
) -> tuple[float, float, float, float] | None:
    """竞价前 open/last 常为 0：买卖一价 → 昨收。无昨收则放弃。"""
    if open_px <= 0:
        open_px = bid or ask or last_px
    if last_px <= 0:
        last_px = open_px or bid or ask
    if prev_close > 0:
        if last_px <= 0:
            last_px = prev_close
        if open_px <= 0:
            open_px = last_px
    if high_px <= 0:
        highs = [x for x in (open_px, last_px) if x > 0]
        high_px = max(highs) if highs else 0.0
    if low_px <= 0:
        lows = [x for x in (open_px, last_px) if x > 0]
        low_px = min(lows) if lows else 0.0
    if open_px <= 0 or last_px <= 0 or prev_close <= 0:
        return None
    return open_px, high_px, low_px, last_px


def fetch_sina_batch(sinas: list[str]) -> dict[str, dict[str, Any]]:
    """新浪批量快照 list=sh...,sz..."""
    codes = [s.lower() for s in sinas if s]
    if not codes:
        return {}
    out: dict[str, dict[str, Any]] = {}
    # 新浪单次不宜过长，50 只足够
    for i in range(0, len(codes), 50):
        batch = codes[i : i + 50]
        try:
            resp = requests.get(
                f"https://hq.sinajs.cn/list={','.join(batch)}",
                headers=_SINA_HEADERS,
                timeout=8,
            )
            text = resp.content.decode("gbk", "ignore")
        except Exception:  # noqa: BLE001
            continue
        for line in text.splitlines():
            line = line.strip()
            if '="' not in line:
                continue
            # var hq_str_sh600552="...";
            left, right = line.split('="', 1)
            code = left.split("_")[-1].lower()
            payload = right.rstrip('";')
            parts = payload.split(",")
            if len(parts) < 32:
                continue

            def _f(idx: int) -> float:
                try:
                    return float(parts[idx])
                except (TypeError, ValueError):
                    return 0.0

            filled = fill_preopen_ohlc(
                open_px=_f(1),
                high_px=_f(4),
                low_px=_f(5),
                last_px=_f(3),
                bid=_f(6),
                ask=_f(7),
                prev_close=_f(2),
            )
            if filled is None:
                continue
            open_px, high_px, low_px, last_px = filled
            prev_close = _f(2)
            session = parts[30] or datetime.now().strftime("%Y-%m-%d")
            stamp = f"{session} {parts[31]}" if parts[31] else f"{session} 09:25:00"
            stock_name = str(parts[0] or "").strip()
            out[code] = {
                "session": session,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "last": last_px,
                "prev_close": prev_close,
                "amount": _f(9),
                "day_chg_pct": price_chg_pct(last_px, prev_close),
                "last_ts": stamp,
                "name": stock_name,
            }
    return out


class SinaBatchPoller:
    """新浪批量轮询。

    - ``always=True``：持续刷新（覆盖无 SSE 的叠加池，并作 SSE 兜底）
    - ``always=False``：仅当 SSE 不健康时启用（旧行为）
    """

    def __init__(
        self,
        hub: QuoteHub,
        sinas: list[str],
        *,
        stop: threading.Event,
        interval: float = 2.0,
        always: bool = True,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.hub = hub
        self.sinas = [s.lower() for s in sinas]
        self.stop = stop
        self.interval = max(1.0, float(interval))
        self.always = bool(always)
        self.on_log = on_log or (lambda _m: None)
        self._fallback_active = False

    def run(self) -> None:
        while not self.stop.is_set():
            healthy = self.hub.sse_healthy()
            if not self.always and healthy:
                if self._fallback_active:
                    self.on_log("SSE 恢复，暂停新浪批量兜底")
                    self._fallback_active = False
                if self.stop.wait(self.interval):
                    break
                continue
            if not self.always and not self._fallback_active:
                self.on_log("SSE 不健康，启用新浪批量兜底")
                self._fallback_active = True
            try:
                batch = fetch_sina_batch(self.sinas)
                if batch:
                    self.hub.mark_quote_ok("sina_batch")
                for sina, spot in batch.items():
                    self.hub.apply_tick(
                        sina,
                        last=float(spot["last"]),
                        high=float(spot["high"]),
                        low=float(spot["low"]),
                        open_px=float(spot["open"]),
                        prev_close=float(spot["prev_close"]),
                        last_ts=str(spot["last_ts"]),
                        source="sina_batch",
                    )
            except Exception as e:  # noqa: BLE001
                self.on_log(f"新浪批量失败: {e}")
            if self.stop.wait(self.interval):
                break


class QuoteFeedManager:
    """管理 SSE（热池）+ 新浪批量（全池，含叠加观察池）。

    同花顺/通达信用专有推送；免费源不能对上百只各开一条 SSE，否则连接风暴。
    默认：SSE 只挂 ``sse_sinas``（持仓+默认策略）；``sinas`` 全量走新浪批量。
    """

    def __init__(
        self,
        sinas: list[str],
        *,
        sse_sinas: list[str] | None = None,
        on_log: Callable[[str], None] | None = None,
        sina_interval: float = 1.0,
    ) -> None:
        self.sinas = [s.lower() for s in sinas]
        self.on_log = on_log or (lambda m: print(m))
        if sse_sinas is None:
            self.sse_sinas = list(self.sinas)
        else:
            self.sse_sinas = [s.lower() for s in sse_sinas]
        try:
            from watch_config import MAX_SSE_QUOTES

            cap = max(1, int(MAX_SSE_QUOTES))
        except Exception:  # noqa: BLE001
            cap = 48
        if len(self.sse_sinas) > cap:
            self.on_log(f"SSE 名单 {len(self.sse_sinas)}→{cap}（MAX_SSE_QUOTES）")
            self.sse_sinas = self.sse_sinas[:cap]
        self.hub = QuoteHub()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.sina_interval = max(1.0, float(sina_interval))

    def start(self) -> None:
        self._stop.clear()
        for sina in self.sse_sinas:
            t = threading.Thread(
                target=EastmoneySseFeed(
                    self.hub, sina, stop=self._stop, on_log=self.on_log
                ).run,
                name=f"em-sse-{sina}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        poller = SinaBatchPoller(
            self.hub,
            self.sinas,
            stop=self._stop,
            interval=self.sina_interval,
            always=True,
            on_log=self.on_log,
        )
        t2 = threading.Thread(target=poller.run, name="sina-batch", daemon=True)
        t2.start()
        self._threads.append(t2)
        n_all = len(self.sinas)
        n_sse = len(self.sse_sinas)
        self.on_log(
            f"行情源已启动: SSE×{n_sse} 热池 + 新浪批量×{n_all} "
            f"（叠加池不占 SSE）"
        )

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()

    def get_quote(self, sina: str) -> dict[str, Any] | None:
        return self.hub.get_quote(sina)

    def seed(self, sina: str, quote: dict[str, Any]) -> None:
        self.hub.seed_from_quote(sina, quote)

    def wait_update(self, timeout: float | None = None) -> bool:
        return self.hub.wait_update(timeout=timeout)

    def quote_health(self, *, max_age_sec: float = QUOTE_STALE_AFTER_SEC) -> dict[str, Any]:
        return self.hub.quote_health(max_age_sec=max_age_sec)


def ws_accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key.strip() + _WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def ws_pack_text(text: str) -> bytes:
    data = text.encode("utf-8")
    n = len(data)
    header = bytearray([0x81])
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", n))
    return bytes(header) + data


def ws_pack_pong(payload: bytes = b"") -> bytes:
    n = len(payload)
    header = bytearray([0x8A])
    if n < 126:
        header.append(n)
    else:
        header.append(126)
        header.extend(struct.pack("!H", n))
    return bytes(header) + payload


class LocalWsHub:
    """ThreadingHTTPServer 上挂的简易本地 WebSocket 广播。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[socket.socket] = set()

    def add(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.add(sock)

    def remove(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.discard(sock)
        try:
            sock.close()
        except OSError:
            pass

    def broadcast_json(self, payload: dict[str, Any]) -> None:
        self.broadcast_text(json.dumps(payload, ensure_ascii=False))

    def broadcast_text(self, text: str) -> None:
        raw = ws_pack_text(text)
        dead: list[socket.socket] = []
        with self._lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.sendall(raw)
            except OSError:
                dead.append(sock)
        for sock in dead:
            self.remove(sock)

    def serve_client(self, sock: socket.socket) -> None:
        """握手完成后读循环：处理 ping/close，忽略业务上行。"""
        self.add(sock)
        try:
            # 浏览器通常不发上行帧；有限超时会导致约 60s 被动断连
            sock.settimeout(None)
            while True:
                hdr = self._recv_exact(sock, 2)
                if not hdr:
                    break
                b0, b1 = hdr[0], hdr[1]
                opcode = b0 & 0x0F
                masked = bool(b1 & 0x80)
                length = b1 & 0x7F
                if length == 126:
                    ext = self._recv_exact(sock, 2)
                    if not ext:
                        break
                    length = struct.unpack("!H", ext)[0]
                elif length == 127:
                    ext = self._recv_exact(sock, 8)
                    if not ext:
                        break
                    length = struct.unpack("!Q", ext)[0]
                mask = b""
                if masked:
                    mask = self._recv_exact(sock, 4)
                    if not mask:
                        break
                payload = self._recv_exact(sock, length) if length else b""
                if payload is None:
                    break
                if masked and payload:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:  # close
                    break
                if opcode == 0x9:  # ping
                    try:
                        sock.sendall(ws_pack_pong(payload or b""))
                    except OSError:
                        break
                # text/binary/pong: ignore
        except OSError:
            pass
        finally:
            self.remove(sock)

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
