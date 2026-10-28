"""Read-only market radar, isolated from trading and its quote subscriptions."""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

REFERENCE = 'https://quotapass.com/'
CACHE = Path(__file__).resolve().parent / 'logs' / 'market_radar_cache.json'
POOL_TYPES = {'sealed': 'getTopicZTPool', 'broken': 'getTopicZBPool', 'down': 'getTopicDTPool'}


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai'))


def fetch_text(url):
    # Use system TLS trust, never disable certificate checks. No user-provided URL.
    result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '3', '--max-time', '7',
        '--user-agent', 'Mozilla/5.0', url], capture_output=True, timeout=9)
    if result.returncode or len(result.stdout) > 6_000_000:
        raise RuntimeError('上游接口连接失败')
    return result.stdout.decode('utf-8')


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def clock(value):
    if value in (None, '', 0, '0'):
        return None
    raw = str(value or '').zfill(6)
    if not raw.isdigit() or len(raw) != 6 or int(raw[:2]) > 23 or int(raw[2:4]) > 59 or int(raw[4:]) > 59:
        return None
    return ':'.join([raw[:2], raw[2:4], raw[4:]])


def normalize_pool(rows):
    output = []
    seen = set()
    for p in rows:
        code = str(p.get('c') or '')
        if not re.fullmatch(r'\d{6}', code) or code in seen:
            continue
        seen.add(code)
        def scale(key, base):
            val = number(p.get(key))
            return round(val/base, 4) if val is not None else None
        output.append(dict(code=code, name=p.get('n') or code, price=scale('p', 1000),
            pct=number(p.get('zdp')), amount_yi=scale('amount', 1e8),
            float_cap_yi=scale('ltsz', 1e8), turnover=number(p.get('hs')),
            limit_days=number(p.get('lbc')), first_seal=clock(p.get('fbt')),
            last_seal=clock(p.get('lbt')), seal_fund_yi=scale('fund', 1e8),
            break_times=number(p.get('zbc')), industry=p.get('hybk') or '',
            zt_stat=f"{p['zttj'].get('days', '')}天{p['zttj'].get('ct', '')}板" if isinstance(p.get('zttj'), dict) else ''))
    return output


def derive(pools, reasons):
    reason_map = {str(r.get('code')): r for r in reasons}
    industries, topics = {}, {}
    stocks = []
    seen = set()
    for source in pools.get('sealed') or []:
        if not re.fullmatch(r'\d{6}', str(source.get('code') or '')) or source['code'] in seen:
            continue
        seen.add(source['code'])
        s = {k: copy.deepcopy(source.get(k)) for k in ('code', 'name', 'price', 'pct', 'amount_yi',
            'float_cap_yi', 'turnover', 'limit_days', 'first_seal', 'last_seal', 'seal_fund_yi',
            'break_times', 'industry', 'zt_stat', 'quote_at')}
        r = reason_map.get(s['code'], {})
        s['reason'] = str(r.get('reason') or r.get('reason_type') or '')
        s['reason_detail'] = str(r.get('reason_detail') or '')
        s['limit_type'] = r.get('limit_type') or r.get('limit_up_type') or ''
        tags = list(dict.fromkeys(t.strip() for t in re.split(r'[+＋、]', s['reason']) if t.strip()))
        s['themes'] = tags
        cap, seal = number(s.get('float_cap_yi')), number(s.get('seal_fund_yi'))
        strength = round(seal/cap*100, 3) if cap and cap > 0 and seal is not None else None
        s['seal_strength'] = strength
        score, why = 0, []
        if strength is not None:
            points = min(40, round(strength*20))
            score += points
            why.append(f'封单/流通市值 {strength:.2f}%')
        first = s.get('first_seal') or ''
        if first and first <= '10:00:00':
            score += 20
            why.append('10点前封板')
        if number(s.get('break_times')) == 0:
            score += 20
            why.append('零炸板')
        if (number(s.get('limit_days')) or 0) >= 2:
            score += 20
            why.append('连板跟踪')
        has_scoring_data = strength is not None or bool(first) or number(s.get('break_times')) is not None
        s.update(score=score if has_scoring_data else None,
            grade=('A' if score >= 80 else 'B' if score >= 60 else '观察') if has_scoring_data else None,
            score_reasons=why if has_scoring_data else [])
        stocks.append(s)
        industry = s.get('industry') or '未分类'
        industries.setdefault(industry, {})[s['code']] = s
        for tag in tags:
            topics.setdefault(tag, {})[s['code']] = s
    def aggregate(groups):
        result = []
        for name, members in groups.items():
            items = sorted(members.values(), key=lambda x: (-(number(x.get('limit_days')) or 0), -(x['score'] or 0)))
            result.append(dict(name=name, count=len(items), max_height=max((number(x.get('limit_days')) or 1 for x in items), default=0),
                seal_fund_yi=round(sum(number(x.get('seal_fund_yi')) or 0 for x in items), 3) if all(number(x.get('seal_fund_yi')) is not None for x in items) else None, stocks=items))
        return sorted(result, key=lambda x: (-x['count'], -x['max_height'], x['name']))
    stocks.sort(key=lambda x: (-(x['score'] or 0), x.get('first_seal') or '99'))
    sealed = len(stocks)
    broken = len(pools['broken']) if pools.get('broken') is not None else None
    return dict(stocks=stocks, broken=pools.get('broken') or [], themes=aggregate(topics), industries=aggregate(industries),
        summary=dict(sealed=sealed, broken=broken, down=len(pools['down']) if pools.get('down') is not None else None,
            break_rate=round(broken/(sealed+broken)*100, 1) if broken is not None and sealed+broken else None,
            max_height=max((number(x.get('limit_days')) or 1 for x in stocks), default=0),
            grade_a=sum(s['grade'] == 'A' for s in stocks) if all(s['score'] is not None for s in stocks) else None),
        reason_coverage=sum(bool(s['themes']) for s in stocks))


