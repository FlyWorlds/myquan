"""Compare Strategy 1: Original open_protect vs Low-open then drop 1% stop."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from backtest.compare_strategy1_pools import *
from backtest.compare_strategy1_morning_stop import collect_current, OUT, DAYS
from strategy.open_break import floor_to_tick, limit_down_state, entry_trigger_price, cannot_buy_limit_up
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.binding_filters import open_break_entry_filter
from strategy.pullback_wave_stop import realized_vol_daily
from holdingStocks.watch_config import MAX_PORTFOLIO_SLOTS, SLOT_WEIGHT, DEFAULT_STOP_REBUY_BOUNCE_PCT
from holdingStocks.quote_exit import evaluate_quote_exit, overnight_note_updates
from holdingStocks.strategy1_entry import phase_at, quota_reason
from holdingStocks.daily_buy_quota import quota_reason as daily_fill_quota_reason
from holdingStocks.condition_buy import auction_entry_blocked
from holdingStocks.attack_wave import AttackWaves
from backtest.strategy1_pool_1m import run as fees
from backtest.strategy16_core_leader.run_month_review import reconcile


def simulate_custom(stocks, calendar, *, replace_open_protect=False):
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
            sold[code] = dict(rebuy=pnl <= .01 or reason in {'vol_giveback', 'half_gain', 'peak_pullback_clear', 'ladder_full_15'},
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

            # 持仓卖出检查
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
                    if protect.triggered and not locked:
                        if replace_open_protect:
                            # 核心替换：不立即在09:30开盘卖出！设开盘下杀1%止损线
                            p['drop_stop_px'] = floor_to_tick(md['opening'] * 0.99, tick=.01)
                            p['drop_stop_session'] = day
                        else:
                            sell(c, md['opening'], p['qty'], day + ' 09:30:00', 'open_protect')
                            continue

                # 检查低开后下杀1%止损（10点前）
                if p.get('drop_stop_px') and p.get('drop_stop_session') == day and clock < '10:00:00':
                    if float(b.close) <= p['drop_stop_px'] + 1e-9:
                        sell(c, float(b.close), p['qty'], stamp, 'low_open_drop_1pct_stop')
                        continue

                # 10点后该早盘保护条件失效
                if clock >= '10:00:00':
                    p.pop('drop_stop_px', None)
                    p.pop('drop_stop_session', None)

                # 原有动态止盈止损
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
    pool = json.loads((OUT / 'pool_snapshot.json').read_text())
    stocks = []
    coverage = []
    for w in pool:
        s, c = collect_current(w)
        stocks.append(s)
        coverage.append(c)
    common = sorted(set.intersection(*(set(c['complete']) for c in coverage)))
    warm = [d for d in common if '2026-10-27' <= d < DAYS[0]]
    calendar = warm + DAYS

    print(f'Running backtest on calendar: {calendar}')
    r_base = simulate_custom(stocks, calendar, replace_open_protect=False)
    r_drop = simulate_custom(stocks, calendar, replace_open_protect=True)

    out_dir = ROOT / 'reports/strategy1_low_open_drop_stop_20261105'
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / 'baseline.json').write_text(json.dumps(r_base, ensure_ascii=False, indent=2))
    (out_dir / 'with_drop_stop.json').write_text(json.dumps(r_drop, ensure_ascii=False, indent=2))
    pd.DataFrame(r_base['trades']).to_csv(out_dir / 'baseline_trades.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(r_drop['trades']).to_csv(out_dir / 'with_drop_stop_trades.csv', index=False, encoding='utf-8-sig')

    base_initial = {
        'baseline': next((e['equity'] for e in reversed(r_base['equity']) if e['date'] < DAYS[0]), 300000.0),
        'drop_stop': next((e['equity'] for e in reversed(r_drop['equity']) if e['date'] < DAYS[0]), 300000.0)
    }

    prev_base = base_initial['baseline']
    prev_drop = base_initial['drop_stop']
    rows = []
    for day in DAYS:
        eb = next(e['equity'] for e in r_base['equity'] if e['date'] == day)
        ed = next(e['equity'] for e in r_drop['equity'] if e['date'] == day)

        pnl_b = eb - prev_base
        pnl_d = ed - prev_drop

        pct_b = (eb / prev_base - 1) * 100
        pct_d = (ed / prev_drop - 1) * 100

        cum_b = (eb / base_initial['baseline'] - 1) * 100
        cum_d = (ed / base_initial['drop_stop'] - 1) * 100

        diff_pnl = pnl_d - pnl_b
        diff_equity = ed - eb

        rows.append(dict(
            date=day,
            baseline_equity=round(eb, 2),
            baseline_pnl=round(pnl_b, 2),
            baseline_daily_pct=round(pct_b, 2),
            baseline_cum_pct=round(cum_b, 2),
            drop_stop_equity=round(ed, 2),
            drop_stop_pnl=round(pnl_d, 2),
            drop_stop_daily_pct=round(pct_d, 2),
            drop_stop_cum_pct=round(cum_d, 2),
            pnl_difference=round(diff_pnl, 2),
            equity_difference=round(diff_equity, 2),
        ))
        prev_base = eb
        prev_drop = ed

    df_comp = pd.DataFrame(rows)
    df_comp.to_csv(out_dir / 'daily_comparison.csv', index=False, encoding='utf-8-sig')

    print('\n=== DAILY COMPARISON ===')
    print(df_comp.to_string(index=False))

    print('\n=== SUMMARY BASELINE ===')
    print(r_base['summary'])
    print('\n=== SUMMARY DROP STOP ===')
    print(r_drop['summary'])


if __name__ == '__main__':
    main()
