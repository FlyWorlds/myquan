"""Global Analysis: 10:00 Morning Drop 1% Stop applied across both Strategy 1 and Strategy 16 pools.

Evaluates:
1. Strategy 1 pool: Baseline vs Morning Drop 1% Stop
2. Strategy 16 pool: Baseline vs Morning Drop 1% Stop
Calculates daily alpha (excess return/pnl) for each day from 2026-10-30 to 2026-11-05.
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from backtest.compare_strategy1_pools import *
from backtest.compare_strategy1_morning_stop import normalize, complete_days, DAYS
from strategy.open_break import floor_to_tick, limit_down_state, entry_trigger_price, cannot_buy_limit_up
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.binding_filters import open_break_entry_filter
from strategy.pullback_wave_stop import realized_vol_daily
from holdingStocks.watch_config import (
    strategy1_watchlist,
    strategy16_watchlist,
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    DEFAULT_STOP_REBUY_BOUNCE_PCT,
)
from holdingStocks.quote_exit import evaluate_quote_exit, overnight_note_updates
from holdingStocks.strategy1_entry import phase_at, quota_reason
from holdingStocks.daily_buy_quota import quota_reason as daily_fill_quota_reason
from holdingStocks.condition_buy import auction_entry_blocked
from holdingStocks.attack_wave import AttackWaves
from backtest.strategy1_pool_1m import run as fees
from backtest.strategy16_core_leader.run_month_review import reconcile


def load_pool_stocks(watchlist, minutes_dir):
    stocks = []
    for w in watchlist:
        sina = w['sina']
        m_path = minutes_dir / f'{sina}.parquet'
        d_path = minutes_dir / f'{sina}_daily.parquet'
        if not m_path.exists() or not d_path.exists():
            raise FileNotFoundError(f'Missing files for {sina}')
        m = normalize(pd.read_parquet(m_path), 'ts')
        d = normalize(pd.read_parquet(d_path), 'date')
        stocks.append(dict(w=w, minutes=m, daily=d))
    return stocks


def simulate(stocks, calendar, mode='baseline'):
    """Simulate Strategy 1 rules.
    mode:
      - 'baseline': original Strategy 1 with 09:30 open_protect
      - 'morning_drop_1pct': 10:00前以开盘价再跌1%才止损(取消09:30开盘割肉, 10点前跌破开盘-1%才止损, 10点后沿用策略1)
    """
    initial = 300000.0
    cash = initial
    positions = {}
    trades = []
    equity = []
    marks = {}
    waves = AttackWaves()
    current_attack_wave = True
    max_slots = MAX_PORTFOLIO_SLOTS
    weight = SLOT_WEIGHT

    def value():
        return cash + sum(p['qty'] * marks[c] for c, p in positions.items())

    def sell(code, px, qty, stamp, reason):
        nonlocal cash
        p = positions[code]
        assert p['buy_time'][:10] < stamp[:10], 'T+1 violation'
        assert 0 < qty <= p['qty']
        cash += fees._sell_credit(float(px), qty, code)
        pnl = float(px) / float(p['cost']) - 1.0
        trades.append(dict(date=stamp[:10], ts=stamp, time=stamp, session=stamp[:10], side='sell', code=code,
                           name=p['name'], px=float(px), shares=qty, pnl_pct=pnl, exit_reason=reason))
        p['qty'] -= qty
        p['available'] = max(0, p.get('available', 0) - qty)
        if not p['qty']:
            sold[code] = dict(rebuy=pnl <= .01 or reason in {'vol_giveback', 'half_gain', 'peak_pullback_clear', 'ladder_half_10', 'ladder_full_15'},
                              ts=stamp, exit_px=float(px))
            del positions[code]

    for day in calendar:
        sold, new_codes, metadata, quotes = {}, set(), {}, {}
        for s in stocks:
            w, d, m = s['w'], s['daily'], s['minutes']
            bars = m[m.ts.dt.strftime('%Y-%m-%d') == day].copy()
            if bars.empty:
                raise ValueError(f'{w["code"]}: missing {day}')
            prior = d[d.date.dt.strftime('%Y-%m-%d') < day]
            if len(prior) < 20:
                raise ValueError(f'{w["code"]}: fewer than 20 prior daily bars')
            prev, prev2 = prior.iloc[-1], prior.iloc[-2]
            ep = float(w.get('entry_pct') or .025)
            allowed = open_break_entry_filter(prev.open, prev.close, prev2.open, prev2.close, entry_pct=ep)
            opening = float(bars.iloc[0].open)
            metadata[w['code']] = dict(w=w, opening=opening, prev_close=float(prev.close), allowed=allowed,
                                       ep=ep, vol=realized_vol_daily(prior.close.tolist()))
            bars['code'] = w['code']
            quotes[w['code']] = bars

        timeline = pd.concat(quotes.values()).sort_values(['ts', 'code'])
        lows, highs = {}, {}

        for ts, bucket in timeline.groupby('ts', sort=True):
            stamp, now = str(ts), ts.to_pydatetime()
            clock = now.strftime('%H:%M:%S')

            for b in bucket.itertuples():
                c = b.code
                md = metadata[c]
                lows[c] = min(lows.get(c, md['opening']), float(b.low))
                highs[c] = max(highs.get(c, md['opening']), float(b.high))
                marks[c] = float(b.close)
                if current_attack_wave:
                    waves.observe(c, dict(session=day, last_ts=stamp, open=md['opening'], last=float(b.close),
                                          high=highs[c], low=lows[c]), now)

            # 检查持仓退出
            for b in bucket.itertuples():
                c = b.code
                md = metadata[c]
                if c not in positions:
                    continue
                p = positions[c]
                q = dict(session=day, last_ts=stamp, open=md['opening'], last=float(b.close),
                         high=highs[c], low=lows[c], prev_close=md['prev_close'])

                # 隔夜仓位开盘第一秒处理
                if p['buy_time'][:10] < day and p.get('opening_session') != day:
                    p.update(overnight_note_updates(p, q, day))
                    p['available'] = p['qty']
                    p['opening_session'] = day
                    protect = evaluate_overnight_open_protect(dict(p, open_px=md['opening'], prev_close=md['prev_close'],
                                                                   session=day, overnight_high_ok=True))
                    locked = limit_down_state(prev_close=md['prev_close'], open_px=md['opening'], high_px=md['opening'],
                                              low_px=md['opening'], close_px=md['opening'], limit_down_pct=.1, tick=.01)['locked']

                    if mode == 'baseline':
                        if protect.triggered and not locked:
                            sell(c, md['opening'], p['qty'], day + ' 09:30:00', 'open_protect')
                            continue
                    elif mode == 'morning_drop_1pct':
                        if protect.triggered and not locked:
                            # 触发低开保护，但不立即卖出，设定开盘-1%止损线
                            p['drop_stop_active'] = True
                            p['drop_stop_px'] = floor_to_tick(md['opening'] * 0.99, tick=.01)
                            p['drop_stop_session'] = day

                # 10点前早盘保护逻辑
                if p.get('drop_stop_active') and p.get('drop_stop_session') == day and clock < '10:00:00':
                    if float(b.close) <= p['drop_stop_px'] + 1e-9:
                        sell(c, float(b.close), p['qty'], stamp, 'morning_drop_1pct_stop')
                        continue

                    # 检查阶梯向上止盈，屏蔽下行止损
                    result = evaluate_quote_exit(p, q, session=day, now=now, received_at=now, vol20_daily=md['vol'],
                                                 morning_open_stop=False)
                    if result:
                        p.update(result['updates'])
                        p['quote_exit_watermark'] = result['watermark']
                        action = result.get('action')
                        if action and action.get('shares', 0) > 0:
                            reason = action.get('reason') or action.get('kind') or ''
                            if 'ladder' in reason:
                                sell(c, float(b.close), int(action['shares']), stamp, reason)
                                if c in positions and action.get('kind') == 'half':
                                    positions[c]['tp_stage'] = 1
                    continue

                if clock >= '10:00:00' and p.get('drop_stop_active'):
                    p.pop('drop_stop_active', None)
                    p.pop('drop_stop_px', None)
                    p.pop('drop_stop_session', None)

                # 常规动态止盈止损
                result = evaluate_quote_exit(p, q, session=day, now=now, received_at=now, vol20_daily=md['vol'],
                                             morning_open_stop=False)
                if result:
                    p.update(result['updates'])
                    p['quote_exit_watermark'] = result['watermark']
                    action = result.get('action')
                    if action and action.get('shares', 0) > 0:
                        sell(c, float(b.close), int(action['shares']), stamp,
                             action.get('reason') or action.get('kind') or 'factor26')
                        if c in positions and action.get('kind') == 'half':
                            positions[c]['tp_stage'] = 1

            # 买入逻辑
            phase = phase_at(now)
            if phase not in ('breakout', 'day_low_rebound'):
                continue
            for b in bucket.itertuples():
                c = b.code
                md = metadata[c]
                w = md['w']
                if c in positions or (not md['allowed'] and not (current_attack_wave and c in sold and sold[c]['rebuy'])) or (c in sold and (not sold[c]['rebuy'] or sold[c]['ts'] >= stamp)):
                    continue
                order = dict(strategy='strategy1', kind=phase)
                if quota_reason(order, trades, day) or len(positions) >= max_slots:
                    continue
                if daily_fill_quota_reason(trades, day, is_rebuy=c in sold):
                    continue
                target = entry_trigger_price(sold[c]['exit_px'], entry_pct=DEFAULT_STOP_REBUY_BOUNCE_PCT) if c in sold else entry_trigger_price(lows[c] if phase == 'day_low_rebound' else md['opening'], entry_pct=md['ep'])
                if current_attack_wave:
                    if c in sold and phase != 'day_low_rebound':
                        continue
                    if phase == 'day_low_rebound':
                        wave = waves.states.get(c, {})
                        if not wave.get('ready') or (c in sold and wave.get('anchor_at', '') <= sold[c]['ts']):
                            continue
                        target = entry_trigger_price(wave['low'], entry_pct=md['ep'])
                if float(b.close) < target or auction_entry_blocked(md['opening'], md['prev_close']):
                    continue
                if cannot_buy_limit_up(prev_close=md['prev_close'], open_px=md['opening'], high_px=highs[c], low_px=lows[c], close_px=float(b.close), limit_up_pct=.1, tick=.01):
                    continue
                px = float(b.close)
                qty = fees._lot_shares(min(cash, value() * weight), fees._buy_unit(px))
                if qty < 100:
                    continue
                cash -= fees._buy_outlay(px, qty)
                positions[c] = dict(code=c, name=w['name'], qty=qty, available=0, cost=px, buy_time=stamp, peak_high=px, tp_stage=0)
                if c not in sold:
                    new_codes.add(c)
                trades.append(dict(date=day, ts=stamp, time=stamp, session=day, side='buy', code=c, name=w['name'], px=px, shares=qty,
                                   kind=phase, signal_factor='factor33' if phase == 'day_low_rebound' else 'factor26', source='minute_close_proxy',
                                   is_rebuy=c in sold, trigger_price=target, rebuy_reference_px=sold[c]['exit_px'] if c in sold else None,
                                   rebuy_pct=DEFAULT_STOP_REBUY_BOUNCE_PCT if c in sold else None))

        equity.append(dict(date=day, equity=round(value(), 2), cash=round(cash, 2), n_pos=len(positions), ret_pct=(value() / initial - 1) * 100))

    peak = initial
    dd = 0.0
    for e in equity:
        peak = max(peak, e['equity'])
        dd = min(dd, e['equity'] / peak - 1)
    result = dict(trades=trades, equity=equity,
                  open_positions=[dict(code=c, name=p['name'], shares=p['qty'], last_px=marks[c], buy_px=p['cost']) for c, p in positions.items()],
                  summary=dict(initial_cash=initial, final_equity=equity[-1]['equity'], return_pct=round((value() / initial - 1) * 100, 4),
                               max_dd_pct=round(dd * 100, 4), calendar=calendar,
                               n_buys=sum(t['side'] == 'buy' for t in trades), n_sells=sum(t['side'] == 'sell' for t in trades), n_open=len(positions)))
    cycles, accounting = reconcile(result)
    closed = [c for c in cycles if not c['remaining_qty']]
    result.update(cycles=cycles, accounting=accounting)
    result['summary'].update(closed_cycles=len(closed), win_rate_pct=round(sum(c['net_pnl'] > 0 for c in closed) / len(closed) * 100, 2) if closed else None)
    return result


def evaluate_pair(pool_name, stocks, calendar):
    r_base = simulate(stocks, calendar, mode='baseline')
    r_drop = simulate(stocks, calendar, mode='morning_drop_1pct')

    init_b = next((e['equity'] for e in reversed(r_base['equity']) if e['date'] < DAYS[0]), 300000.0)
    init_d = next((e['equity'] for e in reversed(r_drop['equity']) if e['date'] < DAYS[0]), 300000.0)

    prev_b = init_b
    prev_d = init_d

    daily_rows = []
    for day in DAYS:
        eb = next(e['equity'] for e in r_base['equity'] if e['date'] == day)
        ed = next(e['equity'] for e in r_drop['equity'] if e['date'] == day)

        pnl_b = eb - prev_b
        pnl_d = ed - prev_d

        pct_b = (eb / prev_b - 1) * 100
        pct_d = (ed / prev_d - 1) * 100

        cum_b = (eb / init_b - 1) * 100
        cum_d = (ed / init_d - 1) * 100

        diff_pnl = pnl_d - pnl_b
        diff_pct = pct_d - pct_b

        daily_rows.append(dict(
            pool=pool_name,
            date=day,
            base_equity=round(eb, 2),
            base_pnl=round(pnl_b, 2),
            base_daily_pct=round(pct_b, 2),
            base_cum_pct=round(cum_b, 2),
            drop_equity=round(ed, 2),
            drop_pnl=round(pnl_d, 2),
            drop_daily_pct=round(pct_d, 2),
            drop_cum_pct=round(cum_d, 2),
            excess_pnl=round(diff_pnl, 2),
            excess_pct=round(diff_pct, 2),
        ))
        prev_b = eb
        prev_d = ed

    return r_base, r_drop, daily_rows


def main():
    warm = ['2026-10-27', '2026-10-28', '2026-10-29']
    calendar = warm + DAYS

    # 1. 策略 1 池子 (25 只)
    s1_wl = strategy1_watchlist()
    s1_dir = ROOT / 'reports/strategy1_open_stop_20261105/minutes'
    stocks_s1 = load_pool_stocks(s1_wl, s1_dir)
    base_s1, drop_s1, rows_s1 = evaluate_pair('策略1池子', stocks_s1, calendar)

    # 2. 策略 16 池子 (34 只)
    s16_wl = strategy16_watchlist()
    s16_dir = ROOT / 'reports/strategy16_run_20261105/minutes'
    stocks_s16 = load_pool_stocks(s16_wl, s16_dir)
    base_s16, drop_s16, rows_s16 = evaluate_pair('策略16池子', stocks_s16, calendar)

    out_dir = ROOT / 'reports/global_morning_drop_stop_analysis_20261105'
    out_dir.mkdir(parents=True, exist_ok=True)

    df_s1 = pd.DataFrame(rows_s1)
    df_s16 = pd.DataFrame(rows_s16)
    df_all = pd.concat([df_s1, df_s16], ignore_index=True)

    df_s1.to_csv(out_dir / 'strategy1_pool_daily_alpha.csv', index=False, encoding='utf-8-sig')
    df_s16.to_csv(out_dir / 'strategy16_pool_daily_alpha.csv', index=False, encoding='utf-8-sig')
    df_all.to_csv(out_dir / 'all_pools_daily_alpha.csv', index=False, encoding='utf-8-sig')

    pd.DataFrame(base_s1['trades']).to_csv(out_dir / 's1_base_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(drop_s1['trades']).to_csv(out_dir / 's1_drop_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(base_s16['trades']).to_csv(out_dir / 's16_base_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(drop_s16['trades']).to_csv(out_dir / 's16_drop_trades.csv', index=False, encoding='utf-8-sig')

    print('\n================== 策略1池子：加规则 vs 不加规则 逐日超额收益 ==================')
    print(df_s1[['date', 'base_equity', 'base_pnl', 'base_daily_pct', 'drop_equity', 'drop_pnl', 'drop_daily_pct', 'excess_pnl', 'excess_pct']].to_string(index=False))

    print('\n================== 策略16池子：加规则 vs 不加规则 逐日超额收益 ==================')
    print(df_s16[['date', 'base_equity', 'base_pnl', 'base_daily_pct', 'drop_equity', 'drop_pnl', 'drop_daily_pct', 'excess_pnl', 'excess_pct']].to_string(index=False))

    print('\n=== S1 POOL SUMMARY ===')
    print('Baseline:', base_s1['summary'])
    print('With Morning Drop Stop:', drop_s1['summary'])

    print('\n=== S16 POOL SUMMARY ===')
    print('Baseline:', base_s16['summary'])
    print('With Morning Drop Stop:', drop_s16['summary'])


if __name__ == '__main__':
    main()
