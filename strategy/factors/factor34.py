"""Research factor: volume contraction followed by bullish expansion.

No execution, portfolio mutation or future-price inputs. Decimal returns use
fractions (0.05 = 5%). Input prices must share an adjustment basis and volume unit.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, time

import numpy as np
import pandas as pd

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec


def _daily(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ['date', 'open', 'high', 'low', 'close', 'volume']
    if not set(columns) <= set(frame.columns):
        raise ValueError('需要date/open/high/low/close/volume')
    d = frame[columns].copy().reset_index(drop=True)
    dates = pd.to_datetime(d.date)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai')
    d['date'] = dates.dt.strftime('%Y-%m-%d')
    if dates.isna().any() or d.date.duplicated().any() or not d.date.is_monotonic_increasing:
        raise ValueError('日线日期必须有效、严格递增且不重复')
    for c in columns[1:]:
        d[c] = pd.to_numeric(d[c], errors='raise').astype(float)
        if not np.isfinite(d[c]).all() or (d[c] <= 0).any():
            raise ValueError(f'{c}必须是正有限数；不允许缺失日线或零量占位')
    if ((d.low > d[['open', 'close']].min(axis=1) + 1e-9)
            | (d.high < d[['open', 'close']].max(axis=1) - 1e-9)).any():
        raise ValueError('OHLC不自洽')
    return d


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gains, losses = delta.clip(lower=0), -delta.clip(upper=0)
    out = pd.Series(np.nan, index=close.index)
    for i in range(n, len(close)):
        if i == n:
            gain, loss = gains.iloc[1:n+1].mean(), losses.iloc[1:n+1].mean()
        else:
            gain = (gain * (n-1) + gains.iloc[i]) / n
            loss = (loss * (n-1) + losses.iloc[i]) / n
        out.iloc[i] = 50 if gain == loss == 0 else 100 if loss == 0 else 100-100/(1+gain/loss)
    return out


def compute(frame: pd.DataFrame, *, lookback: int = 60, max_age: int = 10,
            volume_multiple: float = 2.0, body_min: float = .05) -> pd.DataFrame:
    """Completed daily bars only. Row t depends only on rows <= t.

    Most recent low-volume anchor wins. Each anchor emits at most one daily
    candidate; a later 60-session minimum starts a new anchor lifecycle.
    """
    if (not isinstance(lookback, int) or lookback < 2 or not isinstance(max_age, int)
            or max_age < 1 or not math.isfinite(volume_multiple) or volume_multiple < 1
            or not math.isfinite(body_min) or body_min <= 0):
        raise ValueError('无效因子参数')
    d = _daily(frame)
    d['ready'] = np.arange(len(d)) >= lookback
    d['body_return'] = d.close/d.open-1
    d['volume_ratio20'] = d.volume/d.volume.shift().rolling(20).mean()
    d['low_volume60'] = d.volume <= d.volume.rolling(lookback).min()
    d['high_volume60'] = d.volume >= d.volume.rolling(lookback).max()
    d['rsi14'] = _rsi(d.close)
    d['bias20'] = d.close/d.close.rolling(20).mean()-1
    d['close_position'] = (d.close-d.low)/(d.high-d.low).replace(0, np.nan)
    anchors, ages, ratios, signals = [], [], [], []
    anchor = None
    consumed = set()
    for i, row in d.iterrows():
        age = i-anchor if anchor is not None else None
        eligible = age is not None and 1 <= age <= max_age
        ratio = row.volume/d.iloc[anchor].volume if eligible else np.nan
        hit = bool(eligible and anchor not in consumed and ratio >= volume_multiple
                   and row.body_return >= body_min-1e-12)
        anchors.append(d.iloc[anchor].date if eligible else None)
        ages.append(age if eligible else np.nan)
        ratios.append(ratio)
        signals.append(hit)
        if hit:
            consumed.add(anchor)
        if row.low_volume60:
            anchor = i
    d['anchor_date'], d['anchor_age'] = anchors, ages
    d['anchor_volume_ratio'], d['candidate'] = ratios, signals
    return d


def replay(frame: pd.DataFrame, **params) -> dict:
    """JSON-safe research output; no fills or same-close entry assumption."""
    return {'factor_id': 'factor34', 'status': 'research',
            'rows': json.loads(compute(frame, **params).to_json(orient='records'))}


def signal(frame: pd.DataFrame, *, as_of: datetime, **params) -> dict:
    """Daily candidate only after the supplied final day's close is available."""
    now = _local(as_of)
    d = _daily(frame)
    if d.empty:
        return {'ready': False, 'candidate': False, 'hit_buy': False, 'reason': 'empty'}
    day = now.strftime('%Y-%m-%d')
    if d.date.iloc[-1] > day or (d.date.iloc[-1] == day and now.time() < time(15, 15)):
        raise ValueError('收盘研究接口不能读取尚未完成的当日日线')
    row = replay(d, **params)['rows'][-1]
    return {**row, 'factor_id': 'factor34', 'hit_buy': False, 'mode': 'close_research',
            'execution': 'candidate_only_next_session_or_later'}


