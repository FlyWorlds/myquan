from pathlib import Path
import sys,pickle,json,subprocess,hashlib,decimal,datetime
sys.path.insert(0,str(Path(__file__).parent))
from reconstruct import connect,ROOT,DB,CONN
import pymysql
BACKUP=Path('backend/logs/backups/20261030-101153-aad468/database.sql').resolve()
SCRATCH='myquan_point_20261030_093000'
x=pickle.loads((ROOT/'changes.pkl').read_bytes())
c=connect()
with c.cursor() as q:
 q.execute('SET sql_log_bin=0')
 q.execute('SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',(SCRATCH,))
 if q.fetchone()[0]:raise RuntimeError('Scratch schema already exists')
 q.execute('CREATE DATABASE `'+SCRATCH+'` CHARACTER SET utf8mb4')
c.close()
args=['mysql','--protocol=TCP','--host='+CONN['host'],'--port='+str(CONN['port']),'--user='+CONN['user'],SCRATCH]
import os
env=dict(os.environ,MYSQL_PWD=CONN['password'])
dump=BACKUP.read_bytes().replace(('`'+DB+'`.').encode(),('`'+SCRATCH+'`.').encode())
subprocess.run(args,input=b'SET sql_log_bin=0;\n'+dump,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
del dump

def plain(value):
 if isinstance(value,bytes):return value.decode('utf8')
 if isinstance(value,dict):return {plain(k):plain(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [plain(v) for v in value]
 if isinstance(value,decimal.Decimal):return float(value)
 return value

def chunks(v,n=400):
 for i in range(0,len(v),n):yield v[i:i+n]

c=connect(SCRATCH)
with c.cursor() as q:
 q.execute('SET sql_log_bin=0');q.execute('SET FOREIGN_KEY_CHECKS=0')
 for table,bucket in x['desired'].items():
  if not bucket:continue
  m=x['meta'][table];pk=m['pk'];keys=list(bucket)
  for batch in chunks(keys):
   placeholders=','.join('('+','.join(['%s']*len(pk))+')' for _ in batch)
   pred='('+','.join('`'+p+'`' for p in pk)+') IN ('+placeholders+')'
   q.execute('DELETE FROM `'+table+'` WHERE '+pred,tuple(v for k in batch for v in k))
  cols=m['columns'];statement='INSERT INTO `'+table+'` ('+','.join('`'+p+'`' for p in cols)+') VALUES ('+','.join(['%s']*len(cols))+')'
  rows=[]
  for row in bucket.values():
   if row is None:continue
   values=[]
   for col in cols:
    value=row[col]
    if m['types'][col]=='json' and value is not None:value=json.dumps(plain(value),ensure_ascii=False,separators=(',',':'))
    values.append(value)
   rows.append(tuple(values))
  for batch in chunks(rows,100):q.executemany(statement,batch)
  for auto in m['auto']:
   q.execute('SELECT COALESCE(MAX(`'+auto+'`),0)+1 FROM `'+table+'`');next_id=int(q.fetchone()[0])
   q.execute('ALTER TABLE `'+table+'` AUTO_INCREMENT='+str(next_id))
  print('RESTORED',table,'keys',len(keys),'before_rows',len(rows),flush=True)
 q.execute('SET FOREIGN_KEY_CHECKS=1')
 # Verify each affected primary key against its first committed pre-cutoff image.
 for table,bucket in x['desired'].items():
  if not bucket:continue
  m=x['meta'][table]
  pred=' AND '.join('`'+k+'`=%s' for k in m['pk'])
  for key,expected in bucket.items():
   q.execute('SELECT '+','.join('`'+col+'`' for col in m['columns'])+' FROM `'+table+'` WHERE '+pred,key)
   values=q.fetchone()
   if expected is None:
    if values is not None:raise RuntimeError('Unexpected post-cutoff key: '+table)
   else:
    if values is None:raise RuntimeError('Missing pre-cutoff key: '+table)
    for col,actual in zip(m['columns'],values):
     want=expected[col]
     if m['types'][col]=='json':
      actual=json.loads(actual) if actual is not None else None;want=plain(want)
     if isinstance(actual,decimal.Decimal) and isinstance(want,float):want=decimal.Decimal(str(want))
     if actual!=want:raise RuntimeError('Value mismatch: '+table+'.'+col)
 q.execute('SELECT revision,holdings,trades,ledger FROM paper_account_state WHERE id=1')
 rev,hs,ts,ls=q.fetchone();holdings=json.loads(hs);trades=json.loads(ts);ledger=json.loads(ls)
 for table,records in [('paper_trade_history',trades),('paper_delivery_entries',ledger['entries'])]:
  q.execute('SELECT payload FROM `'+table+'` ORDER BY sequence_no')
  if [json.loads(v[0]) for v in q.fetchall()]!=records:raise RuntimeError('Ledger projection mismatch: '+table)
 q.execute('SELECT code,qty FROM paper_holdings')
 projected={k:int(v) for k,v in q.fetchall()};expected={k:int(v['qty']) for k,v in holdings['positions'].items() if v.get('qty',0)>0}
 if projected!=expected:raise RuntimeError('Holding projection mismatch')
 counts={}
 for table in x['meta']:
  q.execute('SELECT COUNT(*) FROM `'+table+'`');counts[table]=q.fetchone()[0]
 report=dict(verified=True,scratch=SCRATCH,target=x['target'],revision=rev,row_counts=counts,
  affected_keys=sum(len(b) for b in x['desired'].values()),all_before_images_verified=True,
  cash=holdings.get('account_cash'),positions={k:dict(qty=v['qty'],cost=v.get('cost')) for k,v in holdings['positions'].items() if v.get('qty',0)>0},
  latest_trade=max((str(t.get('time','')) for t in trades),default=''))
 (ROOT/'scratch_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
 print('VERIFIED',json.dumps({k:report[k] for k in ['revision','cash','positions','latest_trade']},ensure_ascii=False),flush=True)
c.close()
