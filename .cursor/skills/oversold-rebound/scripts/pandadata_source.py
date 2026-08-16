"""PandaData-only source layer with provenance and explicit missing states."""

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
SENSITIVE_PATTERN = re.compile(r"(?i)(password|passwd|token|username)\s*[=:]\s*[^\s,;]+")
DATE_COLUMNS = ("date", "trade_date", "nature_date", "report_date", "end_date", "ann_date", "list_date")
INDEX_UNIVERSES = {
    "csi300": {"index_symbol": "000300.SH", "label": "沪深300"},
    "csi500": {"index_symbol": "000905.SH", "label": "中证500"},
    "csi1000": {"index_symbol": "000852.SH", "label": "中证1000"},
}


def _read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_credentials() -> tuple[str, str]:
    file_values = _read_env_file()
    username = os.environ.get("PANDA_USERNAME") or file_values.get("PANDA_USERNAME", "")
    password = os.environ.get("PANDA_PASSWORD") or file_values.get("PANDA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "缺少 PandaData 凭证。请设置 PANDA_USERNAME/PANDA_PASSWORD，"
            "或写入 ~/.pandadata/pandadata.env。"
        )
    return username, password


def sanitize_error(error: Exception | str) -> str:
    text = SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", str(error))
    return text[:500]


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
        if key == "fields":
            result[key] = value
        elif key == "symbol" and isinstance(value, list):
            result["symbol_count"] = len(value)
            result["symbol_sample"] = value[:5]
        else:
            result[key] = value
    return result


def latest_date(frame: pd.DataFrame) -> str | None:
    for column in DATE_COLUMNS:
        if column in frame.columns and frame[column].notna().any():
            return str(frame[column].dropna().astype(str).max())
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
        return {
            "method": self.method,
            "status": self.status,
            "rows": self.rows,
            "columns": self.columns,
            "latest_date": self.latest_date,
            "params": self.params,
            "error": self.error,
            "attempts": self.attempts,
        }


class PandaDataSource:
    """Authenticated PandaData client wrapper."""

    def __init__(self, retries: int = 2, retry_delay: float = 0.8):
        try:
            import panda_data
        except ImportError as exc:
            raise RuntimeError("未安装 panda_data，请先安装与项目兼容的 SDK") from exc
        username, password = load_credentials()
        panda_data.init_token(username=username, password=password)
        self.api = panda_data
        self.retries = max(1, retries)
        self.retry_delay = max(0.0, retry_delay)
        self.calls: list[CallResult] = []

    def call(
        self,
        method: str,
        *,
        required_columns: tuple[str, ...] = (),
        unsupported_hint: bool = False,
        **params: Any,
    ) -> CallResult:
        fn: Callable[..., Any] | None = getattr(self.api, method, None)
        safe_params = compact_params(params)
        if fn is None:
            result = CallResult(
                method=method,
                status="unsupported",
                params=safe_params,
                error="当前 panda_data SDK 不包含该方法",
            )
            self.calls.append(result)
            return result

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                raw = fn(**params)
                if raw is None:
                    frame = pd.DataFrame()
                elif isinstance(raw, pd.DataFrame):
                    frame = raw.copy()
                else:
                    frame = pd.DataFrame(raw)
                missing = [column for column in required_columns if column not in frame.columns]
                if frame.empty:
                    status = "empty"
                    error = "接口调用成功但未返回记录"
                elif missing:
                    status = "error"
                    error = f"缺少必要字段: {', '.join(missing)}"
                else:
                    status = "ok"
                    error = None
                result = CallResult(
                    method=method,
                    status=status,
                    data=frame,
                    rows=len(frame),
                    columns=[str(column) for column in frame.columns],
                    latest_date=latest_date(frame),
                    params=safe_params,
                    error=error,
                    attempts=attempt,
                )
                self.calls.append(result)
                return result
            except Exception as exc:  # PandaData uses several service exception classes.
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)

        error_text = sanitize_error(last_error or "未知错误")
        lower_error = error_text.lower()
        unsupported = unsupported_hint and any(
            marker in lower_error
            for marker in ("not support", "unsupported", "not found", "未上线", "废弃", "404")
        )
        result = CallResult(
            method=method,
            status="unsupported" if unsupported else "error",
            params=safe_params,
            error=error_text,
            attempts=self.retries,
        )
        self.calls.append(result)
        return result

    def provenance(self) -> list[dict[str, Any]]:
        return [call.provenance() for call in self.calls]


def date_window(as_of: str, calendar_days: int) -> tuple[str, str]:
    end = datetime.strptime(as_of, "%Y%m%d")
    start = end - timedelta(days=calendar_days)
    return start.strftime("%Y%m%d"), as_of


