"""Reproduce the event study from frozen Sina/Tencent daily observations."""
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd

ROOT = Path(__file__).resolve().parent
d = pd.read_json(ROOT / 'daily_raw.json').sort_values('date').reset_index(drop=True)
d['date'] = pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
assert d.date.is_unique and d.date.iloc[-1] == '2026-11-02'
other = json.loads((ROOT / 'tencent_raw.json').read_text())['data']['sh600330']['day']
t = pd.DataFrame([x[:6] for x in other], columns=['date','open','close','high','low','volume'])
merged = d.merge(t, on='date', suffixes=('', '_t'), validate='one_to_one')
assert len(merged) == len(d)
for c in ['open','high','low','close']:
    assert (merged[c] - merged[c+'_t'].astype(float)).abs().max() < .00001, c
events = []
for i in range(1, len(d)):
    row, prev = d.iloc[i], d.iloc[i-1]
    if row.date < '2025-01-01':
        continue
    limit = float((Decimal(str(prev.close)) * Decimal('0.9')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    if row.low > limit + .00001:
        continue
    assert abs(row.low-limit) < .00001, 'Check ex-rights/reference price'
    nxt = d.iloc[i+1] if i+1 < len(d) else None
    sealed = bool(abs(row.close-limit) < .00001)
    event = dict(date=row.date, category='收盘封跌停' if sealed else '触板后打开',
                 sealed=sealed, one_price=all(abs(row[c]-limit)<.00001 for c in ['open','high','low','close']),
                 prev_close=prev.close, limit_price=limit, close=row.close,
                 next_date=nxt.date if nxt is not None else None)
    for c in ['open','high','low','close']:
        event['next_'+c] = float(nxt[c]) if nxt is not None else None
        event['next_'+c+'_pct'] = (float(nxt[c])/row.close-1)*100 if nxt is not None else None
    event['next_intraday_pct'] = (nxt.close/nxt.open-1)*100 if nxt is not None else None
    events.append(event)
e = pd.DataFrame(events)
groups = {}
for name, subset in [('全部触及跌停',e), ('收盘封跌停',e[e.sealed]), ('触板后打开',e[~e.sealed]), ('全天一字跌停',e[e.one_price])]:
    valid = subset.dropna(subset=['next_close_pct'])
    groups[name] = dict(count=len(subset), evaluated=len(valid),
        up=int((valid.next_close_pct>0).sum()), down=int((valid.next_close_pct<0).sum()),
        flat=int((valid.next_close_pct==0).sum()),
        open_mean=valid.next_open_pct.mean() if len(valid) else None,
        close_mean=valid.next_close_pct.mean() if len(valid) else None,
        close_median=valid.next_close_pct.median() if len(valid) else None,
        close_min=valid.next_close_pct.min() if len(valid) else None,
        close_max=valid.next_close_pct.max() if len(valid) else None,
        intraday_mean=valid.next_intraday_pct.mean() if len(valid) else None)
result = dict(symbol='sh600330', start='2025-01-01', end='2026-11-02',
              cross_checked_ohlc_rows=len(merged), groups=groups, events=events)
(ROOT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
lines = ['# 天通股份跌停事件次日表现', '',
         '区间：2025-01-01 至 2026-11-02；2026-11-03 尚未收盘，不纳入。',
         '数据：新浪不复权日线（AkShare stock_zh_a_daily），腾讯不复权日线交叉核对，464行OHLC全部一致。',
         '跌停价：前收盘×90%，Decimal四舍五入到0.01元；未使用项目向下取整函数。',
         '封死代理：收盘价等于跌停价，不代表逐笔封单或全天未开板；另列OHLC全等于跌停价的一字板。',
         '收益：下一交易日开/高/低/收相对事件日收盘；开盘至收盘单独列示。非可成交策略收益，未扣费用。',
         '', '|分组|次数|次日涨/跌/平|次日平均开盘涨幅|次日平均收盘涨幅|收盘中位数|平均开盘至收盘|',
         '|---|---:|---|---:|---:|---:|---:|']
def fmt(v): return '—' if v is None else f'{v:+.2f}%'
for name,s in groups.items():
    lines.append(f"|{name}|{s['count']}|{s['up']}/{s['down']}/{s['flat']}|{fmt(s['open_mean'])}|{fmt(s['close_mean'])}|{fmt(s['close_median'])}|{fmt(s['intraday_mean'])}|")
lines += ['', '|事件日|类型|跌停价|当日收盘|下一交易日|次日开盘|次日最高|次日最低|次日收盘|开盘至收盘|', '|---|---|---:|---:|---|---:|---:|---:|---:|---:|']
for r in events:
    vals='|'.join(fmt(r['next_'+c+'_pct']) for c in ['open','high','low','close'])
    lines.append(f"|{r['date']}|{r['category']}|{r['limit_price']:.2f}|{r['close']:.2f}|{r['next_date']}|{vals}|{fmt(r['next_intraday_pct'])}|")
lines += ['', '复现：在项目根目录运行 `.venv/bin/python reports/tiantong_limit_down_2025_2026/analyze.py`。',
          '输入已冻结为同目录JSON；results.json保存全部数值。样本存在连续事件，不视为相互独立。']
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
