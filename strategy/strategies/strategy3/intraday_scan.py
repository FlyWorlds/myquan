"""策略3手动盘中快照：交易日9:25起，严格使用已到达的正式行情。"""
from __future__ import annotations
import math
import pandas as pd
from holdingStocks.trading_calendar import is_trading_day, previous_trading_day, last_trading_day_on_or_before


def shanghai_now(now=None):
    ts=pd.Timestamp.now(tz='Asia/Shanghai') if now is None else pd.Timestamp(now)
    return ts.tz_localize('Asia/Shanghai') if ts.tzinfo is None else ts.tz_convert('Asia/Shanghai')


def scan_context(now=None):
    now=shanghai_now(now); day=now.date(); clock=now.strftime('%H:%M:%S')
    live=is_trading_day(day) and '09:25:00'<=clock<'15:15:00'
    completed=(previous_trading_day(day) if is_trading_day(day) and clock<'15:15:00'
               else last_trading_day_on_or_before(day))
    return dict(mode='intraday' if live else 'daily',as_of=str(day if live else completed),
                history_as_of=str(completed),started_at=now.isoformat())


def fetch_scan_quotes(symbols):
    from holdingStocks.quote_feed import fetch_sina_batch
    quotes={}
    for i in range(0,len(symbols),50):
        batch=fetch_sina_batch(symbols[i:i+50])
        received=shanghai_now().isoformat()
        for symbol,q in batch.items():quotes[symbol]={**q,'received_at':received}
    return quotes


class QuoteUnavailable(ValueError):
    def __init__(self,status):
        super().__init__(status); self.status=status


def positive(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError):return None


def live_daily(history,quote,context):
    """只附加当前已知OHLC；历史前复权基准按正式昨收对齐至报价价格基准。"""
    if not quote:raise QuoteUnavailable('missing_quote')
    if not quote.get('source_time_verified'):raise QuoteUnavailable('unconfirmed_quote')
    try:
        stamp=shanghai_now(quote['last_ts']); received=shanghai_now(quote['received_at'])
    except (KeyError,ValueError,TypeError):raise QuoteUnavailable('invalid_quote')
    if str(stamp.date())!=context['as_of'] or str(received.date())!=context['as_of']:
        raise QuoteUnavailable('stale_quote')
    if stamp>received or received<shanghai_now(context['started_at']):raise QuoteUnavailable('future_quote')
    clock=stamp.strftime('%H:%M:%S'); now_clock=received.strftime('%H:%M:%S')
    if clock<'09:25:00' or clock>'15:00:59':raise QuoteUnavailable('unconfirmed_quote')
    # 9:25开盘价在开市前仍有效；午休/收盘后按最近交易时点检查新鲜度。
    reference=received
    if '09:25:00'<=now_clock<'09:30:00':reference=received.normalize()+pd.Timedelta(hours=9,minutes=25)
    elif '11:30:00'<=now_clock<'13:00:00':reference=received.normalize()+pd.Timedelta(hours=11,minutes=30)
    elif now_clock>='15:00:00':reference=received.normalize()+pd.Timedelta(hours=15)
    if (reference-stamp).total_seconds()>180:raise QuoteUnavailable('stale_quote')
    opening=positive(quote.get('raw_open')); previous=positive(quote.get('prev_close'))
    if opening is None or previous is None:raise QuoteUnavailable('invalid_quote')
    auction=clock<'09:30:00'
    # 9:25报价的last/high/low可以尚未发布，正式开盘价独立作为价格基准。
    if auction:
        if now_clock>='09:30:00':raise QuoteUnavailable('stale_quote')
        o=h=l=c=opening
    else:
        o=opening; c=positive(quote.get('raw_last')); h=positive(quote.get('raw_high')); l=positive(quote.get('raw_low'))
        if c is None or h is None or l is None or h<max(o,c) or l>min(o,c):raise QuoteUnavailable('invalid_quote')
    try:volume=float(quote.get('volume',0))/100  # 新浪股数 → 历史日线的手数
    except (ValueError,TypeError):raise QuoteUnavailable('invalid_quote')
    if not math.isfinite(volume) or volume<0 or (not auction and volume<=0):raise QuoteUnavailable('invalid_quote')
    base=history[history.date<=pd.Timestamp(context['history_as_of'])].copy()
    if len(base)<120 or str(base.date.max().date())!=context['history_as_of']:
        raise QuoteUnavailable('stale' if len(base)>=120 else 'short_history')
    scale=previous/float(base.close.iloc[-1])
    for col in ('open','high','low','close'):base[col]=base[col]*scale
    bar=dict(date=pd.Timestamp(context['as_of']),open=o,high=h,low=l,close=c,volume=volume,
             symbol=quote.get('symbol',base.symbol.iloc[-1] if 'symbol' in base else ''))
    return pd.concat([base,pd.DataFrame([bar])],ignore_index=True),dict(
        quote_at=stamp.isoformat(),quote_received_at=received.isoformat(),price_basis='auction_open' if auction else 'live_last',
        price=c,history_scale=scale,provisional=True)


def snapshot_valid(scan,config_digest,now=None):
    context=scan_context(now)
    return (scan.get('config_hash')==config_digest and scan.get('as_of')==context['as_of']
            and scan.get('scan_mode','daily')==context['mode'])