def _local(value: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError('时刻不可为空')
    return ts.tz_localize('Asia/Shanghai') if ts.tzinfo is None else ts.tz_convert('Asia/Shanghai')


def tail_candidate(history: pd.DataFrame, *, quote: dict, now: datetime,
                   consumed_anchors=(), max_quote_age: float = 5.0,
                   limit_up_pct: float = .10, **params) -> dict:
    """14:55 <= local time < 14:57. Uses cumulative volume, never final volume.

    quote requires ts/open/high/low/last/volume/prev_close/source_verified.
    Prices must be unadjusted (including prev_close = official reference price),
    history prices on the same basis, volumes in the SAME unit. Caller checks
    trading calendar, missing sessions, feed authenticity, position/T+1 and orders.
    Persist consumed anchor dates when acting on candidates; this function is pure.
    """
    idle = {'ready': False, 'candidate': False, 'hit_buy': False, 'factor_id': 'factor34'}
    try:
        clock, at = _local(now), _local(quote['ts'])
        if not math.isfinite(max_quote_age) or max_quote_age <= 0 or not 0 < limit_up_pct < 1:
            raise ValueError('无效时效/涨停参数')
        if not time(14, 55) <= clock.time() < time(14, 57):
            return {**idle, 'reason': 'outside_tail_window'}
        if (at.date() != clock.date() or not time(14,55) <= at.time() < time(14,57)
                or not 0 <= (clock-at).total_seconds() <= max_quote_age
                or quote.get('source_verified') is not True):
            return {**idle, 'reason': 'unverified_or_stale_quote'}
        day = clock.strftime('%Y-%m-%d')
        h = _daily(history)
        if not h.empty and h.date.iloc[-1] >= day:
            return {**idle, 'reason': 'history_contains_current_or_future_day'}
        prev = float(quote['prev_close'])
        if not math.isfinite(prev) or prev <= 0:
            raise ValueError('无效昨收参考价')
        current = dict(date=day, open=quote['open'], high=quote['high'], low=quote['low'],
                       close=quote['last'], volume=quote['volume'])
        row = replay(pd.concat([h, pd.DataFrame([current])], ignore_index=True), **params)['rows'][-1]
        reason = 'candidate' if row['candidate'] else 'conditions_not_met'
        candidate = row['candidate']
        if row['anchor_date'] in set(consumed_anchors):
            candidate, reason = False, 'anchor_consumed'
        if float(quote['last'])/prev-1 >= limit_up_pct-.003-1e-12:
            candidate, reason = False, 'near_limit_up'
        return {**row, 'candidate': candidate, 'hit_buy': False, 'reason': reason,
                'factor_id': 'factor34', 'mode': 'tail_observed', 'signal_time': str(at),
                'execution': 'candidate_only_next_observed_quote'}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**idle, 'reason': 'invalid_input'}


SPEC = FactorSpec(
    id='factor34', name='因子34-地量转放量动量', implemented=True,
    description='60日地量后10日内，成交量至少2倍、实体至少5%的首次动量候选；研究状态。',
    rules_text='只输出候选；日线信号收盘后可知，尾盘使用当时累计量。RSI/乖离仅诊断，不强制过滤；不指定最优持有期。',
    signal=signal, replay=replay,
    meta={'category': 'momentum', 'status': 'research', 'auto_trade': False,
          'defaults': {'lookback': 60, 'max_age': 10, 'volume_multiple': 2., 'body_min': .05}},
)
register_factor(SPEC, replace=True)
