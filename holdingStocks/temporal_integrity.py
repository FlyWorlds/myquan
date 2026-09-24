# -*- coding: utf-8 -*-
"""交易系统时间完整性 invariant（禁止未卜先知）。

真源文档：docs/TEMPORAL_INTEGRITY.md
回归：holdingStocks/run_regression_tests.py → test_temporal_integrity

NO LOOK-AHEAD:
  任何 decision_at=T 的决策，只能使用 timestamp<=T 的数据。
  违例 → FUTURE_DATA_VIOLATION（中止动作，不得静默）。

HWM CAUSALITY:
  peak_high 必须和 peak_high_at 一起更新，且 peak_high_at <= decision_at。

EVENT IMMUTABILITY:
  triggered_at / filled_at / exit_kind
  不得根据事后价格或后续行情反向改写。
  禁止 fill≈open 推断开盘时刻（PATH 保持真实 triggered_at）。

STALE DATA:
  旧 timestamp 行情不得覆盖较新的策略状态 → STALE_QUOTE_REJECTED。

研究/模拟用途，不构成投资建议。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

FUTURE_DATA_VIOLATION = "FUTURE_DATA_VIOLATION"
STALE_QUOTE_REJECTED = "STALE_QUOTE_REJECTED"
MISSING_HWM_AT = "MISSING_HWM_AT"
LEGACY_HWM_AT = "LEGACY_UNKNOWN"


class TemporalIntegrityError(ValueError):
    """时间因果破坏；调用方必须中止自动交易动作。"""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.details = details or {}


def parse_event_ts(raw: Any) -> datetime | None:
    """宽松解析事件时间；无法解析返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    s = str(raw).strip()
    if not s or s.startswith("9999"):
        return None
    if s == LEGACY_HWM_AT:
        return None
    s = s.replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%H:%M:%S",
    ):
        try:
            if fmt == "%H:%M:%S":
                # 仅时钟：无法与决策日比较，调用方应补日期
                return None
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    try:
        import pandas as pd

        ts = pd.Timestamp(s)
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("Asia/Shanghai").tz_localize(None)
        return ts.to_pydatetime()
    except Exception:  # noqa: BLE001
        return None


def assert_not_future(
    *,
    event_at: Any,
    decision_at: Any,
    event_name: str = "event",
) -> None:
    """event_at 不得晚于 decision_at。"""
    ev = parse_event_ts(event_at)
    dec = parse_event_ts(decision_at)
    if ev is None or dec is None:
        return
    if ev > dec:
        raise TemporalIntegrityError(
            FUTURE_DATA_VIOLATION,
            f"{event_name}={ev.isoformat(sep=' ')} > decision_at={dec.isoformat(sep=' ')}",
            details={
                "event_name": event_name,
                "event_at": str(event_at),
                "decision_at": str(decision_at),
            },
        )


def assert_quote_usable(
    *,
    quote_at: Any,
    decision_at: Any,
    last_accepted_quote_at: Any = None,
) -> None:
    """拒绝未来行情；拒绝乱序旧行情覆盖。"""
    assert_not_future(event_at=quote_at, decision_at=decision_at, event_name="quote_at")
    q = parse_event_ts(quote_at)
    prev = parse_event_ts(last_accepted_quote_at)
    if q is not None and prev is not None and q < prev:
        raise TemporalIntegrityError(
            STALE_QUOTE_REJECTED,
            f"quote_at={q.isoformat(sep=' ')} < last_accepted={prev.isoformat(sep=' ')}",
            details={
                "quote_at": str(quote_at),
                "last_accepted_quote_at": str(last_accepted_quote_at),
            },
        )


def assert_hwm_causal(*, peak_high_at: Any, decision_at: Any) -> None:
    """peak_high_at <= decision_at；缺时间的旧仓跳过（降级），新仓必须有时间。"""
    if peak_high_at in (None, "", LEGACY_HWM_AT):
        return
    assert_not_future(
        event_at=peak_high_at, decision_at=decision_at, event_name="peak_high_at"
    )


