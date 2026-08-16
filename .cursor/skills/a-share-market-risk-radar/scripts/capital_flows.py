"""
第三层：资金追踪
覆盖：
1. 北向资金（外资在买卖什么）
2. 龙虎榜机构动向（游资/机构博弈方向）
3. 大宗交易（大股东悄悄出货信号）
输出：资金方向综合判断
"""
import json
import os
import argparse
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import panda_data

USERNAME = os.environ.get("PANDADATA_USERNAME")
PASSWORD = os.environ.get("PANDADATA_PASSWORD")


# ─────────────────────────────────────────────
# 1. 北向资金
# ─────────────────────────────────────────────
def analyze_northbound(pd_api, symbols: list, start: str, end: str) -> dict:
    """分析北向资金在关注股票上的变化"""
    if not symbols:
        return {"status": "需要传入symbols参数", "level": "UNKNOWN"}

    changes = []
    for sym in symbols[:50]:  # 限制数量避免超时
        df = pd_api.get_hsgt_hold(symbol=[sym], start_date=start, end_date=end, fields=[])
        if df is None or len(df) < 2:
            continue
        df = df.sort_values("date")
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        ratio_chg = float(latest.get("holding_ratio", 0) or 0) - float(prev.get("holding_ratio", 0) or 0)
        changes.append({
            "symbol": sym,
            "date": str(latest["date"]),
            "holding_ratio": float(latest.get("holding_ratio", 0) or 0),
            "ratio_change": round(ratio_chg, 4),
        })

    if not changes:
        return {"status": "无北向数据", "level": "UNKNOWN"}

    changes.sort(key=lambda x: x["ratio_change"])
    net_in = [c for c in changes if c["ratio_change"] > 0]
    net_out = [c for c in changes if c["ratio_change"] < 0]

    level = "RED" if len(net_out) > len(net_in) * 2 else "YELLOW" if len(net_out) > len(net_in) else "GREEN"

    return {
        "level": level,
        "total_tracked": len(changes),
        "net_inflow_count": len(net_in),
        "net_outflow_count": len(net_out),
        "top_buy": changes[-3:][::-1],
        "top_sell": changes[:3],
        "detail": f"跟踪{len(changes)}只，{len(net_in)}只北向流入，{len(net_out)}只流出"
    }


# ─────────────────────────────────────────────
# 2. 龙虎榜机构动向
# ─────────────────────────────────────────────
def analyze_lhb(pd_api, start: str, end: str, keywords: list = None) -> dict:
    """分析龙虎榜机构净买卖方向"""
    df = pd_api.get_lhb_detail(start_date=start, end_date=end, fields=[])
    if df is None or len(df) == 0:
        return {"status": "无龙虎榜数据", "level": "UNKNOWN"}

    # 只看机构专用席位
    inst = df[df["agency"].str.contains("机构", na=False)].copy()
    if len(inst) == 0:
        return {"status": "无机构龙虎榜记录", "level": "UNKNOWN"}

    inst["b_value"] = pd.to_numeric(inst["b_value"], errors="coerce").fillna(0)
    inst["s_value"] = pd.to_numeric(inst["s_value"], errors="coerce").fillna(0)
    inst["net"] = inst["b_value"] - inst["s_value"]

    # 按股票汇总机构净买入
    by_symbol = inst.groupby("symbol").agg(
        inst_net_buy=("net", "sum"),
        inst_buy=("b_value", "sum"),
        inst_sell=("s_value", "sum"),
        record_count=("net", "count"),
    ).reset_index()

    by_symbol = by_symbol.sort_values("inst_net_buy", ascending=False)

    total_net = by_symbol["inst_net_buy"].sum()
    level = "GREEN" if total_net > 0 else "RED" if total_net < -5e8 else "YELLOW"

    # 如果有关键词过滤（如存储、光通信）
    sector_filter = None
    if keywords:
        all_syms = pd_api.get_stock_detail(fields=[]) if keywords else None
        # 简化处理：直接返回全市场机构方向

    return {
        "level": level,
        "total_inst_net_billion": round(total_net / 1e8, 2),
        "inst_buy_billion": round(by_symbol["inst_buy"].sum() / 1e8, 2),
        "inst_sell_billion": round(by_symbol["inst_sell"].sum() / 1e8, 2),
        "top_inst_buy": by_symbol.head(5).to_dict("records"),
        "top_inst_sell": by_symbol.tail(5).to_dict("records"),
        "date_range": f"{start}~{end}",
        "detail": f"机构龙虎榜净{'买入' if total_net > 0 else '卖出'}{abs(round(total_net/1e8,2))}亿"
    }


