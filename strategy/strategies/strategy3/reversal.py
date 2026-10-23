"""鲍鱼捞饭：逐根日线观察 CZSC 笔，保存当时可知的形态快照。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
POOL = ROOT / 'backtest/strategy16_core_leader/picks_quarter.json'
OUT = ROOT / 'backtest/strategy3_abalone'
RULES = ('日线：60日阶段新低底分型 → CZSC确认向上一笔 → 后续下跌破前底；'
         '比较破位0/2/4/6%、3日跌速加快、止跌确认；收盘信号次日开盘执行。'
         '单票占总资金上限20%，比较初仓占额度33%/50%/100%，分批版本再次下跌3%且止跌后补剩余额度；'
         '成本止损、持有期限、反弹分批止盈由回测比较。研究参数尚未验证。')


@dataclass(frozen=True)
class Policy:
    depth: float = .02
    hold: int = 10
    stop: float = .08
    take: float = .08
    mode: str = 'stabilize'
    acceleration: bool = True
    initial: float = .5
    add_drop: float = .03
    reduce: float = .5
    slot: float = .2
    stop_mode: str = "cost"
    take_mode: str = "cost"
    risk_budget: float = 0.
    min_rr: float = 0.
    max_entry_risk: float = 1.
    stop_buffer_atr: float = .3
    stop_buffer_pct: float = 0.
    stop_trigger: str = "close"

    def dict(self):
        return asdict(self)


def normalize(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d['date'] = pd.to_datetime(d['date'])
    if d.date.dt.tz is not None:
        d['date'] = d.date.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    d['date'] = d.date.dt.normalize()
    for k in ('open', 'high', 'low', 'close', 'volume'):
        if k not in d and k == 'volume':
            d[k] = 0.
        d[k] = pd.to_numeric(d[k], errors='coerce')
    d = d.dropna(subset=['date', 'open', 'high', 'low', 'close'])
    valid = ((d.low > 0) & (d.high >= d[['open', 'close', 'low']].max(axis=1))
             & (d.low <= d[['open', 'close']].min(axis=1)))
    return d[valid].sort_values('date').drop_duplicates('date').reset_index(drop=True)


def load_daily(symbol: str) -> tuple[pd.DataFrame, dict]:
    """先取最新缓存，历史仅在重叠复权比例一致时拼接，记录来源。"""
    dirs = ['backtest/strategy3_abalone/daily', 'data_cache', 'data_cache/ai_concept', 'backtest/universe_wide/daily_cache',
            'backtest/universe_zz500_1000/daily_cache', 'backtest/universe_abc/daily_cache']
    sources = []
    for folder in dirs:
        p = ROOT / folder / f'{symbol}_daily_qfq.parquet'
        if p.exists():
            d = normalize(pd.read_parquet(p))
            if not d.empty:
                sources.append((p, d))
    if not sources:
        return pd.DataFrame(), {'symbol': symbol, 'error': '无日线缓存'}
    sources.sort(key=lambda x: (x[1].date.max(), len(x[1])), reverse=True)
    p, data = sources[0]
    used, rejected = [str(p.relative_to(ROOT))], []
    for p, older in sources[1:]:
        if not (~older.date.isin(data.date)).any():
            continue
        overlap = data.merge(older, on='date', suffixes=('_new', '_old'))
        if len(overlap) < 5:
            rejected.append(str(p.relative_to(ROOT))); continue
        ratios = np.concatenate([(overlap[f'{k}_new'] / overlap[f'{k}_old']).values
                                 for k in ('open', 'high', 'low', 'close')])
        scale = float(np.median(ratios))
        if np.max(np.abs(ratios / scale - 1)) > .005:
            rejected.append(str(p.relative_to(ROOT))); continue
        older = older[~older.date.isin(data.date)].copy()
        older.loc[:, ['open', 'high', 'low', 'close']] *= scale
        data = pd.concat([older, data], ignore_index=True).sort_values('date').reset_index(drop=True)
        used.append(str(p.relative_to(ROOT)))
    return data, dict(symbol=symbol, rows=len(data), start=str(data.date.min().date()),
                      end=str(data.date.max().date()), sources=used, rejected=rejected)


def build_features(d: pd.DataFrame, symbol: str, lookback: int = 60) -> pd.DataFrame:
    from czsc import CZSC, RawBar, Freq, Direction
    d = normalize(d)
    if d.empty:
        return d
    c, lows = d.close.to_numpy(), d.low.to_numpy()
    dates = {pd.Timestamp(t): i for i, t in enumerate(d.date)}
    analyzer = None
    active = None
    seen = set()
    rows = []
    for i, r in enumerate(d.itertuples()):
        bar = RawBar(symbol=symbol, id=i, dt=r.date.to_pydatetime(), freq=Freq.D,
                     open=r.open, close=r.close, high=r.high, low=r.low,
                     vol=r.volume, amount=r.close * r.volume)
        if analyzer is None:
            analyzer = CZSC([bar], max_bi_num=50)
        else:
            analyzer.update(bar)
        # 只观察截至当日的最后一笔；不从最终笔列表向过去填充。
        if analyzer.bi_list:
            bi = analyzer.bi_list[-1]
            key = (str(bi.sdt), str(bi.edt), str(bi.direction))
            if bi.direction == Direction.Up and key not in seen:
                seen.add(key)
                j = dates.get(pd.Timestamp(bi.sdt), -1)
                anchor = float(bi.fx_a.fx)
                if j >= lookback and anchor <= min(lows[j-lookback:j+1]) + 1e-8:
                    if active is None or j > active['j']:
                        active = dict(j=j, anchor=anchor, peak=float(bi.fx_b.fx),
                                      confirmed=i, trough=anchor, broken=False, accelerated=False)
        mom3 = c[i] / c[i-3] - 1 if i >= 3 else 0.
        prior3 = c[i-3] / c[i-6] - 1 if i >= 6 else 0.
        accel = mom3 < min(prior3, 0.) and mom3 < -.02
        stabilize = bool(i > 0 and lows[i] >= lows[i-1] and c[i] > c[i-1]
                         and c[i] > r.open)
        snap = dict(anchor=np.nan, anchor_date='', depth=0., broken=False,
                    accelerated=False, trough=np.nan, state='等待阶段新低及向上一笔')
        if active is not None and i - active['confirmed'] <= 120:
            a = active
            if i > a['confirmed'] and lows[i] < a['anchor']:
                a['broken'] = True
                a['trough'] = min(a['trough'], lows[i])
            if a['broken']:
                a['accelerated'] |= accel
            snap = dict(anchor=a['anchor'], anchor_date=str(d.date.iloc[a['j']].date()),
                        depth=max(0., 1-a['trough']/a['anchor']), broken=a['broken'],
                        accelerated=a['accelerated'], trough=a['trough'],
                        state=('破位后止跌' if stabilize else '破位下跌') if a['broken']
                        else ('接近前低预警' if c[i] <= a['anchor']*1.03 else '向上一笔已确认'))
        rows.append(dict(**snap, mom3=mom3, acceleration=accel, stabilize=stabilize))
    return pd.concat([d, pd.DataFrame(rows)], axis=1)


def eligible(r, p: Policy) -> bool:
    return (bool(r.broken) and r.depth >= p.depth
            and (not p.acceleration or bool(r.accelerated))
            and (p.mode == 'break' or bool(r.stabilize)))


def read_policy() -> Policy:
    path = OUT / 'selected_policy.json'
    return Policy(**json.loads(path.read_text())['policy']) if path.exists() else Policy()
