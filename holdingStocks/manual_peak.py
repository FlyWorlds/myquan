"""Validate manual corrections of a live position's quote-driven peak."""
import math
from datetime import datetime, time
from zoneinfo import ZoneInfo


def update_peak(data, payload, *, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    if now.time() < time(9, 25):
        raise ValueError('峰值仅可在09:25后维护，避免影响盘前开盘准备')
    if not isinstance(payload, dict):
        raise ValueError('请求格式错误')
    code = str(payload.get('code') or '')
    pos = (data.get('positions') or {}).get(code)
    if not pos or int(pos.get('qty') or 0) <= 0:
        raise ValueError('该股票当前没有持仓，请刷新')
    if not payload.get('buyTime') or payload['buyTime'] != pos.get('buy_time'):
        raise ValueError('持仓已变化，请刷新后重试')
    try:
        peak = float(payload['peak'])
        expected = float(payload['expectedPeak'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('请输入有效的峰值价格') from None
    if isinstance(payload['peak'], bool) or not math.isfinite(peak) or peak <= 0:
        raise ValueError('峰值必须是大于零的有效价格')
    current = float(pos.get('peak_high') or pos.get('cost') or 0)
    if expected != current:
        raise ValueError('峰值已更新，请刷新后重新修改')
    at = now.isoformat(sep=' ', timespec='microseconds')
    pos.update(peak_high=peak, peak_high_at=at, peak_manual_at=at)
    return dict(ok=True, code=code, peak=peak)
