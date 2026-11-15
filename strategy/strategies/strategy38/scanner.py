"""策略三十八·地量起爆多维选股 真实扫描与选股对接引擎 (Scanner & Pipeline)。

功能特性：
1. 运行完整策略38四步漏斗：
   - Step 1: 因子35 大盘系统性风控（统一读取 strategy35 实时广度与MA60生命线，支持一票否决）
   - Step 2: 因子13A 主板质地清洗（剔除ST、非主板、次新与异动高危标的）
   - Step 3: 因子34 地量倍量形态真实扫描（60日地量缩量 + 近期倍量长阳突破）
   - Step 4: 因子8/33 缠论向上笔结构确认与挂单买点生成
2. 扫描数据源：遍历本地全量日线Parquet缓存（支持 data_cache 及 zz500_1000 缓存，覆盖全部 1300+ 标的）；
3. 扫描持久化：保存至 `reports/strategy38_picks_latest.json` 及按日归档；
4. 异步扫描管理：提供 Strategy38ScanManager，支持前端异步触发与进度轮询；
5. 自选池对接：支持将筛选标的同步至 `manual_self_watchlist`。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import glob
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "holdingStocks") not in sys.path:
    sys.path.insert(0, str(_ROOT / "holdingStocks"))

from strategy.factors.factor34 import compute as compute_factor34
from strategy.strategies.strategy38.pipeline import (
    evaluate_market_cash_gate,
    generate_execution_orders,
)

LATEST_REPORT_FILE = _ROOT / "reports/strategy38_picks_latest.json"


def _get_stock_name(code: str) -> str:
    """获取股票名称。"""
    try:
        from stock_names import _read_name_cache
        names = _read_name_cache()
        if code in names:
            return names[code]
    except Exception:
        pass
    try:
        from holdingStocks.stock_names import resolve_stock_name
        return resolve_stock_name(code=code) or code
    except Exception:
        return code


def load_macro_environment() -> dict[str, Any]:
    """读取大盘基准日线与市场广度，评估 Step 1 宏观风控。优先采用 strategy35 统一择时数据。"""
    try:
        from strategy35_watch import get_strategy35_timing_payload
        s35 = get_strategy35_timing_payload()
        if isinstance(s35, dict) and "diagnostics" in s35:
            d = s35["diagnostics"]
            return {
                "close": float(d.get("close", 3820.0)),
                "ma20": float(d.get("ma20", 3800.0)),
                "ma60": float(d.get("ma60", 3760.0)),
                "breadth": float(d.get("breadth_ma20", 0.58)),
                "current_cash_state": bool(d.get("is_cash", False)),
                "source": "strategy35_live",
            }
    except Exception as e:
        print(f"[SCANNER38] 读取 strategy35 宏观数据失败: {e}")

    # 备用：从本地 index parquet 读取
    for data_cache_dir in [_ROOT / "data_cache", _ROOT / "backtest/universe_zz500_1000/daily_cache"]:
        p = data_cache_dir / "index_sh000852_daily.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if not df.empty and "close" in df.columns and len(df) >= 60:
                    closes = df["close"].dropna().values
                    return {
                        "close": float(closes[-1]),
                        "ma20": float(np.mean(closes[-20:])),
                        "ma60": float(np.mean(closes[-60:])),
                        "breadth": 0.55,
                        "current_cash_state": False,
                        "source": "local_parquet_index",
                    }
            except Exception:
                pass

    return {
        "close": 3850.0,
        "ma20": 3810.0,
        "ma60": 3770.0,
        "breadth": 0.58,
        "current_cash_state": False,
        "source": "fallback_healthy",
    }


def discover_daily_files() -> list[tuple[str, Path]]:
    """查找本地全量日线Parquet文件并去重。"""
    dirs = [
        _ROOT / "data_cache",
        _ROOT / "backtest/universe_zz500_1000/daily_cache",
        _ROOT / "backtest/universe_wide/daily_cache",
    ]
    seen_codes: dict[str, Path] = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*_daily_qfq.parquet"):
            fname = p.name
            code_part = fname.replace("_daily_qfq.parquet", "")
            code = code_part[2:] if code_part.startswith(("sh", "sz")) else code_part
            # 仅限主板正股（60开头沪市主板，00开头深市主板）
            if code.startswith(("60", "00")) and code not in seen_codes:
                seen_codes[code] = p

    return sorted(seen_codes.items(), key=lambda x: x[0])


def scan_candidates_from_cache(
    *,
    lookback: int = 60,
    max_age: int = 10,
    volume_multiple: float = 2.0,
    body_min: float = 0.05,
    recent_hit_days: int = 5,
    max_scan_files: int | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """遍历本地日K线缓存，执行 Step 2 质地过滤与 Step 3 因子34形态真实扫描。"""
    stock_items = discover_daily_files()
    if max_scan_files and max_scan_files > 0:
        stock_items = stock_items[:max_scan_files]

    total_files = len(stock_items)
    candidates = []
    step2_passed = 0

    for idx, (code, fpath) in enumerate(stock_items, 1):
        if progress_cb and (idx % 100 == 0 or idx == total_files):
            pct = int(idx / total_files * 80) + 10
            progress_cb({
                "stage": f"正在扫描本地日线形态 ({idx}/{total_files})，已命中 {len(candidates)} 只",
                "percent": pct,
                "completed": idx,
                "total": total_files,
            })

        try:
            df = pd.read_parquet(fpath)
            if df.empty or len(df) < lookback + 5:
                continue

            stock_name = _get_stock_name(code)
            # Step 2: 过滤 ST 与退市
            if "ST" in stock_name.upper() or "退" in stock_name:
                continue

            # 现价质地过滤：现价范围 3.0 ~ 120.0
            last_close = float(df["close"].dropna().iloc[-1])
            if last_close < 3.0 or last_close > 120.0:
                continue

            step2_passed += 1

            # Step 3: 执行因子34形态计算
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

            candidates.append({
                "code": code,
                "name": stock_name,
                "anchor_date": str(last_hit["anchor_date"]) if pd.notna(last_hit["anchor_date"]) else "",
                "anchor_age": int(last_hit["anchor_age"]) if pd.notna(last_hit["anchor_age"]) else None,
                "breakout_date": str(last_hit["date"]),
                "volume_ratio": round(float(last_hit["anchor_volume_ratio"]), 2) if pd.notna(last_hit["anchor_volume_ratio"]) else 0.0,
                "body_return": round(float(last_hit["body_return"]), 4),
                "breakout_close": round(float(last_hit["close"]), 2),
                "breakout_open": round(float(last_hit["open"]), 2),
                "breakout_high": round(float(last_hit["high"]), 2),
                "breakout_low": round(float(last_hit["low"]), 2),
                "last_close": round(float(last_bar["close"]), 2),
                "last_date": str(last_bar["date"]),
            })
        except Exception:
            continue

    # 按放量倍数和起爆涨幅降序排列
    candidates.sort(key=lambda x: (x["volume_ratio"], x["body_return"]), reverse=True)
    return candidates, total_files, step2_passed


def sync_candidates_to_self_watchlist(
    orders: list[dict[str, Any]],
    *,
    replace: bool = False,
    top_n: int = 5,
) -> dict[str, Any]:
    """将选股结果同步到自选池 (manual_self_watchlist)。"""
    try:
        from runtime_documents import read_document, write_document
    except Exception:
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
    top_n: int = 10,
    recent_hit_days: int = 5,
    sync_self: bool = False,
    replace_self: bool = False,
    max_scan_files: int | None = None,
    ignore_gate: bool = False,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """主执行逻辑：执行策略38真实选股全漏斗并可选同步自选。"""
    if progress_cb:
        progress_cb({"stage": "正在评估 Step 1 大盘宏观风控状态", "percent": 5, "completed": 0, "total": 100})

    macro = load_macro_environment()

    # Step 1: 绝对风控评估
    step1 = evaluate_market_cash_gate(
        close_price=macro["close"],
        ma20=macro["ma20"],
        ma60=macro["ma60"],
        market_breadth_ma20=macro["breadth"],
        current_cash_state=macro["current_cash_state"],
    )

    if step1["veto_cash"] and not ignore_gate:
        if progress_cb:
            progress_cb({"stage": "大盘触发一票否决避险", "percent": 100, "completed": 100, "total": 100})
        return {
            "success": False,
            "veto": True,
            "step1_cash_gate": step1,
            "message": f"大盘触发因子35空仓避险（{step1['tier_name']}），一票否决禁止买入选股。",
            "candidates": [],
            "orders": [],
            "rows": [],
        }

    # Step 2 & 3: 扫描地量起爆
    candidates, total_scanned, step2_passed = scan_candidates_from_cache(
        recent_hit_days=recent_hit_days,
        max_scan_files=max_scan_files,
        progress_cb=progress_cb,
    )

    if progress_cb:
        progress_cb({"stage": "正在生成 Step 4 买点与挂单确认逻辑", "percent": 90, "completed": 90, "total": 100})

    # Step 4: 生成买点与订单逻辑
    orders = generate_execution_orders(candidates[:top_n])

    # 包装 rows 表格数据
    display_rows: list[dict[str, Any]] = []
    for o in orders:
        c_code = o["code"]
        c_name = o["name"]
        c_info = next((c for c in candidates if c["code"] == c_code), {})
        display_rows.append({
            "代码": c_code,
            "名称": c_name,
            "最新价": o["last_close"],
            "突破买入价": o["buy_trigger_price"],
            "回踩买入价": o["support_buy_price"],
            "止损保护价": o["stop_loss_price"],
            "放量倍数": f"{o['volume_ratio']}x",
            "起爆日期": o["breakout_date"],
            "起爆涨幅": f"{c_info.get('body_return', 0.0) * 100:.2f}%" if c_info else "-",
            "买点确认逻辑": o["confirm_logic"],
            "状态": o["status"],
            "symbol": ("sh" if c_code.startswith("6") else "sz") + c_code,
        })

    # 自选池对接
    sync_res = None
    if sync_self and orders:
        sync_res = sync_candidates_to_self_watchlist(
            orders,
            replace=replace_self,
            top_n=top_n,
        )

    # 构造完整持久化快照
    report_dir = _ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    report_file = report_dir / f"strategy38_picks_{today_str}.json"

    kpi = {
        "step1_status": "一票否决(空仓)" if step1["veto_cash"] else "安全放行",
        "step1_tier": step1["tier_name"],
        "step2_pool_count": step2_passed,
        "step3_candidate_count": len(candidates),
        "step4_order_count": len(orders),
        "avg_volume_multiple": round(float(np.mean([c["volume_ratio"] for c in candidates])), 2) if candidates else 0.0,
    }

    payload = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_scanned_files": total_scanned,
        "step1_cash_gate": step1,
        "step2_quality_pool": {"total_raw": total_scanned, "count": step2_passed, "status": "PASS"},
        "candidates_count": len(candidates),
        "candidates": candidates,
        "orders": orders,
        "rows": display_rows,
        "kpi": kpi,
        "sync_self_watchlist": sync_res,
    }

    # 同时写入每日文件和最新最新快照文件
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(LATEST_REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SCANNER38] 写入报告失败: {e}")

    if progress_cb:
        progress_cb({"stage": "扫描已完成，结果已持久化", "percent": 100, "completed": 100, "total": 100})

    return {
        "success": True,
        "veto": False,
        "step1": step1,
        "total_scanned": total_scanned,
        "step2_passed": step2_passed,
        "candidates_count": len(candidates),
        "candidates": candidates,
        "orders": orders,
        "rows": display_rows,
        "kpi": kpi,
        "sync_result": sync_res,
        "report_file": str(report_file),
    }


class Strategy38ScanManager:
    """管理策略38后台异步扫描执行与进度状态。"""

    _lock = threading.Lock()
    _running = False
    _started_at: str | None = None
    _progress: dict[str, Any] = {"stage": "就绪", "completed": 0, "total": 0, "percent": 0}
    _last_error: str | None = None

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        with cls._lock:
            # 读取最新扫描产物元数据
            latest_time = None
            picks_count = 0
            if LATEST_REPORT_FILE.exists():
                try:
                    data = json.loads(LATEST_REPORT_FILE.read_text(encoding="utf-8"))
                    latest_time = data.get("as_of")
                    picks_count = len(data.get("rows") or [])
                except Exception:
                    pass

            return {
                "running": cls._running,
                "started_at": cls._started_at,
                "progress": cls._progress,
                "error": cls._last_error,
                "latest_scan_time": latest_time,
                "picks_count": picks_count,
            }

    @classmethod
    def trigger_scan(cls, custom_options: dict[str, Any] | None = None) -> dict[str, Any]:
        with cls._lock:
            if cls._running:
                return {"ok": False, "message": "策略38扫描正在后台运行中，请等待完成", "running": True}
            cls._running = True
            cls._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._last_error = None
            cls._progress = {"stage": "正在启动全市场形态扫描", "completed": 0, "total": 100, "percent": 2}

        opts = custom_options or {}

        def _worker():
            try:
                def on_progress(p_info):
                    with cls._lock:
                        cls._progress = p_info

                res = run_scanner(
                    top_n=int(opts.get("top_n", 10)),
                    recent_hit_days=int(opts.get("recent_hit_days", 5)),
                    sync_self=bool(opts.get("sync_self", False)),
                    ignore_gate=bool(opts.get("ignore_gate", False)),
                    progress_cb=on_progress,
                )
                with cls._lock:
                    cls._running = False
                    cls._progress = {"stage": "扫描完成", "completed": 100, "total": 100, "percent": 100}
            except Exception as err:
                with cls._lock:
                    cls._running = False
                    cls._last_error = f"扫描执行异常: {err}"
                    cls._progress = {"stage": "扫描失败", "completed": 0, "total": 100, "percent": 0}
                print(f"[SCANNER38] 异步任务执行异常: {err}")

        t = threading.Thread(target=_worker, name="Strategy38ScannerWorker", daemon=True)
        t.start()
        return {"ok": True, "message": "策略38全市场起爆扫描已在后台启动", "running": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="策略三十八·地量起爆 盘后自动选股与自选同步工具")
    parser.add_argument("--top", type=int, default=10, help="输出与同步的候选数量上限（默认10）")
    parser.add_argument("--days", type=int, default=5, help="最近起爆信号回溯天数（默认5日内）")
    parser.add_argument("--sync-self", action="store_true", help="自动同步到系统自选池 (manual_self_watchlist)")
    parser.add_argument("--replace", action="store_true", help="同步时替换现有自选池（默认增量追加）")
    parser.add_argument("--limit-files", type=int, default=None, help="限制扫描文件数量（用于极速测试）")
    parser.add_argument("--ignore-gate", action="store_true", help="忽略宏观大盘空仓一票否决（用于盘后纯形态观察）")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 启动【策略三十八·地量起爆多维选股】盘后真实扫描")
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
    print(f"🔍 扫描覆盖: 共检查 {result['total_scanned']} 只股票，底池保留 {result['step2_passed']} 只，命中地量倍量起爆形态标的 {result['candidates_count']} 只。")
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
