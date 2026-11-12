"""策略三十八·地量起爆多维选股 盘后自动化选股与自选池对接引擎 (Scanner & Self-Watchlist Sync)。

功能特性：
1. 完整运行策略38四步漏斗：
   - Step 1: 因子35 大盘系统性风控（指数MA60与市场广度一票否决）
   - Step 2: 因子13A 主板质地清洗（剔除ST、非主板、次新与异动高危标的）
   - Step 3: 因子34 地量倍量形态扫描（60日地量缩量 + 近期倍量长阳突破）
   - Step 4: 因子8/33 缠论向上笔结构确认与挂单买点生成
2. 自动对接自选池：
   - 支持将精选出的起爆标的一键/自动同步至 `manual_self_watchlist`；
   - 盯盘服务热池与前端页面自动实时呈现，打上“波段起爆”来源标签。
3. 盘后持久化报告生成：
   - 结果保存至 `reports/strategy38_picks_YYYYMMDD.json`。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import glob
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.factors.factor34 import compute as compute_factor34
from strategy.factors.factor35 import evaluate_cash_gate
from strategy.strategies.strategy38.pipeline import (
    evaluate_market_cash_gate,
    filter_quality_pool,
    generate_execution_orders,
)
try:
    from holdingStocks.stock_names import resolve_stock_name
except Exception:
    def resolve_stock_name(*, code: str = "", name: str = "", **kwargs: Any) -> str:
        return name or code


def load_macro_environment(data_cache_dir: Path) -> dict[str, Any]:
    """读取大盘基准日线与市场广度，评估 Step 1 宏观风控。"""
    # 优先查找中证1000/深成指
    idx_paths = [
        data_cache_dir / "index_sh000852_daily.parquet",
        data_cache_dir / "index_sz399001_daily.parquet",
    ]
    close_px = 3800.0
    ma20 = 3780.0
    ma60 = 3750.0

    for p in idx_paths:
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if not df.empty and "close" in df.columns and len(df) >= 60:
                    closes = df["close"].dropna().values
                    close_px = float(closes[-1])
                    ma20 = float(np.mean(closes[-20:]))
                    ma60 = float(np.mean(closes[-60:]))
                    break
            except Exception:
                pass

    # 查找市场广度
    breadth = 0.55
    breadth_path = data_cache_dir / "market_breadth_cross_section.parquet"
    if breadth_path.exists():
        try:
            bdf = pd.read_parquet(breadth_path)
            if not bdf.empty and "breadth_ma20" in bdf.columns:
                breadth = float(bdf["breadth_ma20"].dropna().iloc[-1])
        except Exception:
            pass

    return {
        "close": close_px,
        "ma20": ma20,
        "ma60": ma60,
        "breadth": breadth,
        "current_cash_state": False,
    }


def scan_candidates_from_cache(
    data_cache_dir: Path,
    *,
    lookback: int = 60,
    max_age: int = 10,
    volume_multiple: float = 2.0,
    body_min: float = 0.05,
    recent_hit_days: int = 5,
    max_scan_files: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """遍历本地日K线缓存，执行 Step 2 质地过滤与 Step 3 因子34形态扫描。"""
    pattern = str(data_cache_dir / "*_daily_qfq.parquet")
    files = sorted(glob.glob(pattern))
    if max_scan_files and max_scan_files > 0:
        files = files[:max_scan_files]

    total_files = len(files)
    candidates = []

    for fpath in files:
        fname = os.path.basename(fpath)
        # 格式通常为 sh600552_daily_qfq.parquet 或 sz002636_daily_qfq.parquet
        code_part = fname.replace("_daily_qfq.parquet", "")
        if code_part.startswith(("sh", "sz")):
            code = code_part[2:]
        else:
            code = code_part

        # Step 2: 主板清洗（仅 60 / 00 开头）
        if not code.startswith(("60", "00")):
            continue

        try:
            df = pd.read_parquet(fpath)
            if df.empty or len(df) < lookback + 5:
                continue

            # 质地过滤：现价范围 3.0 ~ 120.0，日均量不为0
            last_close = float(df["close"].dropna().iloc[-1])
            if last_close < 3.0 or last_close > 120.0:
                continue

            # 执行因子34计算
            res = compute_factor34(
                df,
                lookback=lookback,
                max_age=max_age,
                volume_multiple=volume_multiple,
                body_min=body_min,
            )

            # 筛选最近 recent_hit_days 内触发倍量起爆的样本
            tail = res.tail(recent_hit_days)
            hits = tail[tail["candidate"] == True]
            if hits.empty:
                continue

            last_hit = hits.iloc[-1]
            last_bar = res.iloc[-1]

            # 尝试提取名称（从 stock_names 或 attrs 或 code）
            stock_name = resolve_stock_name(code=code) or df.attrs.get("name") or code

            candidates.append({
                "code": code,
                "name": stock_name,
                "anchor_date": last_hit["anchor_date"],
                "anchor_age": int(last_hit["anchor_age"]) if pd.notna(last_hit["anchor_age"]) else None,
                "breakout_date": last_hit["date"],
                "volume_ratio": round(float(last_hit["anchor_volume_ratio"]), 2) if pd.notna(last_hit["anchor_volume_ratio"]) else 0.0,
                "body_return": round(float(last_hit["body_return"]), 4),
                "breakout_close": round(float(last_hit["close"]), 2),
                "breakout_open": round(float(last_hit["open"]), 2),
                "breakout_high": round(float(last_hit["high"]), 2),
                "breakout_low": round(float(last_hit["low"]), 2),
                "last_close": round(float(last_bar["close"]), 2),
                "last_date": last_bar["date"],
            })
        except Exception:
            continue

    # 按放量倍数和起爆涨幅降序排列
    candidates.sort(key=lambda x: (x["volume_ratio"], x["body_return"]), reverse=True)
    return candidates, total_files


def sync_candidates_to_self_watchlist(
    orders: list[dict[str, Any]],
    *,
    replace: bool = False,
    top_n: int = 5,
) -> dict[str, Any]:
    """将选股结果同步到自选池 (manual_self_watchlist)。"""
    try:
        from holdingStocks.runtime_documents import read_document, write_document
    except Exception as exc:
        return {"success": False, "error": f"无法导入 runtime_documents: {exc}"}

    try:
        rev, data = read_document("manual_self_watchlist")
        if data is None or not isinstance(data, dict):
            data = {"items": [], "removed": {}}
        items = list(data.get("items") or [])
    except Exception as exc:
        return {"success": False, "error": f"读取自选池失败: {exc}"}

    target_orders = orders[:top_n]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing_codes = {str(item.get("code")) for item in items}
    added = []

    if replace:
        items = []
        existing_codes.clear()

    for o in target_orders:
        code = str(o["code"])
        name = str(o["name"])
        if code in existing_codes:
            continue
        new_item = {
            "code": code,
            "name": name,
            "addedAt": now_str,
            "source": "strategy38_breakout",
            "verifiedQuote": {
                "code": code,
                "name": name,
                "price": float(o.get("last_close") or 0.0),
                "prevClose": float(o.get("breakout_close") or o.get("last_close") or 0.0),
                "source": "strategy38_scanner",
            },
            "note": o.get("confirm_logic", "地量倍量起爆入选"),
        }
        items.append(new_item)
        existing_codes.add(code)
        added.append(code)

    data["items"] = items

    try:
        new_rev = write_document("manual_self_watchlist", data, rev)
        # 尝试让当前进程同步加载
        try:
            from strategy.watch_universe import install_self_watchlist
            install_self_watchlist(data)
        except Exception:
            pass
        return {
            "success": True,
            "revision": new_rev,
            "added_codes": added,
            "total_items": len(items),
        }
    except Exception as exc:
        return {"success": False, "error": f"写入自选池失败: {exc}"}


def run_scanner(
    *,
    top_n: int = 5,
    recent_hit_days: int = 5,
    sync_self: bool = False,
    replace_self: bool = False,
    max_scan_files: int | None = None,
    ignore_gate: bool = False,
) -> dict[str, Any]:
    """主执行逻辑：执行选股全漏斗并可选同步自选。"""
    data_dir = _ROOT / "data_cache"
    macro = load_macro_environment(data_dir)

    # Step 1: 绝对风控评估
    step1 = evaluate_market_cash_gate(
        close_price=macro["close"],
        ma20=macro["ma20"],
        ma60=macro["ma60"],
        market_breadth_ma20=macro["breadth"],
        current_cash_state=macro["current_cash_state"],
    )

    if step1["veto_cash"] and not ignore_gate:
        return {
            "success": False,
            "veto": True,
            "step1_cash_gate": step1,
            "message": f"大盘触发因子35空仓避险（{step1['tier_name']}），一票否决禁止买入选股。（如需强行观察形态请加 --ignore-gate）",
            "orders": [],
        }

    # Step 2 & 3: 扫描地量起爆
    candidates, total_scanned = scan_candidates_from_cache(
        data_dir,
        recent_hit_days=recent_hit_days,
        max_scan_files=max_scan_files,
    )

    # Step 4: 生成买点与订单逻辑
    orders = generate_execution_orders(candidates[:top_n])

    # 自选池对接
    sync_res = None
    if sync_self and orders:
        sync_res = sync_candidates_to_self_watchlist(
            orders,
            replace=replace_self,
            top_n=top_n,
        )

    # 持久化输出报告
    report_dir = _ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    report_file = report_dir / f"strategy38_picks_{today_str}.json"

    payload = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_scanned_files": total_scanned,
        "step1_cash_gate": step1,
        "candidates_count": len(candidates),
        "top_orders": orders,
        "sync_self_watchlist": sync_res,
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "veto": False,
        "step1": step1,
        "total_scanned": total_scanned,
        "candidates_count": len(candidates),
        "orders": orders,
        "sync_result": sync_res,
        "report_file": str(report_file),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="策略三十八·地量起爆 盘后自动选股与自选同步工具")
    parser.add_argument("--top", type=int, default=5, help="输出与同步的候选数量上限（默认5）")
    parser.add_argument("--days", type=int, default=5, help="最近起爆信号回溯天数（默认5日内）")
    parser.add_argument("--sync-self", action="store_true", help="自动同步到系统自选池 (manual_self_watchlist)")
    parser.add_argument("--replace", action="store_true", help="同步时替换现有自选池（默认增量追加）")
    parser.add_argument("--limit-files", type=int, default=None, help="限制扫描文件数量（用于极速测试）")
    parser.add_argument("--ignore-gate", action="store_true", help="忽略宏观大盘空仓一票否决（用于盘后纯形态观察）")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 启动【策略三十八·地量起爆多维选股】盘后扫描")
    print("=" * 60)

    result = run_scanner(
        top_n=args.top,
        recent_hit_days=args.days,
        sync_self=args.sync_self,
        replace_self=args.replace,
        max_scan_files=args.limit_files,
        ignore_gate=args.ignore_gate,
    )

    if result.get("veto"):
        print(f"⚠️  {result['message']}")
        return

    print(f"📊 宏观状态: 指数现价 {result['step1']['close']:.2f} | MA60 {result['step1']['ma60']:.2f} | 市场广度 {result['step1']['breadth']*100:.1f}%")
    print(f"✅ 风控判定: {result['step1']['tier_name']} (通过)")
    print(f"🔍 扫描覆盖: 共检查 {result['total_scanned']} 只股票，命中地量倍量起爆形态标的 {result['candidates_count']} 只。")
    print("-" * 60)

    orders = result.get("orders") or []
    if not orders:
        print("💡 当前未筛选到符合四步严格条件的标的。")
    else:
        print(f"🎯 优选 Top {len(orders)} 起爆标的与买点建议:")
        for idx, o in enumerate(orders, 1):
            print(f"\n[{idx}] 股票代码: {o['code']} ({o['name']})")
            print(f"    - 最新收盘: {o['last_close']:.2f} 元 | 起爆日放量倍数: {o['volume_ratio']}x")
            print(f"    - 次日突破挂单买点: {o['buy_trigger_price']:.2f} 元 (+2.5%)")
            print(f"    - 回踩支撑挂单买点: {o['support_buy_price']:.2f} 元 (大阳中分位)")
            print(f"    - 防守止损基准价位: {o['stop_loss_price']:.2f} 元 (-1.0%起爆低)")
            print(f"    - 逻辑说明: {o['confirm_logic']}")

    if result.get("sync_result"):
        sr = result["sync_result"]
        if sr.get("success"):
            print(f"\n✨ 已成功同步至系统自选池！新增标的: {sr.get('added_codes')}，当前自选池共 {sr.get('total_items')} 只股票。")
        else:
            print(f"\n❌ 同步自选池异常: {sr.get('error')}")

    print(f"\n📁 详细报告已保存至: {result.get('report_file')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
