"""Strategy 1 selection drafts; only explicit save changes the active pool."""
from __future__ import annotations
import hashlib
import json
import math
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / 'backtest/strategy1_pool/picks_pool.json'
STATE = ROOT / 'holdingStocks/.strategy1_selection'
INDICES = ['沪深300', '中证500', '中证1000', '中证1500']
LOCK = threading.RLock()
_running = False
_error = None
_progress = {}
_job = None


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(path)


def fingerprint():
    return hashlib.sha256(ACTIVE.read_bytes()).hexdigest() if ACTIVE.exists() else ''


def status():
    with LOCK:
        return dict(running=_running, error=_error,
                    progress=read(_job/'progress.json', {}) if _running and _job else _progress,
                    draft=read(STATE/'draft.json'), active=read(ACTIVE, {}), indices=INDICES)


def start(indices):
    global _running, _error, _progress, _job
    if not isinstance(indices, list) or not indices or any(x not in INDICES for x in indices):
        raise ValueError('请至少勾选一个有效指数范围')
    with LOCK:
        if _running:
            raise ValueError('选股正在运行，请等待完成')
        _progress = dict(stage='准备选股', completed=0, total=0)
        request = dict(indices=list(dict.fromkeys(indices)), base=fingerprint(), id=str(uuid.uuid4()))
        _job = STATE/'jobs'/request['id']
        write(_job/'progress.json', _progress)
        write(STATE/'draft.json', None)
        write(_job/'request.json', request)
        _running, _error = True, None
        try:
            threading.Thread(target=_monitor, args=(_job,), daemon=True, name='strategy1-selection').start()
        except Exception:
            _running = False
            raise
    return status()


def _monitor(job):
    global _running, _error, _progress
    try:
        with (job/'worker.log').open('w') as log:
            proc = subprocess.Popen([sys.executable, '-m', 'holdingStocks.strategy1_selection', '--worker', str(job)],
                                    cwd=ROOT, stdout=log, stderr=log)
            try:
                code = proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise RuntimeError('选股超过60分钟已停止，原股票池保持不变，请重试')
        result = read(job/'result.json', {})
        if code or not result.get('draft'):
            raise RuntimeError(result.get('error') or '选股进程异常退出，请重试')
        with LOCK:
            write(STATE/'draft.json', result['draft'])
            _progress = dict(stage='候选已生成，等待保存', completed=30, total=30)
    except Exception as exc:
        with LOCK:
            _error = str(exc)
    finally:
        with LOCK:
            _running = False


def save(draft_id):
    with LOCK:
        if _running:
            raise ValueError('选股尚未结束')
        draft = read(STATE/'draft.json')
        if not draft or draft.get('id') != draft_id:
            raise ValueError('候选已失效，请重新选股')
        if draft.get('saved_at'):
            return status()
        if fingerprint() != draft['base']:
            raise ValueError('当前股票池已被其他操作修改，请重新选股后保存')
        picks = draft['picks']
        if len(picks) != 30 or len({p['code'] for p in picks}) != 30:
            raise ValueError('必须有30只不同的有效候选股票才能保存')
        now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
        payload = dict(horizon='monthly', label='援军战法30只选股池', as_of=draft['as_of'],
                       built_at=now, source='strategy1_quality_band_factor13a_16',
                       n_picks=30, target_pool=30, selection_id=draft['id'],
                       selection_indices=draft['indices'], selection_period=draft['period'],
                       note='30只 · 因子13A初筛＋因子16排序 · 数量不足允许放宽补足', picks=picks)
        # Thresholds travel in the same atomic payload as membership.
        write(STATE / f"backup-{draft['id']}.json", read(ACTIVE, {}))
        write(ACTIVE, payload)
        draft['saved_at'] = now
        write(STATE/'draft.json', draft)
    return status()


def filter_universe(meta, indices):
    from backtest.universe_zz500_1000 import _is_mainboard
    from backtest.s1_f13_refit_2025 import _is_st_name
    selected = meta[meta['index'].isin(indices)].drop_duplicates('symbol').copy()
    selected['code'] = selected['code'].astype(str).str.zfill(6)
    return selected[selected['code'].map(_is_mainboard) & ~selected['name'].map(_is_st_name)]


