import json
import subprocess
import time

def run_sql(sql):
    cmd = ["/opt/homebrew/bin/mysql", "-u", "root", "-pqweqwe123", "myquan", "-e", sql]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"SQL failed: {res.stderr}\nSQL: {sql}")
    return res.stdout

def main():
    print("=== 开始核查并校准账户资金与快照 ===")
    
    # 1. 读取当前 paper_account_state
    sql_get = "SELECT revision, holdings, trades, ledger FROM paper_account_state WHERE id=1;"
    raw = subprocess.run(["/opt/homebrew/bin/mysql", "-u", "root", "-pqweqwe123", "myquan", "-N", "-e", sql_get], capture_output=True, text=True, check=True).stdout
    parts = raw.split("\t")
    revision = int(parts[0])
    holdings = json.loads(parts[1])
    trades = json.loads(parts[2])
    ledger = json.loads(parts[3])

    print(f"当前 revision: {revision}, trades: {len(trades)}, ledger entries: {len(ledger.get('entries', []))}")
    
    # 2. 调整 trades 的 cash_after 与 reset_archived
    # 195~198 为 11-13 正常早盘交易：
    # 195: 600330 09:25:05 sell (net: 58811.02, cash_after: 182241.22)
    # 196: 603228 09:25:07 sell (net: 53642.28, cash_after: 235883.50)
    # 197: 002993 09:30:16 buy (net: 57282.72, cash_after: 178600.78)
    # 198: 002298 09:32:51 sell (net: 58161.06, cash_after: 236761.84)
    # 199~207 为盘中重复触发卖出单，统一标记为 reset_archived: True
    # 208: 002993 11-16 09:25:02 sell (net: 53913.85, cash_after: 236761.84 + 53913.85 = 290675.69)
    # 209: 601595 11-16 09:25:31 buy (net: 8078.85, cash_after: 290675.69 - 8078.85 = 282596.84)
    
    for i, t in enumerate(trades):
        if i in (195, 196, 198):
            t["reset_archived"] = False
        elif 199 <= i <= 207:
            t["reset_archived"] = True
        elif i == 208:
            t["reset_archived"] = False
            t["account_cash_after"] = 290675.69
        elif i == 209:
            t["reset_archived"] = False
            t["account_cash_after"] = 282596.84

    # 3. 调整 ledger entries
    for e in ledger.get("entries", []):
        eid = e.get("id")
        code = e.get("code")
        t_time = e.get("time", "")
        if "2026-11-16" in t_time:
            if code == "002993" and e.get("side") == "sell":
                e["account_cash_after"] = 290675.69
            elif code == "601595" and e.get("side") == "buy":
                e["account_cash_after"] = 282596.84
        elif "2026-11-13" in t_time:
            if eid in ("414ca73939224937bb2a75b6754c5e13", "ba6bf9520db846359b0fc2019bd7ed39", "06e56d11466f42d3a42293096298c398"):
                pass

    # 4. 调整 holdings 资金
    holdings["account_cash"] = 282596.84
    holdings["account_total"] = 290130.84
    holdings["account_total_open"] = 292241.84
    holdings["account_total_open_session"] = "2026-11-16"
    holdings["paper_equity_base"] = 300000.0

    new_revision = revision + 1
    
    # 5. 生成临时 SQL 文件并用 mysql 执行
    tmp_sql = "scratch/update.sql"
    with open(tmp_sql, "w", encoding="utf-8") as f:
        # 转义单引号
        h_str = json.dumps(holdings, ensure_ascii=False).replace("'", "\\'")
        t_str = json.dumps(trades, ensure_ascii=False).replace("'", "\\'")
        l_str = json.dumps(ledger, ensure_ascii=False).replace("'", "\\'")
        
        f.write(f"UPDATE paper_account_state SET revision={new_revision}, holdings='{h_str}', trades='{t_str}', ledger='{l_str}', updated_at=NOW() WHERE id=1;\n")
        f.write("DELETE FROM paper_account_snapshots WHERE trading_day='2026-11-13' AND (observed_at >= '2026-11-14' OR account_cash < 100000);\n")
        f.write(f"""
INSERT INTO paper_account_snapshots 
(snapshot_key, trading_day, observed_at, account_revision, total_pnl, total_pnl_pct, day_pnl, day_pnl_pct, position_pct, account_total, account_cash, market_value, account_payload, holdings_payload, closed_payload)
VALUES ('2026-11-13:202611131500', '2026-11-13', '2026-11-13 15:00:00', {revision}, -7758.16, -2.59, -2160.36, -0.73, 19.0, 292241.84, 236761.84, 55480.00, '{{}}', '[]', '[]')
ON DUPLICATE KEY UPDATE account_total=292241.84, account_cash=236761.84, market_value=55480.00, total_pnl=-7758.16, total_pnl_pct=-2.59, day_pnl=-2160.36, day_pnl_pct=-0.73;
""")
        f.write("DELETE FROM paper_account_snapshots WHERE trading_day='2026-11-16';\n")
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        now_compact = time.strftime("%Y%m%d%H%M")
        key_today = f"2026-11-16:{now_compact}"
        f.write(f"""
INSERT INTO paper_account_snapshots 
(snapshot_key, trading_day, observed_at, account_revision, total_pnl, total_pnl_pct, day_pnl, day_pnl_pct, position_pct, account_total, account_cash, market_value, account_payload, holdings_payload, closed_payload)
VALUES ('{key_today}', '2026-11-16', '{now_str}', {new_revision}, -9869.16, -3.29, -2111.00, -0.72, 2.6, 290130.84, 282596.84, 7534.00, '{{}}', '[]', '[]');
""")
    
    print("正在执行 SQL 更新...")
    with open(tmp_sql, "rb") as f_in:
        res = subprocess.run(["/opt/homebrew/bin/mysql", "-u", "root", "-pqweqwe123", "myquan"], stdin=f_in, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"SQL execution failed: {res.stderr}")
    print("paper_account_state 及 snapshots 更新成功！新 revision:", new_revision)
    print("=== 数据库校准完成 ===")

if __name__ == "__main__":
    main()
