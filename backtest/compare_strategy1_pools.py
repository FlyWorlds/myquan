"""Compare current S1/S16 snapshots using S1 rules and minute-close quote proxies.

Refuse to label incomplete minute coverage as a requested-window backtest.
Auction paths are unavailable: factor29 is explicitly excluded in both arms.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'holdingStocks')]
from holdingStocks.watch_config import strategy1_watchlist, strategy16_watchlist, DEFAULT_STOP_REBUY_BOUNCE_PCT
from holdingStocks.quote_exit import evaluate_quote_exit, overnight_note_updates
from holdingStocks.strategy1_entry import phase_at, quota_reason
from holdingStocks.daily_buy_quota import quota_reason as daily_fill_quota_reason
from holdingStocks.condition_buy import auction_entry_blocked
from strategy.binding_filters import open_break_entry_filter
from strategy.open_break import entry_trigger_price, cannot_buy_limit_up, limit_down_state
from strategy.pullback_wave_stop import realized_vol_daily
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.minute import pull_akshare_1m
from strategy.data import AKSHARE_CALL_LOCK
from backtest.strategy1_pool_1m import run as fees
from backtest.strategy16_core_leader.run_month_review import reconcile


def normalize(frame, column):
    frame = frame.copy()
    ts = pd.to_datetime(frame[column])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    frame[column] = ts
    return frame.sort_values(column).drop_duplicates(column, keep='last')


def complete_days(minutes):
    result = set()
    for day, frame in minutes.groupby(minutes.ts.dt.strftime('%Y-%m-%d')):
        clocks = set(frame.ts.dt.strftime('%H:%M'))
        # Sina omits 14:58/14:59 during the closing call auction (238 bars/day).
        expected = set(pd.date_range(day+' 09:31', day+' 11:30', freq='min').strftime('%H:%M'))
        expected |= set(pd.date_range(day+' 13:01', day+' 15:00', freq='min').strftime('%H:%M'))
        expected -= {'14:58', '14:59'}
        if not (expected - clocks) and '15:00' in clocks and min(clocks) <= '09:31':
            result.add(day)
    return result


def usable_days(minutes):
    """Supplementary proxy only; sparse minutes are not silently fabricated."""
    result = set()
    for day, frame in minutes.groupby(minutes.ts.dt.strftime('%Y-%m-%d')):
        clocks = frame.ts.dt.strftime('%H:%M')
        if len(set(clocks)) >= 230 and clocks.min() <= '09:31' and clocks.max() == '15:00':
            result.add(day)
    return result


def collect(w, out, refresh):
    symbol = w['sina']
    path = out / 'minutes' / (symbol+'.parquet')
    frames = []
    sources = []
    if path.exists():
        frames.append(normalize(pd.read_parquet(path), 'ts'))
        sources.append(str(path.relative_to(ROOT)))
    else:
        for p in sorted((ROOT/'backtest').rglob(symbol+'*.parquet')):
            # Explicitly exclude qfq/5m/30m bars: execution prices are unadjusted 1m.
            if p.name not in (symbol+'.parquet', symbol+'_1m.parquet'):
                continue
            try:
                df = pd.read_parquet(p)
                if {'ts','open','high','low','close'} <= set(df):
                    frames.append(normalize(df, 'ts'))
                    sources.append(str(p.relative_to(ROOT)))
            except Exception:
                pass
        dbpath = ROOT/'data_cache/research_minutes.sqlite3'
        if dbpath.exists():
            with sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True) as db:
                df = pd.read_sql_query('SELECT ts,open,high,low,close FROM research_minutes WHERE symbol=? ORDER BY fetched_at', db, params=(symbol,))
            if not df.empty:
                frames.append(normalize(df, 'ts'))
                sources.append('research_minutes.sqlite3')
    error = None
    if refresh:
        try:
            with AKSHARE_CALL_LOCK:
                df = pull_akshare_1m(em_symbol=w['code'], sina_symbol=symbol, adjust='', retries=1)
            if not df.empty:
                frames.append(normalize(df, 'ts'))
                sources.append('eastmoney/sina_1m_unadjusted')
        except Exception as e:
            error = str(e)
    if not frames:
        raise ValueError(symbol+': no minute data')
    m = normalize(pd.concat(frames, ignore_index=True), 'ts')
    m = m[['ts','open','high','low','close']].dropna()
    good = (m.low > 0) & (m.low <= m[['open','close']].min(axis=1)) & (m.high >= m[['open','close']].max(axis=1))
    if not good.all():
        raise ValueError(symbol+': invalid OHLC')
    path.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(path, index=False)
    daily_path = ROOT/'data_cache'/f'{symbol}_daily_qfq.parquet'
    d = normalize(pd.read_parquet(daily_path), 'date')
    # A full unadjusted minute day supplies same-scale daily OHLC for the replay.
    # Historical qfq daily bars are retained ONLY before minute coverage for filters/vol.
    aggregates = []
    usable = usable_days(m)
    for day, frame in m.groupby(m.ts.dt.strftime('%Y-%m-%d')):
        if day in usable:
            aggregates.append(dict(date=pd.Timestamp(day)+pd.Timedelta(hours=15), open=float(frame.iloc[0].open),
                high=float(frame.high.max()), low=float(frame.low.min()), close=float(frame.iloc[-1].close)))
    if aggregates:
        d = normalize(pd.concat([d,pd.DataFrame(aggregates)],ignore_index=True), 'date')
    print(symbol, len(complete_days(m)), 'complete days, last', str(m.ts.max()), flush=True)
    return dict(w=w, minutes=m, daily=d, sources=sources, fetch_error=error)


def simulate(stocks, calendar, initial=300000., max_slots=5, weight=.2):
    cash, positions, marks, trades, equity = initial, {}, {}, [], []
    def value():
        return cash + sum(p['qty']*marks[c] for c,p in positions.items())
    def sell(code, px, qty, stamp, reason):
        nonlocal cash
        p = positions[code]
        assert p['buy_time'][:10] < stamp[:10], 'T+1 violation'
        assert 0 < qty <= p['qty']
        cash += fees._sell_credit(px, qty, code)
        pnl = px/p['cost']-1
        trades.append(dict(date=stamp[:10],ts=stamp,time=stamp,session=stamp[:10],side='sell',code=code,
            name=p['name'],px=px,shares=qty,pnl_pct=pnl,exit_reason=reason))
        p['qty'] -= qty
        p['available'] = max(0,p.get('available',0)-qty)
        if not p['qty']:
            sold[code] = dict(rebuy=pnl<=.01 and any(k in reason for k in ('protect','hard','trail','gap','giveback')), ts=stamp, exit_px=float(px))
            del positions[code]
    for day in calendar:
        sold, new_codes, metadata, quotes = {}, set(), {}, {}
        for s in stocks:
            w, d, m = s['w'], s['daily'], s['minutes']
            bars = m[m.ts.dt.strftime('%Y-%m-%d')==day].copy()
            if bars.empty:
                raise ValueError(f'{w["code"]}: missing {day}')
            prior = d[d.date.dt.strftime('%Y-%m-%d') < day]
            if len(prior)<20:
                raise ValueError(f'{w["code"]}: fewer than 20 prior daily bars')
            prev, prev2 = prior.iloc[-1],prior.iloc[-2]
            ep = float(w.get('entry_pct') or .025)
            allowed = open_break_entry_filter(prev.open,prev.close,prev2.open,prev2.close,entry_pct=ep)
            opening = float(bars.iloc[0].open)
            metadata[w['code']] = dict(w=w,opening=opening,prev_close=float(prev.close),allowed=allowed,
                ep=ep,vol=realized_vol_daily(prior.close.tolist()))
            bars['code']=w['code'];quotes[w['code']]=bars
        timeline = pd.concat(quotes.values()).sort_values(['ts','code'])
        lows,highs = {},{}
        for ts, bucket in timeline.groupby('ts',sort=True):
            stamp, now = str(ts), ts.to_pydatetime()
            # Close observation includes only this completed minute's cumulative OHLC.
            for b in bucket.itertuples():
                c=b.code; md=metadata[c]
                lows[c]=min(lows.get(c,md['opening']),float(b.low))
                highs[c]=max(highs.get(c,md['opening']),float(b.high))
                marks[c]=float(b.close)
            for b in bucket.itertuples():
                c=b.code;md=metadata[c]
                if c not in positions:
                    continue
                p=positions[c]
                q=dict(session=day,last_ts=stamp,open=md['opening'],last=float(b.close),high=highs[c],low=lows[c],prev_close=md['prev_close'])
                if p['buy_time'][:10]<day and p.get('opening_session')!=day:
                    p.update(overnight_note_updates(p,q,day));p['available']=p['qty'];p['opening_session']=day
                    protect=evaluate_overnight_open_protect(dict(p,open_px=md['opening'],prev_close=md['prev_close'],session=day,overnight_high_ok=True))
                    locked=limit_down_state(prev_close=md['prev_close'],open_px=md['opening'],high_px=md['opening'],low_px=md['opening'],close_px=md['opening'],limit_down_pct=.1,tick=.01)['locked']
                    if protect.triggered and not locked:
                        sell(c,md['opening'],p['qty'],day+' 09:30:00','open_protect')
                        continue
                result=evaluate_quote_exit(p,q,session=day,now=now,received_at=now,vol20_daily=md['vol'])
                if result:
                    p.update(result['updates']);p['quote_exit_watermark']=result['watermark']
                    action=result.get('action')
                    if action and action.get('shares',0)>0:
                        sell(c,float(b.close),int(action['shares']),stamp,action.get('reason') or action.get('kind') or 'factor26')
                        if c in positions and action.get('kind') == 'half':
                            positions[c]['tp_stage']=1
            phase=phase_at(now)
            if phase not in ('breakout','day_low_rebound'):
                continue
            for b in bucket.itertuples():
                c=b.code;md=metadata[c];w=md['w']
                if c in positions or not md['allowed'] or (c in sold and (not sold[c]['rebuy'] or sold[c]['ts']>=stamp)):
                    continue
                order=dict(strategy='strategy1',kind=phase)
                if quota_reason(order,trades,day) or len(positions)>=max_slots:
                    continue
                if daily_fill_quota_reason(trades, day, is_rebuy=c in sold):
                    continue
                target=entry_trigger_price(sold[c]['exit_px'], entry_pct=DEFAULT_STOP_REBUY_BOUNCE_PCT) if c in sold else entry_trigger_price(lows[c] if phase=='day_low_rebound' else md['opening'],entry_pct=md['ep'])
                if float(b.close)<target or auction_entry_blocked(md['opening'],md['prev_close']):
                    continue
                if cannot_buy_limit_up(prev_close=md['prev_close'],open_px=md['opening'],high_px=highs[c],low_px=lows[c],close_px=float(b.close),limit_up_pct=.1,tick=.01):
                    continue
                px=float(b.close)  # observed proxy; never fill a past threshold/low
                qty=fees._lot_shares(min(cash,value()*weight),fees._buy_unit(px))
                if qty<100:
                    continue
                cash-=fees._buy_outlay(px,qty)
                positions[c]=dict(code=c,name=w['name'],qty=qty,available=0,cost=px,buy_time=stamp,peak_high=px,tp_stage=0)
                if c not in sold:
                    new_codes.add(c)
                trades.append(dict(date=day,ts=stamp,time=stamp,session=day,side='buy',code=c,name=w['name'],px=px,shares=qty,
                    kind=phase,signal_factor='factor33' if phase=='day_low_rebound' else 'factor26',source='minute_close_proxy',is_rebuy=c in sold, trigger_price=target, rebuy_reference_px=sold[c]['exit_px'] if c in sold else None, rebuy_pct=DEFAULT_STOP_REBUY_BOUNCE_PCT if c in sold else None))
                assert cash>=-1e-6 and len(positions)<=max_slots
        equity.append(dict(date=day,equity=round(value(),2),cash=round(cash,2),n_pos=len(positions),ret_pct=(value()/initial-1)*100))
    peak=initial;dd=0.
    for e in equity:
        peak=max(peak,e['equity']);dd=min(dd,e['equity']/peak-1)
    result=dict(trades=trades,equity=equity,open_positions=[dict(code=c,name=p['name'],shares=p['qty'],last_px=marks[c],buy_px=p['cost']) for c,p in positions.items()],
        summary=dict(initial_cash=initial,final_equity=equity[-1]['equity'],return_pct=round((value()/initial-1)*100,4),max_dd_pct=round(dd*100,4),calendar=calendar,
            n_buys=sum(t['side']=='buy' for t in trades),n_sells=sum(t['side']=='sell' for t in trades),n_open=len(positions)))
    cycles,accounting=reconcile(result)
    closed=[c for c in cycles if not c['remaining_qty']]
    result.update(cycles=cycles,accounting=accounting)
    result['summary'].update(closed_cycles=len(closed),win_rate_pct=round(sum(c['net_pnl']>0 for c in closed)/len(closed)*100,2) if closed else None)
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='backtest/strategy1_compare_20261028');ap.add_argument('--refresh',action='store_true');ap.add_argument('--end',default='2026-10-28')
    args=ap.parse_args();out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    pools={'strategy1':strategy1_watchlist({}),'strategy16':strategy16_watchlist({})}
    # Pools keep their frozen per-symbol thresholds; all execution rules are S1.
    (out/'pool_snapshot.json').write_text(json.dumps(pools,ensure_ascii=False,indent=2,default=str))
    universe={w['code']:w for rows in pools.values() for w in rows}
    stocks={};failures=[]
    def worker(w):
        try:return w['code'],collect(w,out,args.refresh),None
        except Exception as e:return w['code'],None,str(e)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for code,s,error in ex.map(worker,universe.values()):
            if error:failures.append(dict(code=code,error=error))
            else:stocks[code]=s
    if not stocks:raise RuntimeError('No usable data')
    ref=stocks['600330'];dates=ref['daily'].date.dt.strftime('%Y-%m-%d')
    calendar=sorted(set(dates[dates<=args.end]))[-20:]
    common=set(calendar);strict_common=set(calendar);coverage=[]
    for c,w in universe.items():
        complete=complete_days(stocks[c]['minutes']) if c in stocks else set()
        usable=usable_days(stocks[c]['minutes']) if c in stocks else set()
        common &= usable
        strict_common &= complete
        coverage.append(dict(code=c,name=w['name'],pool=','.join(k for k,rows in pools.items() if any(x['code']==c for x in rows)),
            complete_requested=len(set(calendar)&complete),usable_requested=len(set(calendar)&usable),missing_days=','.join(sorted(set(calendar)-complete))))
    pd.DataFrame(coverage).to_csv(out/'coverage.csv',index=False)
    common=sorted(common)
    # Never bridge an interior missing trading day as if no market move occurred.
    available_common = list(common)
    suffix = []
    for day in reversed(calendar):
        if day not in common:
            break
        suffix.append(day)
    common = list(reversed(suffix))
    audit=dict(requested_calendar=calendar,requested_days=20,requested_window_complete=len(strict_common)==20 and not failures,
        common_usable_calendar=common,all_common_usable_dates=available_common,failures=failures,minute_api_error='本次探测：Pandadata 200103 API访问权限不足',
        limitations=['当前股票池及当前冻结阈值向历史回放，存在选股/阈值前视偏差，不是历史时点选股或样本外验证',
            '无历史竞价路径，两个池均排除因子29买卖；不等于完整策略1回测',
            '分钟收盘报价代理，买卖按观察价；不还原逐笔成交、分钟内触达顺序及真实排队',
            '同一分钟先处理卖出再买入，同分钟多个买点按代码排序，先后顺序会影响组合结果',
            '补充回放允许每天最多8条缺分钟（每日≥230条且开收盘齐全），缺口不插值，可能漏掉信号；不代表严格连续完整分钟历史',
            '保留池子各自个股阈值；资金、时段、形态过滤和卖出规则完全相同',
            '最大回撤按日末权益计算，未平仓按收盘估值，含佣金杂费印花税和双边0.1%滑点'])
    reports={}
    if common:
        for sid,rows in pools.items():
            payload=[]
            for w in rows:
                s=dict(stocks[w['code']],w=w)
                s['minutes']=s['minutes'][s['minutes'].ts.dt.strftime('%Y-%m-%d').isin(common)]
                payload.append(s)
            result=simulate(payload,common)
            reports[sid]=result
            (out/f'{sid}_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
            for key in ('trades','equity','cycles','open_positions'):
                pd.DataFrame(result[key]).to_csv(out/f'{sid}_{key}.csv',index=False)
            stock_rows=[]
            for w in rows:
                cycles=[c for c in result['cycles'] if c['code']==w['code']]
                stock_rows.append(dict(code=w['code'],name=w['name'],entry_pct=w['entry_pct'],
                    buy_cycles=len(cycles),closed_cycles=sum(not c['remaining_qty'] for c in cycles),
                    net_pnl=round(sum(c['net_pnl'] for c in cycles),2),remaining_shares=sum(c['remaining_qty'] for c in cycles)))
            pd.DataFrame(stock_rows).to_csv(out/f'{sid}_stock_contribution.csv',index=False)
    (out/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    lines=['# 策略1规则 × 两股票池回测核验','',f'请求：最近20个完整交易日，{calendar[0]} 至 {calendar[-1]}。',
        '', '**20日完整回测未完成：历史1分钟数据覆盖不足，不能给出有效20日收益结论。**' if not audit['requested_window_complete'] else '**20日分钟代理回测完成（竞价因子除外）。**',
        '',f'策略1池 {len(pools["strategy1"])} 只；策略16池 {len(pools["strategy16"])} 只；并集 {len(universe)} 只。均含公共自选池。',
        '', '共同可用分钟区间（每日≥230条且开收盘齐全）：'+(', '.join(common) if common else '无')+'。仅为缩短区间的补充研究，不替代请求的20日验证。',
        '', '资金30万元，最多5只，每槽20%；每日买入最多3笔，新增最多2笔、止损接回最多1笔；9:30–10:00开盘突破最多1只，10点后低点反弹补槽；T+1，因子26多层止盈、隔夜开盘保护，止损后符合条件可买回。',
        '', '| 股票池 | 补充区间收益 | 日末最大回撤 | 买入/卖出 | 完整平仓胜率 | 期末权益 |', '|---|---:|---:|---:|---:|---:|']
    for sid,res in reports.items():
        s=res['summary'];lines.append(f'| {sid} | {s["return_pct"]:.2f}% | {s["max_dd_pct"]:.2f}% | {s["n_buys"]}/{s["n_sells"]} | {s["win_rate_pct"]}% | {s["final_equity"]:,.2f} |')
    lines+=['','## 限制','']+['- '+x for x in audit['limitations']]
    lines+=['','数据缺口详见 coverage.csv；股票池及阈值详见 pool_snapshot.json；流水、净值、完整持仓周期及现金权益核对见各池 CSV/JSON。',
        '', '继续完成20日验证需要覆盖请求区间、全部并集股票的未复权1分钟行情；完整策略1还需要9:20–9:25竞价路径。当前Pandadata分钟接口返回200103（权限不足），公共备用源仅提供最近约8个交易日。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(audit=audit,summary={k:v['summary'] for k,v in reports.items()}),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
