"""
全链路市场扫描编排器
宏观 → 市场环境 → 资金追踪 → 板块轮动 → 个股风险
一键跑完全部四层，输出结构化报告
"""
import json
import os
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent

SCRIPTS = {
    "L1_全球宏观": BASE / "global_macro.py",
    "L2_市场环境": BASE / "market_radar.py",
    "L3_资金追踪": BASE / "capital_flows.py",
    "L4_板块轮动": BASE / "sector_rotation.py",
}

TECH_ALERT_SCRIPT = BASE / "tech_alert.py"


def run_layer(name: str, script: Path, extra_args: list = None) -> dict:
    out_file = f"/tmp/{name.replace('/', '_')}.json"
    cmd = [sys.executable, str(script), "--out", out_file]
    if extra_args:
        cmd.extend(extra_args)
    print(f"\n{'='*50}")
    print(f"▶ {name}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode == 0:
        try:
            with open(out_file) as f:
                return json.load(f)
        except Exception:
            return {"status": "error", "file": out_file}
    else:
        return {"status": "script_error", "returncode": result.returncode}


def run_stock_layer(script: Path, symbol: str) -> dict:
    out_file = f"/tmp/stock_{symbol.replace('.','_')}.json"
    cmd = [sys.executable, str(script), symbol, "--out", out_file]
    print(f"\n{'='*50}")
    print(f"▶ L5_个股风险：{symbol}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode == 0:
        try:
            with open(out_file) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def print_report(results: dict, stocks: list):
    print("\n" + "█" * 60)
    print("█  市场全链路风险报告")
    print(f"█  扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("█" * 60)

    level_icon = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢", "UNKNOWN": "⚪"}

    for layer_name, data in results.items():
        if not data:
            continue
        level = data.get("overall_level", "UNKNOWN")
        summary = data.get("summary", "")
        icon = level_icon.get(level, "⚪")
        print(f"\n{icon} {layer_name}：{level}")
        if summary:
            print(f"   {summary}")

        # 子信号
        for key in ["signals", "fear_gauge", "northbound", "lhb_institutional", "block_trades"]:
            sub = data.get(key)
            if not sub:
                continue
            if isinstance(sub, list):
                for s in sub:
                    detail = s.get("detail", "")
                    lv = s.get("level", "")
                    if detail and lv:
                        print(f"   {level_icon.get(lv,'⚪')} {detail}")
            elif isinstance(sub, dict):
                detail = sub.get("detail", "")
                lv = sub.get("level", "")
                if detail and lv:
                    print(f"   {level_icon.get(lv,'⚪')} {detail}")

    # 个股部分
    for sym, data in stocks.items():
        level = data.get("overall_level", "UNKNOWN")
        print(f"\n{level_icon.get(level,'⚪')} 个股 {sym}：{level}")
        print(f"   {data.get('summary','')}")

    # 综合建议
    all_levels = [r.get("overall_level") for r in results.values() if r.get("overall_level")]
    all_levels += [s.get("overall_level") for s in stocks.values() if s.get("overall_level")]
    red_count = all_levels.count("RED")
    yellow_count = all_levels.count("YELLOW")

    print("\n" + "─" * 60)
    print("📋 综合操作建议：")
    if red_count >= 3:
        print("  ⚠️  多层同时亮红：建议显著降低仓位，等待信号修复")
    elif red_count >= 1 or yellow_count >= 3:
        print("  ⚡  风险偏高：控制仓位，回避高PE小票和高融资集中股")
    else:
        print("  ✅  整体风险可控：可正常操作，注意个股预期差风险")
    print("─" * 60)


def main():
    p = argparse.ArgumentParser(description="全链路市场风险扫描")
    p.add_argument("--symbols", nargs="*", default=[], help="个股列表（选填）")
    p.add_argument("--out", default="/tmp/full_scan_report.json")
    args = p.parse_args()

    missing = [name for name in ("PANDADATA_USERNAME", "PANDADATA_PASSWORD") if not os.environ.get(name)]
    if missing:
        p.error("缺少环境变量：" + ", ".join(missing))

    results = {}

    # 四个市场层
    for name, script in SCRIPTS.items():
        extra = []
        if name == "L3_资金追踪" and args.symbols:
            extra = ["--symbols"] + args.symbols
        results[name] = run_layer(name, script, extra)

    # 个股层（基本面风险）
    stock_results = {}
    stock_script = BASE / "stock_risk.py"
    for sym in args.symbols:
        stock_results[sym] = run_stock_layer(stock_script, sym)

    # L6 技术面预警（有股票时单独跑）
    tech_results = {}
    if args.symbols and TECH_ALERT_SCRIPT.exists():
        out_file = "/tmp/tech_alert.json"
        cmd = [sys.executable, str(TECH_ALERT_SCRIPT)] + args.symbols + ["--out", out_file]
        print(f"\n{'='*50}")
        print("▶ L6_技术预警")
        print(f"{'='*50}")
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode == 0:
            try:
                with open(out_file) as f:
                    tech_data = json.load(f)
                    for r in tech_data.get("results", []):
                        tech_results[r["symbol"]] = r
            except Exception:
                pass

    # 汇总输出
    print_report(results, stock_results)

    # 打印技术预警摘要
    if tech_results:
        icon_map = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}
        print("\n【L6 技术面预警摘要】")
        for sym, tr in tech_results.items():
            ic = icon_map.get(tr.get("overall", ""), "⚪")
            top = tr.get("alerts", [{}])[0].get("name", "—") if tr.get("alerts") else "—"
            print(f"  {ic} {sym}  {tr.get('close','?')}  {tr.get('summary','')}  [主要:{top}]")

    final = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_layers": results,
        "stock_risks": stock_results,
        "technical_alerts": tech_results,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📁 完整报告已保存: {args.out}")


if __name__ == "__main__":
    main()