def assert_event_time_chain(
    *,
    quote_at: Any = None,
    decision_at: Any = None,
    triggered_at: Any = None,
    filled_at: Any = None,
) -> None:
    """quote_at <= decision_at <= triggered_at <= filled_at（允许相等）。"""
    chain = [
        ("quote_at", quote_at),
        ("decision_at", decision_at),
        ("triggered_at", triggered_at),
        ("filled_at", filled_at),
    ]
    prev_name = None
    prev_dt = None
    for name, raw in chain:
        cur = parse_event_ts(raw)
        if cur is None:
            continue
        if prev_dt is not None and cur < prev_dt:
            raise TemporalIntegrityError(
                FUTURE_DATA_VIOLATION,
                f"{name}={cur.isoformat(sep=' ')} < {prev_name}={prev_dt.isoformat(sep=' ')}",
                details={name: str(raw), prev_name or "": str(prev_dt)},
            )
        prev_name, prev_dt = name, cur


def stamp_peak_high_atomic(
    pos: dict[str, Any],
    new_peak: float,
    *,
    at: str,
    decision_at: str | None = None,
) -> bool:
    """原子抬升 HWM：同时写 peak_high + peak_high_at；校验时间因果。

    返回 True 表示发生抬升。拒绝：at 为空、at > decision_at、峰值不升。
    """
    if not at or str(at).strip() in ("", LEGACY_HWM_AT):
        raise TemporalIntegrityError(
            MISSING_HWM_AT,
            "new HWM raise requires peak_high_at",
            details={"new_peak": new_peak},
        )
    dec = decision_at or at
    assert_hwm_causal(peak_high_at=at, decision_at=dec)
    try:
        old = float(pos.get("peak_high") or 0)
    except (TypeError, ValueError):
        old = 0.0
    try:
        npx = float(new_peak)
    except (TypeError, ValueError):
        return False
    if npx <= 0 or npx <= old + 1e-9:
        return False
    # 不允许 peak_high_at 倒退（乱序）
    old_at = pos.get("peak_high_at")
    old_dt = parse_event_ts(old_at)
    new_dt = parse_event_ts(at)
    if old_dt is not None and new_dt is not None and new_dt < old_dt and npx <= old + 1e-9:
        return False
    if old_dt is not None and new_dt is not None and new_dt < old_dt:
        # 峰值升高但时间更早 → 未来/乱序异常
        raise TemporalIntegrityError(
            FUTURE_DATA_VIOLATION,
            f"peak_high_at would go backwards {old_at} → {at}",
            details={"old_at": str(old_at), "new_at": str(at), "new_peak": npx},
        )
    pos["peak_high"] = round(npx, 4)
    pos["peak_high_at"] = str(at).strip()
    pos.pop("peak_high_at_degraded", None)
    return True


def migrate_legacy_peak_high_at(pos: dict[str, Any]) -> bool:
    """旧仓有 peak_high 无 peak_high_at：降级标记，不发明未来时间。"""
    if not isinstance(pos, dict):
        return False
    try:
        ph = float(pos.get("peak_high") or 0)
    except (TypeError, ValueError):
        return False
    if ph <= 0:
        return False
    at = pos.get("peak_high_at")
    if at not in (None, ""):
        return False
    # 优先用买入时间作下界，否则 LEGACY_UNKNOWN（审计时跳过严格比较）
    buy = pos.get("buy_time")
    if buy and parse_event_ts(buy) is not None:
        pos["peak_high_at"] = str(buy)
        pos["peak_high_at_degraded"] = True
    else:
        pos["peak_high_at"] = LEGACY_HWM_AT
        pos["peak_high_at_degraded"] = True
    return True


def reject_price_inferred_open_bell(
    *,
    exit_kind: str | None,
    open_bell: bool,
    fill_px: float | None,
    open_px: float | None,
) -> bool:
    """True = 允许记 09:30；仅真正的开盘保护，禁止 fill≈open 推断。"""
    if open_bell or str(exit_kind or "") == "open_protect":
        return True
    return False


def bar_usable_as_of(
    *,
    bar_ts: Any,
    decision_at: Any,
    bar_complete: bool = True,
) -> bool:
    """未完成 1m / 决策时点早于 bar 结束 → 不可用完整 high/low。"""
    if not bar_complete:
        return False
    b = parse_event_ts(bar_ts)
    d = parse_event_ts(decision_at)
    if b is None or d is None:
        return True
    # 1m 标签通常为 bar 开始；完整 bar 需 decision >= bar_start + 1m
    # 保守：decision 必须 >= bar_ts（若标签是结束时刻则刚好；若是开始则调用方应传 complete=False）
    return d >= b
