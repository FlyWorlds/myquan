"""Consistent local MySQL backup and isolated restore verification, never restore over production."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def connection():
    props = {}
    for line in (ROOT / "config/application-local.properties").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    env = dict(os.environ, MYSQL_PWD=props.get("spring.datasource.password", ""))
    args = ["--protocol=TCP", "--host=" + os.environ.get("DB_HOST", "127.0.0.1"),
            "--port=" + os.environ.get("DB_PORT", "3306"),
            "--user=" + props.get("spring.datasource.username", "root")]
    name = os.environ.get("DB_NAME", "myquan")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
        raise ValueError("Invalid database name")
    return args, env, name


def query(args, env, name, sql):
    result = subprocess.run(["mysql", *args, "--batch", "--skip-column-names", "--raw", name,
                             "--execute=" + sql], env=env, capture_output=True, check=True)
    return result.stdout.decode()


def verify(args, env, name, dump):
    scratch = "myquan_restore_check_" + uuid.uuid4().hex[:12]
    query(args, env, name, f"CREATE DATABASE `{scratch}` CHARACTER SET utf8mb4")
    try:
        # mysqldump qualifies views with the source schema; redirect only that exact identifier.
        restored = dump.replace(f"`{name}`.".encode(), f"`{scratch}`.".encode())
        subprocess.run(["mysql", *args, scratch], input=restored, env=env, capture_output=True, check=True)
        values = query(args, env, scratch,
                       "SELECT JSON_OBJECT('revision',revision,'holdings',CAST(holdings AS JSON),"
                       "'trades',CAST(trades AS JSON),'ledger',CAST(ledger AS JSON)) "
                       "FROM paper_account_state WHERE id=1")
        state = json.loads(values)
        for table, records in (("paper_trade_history", state["trades"]),
                               ("paper_delivery_entries", state["ledger"]["entries"])):
            actual = [json.loads(row) for row in query(args, env, scratch,
                      f"SELECT payload FROM {table} ORDER BY sequence_no").splitlines()]
            if actual != records:
                raise ValueError(f"Restored projection mismatch: {table}")
        qty = dict(line.split("\t") for line in query(args, env, scratch,
                   "SELECT code,qty FROM paper_holdings ORDER BY code").splitlines())
        expected = {code: str(pos["qty"]) for code, pos in state["holdings"]["positions"].items()
                    if pos.get("qty", 0) > 0}
        if qty != expected:
            raise ValueError("Restored holdings projection mismatch")
        tables = query(args, env, scratch, "SHOW FULL TABLES").splitlines()
        counts = {line.split("\t")[0]: int(query(args, env, scratch,
                  f"SELECT COUNT(*) FROM `{line.split(chr(9))[0]}`")) for line in tables}
        return dict(verified=True, revision=state["revision"], rowCounts=counts,
                    accountStateSha256=hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest())
    finally:
        query(args, env, name, f"DROP DATABASE `{scratch}`")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-restore", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "logs/backups")
    opts = parser.parse_args()
    args, env, name = connection()
    folder = opts.out_dir / (datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
                             + "-" + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, mode=0o700)
    os.chmod(folder, 0o700)
    target = folder / "database.sql"
    with target.open("xb") as output:
        os.chmod(target, 0o600)
        subprocess.run(["mysqldump", *args, "--single-transaction", "--no-tablespaces",
                        "--skip-lock-tables", "--set-gtid-purged=OFF", "--column-statistics=0", name],
                       env=env, stdout=output, stderr=subprocess.PIPE, check=True)
    dump = target.read_bytes()
    manifest = dict(database=name, bytes=len(dump), sha256=hashlib.sha256(dump).hexdigest(),
                    restoreCheck=verify(args, env, name, dump) if opts.verify_restore else {"verified": False})
    meta = folder / "manifest.json"
    meta.write_text(json.dumps(manifest, indent=2) + "\n")
    os.chmod(meta, 0o600)
    print(meta)


if __name__ == "__main__":
    main()
