"""Verified manual watchlist settings, separate from paper positions and fills."""
from __future__ import annotations

import copy
import math
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from strategy.board_rules import market_of, sina_of
from strategy.watch_universe import SELF_WATCHLIST_PICKS

KEY = 'manual_self_watchlist'


class SelfWatchlist:
    def __init__(self, *, read, write, fetch, install, changed=lambda: None, now=datetime.now):
        self.read, self.write, self.fetch = read, write, fetch
        self.install, self.changed, self.now = install, changed, now
        self.lock = threading.RLock()
        self.pending = {}

    def _load(self):
        revision, data = self.read(KEY)
        if data is None:
            data = {'items': [{'code': c, 'name': n} for c, n in SELF_WATCHLIST_PICKS], 'removed': {}}
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise RuntimeError('自选池数据格式异常，请检查数据库')
        return revision, copy.deepcopy(data)

    def snapshot(self):
        with self.lock:
            revision, data = self._load()
            self.install(data)
            return dict(revision=revision, items=data['items'])

    @staticmethod
    def code(value):
        value = str(value or '').strip().lower()
        match = re.fullmatch(r'(?:(sh|sz))?([0-9]{6})', value)
        if not match or not match[2].startswith(('000', '001', '002', '003', '300', '301', '600', '601', '603', '605', '688', '689')) or match[2] == '000000':
            raise ValueError('请输入有效的6位沪深A股股票代码')
        code = match[2]
        if match[1] and sina_of(code) != match[1] + code:
            raise ValueError('交易所与股票代码不匹配')
        return code

    def _quote(self, code):
        q = self.fetch(sina_of(code))
        if not isinstance(q, dict) or not str(q.get('name') or '').strip():
            raise ValueError('未取得可核对的股票名称和行情，未添加')
        price = q.get('last')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError('行情价格不可用，未添加')
        from trading_calendar import last_trading_day_on_or_before, previous_trading_day
        now = self.now()
        day = last_trading_day_on_or_before(now.date())
        if day == now.date() and now.strftime('%H:%M:%S') < '09:25:00':
            day = previous_trading_day(day)
        try:
            at = datetime.fromisoformat(str(q.get('last_ts') or ''))
            valid = at.tzinfo is None and at.date() == day and at <= now + timedelta(seconds=60)
            if day == now.date() and ('09:30:00' <= now.strftime('%H:%M:%S') <= '11:30:00'
                    or '13:00:00' <= now.strftime('%H:%M:%S') <= '15:00:00'):
                valid = valid and (now - at).total_seconds() <= 120
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError('行情时间过旧或无效，请稍后重新核对，未添加')
        return dict(code=code, name=str(q['name']).strip(), market=market_of(code),
                    price=price, prevClose=q.get('prev_close'), changePct=q.get('day_chg_pct'),
                    quoteTime=q['last_ts'], source=q.get('_quote_source') or 'sina_batch')

    def preview(self, raw):
        code = self.code(raw)
        quote = self._quote(code)
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v['expires'] > time.monotonic()}
            if len(self.pending) >= 100:
                self.pending.pop(next(iter(self.pending)))
            token = secrets.token_urlsafe(24)
            self.pending[token] = dict(quote=quote, expires=time.monotonic() + 120)
            _revision, data = self._load()
            return dict(quote=quote, token=token, alreadyAdded=any(i['code'] == code for i in data['items']))

    def confirm(self, token):
        with self.lock:
            pending = self.pending.get(str(token))
            if not pending or pending['expires'] <= time.monotonic():
                raise ValueError('核对结果已过期，请重新查询行情')
            quote = self._quote(pending['quote']['code'])
            if quote['name'] != pending['quote']['name']:
                raise ValueError('股票名称发生变化，请重新核对')
            revision, data = self._load()
            if not any(i['code'] == quote['code'] for i in data['items']):
                if len(data['items']) >= 200:
                    raise ValueError('自选池最多200只，请先删除部分股票')
                data['items'].append(dict(code=quote['code'], name=quote['name'],
                    addedAt=self.now().isoformat(sep=' ', timespec='seconds'), verifiedQuote=quote))
                data.setdefault('removed', {}).pop(quote['code'], None)
                self.write(KEY, data, revision)
            self.pending.pop(str(token), None)
            self.install(data)
        self.changed()
        return dict(ok=True, items=data['items'], quote=quote)

    def remove(self, raw):
        code = self.code(raw)
        with self.lock:
            revision, data = self._load()
            if any(i['code'] == code for i in data['items']):
                data['items'] = [i for i in data['items'] if i['code'] != code]
                from alert_retention import retention_session
                session = retention_session(self.now())
                data['removed'] = {c: day for c, day in data.get('removed', {}).items() if day == session}
                data['removed'][code] = session
                self.write(KEY, data, revision)
            self.install(data)
        self.changed()
        return dict(ok=True, items=data['items'], message='已移出自选；当天信号和成交记录保留')
