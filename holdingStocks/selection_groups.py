"""Database-only selections and explicitly requested minute replay jobs."""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

_LOCK = threading.Lock()
_JOBS = {}


def backend(path, body=None):
    base = os.environ.get('PAPER_BACKEND_URL', 'http://127.0.0.1:8080').rstrip('/')
    req = Request(base + '/api/paper/' + path,
                  data=None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode(),
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def start_replay(group_id):
    selection = json.loads(backend('selection-groups/' + group_id)['payload'])
    with _LOCK:
        if any(j['status'] == 'running' for j in _JOBS.values()):
            raise ValueError('已有回测正在运行，请等待完成')
        job_id = str(uuid.uuid4())
        _JOBS.clear()
        _JOBS[job_id] = {'status': 'running', 'completed': 0}
    threading.Thread(target=_replay, args=(job_id, selection), daemon=True).start()
    return {'id': job_id}


def replay_status(job_id):
    with _LOCK:
        return dict(_JOBS.get(job_id, {'status': 'missing'}))


def _replay(job_id, selection):
    try:
        # Heavy market-data imports and fetching exist only inside the click-started worker.
        import pandas as pd
        from backtest.strategy1_pool_1m import run as r
        from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT
        end = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        start = end - timedelta(days=6)
        from holdingStocks.trading_calendar import is_trading_day
        expected = {start + timedelta(days=i) for i in range(7) if is_trading_day(start + timedelta(days=i))}
        stocks, coverage = [], []
        for item in selection['picks']['items']:
            code = item['code']
            symbol = r._sina(code)
            minutes = r._minutes(symbol, refresh=True, days=7, source='auto')
            if minutes.empty or 'ts' not in minutes:
                raise ValueError(f'{code} 没有可用的1分钟行情')
            dates = pd.to_datetime(minutes['ts']).dt.date
            minutes = minutes[(dates >= start) & (dates <= end)].copy()
            daily = r._daily(symbol)
            if minutes.empty or daily.empty:
                raise ValueError(f'{code} 近7天分钟行情或前置日线缺失，未生成不完整池子回测')
            coverage.append({'code': code, 'rows': len(minutes),
                             'start': str(minutes['ts'].min()), 'end': str(minutes['ts'].max()),
                             'days': len(pd.to_datetime(minutes['ts']).dt.date.unique()),
                             'missingDays': sorted(str(d) for d in expected - set(pd.to_datetime(minutes['ts']).dt.date))})
            stocks.append(dict(code=code, name=item.get('name', code), daily=daily, minutes=minutes,
                               entry_pct=float(DEFAULT_ENTRY_PCT), pullback_pct=float(DEFAULT_PULLBACK_PCT)))
            with _LOCK:
                _JOBS[job_id]['completed'] = len(stocks)
        result = r.simulate_portfolio_3slots(stocks, days=7, max_slots=4, initial_cash=300000,
                                           slot_weight=0.25, max_buys_per_day=4, exit_mode='half_gain')
        # Fail on unserializable/nonfinite output before publishing a completed job.
        result = json.loads(json.dumps(result, allow_nan=False, default=str))
        with _LOCK:
            _JOBS[job_id].update(status='done', result=result, coverage=coverage,
                                start=str(start), end=str(end),
                                note='当前保存池子回放；不代表历史时点选股。近7个自然日，四槽30万，因子26分钟回放；数据覆盖见明细。')
    except Exception as exc:
        with _LOCK:
            _JOBS[job_id].update(status='failed', error=str(exc))