def select(request, progress):
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backtest import s1_f13_refit_2025 as engine
    from backtest.strategy1_pool.fit_s1_pool import fit_one
    from strategy.data import fetch_daily
    from strategy.factor16_leader_score import eval_stock_metrics_from_daily, attach_factor13_scores, rank_leader_pool
    engine.POOL_SIZE = 30
    meta = pd.read_csv(engine.WIDE_META, dtype={'code': str})
    meta = filter_universe(meta, request['indices'])
    panel = pd.read_csv(engine.OUT/'year_thr_panel_mainboard.csv')
    panel = panel[panel.symbol.isin(meta.symbol)]
    cfg = read(engine.OUT/'summary.json', {}).get('factor13_best')
    if not cfg:
        raise ValueError('缺少因子13A参数，请先生成研究参数')
    # Existing research panel covers only part of the index union. Build missing
    # 2025 rows instead of silently ignoring selected indices.
    from strategy.run_factor13_quality_opt import process_symbol
    missing = meta[~meta.symbol.isin(panel.loc[panel.year == 2025, 'symbol'])]
    extra_rows = []
    def build_missing(row):
        cache = STATE/'panel_2025'/f'{row.symbol}.json'
        existing = read(cache)
        if existing:
            return existing
        daily = engine._wide_load_daily(row.symbol)
        if daily is None or not (daily['date'].dt.year == 2025).any():
            daily = fetch_daily(row.symbol, '20250101', '20251231', force_refresh=False)
        if daily is None or daily.empty:
            return []
        result = process_symbol(dict(symbol=row.symbol, name=row.name, daily=daily, years=[2025]))
        # Pandas serializes nonfinite values to null for the JSON cache.
        if result:
            write(cache, json.loads(pd.DataFrame(result).to_json(orient='records')))
        return result
    progress('补齐所选范围的2025初筛回测', 0, len(missing))
    missing_errors = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(build_missing, row): row for row in missing.itertuples(index=False)}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                built = future.result()
                extra_rows.extend(built)
                if not built:
                    missing_errors.append(futures[future].symbol)
            except Exception:
                missing_errors.append(futures[future].symbol)
            progress('补齐所选范围的2025初筛回测', i, len(missing))
    if extra_rows:
        panel = pd.concat([panel, pd.DataFrame(extra_rows)], ignore_index=True)
    if panel.empty:
        raise ValueError('所选范围没有足够的2025日线，请检查行情源后重试')
    candidates = engine._f13a_candidates(panel, cfg)
    if candidates.empty:
        raise ValueError('所选范围没有可用的初筛数据')
    end = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    progress('更新候选日线', 0, len(candidates))
    rows, frames, thrs, skipped = [], {}, {}, []

    def evaluate(row):
        symbol, name = row.symbol, row.name
        code = engine._sym_to_code(symbol)
        daily = fetch_daily(symbol, '20250101', end, force_refresh=True)
        if daily is None or daily.empty:
            raise ValueError('日线为空')
        daily = daily.copy()
        daily['date'] = pd.to_datetime(daily['date']).dt.tz_localize(None)
        daily = daily.sort_values('date')
        if float(daily.iloc[-1]['close']) >= 100:
            return None
        metric = eval_stock_metrics_from_daily(code, daily, name=name, fit_start='20250101',
                    fit_end='20251231', oos_start='20260101', oos_end=end, with_chan=False)
        if metric is None:
            return None
        return metric, daily, fit_one(daily, code)

    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {executor.submit(evaluate, row): row for row in candidates.itertuples(index=False)}
        for i, job in enumerate(as_completed(jobs), 1):
            row = jobs[job]
            try:
                result = job.result()
                if result:
                    metric, daily, threshold = result
                    rows.append(metric)
                    frames[metric['code']] = daily
                    thrs[metric['code']] = threshold
            except Exception as exc:
                skipped.append(f'{row.symbol}: {type(exc).__name__}')
            progress(f'候选回测 · {row.name}', i, len(jobs))
    if len(rows) < 30:
        raise ValueError(f'所选范围有效候选仅{len(rows)}只，不足30只；行情失败{len(skipped)}只。请扩大范围或重试')
    rule = engine._cfg_to_f13_rule(cfg)
    scored = attach_factor13_scores(pd.DataFrame(rows), params=rule)
    ranked = rank_leader_pool(scored, top_k=30, params={**rule, 'min_oos_trades':3, 'min_bars':60})
    if len(ranked) < 30:
        raise ValueError(f'满足最低数据及交易次数的候选仅{len(ranked)}只，请扩大范围')
    picks = []
    for rank, row in enumerate(ranked.to_dict('records'), 1):
        code = row['code']; thr = thrs[code]
        def number(value):
            return float(value) if value is not None and math.isfinite(float(value)) else None
        picks.append(dict(rank=rank, code=code, symbol=code, name=row['name'],
            thr=thr['thr'], sharpe=number(thr.get('sharpe')), chg_pct=number(thr.get('ret_pct')),
            quality_pass=bool(row['f13_pass']), pl_ratio=number(row.get('oos_pl_ratio')),
            data_end=str(frames[code].iloc[-1]['date'])[:10],
            category='策略池', pool_src='strategy1_pool'))
    old = {p['code'] for p in read(ACTIVE, {}).get('picks', [])}
    new = {p['code'] for p in picks}
    return {**request, 'as_of': datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d'),
            'period': f'初筛2025年；排序/阈值2026年初至{end}（非独立样本外）',
            'picks': picks, 'added': sorted(new-old), 'removed': sorted(old-new),
            'failed_candidates': skipped + [f'{symbol}: 初筛数据不足或获取失败' for symbol in missing_errors],
            'warning': '现有成分表“中证1500”标签含2000只股票，范围沿用该表，尚未核实指数身份。' if '中证1500' in request['indices'] else ''}


if __name__ == '__main__':
    job = Path(sys.argv[-1])
    try:
        import requests
        original_request = requests.sessions.Session.request
        def bounded(self, method, url, **kwargs):
            if kwargs.get('timeout') is None:
                kwargs['timeout'] = (5, 15)
            return original_request(self, method, url, **kwargs)
        requests.sessions.Session.request = bounded
        def progress(stage, completed, total):
            write(job/'progress.json', dict(stage=stage, completed=completed, total=total))
        write(job/'result.json', {'draft': select(read(job/'request.json'), progress)})
    except BaseException as exc:
        write(job/'result.json', {'error': str(exc)})
        raise