CLS_POOL_TYPES = {'sealed': 'up_pool', 'broken': 'up_open_pool', 'down': 'down_pool'}


def collect_cls():
    """Current official pools only; row time is not assumed to be first-seal time."""
    day = now().date().isoformat()
    def read(item):
        key, kind = item
        url = 'https://x-quote.cls.cn/quote/index/up_down_analysis?' + urlencode(dict(
            app='CailianpressWeb', os='web', sv='7.7.5', type=kind, way='change', rever=1,
            _=int(time.time())))
        body = json.loads(fetch_text(url))
        rows = body.get('data')
        if body.get('code') != 200 or not isinstance(rows, list):
            raise ValueError('财联社行情响应无效')
        if not rows:
            # No dated rows: cannot prove this empty list belongs to today's session.
            raise ValueError('财联社空池日期无法核验')
        if any(str(r.get('time', ''))[:10] != day for r in rows):
            raise ValueError('拒绝非当日财联社行情')
        codes = [str(r.get('secu_code', '')) for r in rows]
        if any(not re.fullmatch(r'(sh|sz|bj)\d{6}', c) for c in codes) or len(set(codes)) != len(codes):
            raise ValueError('财联社代码或重复记录异常')
        if any(number(r.get('num_stocks')) != len(rows) for r in rows):
            raise ValueError('财联社列表不完整')
        output, reasons = [], []
        for row, code in zip(rows, codes):
            pct = number(row.get('change'))
            price = number(row.get('last_px'))
            if price is None or price <= 0 or pct is None:
                raise ValueError('财联社价格缺失')
            output.append(dict(code=code[2:], name=row.get('secu_name') or code[2:],
                price=price, pct=round(pct*100, 3), limit_days=number(row.get('limit_up_days')),
                quote_at=row['time']))
            # Before | is the provider's theme title; after it is narrative, not tags.
            title, separator, detail = str(row.get('up_reason') or '').partition('|')
            reason = title.strip()
            reason_detail = detail.strip() if separator else ''
            output[-1].update(reason=reason, reason_detail=reason_detail,
                themes=list(dict.fromkeys(t.strip() for t in re.split(r'[+＋、]', reason) if t.strip())))
            reasons.append(dict(code=code[2:], reason=reason, reason_detail=reason_detail))
        return key, output, reasons, max(r['time'] for r in rows)
    pools, reasons, times, errors = {}, [], [], []
    def safe_read(item):
        try:
            return read(item)
        except Exception:
            return item[0], None, [], None
    with ThreadPoolExecutor(max_workers=3) as executor:
        for key, rows, tags, stamp in executor.map(safe_read, CLS_POOL_TYPES.items()):
            pools[key] = rows
            if rows is None:
                errors.append({'sealed':'财联社涨停池', 'broken':'财联社炸板池', 'down':'财联社跌停池'}[key]+'暂不可用或日期无法核验')
            if key == 'sealed':
                reasons = tags
            if stamp:
                times.append(stamp)
    if pools.get('sealed') is None:
        raise RuntimeError('财联社当日涨停池不可用')
    return dict(version=1, mode='provider', trade_date=day,
        fetched_at=now().strftime('%Y-%m-%d %H:%M:%S'), source_at=max(times),
        source='财联社当日涨跌停池', errors=errors, reference='https://www.cls.cn/',
        **derive(pools, reasons))


