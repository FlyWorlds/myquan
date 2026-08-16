"""
融资盘脆弱性扫描
核心逻辑：
1. 全市场融资余额趋势（连续净卖出是抛压前兆）
2. 高融资集中度股票列表（杠杆最集中的地方跌最狠）
3. 融资净买入连续天数（类今年1-2月开门红高点的特征）
"""
import sys
import os
import json
import argparse
from datetime import datetime, timedelta
import pandas as pd
import panda_data

USERNAME = os.environ.get("PANDADATA_USERNAME")
PASSWORD = os.environ.get("PANDADATA_PASSWORD")


def get_dates(days):
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    return start, end


def analyze_margin_trend(pd_api, symbols: list):
    """分析给定股票池的融资趋势"""
    start, end = get_dates(30)
    all_dfs = []
    for sym in symbols:
        df = pd_api.get_margin(symbol=[sym], start_date=start, end_date=end, fields=[])
        if df is not None and len(df) > 0:
            all_dfs.append(df)

    if not all_dfs:
        return None

    merged = pd.concat(all_dfs)
    # 按日汇总全市场
    daily = merged.groupby("date").agg(
        total_margin_balance=("margin_balance", "sum"),
        total_buy=("buy_on_margin_value", "sum"),
        total_repay=("margin_repayment", "sum"),
    ).reset_index().sort_values("date")

    daily["net_buy"] = daily["total_buy"] - daily["total_repay"]
    daily["balance_chg"] = daily["total_margin_balance"].diff()

    # 连续净卖出天数
    consecutive_sell = 0
    for val in reversed(daily["net_buy"].tolist()):
        if val < 0:
            consecutive_sell += 1
        else:
            break

    # 近30日峰值萎缩比
    peak_balance = daily["total_margin_balance"].max()
    current_balance = daily["total_margin_balance"].iloc[-1]
    shrink_pct = (peak_balance - current_balance) / peak_balance * 100

    # 近7日累计净卖出
    net_7d = daily.tail(7)["net_buy"].sum()

    return {
        "consecutive_sell_days": consecutive_sell,
        "net_7d_billion": round(net_7d / 1e8, 2),
        "peak_balance_billion": round(peak_balance / 1e8, 0),
        "current_balance_billion": round(current_balance / 1e8, 0),
        "shrink_from_peak_pct": round(shrink_pct, 1),
        "daily_trend": daily.tail(10)[["date", "net_buy", "total_margin_balance"]].to_dict("records"),
    }


def find_high_margin_stocks(pd_api, symbols: list):
    """找融资集中度最高的股票（踩踏风险最大的位置）"""
    start, end = get_dates(5)
    records = []
    for sym in symbols:
        df = pd_api.get_margin(symbol=[sym], start_date=start, end_date=end, fields=[])
        if df is not None and len(df) > 0:
            latest = df.sort_values("date").iloc[-1]
            daily_df = pd_api.get_stock_daily(symbol=[sym], start_date=start, end_date=end, fields=[])
            mktcap = None
            if daily_df is not None and len(daily_df) > 0:
                row = daily_df.sort_values("date").iloc[-1]
                mktcap = row.get("amount", None)
            records.append({
                "symbol": sym,
                "margin_balance": latest.get("margin_balance", 0),
                "name": latest.get("name", sym) if "name" in latest else sym,
            })

    if not records:
        return []

    records.sort(key=lambda x: x["margin_balance"], reverse=True)
    top = records[:20]
    for r in top:
        r["margin_balance_billion"] = round(r["margin_balance"] / 1e8, 1)
    return top


def assess_risk(trend):
    if trend is None:
        return "UNKNOWN", "数据不足"
    d = trend["consecutive_sell_days"]
    n = trend["net_7d_billion"]
    shrink = trend["shrink_from_peak_pct"]

    if d >= 7 or n < -500 or shrink > 15:
        return "RED", f"⚠️ 高风险：连续净卖出{d}天，近7日{n}亿，余额较峰值萎缩{shrink}%"
    elif d >= 3 or n < -100 or shrink > 5:
        return "YELLOW", f"⚡ 中风险：连续净卖出{d}天，近7日{n}亿，余额较峰值萎缩{shrink}%"
    else:
        return "GREEN", f"✅ 低风险：融资盘稳定，连续净卖出{d}天"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", default=["000001.SZ", "600519.SH", "300750.SZ"],
                   help="要监控的股票列表（代理全市场时用沪深宽基成分）")
    p.add_argument("--out", default="/tmp/margin_fragility.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    print("📊 融资盘脆弱性扫描...")
    print(f"  监控标的数: {len(args.symbols)}")

    trend = analyze_margin_trend(panda_data, args.symbols)
    level, assessment = assess_risk(trend)
    top_stocks = find_high_margin_stocks(panda_data, args.symbols)

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "risk_level": level,
        "assessment": assessment,
        "trend": trend,
        "high_margin_stocks": top_stocks[:10],
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    icon = "🔴" if level == "RED" else "🟡" if level == "YELLOW" else "🟢"
    print(f"\n{icon} 融资盘风险等级：{level}")
    print(f"   {assessment}")
    if trend:
        print(f"\n   连续净卖出：{trend['consecutive_sell_days']} 天")
        print(f"   近7日净额：{trend['net_7d_billion']} 亿")
        print(f"   余额较峰值萎缩：{trend['shrink_from_peak_pct']}%")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