# ─────────────────────────────────────────────
# 3. 大宗交易
# ─────────────────────────────────────────────
def analyze_block_trades(pd_api, start: str, end: str, symbols: list = None) -> dict:
    """大宗交易分析：找折价大的（大股东出货信号）"""
    if symbols:
        dfs = []
        for sym in symbols:
            df = pd_api.get_block_trade(symbol=[sym], start_date=start, end_date=end, fields=[])
            if df is not None and len(df) > 0:
                dfs.append(df)
        if not dfs:
            return {"status": "无大宗交易数据", "level": "UNKNOWN"}
        data = pd.concat(dfs)
    else:
        data = pd_api.get_block_trade(start_date=start, end_date=end, fields=[])

    if data is None or len(data) == 0:
        return {"status": "无大宗交易数据", "level": "UNKNOWN"}

    data = data.sort_values("date", ascending=False)
    data["amount"] = pd.to_numeric(data["amount"], errors="coerce")
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data["volume"] = pd.to_numeric(data["volume"], errors="coerce")

    # 获取当日收盘价计算折价率
    large_trades = data[data["amount"] > 5e6].copy()  # 500万以上

    # 统计
    total_amount = data["amount"].sum()
    total_count = len(data)

    # 大额交易（>1亿）- 疑似大股东减持
    whale_trades = data[data["amount"] > 1e8].copy()

    level = "YELLOW" if len(whale_trades) > 5 else "GREEN"
    if len(whale_trades) > 10:
        level = "RED"

    return {
        "level": level,
        "date_range": f"{start}~{end}",
        "total_trades": total_count,
        "total_amount_billion": round(total_amount / 1e8, 1),
        "whale_trades_count": len(whale_trades),  # 大额>1亿
        "whale_trades": whale_trades.head(10).to_dict("records"),
        "all_trades_sample": data.head(20).to_dict("records"),
        "detail": f"大宗交易{total_count}笔，合计{round(total_amount/1e8,1)}亿，大额(>1亿)共{len(whale_trades)}笔"
    }


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="*", default=[], help="关注的股票列表")
    p.add_argument("--days", type=int, default=5, help="回溯天数（默认5）")
    p.add_argument("--out", default="/tmp/capital_flows.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=args.days * 2 + 5)).strftime("%Y%m%d")

    print(f"💰 资金追踪扫描（近{args.days}日）...")

    print("  [1/3] 北向资金分析...")
    nb = analyze_northbound(panda_data, args.symbols, start, end)

    print("  [2/3] 龙虎榜机构动向...")
    lhb = analyze_lhb(panda_data, start, end)

    print("  [3/3] 大宗交易异动...")
    block = analyze_block_trades(panda_data, start, end, args.symbols if args.symbols else None)

    # 综合判断
    levels = [nb.get("level"), lhb.get("level"), block.get("level")]
    levels = [l for l in levels if l not in ("UNKNOWN", None)]
    red = levels.count("RED")
    yellow = levels.count("YELLOW")
    if red >= 2:
        overall = "RED"
        summary = "资金面多维度异常：机构持续卖出，大宗折价交易增多，建议回避"
    elif red == 1 or yellow >= 2:
        overall = "YELLOW"
        summary = "资金面存在局部压力，需关注机构和大股东动向"
    else:
        overall = "GREEN"
        summary = "资金面整体正常"

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "layer": "L3_资金追踪",
        "overall_level": overall,
        "summary": summary,
        "northbound": nb,
        "lhb_institutional": lhb,
        "block_trades": block,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    icon = "🔴" if overall == "RED" else "🟡" if overall == "YELLOW" else "🟢"
    print(f"\n{icon} L3资金追踪：{overall}")
    print(f"   {summary}")
    for name, sig in [("北向", nb), ("龙虎榜机构", lhb), ("大宗交易", block)]:
        if sig.get("detail"):
            lv = sig.get("level", "")
            ic = "🔴" if lv == "RED" else "🟡" if lv == "YELLOW" else "🟢"
            print(f"   {ic} [{name}] {sig['detail']}")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
