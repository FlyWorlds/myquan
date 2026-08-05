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

    def mark_sse_ok(self) -> None:
        self.sse_ok = True
        self.sse_last_ok_ts = time.time()

    def mark_sse_down(self) -> None:
        self.sse_ok = False

    def sse_healthy(self, *, max_age_sec: float = 15.0) -> bool:
        if not self.sse_ok:
            return False
        return (time.time() - self.sse_last_ok_ts) <= max_age_sec

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
            day_bars=quote.get("_day_bars"),
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
        with self._lock:
            cur = self._quotes.get(sina)
            if cur is None:
                if last is None or last <= 0:
                    return False
                o = float(open_px or last)
                h = float(high or last)
                l = float(low or last)
                pc = prev_close
                chg = None
                if pc is not None and pc > 0:
                    chg = (float(last) / pc - 1.0) * 100.0
                self._quotes[sina] = QuoteSnapshot(
                    sina=sina,
                    session=datetime.now().strftime("%Y-%m-%d"),
                    open=o,
                    high=max(h, float(last)),
                    low=min(l, float(last)) if l > 0 else float(last),
                    last=float(last),
                    prev_close=pc,
                    day_chg_pct=chg,
                    last_ts=last_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    source=source,
                )
                self._gen += 1
                self.updated.set()
                return True

            changed = False
            if open_px is not None and open_px > 0 and cur.open <= 0:
                cur.open = float(open_px)
                changed = True
            if prev_close is not None and prev_close > 0:
                if cur.prev_close is None or abs(cur.prev_close - prev_close) > 1e-9:
                    cur.prev_close = float(prev_close)
                    changed = True
            if last is not None and last > 0 and abs(cur.last - last) > 1e-9:
                cur.last = float(last)
                changed = True
            if high is not None and high > 0:
                nh = max(cur.high, float(high), cur.last)
                if nh > cur.high + 1e-12:
                    cur.high = nh
                    changed = True
            elif last is not None and last > 0 and last > cur.high:
                cur.high = float(last)
                changed = True
            if low is not None and low > 0:
                nl = min(cur.low, float(low), cur.last) if cur.low > 0 else float(low)
                if cur.low <= 0 or nl < cur.low - 1e-12:
                    cur.low = nl
                    changed = True
            elif last is not None and last > 0 and (cur.low <= 0 or last < cur.low):
                cur.low = float(last)
                changed = True
            if last_ts:
                cur.last_ts = last_ts
            if cur.prev_close is not None and cur.prev_close > 0 and cur.last > 0:
                cur.day_chg_pct = (cur.last / cur.prev_close - 1.0) * 100.0
            cur.source = source
            if changed:
                self._gen += 1
                self.updated.set()
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
                        if tick["last"] is None or tick["last"] <= 0:
                            continue
                        self.hub.mark_sse_ok()
                        self.hub.apply_tick(
                            self.sina,
                            last=tick["last"],
                            high=tick["high"],
                            low=tick["low"],
                            open_px=tick["open"],
                            prev_close=tick["prev_close"],
                            last_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            source="em_sse",
                        )


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

            open_px = _f(1)
            prev_close = _f(2)
            last_px = _f(3)
            high_px = _f(4)
            low_px = _f(5)
            bid = _f(6)
            ask = _f(7)
            if open_px <= 0:
                open_px = bid or ask or last_px
            if last_px <= 0:
                last_px = open_px or bid or ask
            if high_px <= 0:
                high_px = max(open_px, last_px)
            if low_px <= 0:
                lows = [x for x in (open_px, last_px) if x > 0]
                low_px = min(lows) if lows else 0.0
            if open_px <= 0 or last_px <= 0 or prev_close <= 0:
                continue
            session = parts[30] or datetime.now().strftime("%Y-%m-%d")
            stamp = f"{session} {parts[31]}" if parts[31] else f"{session} 09:25:00"
            out[code] = {
                "session": session,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "last": last_px,
                "prev_close": prev_close,
                "last_ts": stamp,
            }
    return out


class SinaBatchPoller:
    """SSE 不健康时的新浪批量兜底（约 2s）。"""

    def __init__(
        self,
        hub: QuoteHub,
        sinas: list[str],
        *,
        stop: threading.Event,
        interval: float = 2.0,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.hub = hub
        self.sinas = [s.lower() for s in sinas]
        self.stop = stop
        self.interval = max(1.0, float(interval))
        self.on_log = on_log or (lambda _m: None)
        self._fallback_active = False

    def run(self) -> None:
        while not self.stop.is_set():
            healthy = self.hub.sse_healthy()
            if healthy:
                if self._fallback_active:
                    self.on_log("SSE 恢复，暂停新浪批量兜底")
                    self._fallback_active = False
                if self.stop.wait(self.interval):
                    break
                continue
            if not self._fallback_active:
                self.on_log("SSE 不健康，启用新浪批量兜底")
                self._fallback_active = True
            try:
                batch = fetch_sina_batch(self.sinas)
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
    """管理 SSE + 新浪兜底线程。"""

    def __init__(
        self,
        sinas: list[str],
        *,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.sinas = [s.lower() for s in sinas]
        self.hub = QuoteHub()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.on_log = on_log or (lambda m: print(m))

    def start(self) -> None:
        self._stop.clear()
        for sina in self.sinas:
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
            self.hub, self.sinas, stop=self._stop, interval=2.0, on_log=self.on_log
        )
        t2 = threading.Thread(target=poller.run, name="sina-batch", daemon=True)
        t2.start()
        self._threads.append(t2)
        self.on_log(
            f"行情源已启动: SSE×{len(self.sinas)} + 新浪批量兜底 "
            f"({', '.join(self.sinas)})"
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
        raw = ws_pack_text(json.dumps(payload, ensure_ascii=False))
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
            sock.settimeout(60.0)
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