def resolve_as_of(source: PandaDataSource, requested: str | None = None) -> str:
    """Resolve the latest complete PandaData trading day not after requested/today."""
    if requested:
        value = requested.replace("-", "")
        datetime.strptime(value, "%Y%m%d")
        upper = value
    else:
        upper = datetime.now().strftime("%Y%m%d")
    start, end = date_window(upper, 14)
    calendar = source.call(
        "get_trade_cal",
        start_date=start,
        end_date=end,
        exchange="SH",
        is_trading_day=1,
        fields=[],
    )
    if calendar.ok:
        frame = calendar.data
        date_column = next(
            (column for column in ("date", "trade_date", "nature_date") if column in frame.columns),
            None,
        )
        if date_column:
            dates = frame[date_column].dropna().astype(str).str.replace("-", "", regex=False)
            dates = dates[dates <= upper]
            if not dates.empty:
                return str(dates.max())
    return upper


def fetch_index_universe(
    source: PandaDataSource,
    as_of: str,
    universe: str,
    calendar_days: int = 190,
) -> CallResult:
    """Fetch the latest constituent snapshot on or before ``as_of``."""
    if universe not in INDEX_UNIVERSES:
        supported = ", ".join(INDEX_UNIVERSES)
        raise ValueError(f"不支持的股票池 {universe!r}；可选值：{supported}")
    start, end = date_window(as_of, calendar_days)
    definition = INDEX_UNIVERSES[universe]
    result = source.call(
        "get_index_weights",
        index_symbol=definition["index_symbol"],
        start_date=start,
        end_date=end,
        fields=[],
        required_columns=("stock_symbol",),
    )
    if not result.ok or "date" not in result.data.columns:
        return result

    dates = result.data["date"].astype(str).str.replace("-", "", regex=False)
    valid_dates = dates[dates <= as_of]
    if valid_dates.empty:
        result.status = "empty"
        result.data = pd.DataFrame(columns=result.data.columns)
        result.rows = 0
        result.latest_date = None
        result.error = f"{definition['label']}在分析日及之前未返回成分股快照"
        return result

    snapshot_date = str(valid_dates.max())
    result.data = result.data.loc[dates == snapshot_date].copy()
    result.rows = len(result.data)
    result.latest_date = snapshot_date
    return result


def fetch_stock_daily(
    source: PandaDataSource,
    as_of: str,
    symbols: list[str] | None,
    calendar_days: int = 190,
) -> CallResult:
    start, end = date_window(as_of, calendar_days)
    return source.call(
        "get_stock_daily",
        symbol=symbols or [],
        start_date=start,
        end_date=end,
        fields=[],
        st=True,
        required_columns=("symbol", "date", "close", "pre_close", "high", "low", "open"),
    )


def fetch_index_daily(source: PandaDataSource, as_of: str, calendar_days: int = 190) -> CallResult:
    start, end = date_window(as_of, calendar_days)
    return source.call(
        "get_index_daily",
        symbol=["000300.SH", "000905.SH", "000852.SH", "399006.SZ"],
        start_date=start,
        end_date=end,
        fields=[],
        required_columns=("symbol", "date", "close", "pre_close", "high", "low", "open"),
    )


def fetch_northbound_hold(
    source: PandaDataSource, as_of: str, symbols: list[str]
) -> CallResult:
    """Fetch quarterly HSGT holding snapshots for an explicit stock pool."""
    start, end = date_window(as_of, 550)
    return source.call(
        "get_hsgt_hold",
        symbol=symbols,
        start_date=start,
        end_date=end,
        fields=[],
        required_columns=("symbol", "date", "shares_num", "holding_ratio"),
    )


def fetch_recent_funds(source: PandaDataSource, as_of: str, symbols: list[str] | None = None) -> dict[str, CallResult]:
    short_start, end = date_window(as_of, 35)
    # HSGT holdings are quarterly snapshots in this API; use a wide window so
    # at least two comparable disclosure dates can be present.
    northbound_start, _ = date_window(as_of, 550)
    return {
        "margin": source.call(
            "get_margin",
            symbol=symbols or None,
            start_date=short_start,
            end_date=end,
            fields=[],
        ),
        "northbound": source.call(
            "get_hsgt_hold",
            symbol=symbols or None,
            start_date=northbound_start,
            end_date=end,
            fields=[],
        ),
        "lhb": source.call(
            "get_lhb_detail",
            symbol=symbols or None,
            start_date=short_start,
            end_date=end,
            fields=[],
        ),
    }


