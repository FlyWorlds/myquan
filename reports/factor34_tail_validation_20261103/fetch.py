import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
import akshare as ak

ROOT=Path(__file__).resolve().parent
POOL=json.loads((ROOT/'pools.json').read_text())
union={w['code']:w for v in POOL.values() for w in v}
union['000300_index']={'sina':'sh000300'}
def get(url,params):
    for attempt in range(3):
        try:
            r=requests.get(url,params=params,timeout=25);r.raise_for_status();return r
        except requests.RequestException:
            if attempt==2:raise

def fetch(item):
    c,w=item;dest=ROOT/'raw'/f'{c}.json'
    if dest.exists():
        frozen=json.loads(dest.read_text())
        if min(r[0] for r in frozen['daily'])<='2026-09-01':return c,'cached'
        d=ak.stock_zh_a_daily(symbol=w['sina'],start_date='20260801',end_date='20261102',adjust='')
        frozen['daily']=[[str(r.date),float(r.open),float(r.close),float(r.high),float(r.low),float(r.volume)/100] for _,r in d.iterrows()]
        frozen['daily_source']='sina_daily_via_akshare_extended'
        dest.write_text(json.dumps(frozen,ensure_ascii=False,indent=2))
        return c,'extended_daily'
    old=ROOT.parent/'pool_first5m_bear_20261103'/'raw'/f'{c}.json'
    if old.exists():dest.write_bytes(old.read_bytes());return c,'frozen'
    r=get('https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_k=/CN_MarketDataService.getKLineData',
          {'symbol':w['sina'],'scale':5,'ma':'no','datalen':1970})
    b=r.text;bars=json.loads(b[b.index('([')+1:b.rindex('])')+1]);assert bars
    if c=='000300_index':
        daily=json.loads((ROOT.parent/'factor34_pool_tuning_20261103'/'raw'/f'{c}.json').read_text())
        source='frozen_tencent_index'
    else:
        d=ak.stock_zh_a_daily(symbol=w['sina'],start_date='20260801',end_date='20261102',adjust='')
        daily=[[str(r.date),float(r.open),float(r.close),float(r.high),float(r.low),float(r.volume)/100] for _,r in d.iterrows()]
        source='sina_daily_via_akshare_fallback'
    dest.write_text(json.dumps(dict(bars=bars,daily=daily,daily_source=source),ensure_ascii=False,indent=2))
    return c,len(bars)

errors={}
for item in union.items():
    try:print(fetch(item),flush=True)
    except Exception as exc:errors[item[0]]=str(exc)
print('errors',errors)
if errors:raise RuntimeError(errors)
