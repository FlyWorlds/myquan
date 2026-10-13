from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

from .models import DataSourceResult, LimitUpRecord

EASTMONEY_LIMIT_UP_SOURCE = "eastmoney_limit_up_pool"
_ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"
_BASE = "https://push2ex.eastmoney.com/getTopicZTPool"
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _f(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _i(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _time_hms(v: Any) -> str:
    s = str(v or "").strip()
    if not s or s == "-":
        return ""
    if len(s) == 6 and s.isdigit():
        return f"{s[:2]}:{s[2:4]}:{s[4:]}"
    if len(s) == 8 and s[2:3] == ":":
        return s
    return s


def parse_limit_up_pool_payload(
    payload: dict[str, Any],
    *,
    trade_date: str | None = None,
    fetched_at: str | None = None,
) -> list[LimitUpRecord]:
    data = payload.get("data") if isinstance(payload, dict) else None
    pool = None
    if isinstance(data, dict):
        pool = data.get("pool") or data.get("diff")
    elif isinstance(data, list):
        pool = data
    if pool is None and isinstance(payload, dict):
        pool = payload.get("pool")
    if not isinstance(pool, list):
        return []
    fetched = fetched_at or _now()
    out: list[LimitUpRecord] = []
    for row in pool:
        if not isinstance(row, dict):
            continue
        code = str(row.get("c") or row.get("code") or row.get("f12") or "").zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        out.append(
            LimitUpRecord(
                code=code,
                name=str(row.get("n") or row.get("name") or row.get("f14") or ""),
                price=_f(row.get("p") or row.get("price") or row.get("f2")),
                pct=_f(row.get("zdp") or row.get("pct") or row.get("f3")),
                amount_yi=_f(row.get("amount") or row.get("成交额") or row.get("f6")),
                turnover_pct=_f(row.get("hs") or row.get("turnover") or row.get("f8")),
                float_cap_yi=_f(row.get("lbc") or row.get("float_cap_yi") or row.get("f20")),
                seal_fund_yi=_f(row.get("fund") or row.get("seal_fund_yi") or row.get("fbt")),
                first_seal=_time_hms(row.get("fbt") or row.get("first_seal")),
                last_seal=_time_hms(row.get("lbt") or row.get("last_seal")),
                break_times=_i(row.get("zbc") or row.get("break_times")),
                limit_days=_i(row.get("lbc") or row.get("limit_days")),
                industry=str(row.get("hybk") or row.get("industry") or ""),
                zt_stat=str(row.get("zttj") or row.get("zt_stat") or ""),
                source=EASTMONEY_LIMIT_UP_SOURCE,
                trade_date=trade_date,
                fetched_at=fetched,
            )
        )
    return out


def fetch_limit_up_pool(
    *,
    trade_date: str | None = None,
    timeout: float = 8.0,
) -> DataSourceResult:
    started = time.time()
    fetched = _now()
    params = {
        "ut": _ZTB_UT,
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "10000",
        "sort": "fbt:asc",
    }
    if trade_date:
        params["date"] = str(trade_date).replace("-", "")
    try:
        resp = requests.get(_BASE, params=params, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        records = parse_limit_up_pool_payload(
            payload,
            trade_date=trade_date,
            fetched_at=fetched,
        )
        return DataSourceResult(
            source=EASTMONEY_LIMIT_UP_SOURCE,
            fetched_at=fetched,
            trade_date=trade_date,
            status="ok" if records else "empty",
            rows=[r.as_row() for r in records],
            latency_ms=int((time.time() - started) * 1000),
            meta={"url": resp.url, "count": len(records)},
        )
    except Exception as exc:  # noqa: BLE001
        return DataSourceResult(
            source=EASTMONEY_LIMIT_UP_SOURCE,
            fetched_at=fetched,
            trade_date=trade_date,
            status="error",
            rows=[],
            latency_ms=int((time.time() - started) * 1000),
            error=str(exc),
        )
