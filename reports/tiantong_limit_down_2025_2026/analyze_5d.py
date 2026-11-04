"""Five-session extension of the frozen, cross-checked limit-down event study."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
source = json.loads((ROOT/'results.json').read_text())
d = pd.read_json(ROOT/'daily_raw.json').sort_values('date').reset_index(drop=True)
d['date'] = pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
events = []
for original in source['events']:
    i = d.index[d.date == original['date']].item()
    future = d.iloc[i+1:i+6]
    assert len(future) == 5, 'Incomplete forward window'
    base = original['close']
    row = dict(date=original['date'], category=original['category'], sealed=original['sealed'], base_close=base)
    for n, (_, day) in enumerate(future.iterrows(), 1):
        row[f'd{n}_date'] = day.date
        row[f'd{n}_close'] = float(day.close)
        row[f'd{n}_pct'] = (float(day.close)/base-1)*100
    row['window_high_pct'] = (float(future.high.max())/base-1)*100
    row['window_low_pct'] = (float(future.low.min())/base-1)*100
    assert abs(row['d1_pct']-original['next_close_pct']) < 1e-9
    events.append(row)
e = pd.DataFrame(events)
groups = {}
for name, subset in [('全部触及跌停',e),('收盘封跌停',e[e.sealed]),('触板后打开',e[~e.sealed])]:
    groups[name] = dict(count=len(subset), means=[float(subset[f'd{n}_pct'].mean()) for n in range(1,6)],
        d5_up=int((subset.d5_pct>0).sum()), d5_down=int((subset.d5_pct<0).sum()),
        d5_median=float(subset.d5_pct.median()),d5_min=float(subset.d5_pct.min()),d5_max=float(subset.d5_pct.max()),
        window_low_min=float(subset.window_low_pct.min()))
result = dict(source='results.json + daily_raw.json',groups=groups,events=events)
(ROOT/'results_5d.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
fmt=lambda x:f'{x:+.2f}%'
lines=['# 天通股份跌停事件后5个交易日表现','',
       '沿用2025-01-01至2026-11-02的14次事件，全部具备5个后续交易日。D1至D5均为相对事件日收盘的累计价格涨跌幅，不是单日涨跌幅。',
       '收盘封跌停仅以收盘价等于跌停价判断，不代表封单或全天未开板。未扣费用；不是可成交策略回测。',
       '事件窗口可能重叠（例如2026-07-17与2026-07-20），样本不独立，不叠加为组合收益。', '',
       '|分组|样本|D1均值|D2均值|D3均值|D4均值|D5均值|D5上涨|D5中位数|D5最差|D5最好|',
       '|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|']
for name,s in groups.items():
    values='|'.join(map(fmt,s['means']))
    lines.append(f"|{name}|{s['count']}|{values}|{s['d5_up']}/{s['count']}|{fmt(s['d5_median'])}|{fmt(s['d5_min'])}|{fmt(s['d5_max'])}|")
lines += ['', '|事件日|状态|D1|D2|D3|D4|D5|D5日期|5日内最高相对收益|5日内最低相对收益|', '|---|---|---:|---:|---:|---:|---:|---|---:|---:|']
for r in events:
    values='|'.join(fmt(r[f'd{n}_pct']) for n in range(1,6))
    lines.append(f"|{r['date']}|{r['category']}|{values}|{r['d5_date']}|{fmt(r['window_high_pct'])}|{fmt(r['window_low_pct'])}|")
lines += ['', '窗口最高/最低为未来5个交易日最高/最低价相对事件收盘的涨跌幅，非可实现收益，也不是峰谷最大回撤。',
          '数据来源、跌停价取整及双源核验口径沿用REPORT.md。原始价格与逐日日期见results_5d.json。']
(ROOT/'REPORT_5D.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
