"""Monthly Shanghai index return from prior month close."""
from functools import lru_cache
import time
@lru_cache(maxsize=12)
def _prices(bucket):
    import akshare as ak
    return {str(r['date'])[:10]: float(r['close']) for r in ak.stock_zh_index_daily(symbol='sh000001').to_dict('records')}
def monthly_index(year, month):
    prefix = f'{int(year):04d}-{int(month):02d}'
    if not 1 <= int(month) <= 12: raise ValueError('Invalid month')
    prices = dict(_prices(int(time.time() // 300)))
    from database_quotes import read_quotes
    q = read_quotes().get('sh000001', {})
    if not q.get('session'):
        from quote_feed import fetch_sina_batch
        q = fetch_sina_batch(['sh000001']).get('sh000001', {})
    if q.get('session') and q.get('last'): prices[str(q['session'])[:10]] = float(q['last'])
    prior = sorted(d for d in prices if d < prefix+'-01')
    base = prices[prior[-1]]
    return [{'date': d, 'rate': (prices[d]/base-1)*100} for d in sorted(prices) if d.startswith(prefix)]
