"""重放已绑定的组合因子，读取同一组绑定参数，而不是另设回测参数。"""
import json
from pathlib import Path
import pandas as pd
from .reversal import Policy
from .factor_mining import OUT as FEATURES
from .combo_config import config_from_bindings,compose_entry
from .research import simulate


def run_bound(*,start='2025-01-01',end=None,initial_cash=1_000_000.,frames=None,universe='manual'):
    from .bindings import FACTOR_BINDINGS
    cfg=config_from_bindings(FACTOR_BINDINGS)
    out=FEATURES.parent/'bound_strategy'
    if frames is None and universe in ('manual','market'):
        from .market_scan import OUT as MARKET_OUT,config_hash
        from .manual_scan import OUT as MANUAL_OUT
        SCAN_OUT=MANUAL_OUT if universe=='manual' else MARKET_OUT
        if not (SCAN_OUT/'snapshot.json').exists():raise ValueError('请先运行research=scan生成市场扫描')
        scan=json.loads((SCAN_OUT/'snapshot.json').read_text())
        if not scan.get('scanned_count'):raise ValueError('股票池为空，请先点击手动扫描并等待完成')
        if scan.get('config_hash')!=config_hash(cfg):raise ValueError('扫描参数与当前绑定不同，请重新扫描')
        symbols=sorted(r['symbol'] for r in scan['rows'] if r['status']=='ready')
        frames={s:pd.read_parquet(SCAN_OUT/'features'/f'{s}.parquet') for s in symbols}
        end=end or scan['as_of'];out=SCAN_OUT/'bound_strategy'
    elif frames is None and universe=='legacy30':
        frames={p.name.split('_features')[0]:pd.read_parquet(p) for p in FEATURES.glob('*_features.parquet')}
    elif frames is None:raise ValueError('universe只支持manual、market或legacy30')
    if not frames:raise ValueError('没有可回放的行情')
    end=end or str(min(f.date.max() for f in frames.values()).date())
    pf=compose_entry(frames,cfg['rule'])
    p=Policy(**cfg['policy'])
    stats,eq,orders,tr=simulate(pf,p,start=start,end=end,initial_cash=initial_cash)
    stats.update(universe_count=len(frames),universe=universe,
                 universe_note='当前行情齐备子集，有覆盖/名单偏差；不代表完整历史成分股回测' if universe in ('manual','market') else '原固定池研究')
    out.mkdir(parents=True,exist_ok=True)
    (out/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    (out/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
    eq.to_csv(out/'equity.csv',index=False);orders.to_csv(out/'orders.csv',index=False);tr.to_csv(out/'trades.csv',index=False)
    return dict(config=cfg,summary=stats,output=str(out))
