"""PandaData-only source layer for Keynes/contrarian research."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ENV_FILE = Path.home() / ".pandadata" / "pandadata.env"
SENSITIVE = re.compile(r"(?i)(password|passwd|token|username)\s*[=:]\s*[^\s,;]+")
DATE_COLUMNS = ("date", "trade_date", "report_date", "ann_date", "publish_date", "end_date", "nature_date")
INDEX_UNIVERSES = {
    "csi300": {"index_symbol": "000300.SH", "label": "沪深300"},
    "csi500": {"index_symbol": "000905.SH", "label": "中证500"},
    "csi1000": {"index_symbol": "000852.SH", "label": "中证1000"},
}


def _read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return values


def load_credentials() -> tuple[str, str]:
    values = _read_env_file()
    username = os.environ.get("PANDA_USERNAME") or values.get("PANDA_USERNAME", "")
    password = os.environ.get("PANDA_PASSWORD") or values.get("PANDA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("缺少 PandaData 凭证，请设置 PANDA_USERNAME/PANDA_PASSWORD 或 ~/.pandadata/pandadata.env")
    return username, password


def sanitize_error(error: Exception | str) -> str:
    return SENSITIVE.sub(lambda m: f"{m.group(1)}=<redacted>", str(error))[:500]


def normalize_symbol(symbol: str) -> str:
    code = symbol.strip().upper()
    if "." in code:
        return code
    if code.startswith(("600", "601", "603", "605", "688", "689", "510", "511", "512", "513", "515", "516", "518", "560", "561", "562", "563", "588")):
        return f"{code}.SH"
    if code.startswith(("000", "001", "002", "003", "159", "300", "301")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    raise ValueError(f"无法识别代码 {symbol!r}，请提供交易所后缀")


def compact_params(params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in params.items():
        if value in (None, "", []):
            continue
        if isinstance(value, list) and key in ("symbol", "index_symbol"):
            result[f"{key}_count"] = len(value)
            result[f"{key}_sample"] = value[:5]
        else:
            result[key] = value
    return result


def latest_date(frame: pd.DataFrame) -> str | None:
    for column in DATE_COLUMNS:
        if column in frame.columns and frame[column].notna().any():
            return str(frame[column].dropna().astype(str).max()).replace("-", "")
    return None


@dataclass
class CallResult:
    method: str
    status: str
    data: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    latest_date: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def provenance(self) -> dict[str, Any]:
        return {"method": self.method, "status": self.status, "rows": self.rows, "columns": self.columns, "latest_date": self.latest_date, "params": self.params, "error": self.error, "attempts": self.attempts}


class PandaDataSource:
    def __init__(self, retries: int = 2, retry_delay: float = 0.5):
        try:
            import panda_data
        except ImportError as exc:
            raise RuntimeError("未安装 panda_data，请先安装兼容的 PandaData SDK") from exc
        username, password = load_credentials()
        panda_data.init_token(username=username, password=password)
        self.api = panda_data
        self.retries = max(1, retries)
        self.retry_delay = max(0.0, retry_delay)
        self.calls: list[CallResult] = []

    def call(self, method: str, *, required_columns: tuple[str, ...] = (), unsupported_hint: bool = False, **params: Any) -> CallResult:
        fn: Callable[..., Any] | None = getattr(self.api, method, None)
        safe = compact_params(params)
        if fn is None:
            result = CallResult(method, "unsupported", params=safe, error="SDK不包含该方法")
            self.calls.append(result)
            return result
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                raw = fn(**params)
                frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw) if raw is not None else pd.DataFrame()
                missing = [col for col in required_columns if col not in frame.columns]
                status = "empty" if frame.empty else "error" if missing else "ok"
                error = "接口成功但无记录" if frame.empty else f"缺少必要字段: {', '.join(missing)}" if missing else None
                result = CallResult(method, status, frame, len(frame), [str(c) for c in frame.columns], latest_date(frame), safe, error, attempt)
                self.calls.append(result)
                return result
            except Exception as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
        text = sanitize_error(last or "未知错误")
        lower = text.lower()
        unsupported = unsupported_hint and any(marker in lower for marker in ("unsupported", "not support", "not found", "未上线", "废弃", "404"))
        result = CallResult(method, "unsupported" if unsupported else "error", params=safe, error=text, attempts=self.retries)
        self.calls.append(result)
        return result

    def provenance(self) -> list[dict[str, Any]]:
        return [call.provenance() for call in self.calls]


def date_window(as_of: str, calendar_days: int) -> tuple[str, str]:
    end = datetime.strptime(as_of.replace("-", ""), "%Y%m%d")
    return (end - timedelta(days=calendar_days)).strftime("%Y%m%d"), end.strftime("%Y%m%d")


def resolve_as_of(source: PandaDataSource, requested: str | None = None) -> str:
    upper = (requested or datetime.now().strftime("%Y%m%d")).replace("-", "")
    datetime.strptime(upper, "%Y%m%d")
    start, end = date_window(upper, 14)
    result = source.call("get_trade_cal", start_date=start, end_date=end, exchange="SH", is_trading_day=1, fields=[])
    if result.ok:
        column = next((c for c in ("date", "trade_date", "nature_date") if c in result.data.columns), None)
        if column:
            dates = result.data[column].dropna().astype(str).str.replace("-", "", regex=False)
            dates = dates[dates <= upper]
            if not dates.empty:
                return str(dates.max())
    return upper


def filter_as_of(frame: pd.DataFrame, as_of: str, date_columns: tuple[str, ...] = DATE_COLUMNS) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    for column in date_columns:
        if column in result.columns:
            values = result[column].astype(str).str.replace("-", "", regex=False)
            mask = values.isin(("", "nan", "None", "NaT")) | (values <= as_of)
            result = result.loc[mask].copy()
            break
    return result


def fetch_windows(source: PandaDataSource, method: str, symbols: list[str], start: str, end: str, required: tuple[str, ...] = (), fields: list[str] | None = None) -> CallResult:
    begin = datetime.strptime(start, "%Y%m%d")
    finish = datetime.strptime(end, "%Y%m%d")
    frames: list[pd.DataFrame] = []
    cur = begin
    while cur <= finish:
        chunk_end = min(cur + timedelta(days=363), finish)
        result = source.call(method, symbol=symbols, start_date=cur.strftime("%Y%m%d"), end_date=chunk_end.strftime("%Y%m%d"), fields=fields or [], required_columns=required, unsupported_hint=True)
        if result.ok:
            frames.append(result.data)
        cur = chunk_end + timedelta(days=1)
    if not frames:
        return CallResult(method, "empty", params={"symbol_count": len(symbols), "start_date": start, "end_date": end}, error="分段查询未返回记录")
    frame = pd.concat(frames, ignore_index=True)
    keys = [c for c in ("symbol", "stock_symbol", "date", "report_date", "ann_date") if c in frame.columns]
    if keys:
        frame = frame.drop_duplicates(keys, keep="last")
    return CallResult(method, "ok", frame, len(frame), [str(c) for c in frame.columns], latest_date(frame), {"symbol_count": len(symbols), "start_date": start, "end_date": end})


def fetch_index_universe(source: PandaDataSource, as_of: str, universe: str, calendar_days: int = 190) -> CallResult:
    if universe not in INDEX_UNIVERSES:
        raise ValueError(f"不支持股票池 {universe!r}")
    start, end = date_window(as_of, calendar_days)
    definition = INDEX_UNIVERSES[universe]
    result = source.call("get_index_weights", index_symbol=definition["index_symbol"], start_date=start, end_date=end, fields=[], required_columns=("stock_symbol",))
    if not result.ok or "date" not in result.data.columns:
        return result
    dates = result.data["date"].astype(str).str.replace("-", "", regex=False)
    valid = dates[dates <= as_of]
    if valid.empty:
        return CallResult("get_index_weights", "empty", error=f"{definition['label']}无截止日前成分快照")
    snapshot = str(valid.max())
    data = result.data.loc[dates == snapshot].copy()
    return CallResult(result.method, "ok", data, len(data), result.columns, snapshot, result.params, result.error, result.attempts)


def quarter_for_date(value: str) -> str:
    date = datetime.strptime(value.replace("-", ""), "%Y%m%d")
    return f"{date.year}Q{(date.month - 1) // 3 + 1}"


def probe_interfaces(source: PandaDataSource, as_of: str, symbols: list[str]) -> dict[str, CallResult]:
    start, end = date_window(as_of, 14)
    holder_start, _ = date_window(as_of, 550)
    financial_start, _ = date_window(as_of, 365 * 3 + 30)
    symbol = symbols[:2] or ["000001.SZ"]
    start_quarter = quarter_for_date(financial_start)
    end_quarter = quarter_for_date(as_of)
    return {
        "trade_calendar": source.call("get_trade_cal", start_date=start, end_date=end, exchange="SH", is_trading_day=1, fields=[]),
        "stock_detail": source.call("get_stock_detail", symbol=symbol, fields=[]),
        "stock_daily": source.call("get_stock_daily", symbol=symbol, start_date=start, end_date=end, fields=[]),
        "index_daily": source.call("get_index_daily", symbol=["000300.SH"], start_date=start, end_date=end, fields=[]),
        "fina_reports": source.call("get_fina_reports", symbol=symbol, start_quarter=start_quarter, end_quarter=end_quarter, fields=[]),
        "fina_performance": source.call("get_fina_performance", symbol=symbol, fields=[]),
        "fina_forecast": source.call("get_fina_forecast", symbol=symbol, fields=[]),
        "audit_opinion": source.call("get_audit_opinion", symbol=symbol, fields=[]),
        "factor_valuation": source.call(
            "get_factor",
            symbol=symbol,
            start_date=financial_start,
            end_date=as_of,
            type="stock",
            factors=["pe_ratio_ttm", "pe_ratio_lyr", "pb_ratio_lf", "pb_ratio_ttm", "pb_ratio_lyr", "market_cap"],
        ),
        "index_indicator": source.call(
            "get_index_indicator",
            symbol=["000300.SH"],
            start_date=financial_start,
            end_date=as_of,
            fields=[],
        ),
        "margin": source.call("get_margin", symbol=symbol, start_date=start, end_date=end, fields=[]),
        "hsgt_hold": source.call("get_hsgt_hold", symbol=symbol, start_date=holder_start, end_date=end, fields=[]),
        "lhb_detail": source.call("get_lhb_detail", symbol=symbol, start_date=start, end_date=end, fields=[], unsupported_hint=True),
        "etf_flow": source.call("get_fund_etf_cr_net", symbol=["510300.SH"], start_date=start, end_date=end, fields=[], unsupported_hint=True),
    }
