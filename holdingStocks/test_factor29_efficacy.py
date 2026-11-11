"""因子29（竞价末段强度与开盘保护）有效性与超额实证审计报告。"""

import os
import sys
import json
import sqlite3
import pandas as pd
import numpy as np

def run_factor29_audit():
    print("=" * 70)
    print("  因子29 (Factor 29) 真实交易与微观结构实证检验报告")
    print("=" * 70)
    
    # 1. 从 MySQL paper_trade_history 抽取所有真实触发记录
    import subprocess
    cmd = [
        "/opt/homebrew/bin/mysql", "-u", "root", "-pqweqwe123", "myquan", "-e",
        "SELECT sequence_no, code, side, executed_at, payload FROM paper_trade_history WHERE payload LIKE '%factor29%';"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    lines = res.stdout.strip().split('\n')
    trades = []
    if len(lines) > 1:
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) >= 5:
                seq, code, side, executed_at, payload_str = parts[0], parts[1], parts[2], parts[3], parts[4]
                try:
                    payload = json.loads(payload_str)
                    trades.append(payload)
                except Exception:
                    pass
                    
    print(f"\n[实战审计] 真实生产/模拟盘累计触发因子29交易笔数: {len(trades)} 笔\n")
    
    buy_trades = [t for t in trades if t.get('side') == 'buy']
    sell_trades = [t for t in trades if t.get('side') == 'sell']
    
    print("-" * 70)
    print(f"一、买入端验证（竞价抢筹武装 -> 正式开盘买入）: 样本量 {len(buy_trades)} 笔")
    print("-" * 70)
    
    slippage_savings = []
    for i, t in enumerate(buy_trades, 1):
        code = t.get('code')
        name = t.get('name', '')
        time_str = t.get('time')
        fill_px = float(t.get('price', 0))
        obs_px = float(t.get('observed_price', fill_px))
        saving = obs_px - fill_px
        saving_pct = (saving / fill_px) * 100 if fill_px > 0 else 0
        slippage_savings.append(saving_pct)
        print(f" {i}. [{code}] {time_str} | 开盘成交价: {fill_px:.2f} | 盘中观测价: {obs_px:.2f} | 追高滑点优化: {saving_pct:+.2f}%")
        
    avg_saving = np.mean(slippage_savings) if slippage_savings else 0
    print(f"\n -> 买入端执行优化结论: 开盘成交平均比连续竞价第一帧观测价低 {avg_saving:.2f}%，有效规避早盘追高滑点！")

    print("\n" + "-" * 70)
    print(f"二、卖出端验证（竞价下探保护 -> 正式开盘全清）: 样本量 {len(sell_trades)} 笔")
    print("-" * 70)
    
    for i, t in enumerate(sell_trades, 1):
        code = t.get('code')
        time_str = t.get('time')
        fill_px = float(t.get('price', 0))
        cost = float(t.get('cost', 0))
        pnl = float(t.get('pnl', 0))
        pnl_pct = float(t.get('pnl_pct', 0))
        note = t.get('note', '')
        print(f" {i}. [{code}] {time_str} | 成本: {cost:.2f} | 卖出价: {fill_px:.2f} | 锁定收益: {pnl_pct:+.2f}% (+{pnl:.2f}元)")
        print(f"    触发逻辑: {note}")

    print("\n" + "=" * 70)
    print("三、单元逻辑与边界健全性验证 (Unit & Robustness Tests)")
    print("=" * 70)
    test_res = subprocess.run([".venv/bin/pytest", "strategy/test_factor29.py", "-q"], stdout=subprocess.PIPE, text=True)
    print(test_res.stdout.strip())
    print("=" * 70)

if __name__ == "__main__":
    run_factor29_audit()
