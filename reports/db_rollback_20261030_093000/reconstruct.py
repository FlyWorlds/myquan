"""Read full row binlogs to reconstruct the committed logical database at the cutoff."""
from pathlib import Path
import sys,os,json,pickle,hashlib,time,re
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path[:0]=['/tmp/myquan-pitr-deps',str(Path(__file__).resolve().parents[2]/'backend')]
from backup_database import connection
import pymysql
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.row_event import WriteRowsEvent,UpdateRowsEvent,DeleteRowsEvent
from pymysqlreplication.event import QueryEvent,XidEvent
ROOT=Path(__file__).parent
TARGET=datetime(2026,10,30,9,30,tzinfo=ZoneInfo('Asia/Shanghai'))
a,e,DB=connection();v={x.split('=',1)[0]:x.split('=',1)[1] for x in a if '=' in x}
CONN=dict(host=v['--host'],port=int(v['--port']),user=v['--user'],password=e['MYSQL_PWD'],charset='utf8mb4')

def connect(db=DB):return pymysql.connect(**CONN,database=db,autocommit=True)
def schema():
 c=connect();result={}
 with c.cursor() as q:
  q.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE=%s',(DB,'BASE TABLE'))
  for (table,) in q.fetchall():
   q.execute('SELECT COLUMN_NAME,DATA_TYPE,COLUMN_KEY,EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION',(DB,table))
   cols=q.fetchall();pk=[x[0] for x in cols if x[2]=='PRI']
   if not pk:raise RuntimeError('No primary key: '+table)
   result[table]=dict(columns=[x[0] for x in cols],types={x[0]:x[1] for x in cols},pk=pk,auto=[x[0] for x in cols if 'auto_increment' in x[3]])
 c.close();return result

def maprow(raw,meta):
 result={}
 for k,value in raw.items():
  if k.startswith('UNKNOWN_COL'):k=meta['columns'][int(k[len('UNKNOWN_COL'):])]
  result[k]=value
 if set(result)!=set(meta['columns']):raise RuntimeError('Incomplete row image')
 return result

def scan():
 meta=schema();desired={t:{} for t in meta};pending=[];transactions=events=0;last=time.monotonic()
 stream=BinLogStreamReader(connection_settings=CONN,server_id=93731031,log_file='binlog.000243',log_pos=4,
  resume_stream=True,blocking=False,only_schemas=[DB],only_events=[WriteRowsEvent,UpdateRowsEvent,DeleteRowsEvent,QueryEvent,XidEvent],enable_logging=False)
 def record(table,before,after):
  m=meta[table];bucket=desired[table]
  def key(row):return tuple(row[k] for k in m['pk'])
  if before is not None:
   before=maprow(before,m);bucket.setdefault(key(before),before)
  if after is not None:
   after=maprow(after,m)
   if before is None or key(after)!=key(before):bucket.setdefault(key(after),None)
 def commit(ts):
  nonlocal transactions
  if ts>=TARGET.timestamp():
   for ev in pending:
    table=ev.table
    if isinstance(table,bytes):table=table.decode()
    for row in ev.rows:
     if isinstance(ev,WriteRowsEvent):record(table,None,row['values'])
     elif isinstance(ev,DeleteRowsEvent):record(table,row['values'],None)
     else:record(table,row['before_values'],row['after_values'])
   transactions+=1
  pending.clear()
 try:
  for ev in stream:
   events+=1
   if isinstance(ev,XidEvent):commit(ev.timestamp)
   elif isinstance(ev,QueryEvent):
    query=ev.query.decode() if isinstance(ev.query,bytes) else ev.query
    upper=query.upper().strip()
    if upper=='BEGIN':
     if pending:raise RuntimeError('Unexpected nested transaction')
    elif upper=='COMMIT':commit(ev.timestamp)
    elif upper=='ROLLBACK':pending.clear()
    elif ev.timestamp>=TARGET.timestamp() and any(upper.startswith(k) for k in ['ALTER TABLE','CREATE TABLE','DROP TABLE','TRUNCATE','RENAME TABLE']):
     sch=ev.schema.decode() if isinstance(ev.schema,bytes) else ev.schema
     if sch==DB:raise RuntimeError('DDL requires additional recovery: '+query[:100])
   else:
    table=ev.table.decode() if isinstance(ev.table,bytes) else ev.table
    if table in meta:pending.append(ev)
   if time.monotonic()-last>15:
    print('SCAN',stream.log_file,stream.log_pos,'transactions',transactions,'changed_keys',sum(len(v) for v in desired.values()),flush=True);last=time.monotonic()
  if pending:raise RuntimeError('Incomplete final transaction')
 finally:stream.close()
 payload=dict(target=TARGET.isoformat(),database=DB,meta=meta,desired=desired,transactions=transactions,end_file=stream.log_file,end_pos=stream.log_pos)
 with (ROOT/'changes.pkl').open('wb') as f:pickle.dump(payload,f)
 (ROOT/'scan.json').write_text(json.dumps({k:v for k,v in payload.items() if k not in ['meta','desired']}|{'changed_keys':{k:len(v) for k,v in desired.items()}},indent=2))
 print('SCAN_DONE',sum(len(v) for v in desired.values()),flush=True)

if __name__=='__main__':scan()
