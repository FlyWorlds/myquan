import json,sys,os,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'holdingStocks'))
import start_project as launcher
from database_holdings import request_state
from account_reconciliation import effective_deliveries
OUT=Path(__file__).parent
with launcher.operation_lock():
 if launcher.port_open(launcher.HOST,8765):raise RuntimeError('Watch must be stopped before applying replay')
 before=json.loads((OUT/'before_state.json').read_text());proposed=json.loads((OUT/'proposed_state.json').read_text())
 current=request_state();assert current==before,'Account changed; regenerate replay before commit'
 (OUT/'safety_state.json').write_text(json.dumps(current,ensure_ascii=False,indent=2));os.chmod(OUT/'safety_state.json',0o600)
 report=json.loads((OUT/'replay_report.json').read_text());assert report['verified'] and report['account']['dayPnlVsEquity']==0
 payload=dict(expectedRevision=current['revision'],requestId=proposed['trades'][-1]['id'],holdings=proposed['holdings'],trades=proposed['trades'],ledger=proposed['ledger'])
 result=request_state('PUT',payload)
 for key in ['holdings','trades','ledger']:assert result[key]==proposed[key]
 read=request_state();assert read==result
 effective,issues=effective_deliveries(read)
 today=[e for e in effective if str(e.get('session')or e.get('time',''))[:10]=='2026-10-30']
 assert len(today)==6 and len({e['id']for e in today})==6
 assert all(t.get('reset_archived') for t in read['trades'][:len(before['trades'])] if t.get('id') in report['original_trade_ids'])
 (OUT/'committed_state.json').write_text(json.dumps(read,ensure_ascii=False,indent=2))
 (OUT/'commit_verification.json').write_text(json.dumps(dict(verified=True,revision=read['revision'],originals_preserved=True,effective_today_count=len(today),cash=read['holdings']['account_cash']),indent=2))
 print('COMMITTED verified revision',read['revision'],'cash',read['holdings']['account_cash'])
for p in OUT.glob('*.json'):os.chmod(p,0o600)
