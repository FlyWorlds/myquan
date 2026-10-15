"""Optional research-only minute archive. Never imported by execution or valuation."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE = "sina_1m_unadjusted"
URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"


def opening_busy(now):
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") < "09:40"


def validated_bars(raw, now):
    if not isinstance(raw, list):
        raise ValueError("Expected minute array")
    cutoff = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    bars = {}
    for row in raw:
        at = datetime.fromisoformat(str(row["day"]))
        if at.tzinfo is not None:
            at = at.astimezone(SHANGHAI).replace(tzinfo=None)
        # A conservative extra minute avoids caching either start/end-labelled forming bars.
        if at > cutoff or at.weekday() >= 5:
            continue
        clock = at.strftime("%H:%M:%S")
        if not ("09:30:00" <= clock <= "11:30:00" or "13:00:00" <= clock <= "15:00:00"):
            continue
        values = [float(row[k]) for k in ("open", "high", "low", "close")]
        o, h, low, c = values
        volume = float(row.get("volume", 0))
        if (not all(math.isfinite(v) and v > 0 for v in values)
                or not math.isfinite(volume) or volume < 0 or low > min(o, c) or h < max(o, c)):
            raise ValueError("Invalid minute OHLCV")
        bars[at.isoformat(sep=" ")] = (*values, volume)
    if not bars:
        raise ValueError("No completed minute bars")
    return sorted(bars.items())


def archive(symbol, path, *, now=None, raw=None):
    if not re.fullmatch(r"(?:sh|sz|bj)[0-9]{6}", symbol):
        raise ValueError("Invalid symbol")
    now = now or datetime.now(SHANGHAI).replace(tzinfo=None)
    if raw is None:
        request = Request(URL + "?" + urlencode(dict(symbol=symbol, scale=1, ma="no", datalen=1023)),
                          headers={"Referer": "https://finance.sina.com.cn"})
        with urlopen(request, timeout=8) as response:
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Oversized minute response")
        _, marker, body = payload.decode("utf-8").partition("=(")
        if not marker:
            raise ValueError("Unexpected minute response")
        raw, _ = json.JSONDecoder().raw_decode(body)
    bars = validated_bars(raw, now)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=3) as db:
        db.execute("CREATE TABLE IF NOT EXISTS research_minutes (symbol TEXT, ts TEXT, open REAL, high REAL, "
                   "low REAL, close REAL, volume REAL, source TEXT, fetched_at TEXT, PRIMARY KEY(symbol,ts,source))")
        db.executemany("INSERT OR REPLACE INTO research_minutes VALUES (?,?,?,?,?,?,?,?,?)",
                       [(symbol, at, *values, SOURCE, str(now)) for at, values in bars])
        db.execute("CREATE TABLE IF NOT EXISTS research_fetches (symbol TEXT PRIMARY KEY, fetched_at TEXT, "
                   "first_bar TEXT, last_bar TEXT, bar_count INTEGER, source TEXT)")
        db.execute("INSERT OR REPLACE INTO research_fetches VALUES (?,?,?,?,?,?)",
                   (symbol, str(now), bars[0][0], bars[-1][0], len(bars), SOURCE))
    return len(bars)


class MinuteBackup:
    def __init__(self, *, stop, rendered, symbols, path, log=print):
        self.stop, self.rendered, self.symbols = stop, rendered, symbols
        self.path, self.log = Path(path), log
        self.due = {}

    def run_once(self, now=None):
        now = now or datetime.now(SHANGHAI).replace(tzinfo=None)
        if self.stop.is_set() or not self.rendered.is_set() or opening_busy(now):
            return False
        # Priority is holdings then strategy pool, never an implicit full-A scan.
        symbols = list(dict.fromkeys(self.symbols()))[:256]
        for symbol in symbols:
            if not re.fullmatch(r"(?:sh|sz|bj)[0-9]{6}", symbol) or self.due.get(symbol, 0) > time.monotonic():
                continue
            try:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), symbol, str(self.path)],
                               check=True, timeout=20, capture_output=True)
                self.due[symbol] = time.monotonic() + 1800
            except (OSError, subprocess.SubprocessError) as exc:
                self.due[symbol] = time.monotonic() + 300
                self.log(f"Minute backup deferred {symbol}: {type(exc).__name__}")
            return True
        return False

    def run(self):
        while not self.stop.is_set() and not self.rendered.wait(.5):
            pass
        if self.stop.wait(15):
            return
        while not self.stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self.log(f"Minute backup unavailable: {type(exc).__name__}")
            self.stop.wait(3)


if __name__ == "__main__":
    try:
        import os
        os.nice(10)
        archive(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
