"""Weekly Unit Backtest: Evaluate 'Morning Drop 1% Stop' across multiple weeks for S1 and S16 pools.

Weeks:
- Week 1: 2026-10-26 to 2026-10-30 (5 trading days, Mon-Fri)
- Week 2: 2026-11-02 to 2026-11-05 (4 trading days, Mon-Thu)
- Combined: 2026-10-26 to 2026-11-05 (continuous rolling)

Evaluates:
- Baseline Strategy 1 (09:30 open_protect)
- Modified Strategy 1 (10:00 morning drop 1% stop)
Outputs weekly summary, daily excess return, and trade attribution.
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from backtest.compare_strategy1_pools import *
from backtest.compare_strategy1_morning_stop import normalize, complete_days
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

MINUTES_DIR = ROOT / 'reports/multi_week_data/minutes'


def load_pool_stocks(watchlist):
    stocks = []
    for w in watchlist:
        sina = w['sina']
        m_path = MINUTES_DIR / f'{sina}.parquet'
        d_path = MINUTES_DIR / f'{sina}_daily.parquet'
        if not m_path.exists() or not d_path.exists():
            raise FileNotFoundError(f'Missing files for {sina}')
        m = normalize(pd.read_parquet(m_path), 'ts')
        d = normalize(pd.read_parquet(d_path), 'date')
        stocks.append(dict(w=w, minutes=m, daily=d))
    return stocks


def simulate_period(stocks, calendar, mode='baseline', initial=300000.0):
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
                raise ValueError(f'{w["code"]}: fewer than 20 prior daily bars on {day}')
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

            # 检查持仓卖出
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
                            p['drop_stop_active'] = True
                            p['drop_stop_px'] = floor_to_tick(md['opening'] * 0.99, tick=.01)
                            p['drop_stop_session'] = day

                # 10点前早盘保护逻辑
                if p.get('drop_stop_active') and p.get('drop_stop_session') == day and clock < '10:00:00':
                    if float(b.close) <= p['drop_stop_px'] + 1e-9:
                        sell(c, float(b.close), p['qty'], stamp, 'morning_drop_1pct_stop')
                        continue

                    # 阶梯止盈允许触发，下行常规止损屏蔽
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


def main():
    s1_wl = strategy1_watchlist()
    s16_wl = strategy16_watchlist()

    stocks_s1 = load_pool_stocks(s1_wl)
    stocks_s16 = load_pool_stocks(s16_wl)

    # 自然周定义：
    # Week 1: 2026-10-26 至 2026-10-30 (前一周)
    # Week 2: 2026-11-02 至 2026-11-05 (本周)
    # 连续跨周: 2026-10-26 至 2026-11-05
    w1_days = ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30']
    w2_days = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05']
    all_days = w1_days + w2_days

    # 1. 运行连续完整跨周模拟（最真实反映持仓继承）
    print('Running continuous rolling 2-week simulation...')
    r_s1_base = simulate_period(stocks_s1, all_days, mode='baseline')
    r_s1_drop = simulate_period(stocks_s1, all_days, mode='morning_drop_1pct')

    r_s16_base = simulate_period(stocks_s16, all_days, mode='baseline')
    r_s16_drop = simulate_period(stocks_s16, all_days, mode='morning_drop_1pct')

    # 统计两周拆解
    def decompose_weeks(r_b, r_d, pool_name):
        eq_b = {e['date']: e['equity'] for e in r_b['equity']}
        eq_d = {e['date']: e['equity'] for e in r_d['equity']}

        # 初始资金
        init = 300000.0

        # Week 1 (10-26 ~ 10-30)
        w1_end_b = eq_b['2026-10-30']
        w1_end_d = eq_d['2026-10-30']
        w1_ret_b = (w1_end_b / init - 1) * 100
        w1_ret_d = (w1_end_d / init - 1) * 100
        w1_alpha_pnl = (w1_end_d - init) - (w1_end_b - init)
        w1_alpha_pct = w1_ret_d - w1_ret_b

        # Week 2 (11-02 ~ 11-05)
        w2_end_b = eq_b['2026-11-05']
        w2_end_d = eq_d['2026-11-05']
        w2_ret_b = (w2_end_b / w1_end_b - 1) * 100
        w2_ret_d = (w2_end_d / w1_end_d - 1) * 100
        w2_pnl_b = w2_end_b - w1_end_b
        w2_pnl_d = w2_end_d - w1_end_d
        w2_alpha_pnl = w2_pnl_d - w2_pnl_b
        w2_alpha_pct = w2_ret_d - w2_ret_b

        # 累计 2 周
        tot_ret_b = (w2_end_b / init - 1) * 100
        tot_ret_d = (w2_end_d / init - 1) * 100
        tot_alpha_pnl = (w2_end_d - init) - (w2_end_b - init)
        tot_alpha_pct = tot_ret_d - tot_ret_b

        return dict(
            pool=pool_name,
            # Week 1
            w1_pnl_base=round(w1_end_b - init, 2),
            w1_ret_base=round(w1_ret_b, 2),
            w1_pnl_drop=round(w1_end_d - init, 2),
            w1_ret_drop=round(w1_ret_d, 2),
            w1_alpha_pnl=round(w1_alpha_pnl, 2),
            w1_alpha_pct=round(w1_alpha_pct, 2),
            # Week 2
            w2_pnl_base=round(w2_pnl_b, 2),
            w2_ret_base=round(w2_ret_b, 2),
            w2_pnl_drop=round(w2_pnl_d, 2),
            w2_ret_drop=round(w2_ret_d, 2),
            w2_alpha_pnl=round(w2_alpha_pnl, 2),
            w2_alpha_pct=round(w2_alpha_pct, 2),
            # Total 2 Weeks
            tot_pnl_base=round(w2_end_b - init, 2),
            tot_ret_base=round(tot_ret_b, 2),
            tot_pnl_drop=round(w2_end_d - init, 2),
            tot_ret_drop=round(tot_ret_d, 2),
            tot_alpha_pnl=round(tot_alpha_pnl, 2),
            tot_alpha_pct=round(tot_alpha_pct, 2),
        )

    w_s1 = decompose_weeks(r_s1_base, r_s1_drop, '策略1池子')
    w_s16 = decompose_weeks(r_s16_base, r_s16_drop, '策略16池子')

    # 逐日流水拆解
    def get_daily_alpha(r_b, r_d, pool_name):
        rows = []
        prev_b = 300000.0
        prev_d = 300000.0
        for e_b in r_b['equity']:
            day = e_b['date']
            e_d = next(x for x in r_d['equity'] if x['date'] == day)
            pnl_b = e_b['equity'] - prev_b
            pnl_d = e_d['equity'] - prev_d
            pct_b = (e_b['equity'] / prev_b - 1) * 100
            pct_d = (e_d['equity'] / prev_d - 1) * 100
            rows.append(dict(
                pool=pool_name,
                week='前一周(Week 1)' if day <= '2026-10-30' else '本周(Week 2)',
                date=day,
                base_equity=round(e_b['equity'], 2),
                base_pnl=round(pnl_b, 2),
                base_daily_pct=round(pct_b, 2),
                drop_equity=round(e_d['equity'], 2),
                drop_pnl=round(pnl_d, 2),
                drop_daily_pct=round(pct_d, 2),
                daily_alpha_pnl=round(pnl_d - pnl_b, 2),
                daily_alpha_pct=round(pct_d - pct_b, 2),
            ))
            prev_b = e_b['equity']
            prev_d = e_d['equity']
        return rows

    daily_s1 = get_daily_alpha(r_s1_base, r_s1_drop, '策略1池子')
    daily_s16 = get_daily_alpha(r_s16_base, r_s16_drop, '策略16池子')

    out_dir = ROOT / 'reports/weekly_alpha_backtest_20261105'
    out_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([w_s1, w_s16]).to_csv(out_dir / 'weekly_summary.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(daily_s1).to_csv(out_dir / 's1_daily_alpha.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(daily_s16).to_csv(out_dir / 's16_daily_alpha.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(r_s1_base['trades']).to_csv(out_dir / 's1_base_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(r_s1_drop['trades']).to_csv(out_dir / 's1_drop_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(r_s16_base['trades']).to_csv(out_dir / 's16_base_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(r_s16_drop['trades']).to_csv(out_dir / 's16_drop_trades.csv', index=False, encoding='utf-8-sig')

    print('\n================== 周度汇总对比表 (WEEKLY SUMMARY) ==================')
    print(pd.DataFrame([w_s1, w_s16]).to_string(index=False))

    print('\n================== 策略1池子逐日超额收益 ==================')
    print(pd.DataFrame(daily_s1)[['week', 'date', 'base_equity', 'drop_equity', 'base_daily_pct', 'drop_daily_pct', 'daily_alpha_pnl', 'daily_alpha_pct']].to_string(index=False))

    print('\n================== 策略16池子逐日超额收益 ==================')
    print(pd.DataFrame(daily_s16)[['week', 'date', 'base_equity', 'drop_equity', 'base_daily_pct', 'drop_daily_pct', 'daily_alpha_pnl', 'daily_alpha_pct']].to_string(index=False))


if __name__ == '__main__':
    main()
