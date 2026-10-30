from pathlib import Path
import sys,subprocess,os
sys.path.insert(0,str(Path.cwd()))
import start_project as launcher
with launcher.operation_lock():
 launcher.stop()
 if any(launcher.port_open(launcher.HOST,p) for p in (8080,8765)):
  raise RuntimeError("Application ports still active; no restoration performed")
 print("BACKUP stopped current database",flush=True)
 result=subprocess.run([sys.executable,"backend/backup_database.py","--verify-restore"],capture_output=True,text=True,check=True)
 manifest=Path(result.stdout.strip().splitlines()[-1])
 print("SAFETY",manifest,flush=True)
 env=dict(os.environ,PITR_SAFETY_BACKUP=str(manifest.parent))
 subprocess.run([sys.executable,"reports/db_rollback_20261030_093000/apply_verified.py"],env=env,check=True)
 if any(launcher.port_open(launcher.HOST,p) for p in (8080,8765)):
  raise RuntimeError("Unexpected application restart")
 print("SERVICES_STOPPED_VERIFIED",flush=True)
