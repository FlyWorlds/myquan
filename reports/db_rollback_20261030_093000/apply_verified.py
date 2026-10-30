from pathlib import Path
import sys,json,subprocess,hashlib,os,decimal,datetime
sys.path.insert(0,str(Path(__file__).parent))
from reconstruct import connect,ROOT,DB,CONN
import pymysql
CHECK=json.loads((ROOT/'scratch_verification.json').read_text());assert CHECK['verified'] and CHECK['all_before_images_verified']
SCRATCH=CHECK['scratch'];BASE=Path(os.environ['PITR_SAFETY_BACKUP'])
manifest=json.loads((BASE/'manifest.json').read_text());assert manifest['restoreCheck']['verified']
backup=BASE/'database.sql';assert hashlib.sha256(backup.read_bytes()).hexdigest()==manifest['sha256']
args=['--protocol=TCP','--host='+CONN['host'],'--port='+str(CONN['port']),'--user='+CONN['user']]
env=dict(os.environ,MYSQL_PWD=CONN['password'])

def canonical(value):
 if isinstance(value,bytes):return {'bytes_hex':value.hex()}
 if isinstance(value,(datetime.datetime,datetime.date,datetime.time)):return value.isoformat()
 if isinstance(value,(decimal.Decimal,datetime.timedelta)):return str(value)
 raise TypeError(type(value).__name__)

def fingerprints(db):
 c=connect(db);results={}
 with c.cursor() as q:
  q.execute('SHOW FULL TABLES');tables=q.fetchall()
 for table,kind in tables:
  if kind!='BASE TABLE':continue
  with c.cursor() as q:
   q.execute('SHOW KEYS FROM `'+table+'` WHERE Key_name=\'PRIMARY\'')
   keys=[r[4] for r in sorted(q.fetchall(),key=lambda r:r[3])]
  if not keys:raise RuntimeError('No deterministic primary key '+table)
  h=hashlib.sha256();count=0
  with c.cursor(pymysql.cursors.SSCursor) as q:
   q.execute('SELECT * FROM `'+table+'` ORDER BY '+','.join('`'+k+'`' for k in keys))
   for row in q:
    h.update(json.dumps(row,ensure_ascii=False,default=canonical,separators=(',',':')).encode());h.update(b'\n');count+=1
  results[table]=dict(count=count,sha256=h.hexdigest())
 c.close();return results

print('HASH staging',flush=True);wanted=fingerprints(SCRATCH)
assert {k:v['count'] for k,v in wanted.items()}==CHECK['row_counts']
print('HASH current',flush=True);before=fingerprints(DB)
(ROOT/'source_before_hashes.json').write_text(json.dumps(before,indent=2))
c=connect()
with c.cursor() as q:
 q.execute('SELECT revision FROM paper_account_state WHERE id=1')
 if q.fetchone()[0]!=manifest['restoreCheck']['revision']:raise RuntimeError('Source changed after safety backup; stopped before restore')
c.close()
path=ROOT/'target_093000.sql'
with path.open('wb') as out:
 subprocess.run(['mysqldump',*args,'--single-transaction','--no-tablespaces','--skip-lock-tables','--set-gtid-purged=OFF','--column-statistics=0',SCRATCH],env=env,stdout=out,stderr=subprocess.PIPE,check=True)
raw=path.read_bytes().replace(('`'+SCRATCH+'`.').encode(),('`'+DB+'`.').encode())
assert fingerprints(DB)==before,'Source still being modified; stopped before restore'

def restore(data):
 # Drop the derived view first; base-table definitions and all rows come from the verified dump.
 prefix=b'SET FOREIGN_KEY_CHECKS=0;\nDROP VIEW IF EXISTS `paper_closed_trades`;\n'
 subprocess.run(['mysql',*args,DB],input=prefix+data,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)

try:
 print('APPLY verified 09:30 state',flush=True);restore(raw)
 print('VERIFY production all base tables',flush=True);actual=fingerprints(DB)
 if actual!=wanted:raise RuntimeError('Production verification differs from isolated target')
 c=connect()
 with c.cursor() as q:
  q.execute('SELECT COUNT(*) FROM paper_closed_trades');views=q.fetchone()[0]
 c.close()
 report=dict(complete=True,target=CHECK['target'],database=DB,revision=CHECK['revision'],
  all_tables_match=True,table_hashes=actual,derived_view_rows=views,
  safety_backup=str(BASE.resolve()),safety_backup_sha256=manifest['sha256'],
  restored_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),services_running=False)
 (ROOT/'production_verification.json').write_text(json.dumps(report,indent=2))
 print('COMPLETE',CHECK['target'],'revision',CHECK['revision'],'tables',len(actual),flush=True)
except Exception:
 print('Restore error: reverting to safety backup',flush=True)
 restore(backup.read_bytes())
 if fingerprints(DB)!=before:raise RuntimeError('Emergency restoration requires manual database review')
 raise