def collect():
    try:
        return collect_cls()
    except Exception:
        return collect_eastmoney()


def collect_eastmoney():
    day = now().date().isoformat()
    compact = day.replace('-', '')
    jobs = {k: 'https://push2ex.eastmoney.com/'+ep+'?'+urlencode(dict(ut='7eea3edcaed734bea9cbfc24409ed989',
        dpt='wz.ztzt', Pageindex=0, pagesize=10000, sort='fund:asc' if k == 'down' else 'fbt:asc', date=compact)) for k, ep in POOL_TYPES.items()}
    jobs['reasons'] = 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?'+urlencode(dict(page=1, limit=200,
        field='199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004',
        filter='HS,GEM2STAR', order_field=330324, order_type=0, date=compact))
    pools, reasons, errors = {}, [], []
    def read(item):
        key, url = item
        try:
            d = json.loads(fetch_text(url))
            data = d.get('data')
            rows = data.get('info' if key == 'reasons' else 'pool') if isinstance(data, dict) else None
            source_day = str(data.get('qdate') or data.get('date') or compact).replace('-', '') if isinstance(data, dict) else ''
            if source_day != compact:
                raise ValueError('拒绝非当日行情')
            if not isinstance(rows, list):
                raise ValueError('上游响应缺少数据列表')
            return key, rows, None
        except Exception:
            return key, None, {'reasons': '同花顺题材', 'sealed': '东财涨停池', 'broken': '东财炸板池', 'down': '东财跌停池'}[key]+'暂不可用'
    with ThreadPoolExecutor(max_workers=4) as executor:
        for key, rows, error in executor.map(read, jobs.items()):
            if error:
                errors.append(error)
            if key == 'reasons' and rows is not None:
                reasons = rows
            elif key in POOL_TYPES:
                pools[key] = normalize_pool(rows) if rows is not None else None
    source, source_at = '东方财富涨停池 / 同花顺涨停题材', None
    if pools.get('sealed') is None:
        raise RuntimeError('当日实时涨停池暂不可用')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('无效数据日期')
    return dict(version=1, trade_date=day, fetched_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        source_at=source_at, source=source, errors=errors, reference=REFERENCE,
        mode='snapshot' if source_at else 'provider', **derive(pools, reasons))


class RadarService:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy, self.attempt, self.data, self.error = False, 0., None, None
        try:
            cached = json.loads(CACHE.read_text())
            if cached.get('version') == 1 and cached.get('mode') == 'provider' and cached.get('trade_date') == now().date().isoformat() and isinstance(cached.get('stocks'), list):
                self.data = cached
        except (OSError, ValueError):
            pass

    def _refresh(self):
        try:
            value = collect()
            with self.lock:
                self.data, self.error = value, None
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix('.tmp')
            tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
            tmp.replace(CACHE)
        except Exception:
            with self.lock:
                self.error = '当日实时数据暂不可用，已隐藏无法确认的涨停状态。'
        finally:
            with self.lock:
                self.busy = False

    def get(self, force=False):
        with self.lock:
            elapsed = time.monotonic()-self.attempt
            if not self.busy and elapsed >= (5 if force else 15):
                self.busy, self.attempt = True, time.monotonic()
                threading.Thread(target=self._refresh, daemon=True, name='market-radar').start()
            payload = copy.deepcopy(self.data or {})
            historical = payload.get('trade_date') != now().date().isoformat()
            try:
                age = (now()-datetime.strptime(payload['fetched_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Shanghai'))).total_seconds()
            except (ValueError, KeyError):
                age = math.inf
            unavailable = not self.data or historical or age > 45 or self.error is not None or payload.get('mode') != 'provider'
            if unavailable:
                payload = dict(stocks=[], broken=[], themes=[], industries=[],
                    error=self.error or '实时数据暂不可用，未展示昨日或过期涨停池。')
            payload.update(refreshing=self.busy, historical=False,
                stale=unavailable, refresh_sec=15,
                status='unavailable' if unavailable else 'current')
            return payload


SERVICE = RadarService()
