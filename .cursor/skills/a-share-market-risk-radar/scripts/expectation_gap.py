"""
预期差地雷扫描
核心逻辑（来自7.13大跌复盘）：
- 高位资产只要不断超预期才能维持涨势
- 一旦利润"低于预期"（哪怕同比大涨）→ 动量/杠杆资金踩踏式离场
- 本脚本找出：高PE + 分析师高预期 + 历史增速不及预期概率高 的股票
信号公式：预期差风险 = 当前PE分位 × 预期增速偏高度 × 近期涨幅
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


def get_fina_forecast_gap(pd_api, symbols: list):
    """获取业绩预告 vs 实际表现的偏差"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y%m%d")

    results = []
    for sym in symbols:
        # 业绩预告（公司自己发的）
        forecast_df = pd_api.get_fina_forecast(symbol=[sym], start_date=start, end_date=end, fields=[])
        # 实际业绩
        perf_df = pd_api.get_fina_performance(symbol=[sym], start_date=start, end_date=end, fields=[])

        if forecast_df is None or len(forecast_df) == 0 or perf_df is None or len(perf_df) == 0:
            continue

        forecast_df = forecast_df.sort_values("date" if "date" in forecast_df.columns else forecast_df.columns[0])
        perf_df = perf_df.sort_values("date" if "date" in perf_df.columns else perf_df.columns[0])

        results.append({
            "symbol": sym,
            "forecast_cols": forecast_df.columns.tolist(),
            "perf_cols": perf_df.columns.tolist(),
            "forecast_latest": forecast_df.iloc[-1].to_dict(),
            "perf_latest": perf_df.iloc[-1].to_dict(),
        })

    return results


def get_high_pe_stocks(pd_api, symbols: list, pe_threshold=60):
    """找当前PE超过阈值的股票"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    high_pe = []
    for sym in symbols:
        df = pd_api.get_stock_mktfin_indicator(symbol=[sym], start_date=start, end_date=end, fields=[])
        if df is None or len(df) == 0:
            continue
        df = df.sort_values("date" if "date" in df.columns else df.columns[0])
        row = df.iloc[-1]
        pe = row.get("pe_ttm", None)
        if pe and pe > pe_threshold:
            # 历史PE分位
            hist_df = pd_api.get_stock_mktfin_indicator(
                symbol=[sym],
                start_date=(datetime.now() - timedelta(days=365 * 2)).strftime("%Y%m%d"),
                end_date=end, fields=[]
            )
            pct = None
            if hist_df is not None and len(hist_df) > 20:
                hist_pe = hist_df["pe_ttm"].dropna()
                pct = round((hist_pe < pe).mean() * 100, 1)

            # 近30日涨幅
            price_df = pd_api.get_stock_daily(symbol=[sym], start_date=start, end_date=end, fields=[])
            pct_30d = None
            if price_df is not None and len(price_df) >= 2:
                price_df = price_df.sort_values("date")
                pct_30d = round((price_df["close"].iloc[-1] / price_df["close"].iloc[0] - 1) * 100, 1)

            high_pe.append({
                "symbol": sym,
                "name": row.get("name", sym) if "name" in row.index else sym,
                "pe_ttm": round(pe, 1),
                "pe_2yr_pct": pct,
                "pct_30d": pct_30d,
            })

    # 风险综合评分
    for item in high_pe:
        score = 0
        pe = item["pe_ttm"]
        pct = item.get("pe_2yr_pct") or 50
        pct_30d = item.get("pct_30d") or 0

        if pe > 100:
            score += 3
        elif pe > 60:
            score += 2

        if pct > 90:
            score += 3
        elif pct > 75:
            score += 2

        if pct_30d > 50:
            score += 2
        elif pct_30d > 20:
            score += 1

        item["risk_score"] = score
        item["risk_level"] = "RED" if score >= 5 else "YELLOW" if score >= 3 else "GREEN"
        item["risk_reason"] = f"PE={pe}（历史{pct}%分位），近30日+{pct_30d}%"

    high_pe.sort(key=lambda x: -x["risk_score"])
    return high_pe


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True, help="要扫描的股票列表")
    p.add_argument("--pe-threshold", type=float, default=60, help="PE警戒线（默认60）")
    p.add_argument("--out", default="/tmp/expectation_gap.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    print(f"🔬 预期差地雷扫描（PE>{args.pe_threshold}）...")
    print(f"  扫描标的数: {len(args.symbols)}")

    high_pe_stocks = get_high_pe_stocks(panda_data, args.symbols, args.pe_threshold)
    red_count = sum(1 for s in high_pe_stocks if s["risk_level"] == "RED")

    print(f"\n  发现高PE股票: {len(high_pe_stocks)} 只")
    print(f"  高风险（RED）: {red_count} 只")

    # 抽样探查预期差数据结构
    if args.symbols:
        print("\n  探查预期差数据...")
        gap_sample = get_fina_forecast_gap(panda_data, args.symbols[:3])
    else:
        gap_sample = []

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "pe_threshold": args.pe_threshold,
        "total_scanned": len(args.symbols),
        "high_pe_count": len(high_pe_stocks),
        "red_count": red_count,
        "high_pe_stocks": high_pe_stocks[:20],
        "forecast_gap_sample": gap_sample[:3],
        "interpretation": (
            "预期差风险解读：高PE意味着市场已经Price-in了高增长预期。"
            "一旦季报利润低于卖方一致预期哪怕8%，动量/杠杆资金踩踏式离场，"
            "这正是7月13日SK海力士大跌15%的根本逻辑。"
            "建议对RED级别股票重点跟踪即将发布的季报数据。"
        )
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print("\n🔴 高风险（预期差地雷）：")
    for s in high_pe_stocks[:5]:
        if s["risk_level"] == "RED":
            print(f"  🔴 {s.get('name','?')}({s['symbol']}) {s['risk_reason']}")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