def fetch_stock_metadata(source: PandaDataSource, symbols: list[str] | None = None) -> dict[str, CallResult]:
    detail = source.call("get_stock_detail", symbol=symbols or [], fields=[], status=1)
    industry_frames = []
    if symbols and len(symbols) <= 100:
        for symbol in symbols:
            result = source.call("get_stock_industry", stock_symbol=symbol, level="L1")
            if result.ok:
                frame = result.data.copy()
                if "symbol" not in frame.columns and "stock_symbol" not in frame.columns:
                    frame["symbol"] = symbol
                industry_frames.append(frame)
        if industry_frames:
            combined = pd.concat(industry_frames, ignore_index=True)
            industry = CallResult(
                method="get_stock_industry",
                status="ok",
                data=combined,
                rows=len(combined),
                columns=[str(column) for column in combined.columns],
                latest_date=latest_date(combined),
                params={"symbol_count": len(symbols), "level": "L1"},
            )
        else:
            industry = CallResult(
                method="get_stock_industry",
                status="empty",
                params={"symbol_count": len(symbols), "level": "L1"},
                error="逐股票查询未返回行业记录",
            )
    else:
        symbol_count = len(symbols) if symbols else 0
        industry = CallResult(
            method="get_stock_industry",
            status="unsupported",
            params={"scope": "batch_skipped", "symbol_count": symbol_count},
            error=(
                "该接口要求单个 stock_symbol；股票池超过100只时不逐股查询，"
                "以避免数百至数千次请求"
            ),
        )
    return {"detail": detail, "industry": industry}


def fetch_national_team(source: PandaDataSource, as_of: str, symbols: list[str] | None = None) -> CallResult:
    start, end = date_window(as_of, 550)
    return source.call(
        "get_top_holders",
        symbol=symbols or None,
        start_date=start,
        end_date=end,
        start_rank=1,
        end_rank=10,
        stock_type="flow",
        market="cn",
        fields=[],
    )


def fetch_etf_proxy(source: PandaDataSource, as_of: str) -> dict[str, CallResult]:
    start, end = date_window(as_of, 35)
    symbols = ["510050.SH", "510300.SH", "510500.SH", "512100.SH", "159915.SZ"]
    return {
        "etf_net_creation": source.call(
            "get_fund_etf_cr_net",
            symbol=symbols,
            start_date=start,
            end_date=end,
            fields=[],
            unsupported_hint=True,
        ),
        "etf_daily": source.call(
            "get_fund_daily",
            symbol=symbols,
            start_date=start,
            end_date=end,
            fields=[],
            unsupported_hint=True,
        ),
    }


def probe_interfaces(source: PandaDataSource, as_of: str) -> dict[str, CallResult]:
    short_start, end = date_window(as_of, 12)
    holder_start, _ = date_window(as_of, 550)
    symbol = ["000001.SZ"]
    probes = {
        "trade_calendar": source.call(
            "get_trade_cal",
            start_date=short_start,
            end_date=end,
            exchange="SH",
            is_trading_day=1,
            fields=[],
        ),
        "stock_daily": source.call(
            "get_stock_daily",
            symbol=symbol,
            start_date=short_start,
            end_date=end,
            fields=[],
        ),
        "stock_rt_daily": source.call("get_stock_rt_daily", symbol=symbol, fields=[]),
        "index_daily": source.call(
            "get_index_daily",
            symbol=["000300.SH"],
            start_date=short_start,
            end_date=end,
            fields=[],
        ),
        "margin": source.call(
            "get_margin", symbol=symbol, start_date=short_start, end_date=end, fields=[]
        ),
        "northbound": source.call(
            "get_hsgt_hold", symbol=symbol, start_date=holder_start, end_date=end, fields=[]
        ),
        "lhb_list": source.call(
            "get_lhb_list", symbol=symbol, start_date=short_start, end_date=end, fields=[]
        ),
        "lhb_detail": source.call(
            "get_lhb_detail", symbol=symbol, start_date=short_start, end_date=end, fields=[]
        ),
        "top_holders": source.call(
            "get_top_holders",
            symbol=symbol,
            start_date=holder_start,
            end_date=end,
            start_rank=1,
            end_rank=10,
            stock_type="flow",
            market="cn",
            fields=[],
        ),
        "etf_net_creation": source.call(
            "get_fund_etf_cr_net",
            symbol=["510300.SH"],
            start_date=short_start,
            end_date=end,
            fields=[],
            unsupported_hint=True,
        ),
        "fund_daily": source.call(
            "get_fund_daily",
            symbol=["510300.SH"],
            start_date=short_start,
            end_date=end,
            fields=[],
            unsupported_hint=True,
        ),
    }
    return probes
