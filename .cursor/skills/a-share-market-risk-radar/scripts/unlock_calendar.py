"""
解禁压力日历
逻辑：
1. 扫描未来30日内有大额解禁的股票
2. 叠加当前估值（高PE+大解禁=双杀风险）
3. 叠加近期涨幅（高位+大解禁=减持冲动强）
输出：危险等级排序的解禁日历
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


def get_upcoming_unlocks(pd_api, symbols: list, days_ahead=30):
    """获取未来N天解禁数据"""
    today = datetime.now().strftime("%Y%m%d")
    future = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y%m%d")

    if symbols:
        df = pd_api.get_restricted_list(symbol=symbols, start_date=today, end_date=future, fields=[])
    else:
        df = pd_api.get_restricted_list(start_date=today, end_date=future, fields=[])

    if df is None or len(df) == 0:
        return pd.DataFrame()
    return df


def get_current_valuation(pd_api, symbols: list):
    """获取当前PE和近期涨幅"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    val_data = {}
    for sym in symbols:
        df = pd_api.get_stock_mktfin_indicator(symbol=[sym], start_date=start, end_date=end, fields=[])
        if df is not None and len(df) > 0:
            df = df.sort_values("date")
            latest = df.iloc[-1]
            pe = latest.get("pe_ttm", None)
            val_data[sym] = {"pe_ttm": round(pe, 1) if pe else None}

        # 近30日涨幅
        price_df = pd_api.get_stock_daily(symbol=[sym], start_date=start, end_date=end, fields=[])
        if price_df is not None and len(price_df) >= 20:
            price_df = price_df.sort_values("date")
            pct_30d = (price_df["close"].iloc[-1] / price_df["close"].iloc[-20] - 1) * 100
            if sym not in val_data:
                val_data[sym] = {}
            val_data[sym]["pct_30d"] = round(pct_30d, 1)

    return val_data


def assess_unlock_risk(row, val_info):
    """单条解禁风险评分"""
    risk_score = 0
    reasons = []

    # 解禁规模（相对流通股比例）
    unlock_ratio = row.get("restrict_ratio", 0) or 0
    if unlock_ratio > 20:
        risk_score += 3
        reasons.append(f"解禁比例{unlock_ratio}%（极大）")
    elif unlock_ratio > 10:
        risk_score += 2
        reasons.append(f"解禁比例{unlock_ratio}%（较大）")
    elif unlock_ratio > 5:
        risk_score += 1
        reasons.append(f"解禁比例{unlock_ratio}%")

    # 当前估值
    pe = val_info.get("pe_ttm")
    if pe and pe > 80:
        risk_score += 2
        reasons.append(f"PE={pe}（高估值）")
    elif pe and pe > 50:
        risk_score += 1
        reasons.append(f"PE={pe}（较高）")

    # 近期涨幅
    pct_30d = val_info.get("pct_30d", 0) or 0
    if pct_30d > 50:
        risk_score += 2
        reasons.append(f"近30日+{pct_30d}%（高位）")
    elif pct_30d > 20:
        risk_score += 1
        reasons.append(f"近30日+{pct_30d}%")

    level = "RED" if risk_score >= 4 else "YELLOW" if risk_score >= 2 else "GREEN"
    return level, risk_score, "，".join(reasons) if reasons else "风险较低"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="*", default=[], help="关注的股票列表（空则扫全市场）")
    p.add_argument("--days", type=int, default=30, help="向前看多少天（默认30）")
    p.add_argument("--out", default="/tmp/unlock_calendar.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    print(f"📅 解禁压力扫描（未来{args.days}天）...")

    unlock_df = get_upcoming_unlocks(panda_data, args.symbols, args.days)

    if len(unlock_df) == 0:
        print("  未发现即将解禁数据（可能接口需要symbol参数或当前无数据）")
        result = {"scan_date": datetime.now().strftime("%Y-%m-%d"), "events": [], "note": "无解禁数据"}
        with open(args.out, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return

    print(f"  发现 {len(unlock_df)} 条解禁记录")
    print(f"  字段: {unlock_df.columns.tolist()}")

    # 获取这些股票的估值
    syms = unlock_df["symbol"].unique().tolist() if "symbol" in unlock_df.columns else []
    val_map = get_current_valuation(panda_data, syms) if syms else {}

    # 评估每条解禁
    events = []
    for _, row in unlock_df.iterrows():
        sym = row.get("symbol", "")
        val_info = val_map.get(sym, {})
        level, score, reason = assess_unlock_risk(row, val_info)
        events.append({
            "symbol": sym,
            "name": row.get("name", ""),
            "unlock_date": str(row.get("list_date", row.get("date", ""))),
            "unlock_ratio": row.get("restrict_ratio", None),
            "unlock_amount_billion": round(row.get("restrict_value", 0) / 1e8, 1) if row.get("restrict_value") else None,
            "pe_ttm": val_info.get("pe_ttm"),
            "pct_30d": val_info.get("pct_30d"),
            "risk_level": level,
            "risk_score": score,
            "risk_reason": reason,
        })

    events.sort(key=lambda x: (-x["risk_score"], x["unlock_date"]))

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "days_ahead": args.days,
        "total_events": len(events),
        "red_count": sum(1 for e in events if e["risk_level"] == "RED"),
        "events": events[:30],
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n🔴 高风险解禁: {result['red_count']} 只")
    for e in events[:5]:
        icon = "🔴" if e["risk_level"] == "RED" else "🟡" if e["risk_level"] == "YELLOW" else "🟢"
        print(f"  {icon} {e.get('name','?')}({e['symbol']}) {e['unlock_date']} - {e['risk_reason']}")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
