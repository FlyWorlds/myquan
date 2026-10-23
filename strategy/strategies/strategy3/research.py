"""可复现日线组合回测；现金、整手、T+1、涨跌停、次日开盘、逐日净值。"""
from __future__ import annotations
from dataclasses import replace
from itertools import product
import json
import numpy as np
import pandas as pd
from strategy.costs import ENGINE_COMMISSION_RATE as FEE, SLIPPAGE_VALUE as SLIP, STAMP_TAX_RATE as TAX
from strategy.abalone_risk import entry_plan
from .reversal import POOL, OUT, Policy, load_daily, build_features, eligible, RULES


def _closed_cycle(pos,symbol,day,age,reason,stop_level):
    return dict(symbol=symbol,entry_date=pos['entry_date'],exit_date=str(day.date()),
                pnl=pos['realized'],invested=pos['invested'],return_pct=pos['realized']/pos['invested']*100,
                hold_days=age,exit_reason=reason,event_id=pos['event_id'],anchor=pos['anchor'],
                prior_high=pos['prior_high'],event_low=pos['event_low'],entry_price=pos['first_px'],
                stop_px=stop_level,target_px=pos['target_px'],new_low_after_entry=pos['new_low'])


def simulate(frames, policy=Policy(), start='2020-01-01', end='2026-10-21', initial_cash=1_000_000.):
    frames = {s: f[(f.date >= pd.Timestamp(start)) & (f.date <= pd.Timestamp(end))]
              for s, f in frames.items()}
    records = {s: {r.date: r for r in f.itertuples()} for s, f in frames.items()}
    days = sorted(set(t for f in frames.values() for t in f.date))
    cash, positions, previous, consumed = initial_cash, {}, {}, set()
    events, cycles, equity = [], [], []
    last_prices = {}
    for day in days:
        today = {s: rs[day] for s, rs in records.items() if day in rs}
        # 前收盘信号决定今日开盘的操作；不可成交时退出单持续挂起。
        for s in list(positions):
            pos = positions[s]
            r, prev = today.get(s), previous.get(s)
            if r is None or prev is None:
                continue
            age = pos['age']
            avg = pos['cost'] / pos['shares']
            raw_sell_px = r.open
            stop_level = avg * (1-policy.stop) if policy.stop_mode == 'cost' and policy.risk_budget == 0 else pos['stop_px']
            if pos['pending']:
                reason = pos['pending']
            elif prev.close <= stop_level:
                reason = '止损'
            elif policy.stop_trigger == 'touch_next_open' and prev.low <= stop_level:
                reason = '日低破位次开止损'
            elif policy.stop_trigger == 'intraday' and age == 1 and prev.low <= stop_level:
                reason = 'T+1次开止损'
            elif age >= policy.hold:
                reason = '到期'
            elif policy.take > 0 and prev.close >= (pos['target_px'] if policy.take_mode in ('anchor','swing_top','structure') else avg * (1+policy.take)) and not pos['reduced']:
                reason = '分批止盈'
            elif pos['reduced'] and pos.get('second_target_px') and prev.close >= pos['second_target_px']:
                reason = '前高目标清仓'
            elif pos['reduced'] and prev.close <= pos['peak'] * .97:
                reason = '止盈后回落3%'
            else:
                reason = ''
            # 持仓过夜后的预置止损：跳空按开盘，盘中触线按止损价；不使用当日高点。
            if not reason and policy.stop_trigger == 'intraday' and r.low <= stop_level:
                reason = '结构触价止损' if policy.stop_mode != 'cost' else '成本触价止损'
                raw_sell_px = min(r.open, stop_level)
            limit = .1
            locked_down = r.open <= prev.close * (1-limit+.002)
            tradable = r.open > 0 and not locked_down
            if reason and tradable:
                qty = pos['shares'] if reason != '分批止盈' else int(pos['shares']*policy.reduce//100)*100
                if qty < 100:
                    qty = pos['shares']
                if raw_sell_px < pos.get('event_low',float('-inf')):
                    pos['new_low'] = True
                px = raw_sell_px * (1-SLIP)
                proceeds = qty*px*(1-FEE-TAX)
                cost = pos['cost']*qty/pos['shares']
                cash += proceeds
                pos['realized'] += proceeds-cost
                pos['cost'] -= cost
                pos['shares'] -= qty
                pos['pending'] = ''
                events.append(dict(date=str(day.date()), symbol=s, side='sell', reason=reason,
                                   shares=qty, price=px, cash=cash, pnl=proceeds-cost,
                                   event_id=pos['event_id'],stop_px=stop_level,target_px=pos['target_px']))
                if not pos['shares']:
                    cycles.append(_closed_cycle(pos,s,day,age,reason,stop_level))
                    del positions[s]
                else:
                    pos['reduced'] = True
                    # 开盘减半后，余仓的过夜止损仍在当日有效，不能漏掉稍后触价。
                    if policy.stop_trigger == 'intraday' and r.low <= stop_level:
                        qty2 = pos['shares']; px2 = min(r.open,stop_level)*(1-SLIP)
                        proceeds2 = qty2*px2*(1-FEE-TAX)
                        pnl2 = proceeds2-pos['cost']; cash += proceeds2; pos['realized'] += pnl2
                        if min(r.open,stop_level)<pos.get('event_low',float('-inf')):pos['new_low']=True
                        reason2='减仓后同日触价止损'
                        events.append(dict(date=str(day.date()),symbol=s,side='sell',reason=reason2,
                                           shares=qty2,price=px2,cash=cash,pnl=pnl2,event_id=pos['event_id'],
                                           stop_px=stop_level,target_px=pos['target_px']))
                        cycles.append(_closed_cycle(pos,s,day,age,reason2,stop_level))
                        del positions[s]
                continue
            if reason:
                pos['pending'] = reason
                continue
            # 仅补一次，需先跌够3%再形成新的止跌，补仓后仍可在下一交易日卖出。
            if (policy.stop_mode == 'cost' and policy.risk_budget == 0 and not pos['added'] and not pos['reduced'] and policy.initial < 1
                    and prev.close <= pos['first_px']*(1-policy.add_drop) and prev.stabilize):
                budget = min(cash, max(0., pos['budget']-pos['invested']))
                locked_up = r.open >= prev.close*1.098
                if budget > 0 and tradable and not locked_up:
                    px = r.open*(1+SLIP)
                    qty = int(budget/(px*(1+FEE))//100)*100
                    if qty:
                        cost = qty*px*(1+FEE)
                        cash -= cost
                        pos['shares'] += qty; pos['cost'] += cost; pos['invested'] += cost
                        pos['added'] = True
                        events.append(dict(date=str(day.date()), symbol=s, side='buy', reason='补跌止跌',
                                           shares=qty, price=px, cash=cash, pnl=0.))
        nav_open = cash + sum(p['shares']*today[s].open if s in today else p['shares']*last_prices[s]
                              for s, p in positions.items())
        candidates = []
        for s, r in today.items():
            prev = previous.get(s)
            if prev is None or s in positions or not eligible(prev, policy):
                continue
            # 不用停牌前的陈旧信号；一个前底事件只进入一次。
            key = (s, prev.anchor_date)
            if key in consumed or (day-prev.date).days > 10:
                continue
            locked = r.open >= prev.close*1.098 or r.open <= prev.close*.902
            if r.open <= 0 or locked:
                continue
            candidates.append((s, r, prev, key))
        candidates.sort(key=lambda x: (-x[2].depth, x[0]))
        for s, r, prev, key in candidates:
            if len(positions) >= round(1/policy.slot):
                break
            budget = nav_open*policy.slot
            px = r.open*(1+SLIP)
            plan = entry_plan(prev,px,policy.dict())
            if not plan['allowed']:
                continue
            stop_px, target_px, risk = plan['stop_px'], plan['target_px'], plan['risk_pct']
            entry_budget = min(cash, budget*policy.initial)
            if policy.risk_budget > 0:
                entry_budget = min(entry_budget, nav_open*policy.risk_budget/risk)
            qty = int(entry_budget/(px*(1+FEE))//100)*100
            if qty < 100:
                continue
            cost = qty*px*(1+FEE)
            cash -= cost; consumed.add(key)
            positions[s] = dict(shares=qty, cost=cost, invested=cost, realized=0.,
                                entry_date=str(day.date()), first_px=px, budget=budget,
                                added=False, reduced=False, age=0, peak=r.close, pending='',stop_px=stop_px,target_px=target_px,
                                second_target_px=plan['second_target_px'],anchor=plan['anchor'],prior_high=plan['prior_high'],
                                event_low=plan['event_low'],event_id=key[1],new_low=False)
            events.append(dict(date=str(day.date()), symbol=s, side='buy', reason='破位止跌' if policy.mode != 'break' else '直接破位',
                               shares=qty, price=px, cash=cash, pnl=0.,
                               event_id=key[1],anchor=plan['anchor'],prior_high=plan['prior_high'],
                               event_low=plan['event_low'],stop_px=stop_px,target_px=target_px,
                               second_target_px=plan['second_target_px'],risk_pct=risk,reward_risk=plan['reward_risk']))
        for s, r in today.items():
            last_prices[s] = r.close
            if s in positions:
                if r.low < positions[s].get('event_low',float('-inf')):
                    positions[s]['new_low'] = True
                positions[s]['age'] += 1
                positions[s]['peak'] = max(positions[s]['peak'], r.close)
        nav = cash + sum(p['shares']*last_prices[s] for s, p in positions.items())
        equity.append(dict(date=str(day.date()), nav=nav, cash=cash, positions=len(positions)))
        previous.update(today)
    eq = pd.DataFrame(equity, columns=['date', 'nav', 'cash', 'positions'])
    tr = pd.DataFrame(cycles)
    returns = eq.nav.pct_change().fillna(0) if len(eq) else pd.Series([0.])
    summary = dict(total_return_pct=(eq.nav.iloc[-1]/initial_cash-1)*100 if len(eq) else 0.,
                   max_drawdown_pct=float((eq.nav/eq.nav.cummax()-1).min()*100) if len(eq) else 0.,
                   sharpe_ratio=float(returns.mean()/returns.std()*np.sqrt(252)) if returns.std()>0 else 0.,
                   n_trades=len(tr), win_rate=float((tr.pnl>0).mean()) if len(tr) else 0.,
                   mean_hold_days=float(tr.hold_days.mean()) if len(tr) else 0.,
                   open_positions=len(positions), final_nav=float(eq.nav.iloc[-1]) if len(eq) else initial_cash,
                   start=str(days[0].date()) if days else '', end=str(days[-1].date()) if days else '')
    return summary, eq, pd.DataFrame(events), tr


def run_research(start='20200101', end='20261021', initial_cash=1_000_000., **_):
    OUT.mkdir(parents=True, exist_ok=True)
    pool = json.loads(POOL.read_text())
    # 明确复制策略16全部名单，新策略独立产物，不修改策略16。
    (OUT/'pool.json').write_text(json.dumps(pool, ensure_ascii=False, indent=2))
    frames, coverage = {}, []
    for item in pool['picks']:
        code = item['code']; s = ('sh' if code.startswith('6') else 'sz')+code
        d, meta = load_daily(s)
        coverage.append(meta)
        if len(d) >= 70:
            frames[s] = build_features(d[d.date <= pd.Timestamp(end)], s)
            frames[s].to_parquet(OUT/f'{s}_features.parquet', index=False)
    pd.DataFrame(coverage).to_json(OUT/'coverage.json', orient='records', force_ascii=False, indent=2)
    if not frames:
        raise ValueError('没有满足70根日线的股票，检查 coverage.json')
    print(f'features ready: {len(frames)}/{len(pool["picks"])}', flush=True)
    trials = []
    configs = [Policy(depth=depth, hold=hold, stop=stop, take=take, mode=mode, acceleration=accel)
               for depth, hold, stop, take, mode, accel in product(
                   (0., .02, .04, .06), (5, 10, 20), (.06, .1), (0., .06, .1),
                   ('break', 'stabilize'), (False, True))]
    for n, p in enumerate(configs):
        stats, *_ = simulate(frames, p, start=start, end='2023-12-31', initial_cash=initial_cash)
        trials.append(dict(trial=n, **p.dict(), **stats))
    table = pd.DataFrame(trials)
    table['score'] = table.total_return_pct + table.max_drawdown_pct*.7
    table.to_csv(OUT/'train_grid.csv', index=False)
    viable = table[(table.n_trades >= 15) & (table['mode'] == 'stabilize') & table.acceleration].sort_values('score', ascending=False).head(5)
    if viable.empty:
        raise ValueError('训练集不足15笔交易，不能选择参数')
    validations = []
    for row in viable.itertuples():
        base = configs[row.trial]
        for initial in (.33, .5, 1.):
            for reduce in (.5, 1.):
                p = replace(base, initial=initial, reduce=reduce)
                stats, *_ = simulate(frames, p, start='2024-01-01', end='2024-12-31', initial_cash=initial_cash)
                validations.append(dict(policy=p.dict(), **stats))
    valid = [x for x in validations if x['n_trades'] >= 5]
    chosen = max(valid or validations, key=lambda x: x['total_return_pct']+.7*x['max_drawdown_pct'])
    p = Policy(**chosen['policy'])
    (OUT/'validation.json').write_text(json.dumps(validations, ensure_ascii=False, indent=2))
    (OUT/'selected_policy.json').write_text(json.dumps(dict(policy=p.dict(), status='research_only',
        selected_on='train<=2023, validation=2024; test>=2025 untouched', universe_bias=True), indent=2))
    results = []
    for label, a, b, policy in [('训练',start,'2023-12-31',p), ('验证','2024-01-01','2024-12-31',p),
                               ('留出测试','2025-01-01',end,p),
                               ('留出直接破位对照','2025-01-01',end,replace(p,mode='break')),
                               ('留出不补仓对照','2025-01-01',end,replace(p,initial=1.)),
                               ('留出无加速过滤','2025-01-01',end,replace(p,acceleration=False)),
                               ('名单冻结后','2026-10-01',end,p),
                               ('留出分批仓位对照','2025-01-01',end,replace(p,initial=.5,reduce=.5))]:
        stats, eq, ev, tr = simulate(frames, policy, start=a, end=b, initial_cash=initial_cash)
        results.append(dict(label=label, **policy.dict(), **stats))
        if label == '留出分批仓位对照':
            eq.to_csv(OUT/'staged_equity.csv', index=False)
            ev.to_csv(OUT/'staged_orders.csv', index=False)
            tr.to_csv(OUT/'staged_trades.csv', index=False)
        if label == '留出测试':
            eq.to_csv(OUT/'equity.csv',index=False); ev.to_csv(OUT/'orders.csv',index=False)
            tr.to_csv(OUT/'trades.csv',index=False)
    (OUT/'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    report = ['# 策略三·鲍鱼捞饭', '', RULES, '',
              '## 证据边界',
              f'策略16名单截至 {pool.get("as_of")}，全部{len(pool["picks"])}只已纳入池。有效长历史{len(frames)}只。',
              '这是当前股票池的历史条件回看，存在选股/幸存者偏差，不能当作历史可交易选股收益。',
              'CZSC逐根更新，以向上一笔首次可观察时刻起监控后续破位；不回填历史分型/笔。',
              '阶段低点：底分型低点不高于此前60根日线低点；确认向上一笔后120交易日内有效。',
              '新低动量：3日收益<−2%，且低于此前3日收益；破位后的加速曾发生即记住。',
              '止跌：日低点不再下降、收盘高于前收且收阳。破位深度按本轮最低点相对前底计算。',
              '预警：已确认向上一笔且收盘距前底不超过3%；破位后进入准备阶段。',
              '所有操作使用前收盘信号、下一开盘价，双边0.1%滑点及统一费用；100股整手、最多5票。',
              '止损按加权成交成本比较日收盘，下一开盘退出；不是盘中硬止损，跳空损失可能超过阈值。',
              '补仓一次：首仓后再跌3%且重新止跌，补足原始单票额度；减仓后不再补仓。',
              '止盈按加权成本涨幅触发，减仓比例为当时持股；剩余股峰值回落3%退出，或到期退出。',
              'T+1：买入当日不卖；开盘接近涨/跌停的买单保守跳过，开盘跌停卖单顺延，不利用全天高低点判断开盘成交。未平仓按日收盘计价。',
              '费用采用项目统一当前口径，未按历史印花税率分段；复权日线整手股数为近似，未独立记分红送转。',
              '训练<=2023扫描288组；主策略仅从止跌+加速组合筛前5，直接破位只作为对照；2024比较初仓33%/50%/100%及减仓50%/100%；2025起仅评价。',
              '当前名单冻结后独立样本仅数周，尚不支持实盘有效性结论。', '', '## 结果',
              '|区间|收益%|日线最大回撤%|夏普|闭环笔数|胜率%|平均持有日|',
              '|---|---:|---:|---:|---:|---:|---:|']
    for r in results:
        report.append(f'|{r["label"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["sharpe_ratio"]:.2f}|{r["n_trades"]}|{r["win_rate"]*100:.1f}|{r["mean_hold_days"]:.1f}|')
    report += ['', '## 选定研究参数', '```json', json.dumps(p.dict(),ensure_ascii=False,indent=2),'```', '',
               '复现：`.venv/bin/python -m strategy.strategies.strategy3.research`。',
               '明细：pool.json、coverage.json、train_grid.csv、validation.json、selected_policy.json、equity.csv、orders.csv、trades.csv。']
    report += ['', '## 研究解读',
               '主策略保留加速及止跌条件；参数由训练和验证期选择，留出结果不用于重选。',
               '分批仓位对照：单票资金10%+10%，补仓需再跌3%且止跌；盈利阈值处减半，剩余股峰值回落3%或到期退出。',
               '若选中initial=1则不补仓，reduce=1表示止盈清仓；take=0表示仅期限及止损退出。',
               '对照结果用于检验假设，不能仅凭训练/验证最优解释为未来最优；加速过滤的价值须看留出对照。']
    (OUT/'REPORT.md').write_text('\n'.join(report))
    return dict(policy=p.dict(), results=results, output=str(OUT))


if __name__ == '__main__':
    print(json.dumps(run_research(),ensure_ascii=False,indent=2))
