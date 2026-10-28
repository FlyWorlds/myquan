"""Display-only alert history, retained until the next exchange session at 09:00."""
from copy import deepcopy
from datetime import datetime, time
import os
import threading
from zoneinfo import ZoneInfo

from trading_calendar import last_trading_day_on_or_before, previous_trading_day
from watch_buy_signal import is_buy_hit, is_holdings_tab_signal_row

KEY = 'watch_alert_retention'
FIELDS = ('预警', '近买点', '近止损', '已触买', '信号时间', '已触发因子侧',
          '已触发因子价', '因子侧', '因子价', '因子触发', '买点', '买入侧价',
          '过门OK', '过门', '前日形态', '阈值就绪', 'bg_class', '挂单说明',
          '已触止损', '信号时刻', '买信号时间', '卖信号时间')


def retention_session(now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    day = last_trading_day_on_or_before(now.date())
    if day == now.date() and now.time().replace(tzinfo=None) < time(9):
        day = previous_trading_day(day)
    return str(day)


class AlertRetention:
    def __init__(self, read=None, write=None, strategy_id=None):
        from watch_config import STRATEGY_ID
        self.strategy_id = strategy_id or STRATEGY_ID
        self.read = read
        self.write = write
        self.loaded = False
        self.records = {}
        self.lock = threading.RLock()
        self.dirty = False

    def merge(self, rows, now=None, strategy_codes=None):
        session = retention_session(now)
        with self.lock:
            if not self.loaded:
                if self.read:
                    self.records = self.read() or {}
                self.loaded = True
            before = deepcopy(self.records)
            self.records = {c: r for c, r in self.records.items()
                            if r.get('session') == session
                            and r.get('strategy_id', 'strategy16') == self.strategy_id
                            and (strategy_codes is None or c in strategy_codes)}
            for row in rows:
                code = str(row.get('代码') or '')
                saved = self.records.get(code)
                # Never turn a retained display signal into an order or a position.
                entry_session = str(row.get('策略入场时间') or '')[:10]
                hit = is_buy_hit(row) or (
                    entry_session == session and row.get('策略状态') == '策略持有'
                )
                active = is_holdings_tab_signal_row(row) or hit or bool(row.get('近止损'))
                if (strategy_codes is not None and code not in strategy_codes
                        or row.get('信号策略ID', self.strategy_id) != self.strategy_id):
                    for key in ('预警保留', '预警交易日', '策略展示状态', '首次触买时间'):
                        row.pop(key, None)
                    continue
                if str(row.get('交易日') or '')[:10] == session and active:
                    if not saved or hit or not saved.get('hit'):
                        first_buy_at = (saved or {}).get('first_buy_at')
                        if hit and not first_buy_at:
                            first_buy_at = (row.get('买信号时间') or row.get('策略入场时间')
                                            or row.get('信号时刻') or row.get('信号时间'))
                        saved = dict(session=session, strategy_id=self.strategy_id, hit=hit, first_buy_at=first_buy_at,
                                     fields={k: deepcopy(row[k]) for k in FIELDS if k in row},
                                     row={k: deepcopy(row[k]) for k in
                                          ('代码', '名称', '市场', '交易日', '现价', '持仓状态',
                                           '策略回放持有') + FIELDS if k in row})
                        self.records[code] = saved
                # Only the strategy panel consumes this display override. The
                # simulator state and actual inventory stay current.
                row.pop('策略展示状态', None)
                row.pop('首次触买时间', None)
                if saved and saved['hit']:
                    row['策略展示状态'] = '已触买'
                    row['首次触买时间'] = saved.get('first_buy_at')
                if saved:
                    if int(row.get('持仓') or 0) == 0 and not row.get('已实现'):
                        if row.get('error') and saved.get('row'):
                            row.update(deepcopy(saved['row']))
                            row.pop('error', None)
                            row['预警行情说明'] = '行情暂不可用，展示最近预警快照'
                        row.update(deepcopy(saved['fields']))
                        if saved['hit']:
                            row['已触买'] = '是'
                        row['当日预警'] = True
                        row['预警保留'] = True
                        row['预警交易日'] = session
                    elif saved['hit']:
                        row['已触买'] = '是'
                        row['信号时间'] = saved['fields'].get('信号时间') or row.get('买入时间')
            seen = {str(r.get('代码') or '') for r in rows}
            for code, saved in self.records.items():
                if code not in seen:
                    restored = deepcopy(saved.get('row') or dict(saved['fields'], 代码=code))
                    restored.update(持仓=0, 当日预警=True, 预警保留=True, 预警交易日=session, 信号策略ID=self.strategy_id)
                    if saved['hit']:
                        restored['策略展示状态'] = '已触买'
                        restored['首次触买时间'] = saved.get('first_buy_at')
                    rows.append(restored)
            self.dirty = self.dirty or self.records != before
            if self.write and self.dirty:
                self.write(deepcopy(self.records))
                self.dirty = False
        return rows


def _retention_document_key():
    from watch_config import STRATEGY_ID
    return KEY if STRATEGY_ID == 'strategy16' else f'{KEY}_{STRATEGY_ID}'


def _read():
    if os.environ.get('HOLDINGS_STORAGE') == 'local_json':
        return {}
    from runtime_documents import read_document
    return read_document(_retention_document_key())[1] or {}


def _write(records):
    if os.environ.get('HOLDINGS_STORAGE') == 'local_json':
        return
    from runtime_documents import write_merging
    write_merging(_retention_document_key(), records)


LIVE_ALERT_RETENTION = AlertRetention(_read, _write)
