"""
第五层：个股全维度风险扫描
覆盖：
1. 解禁压力（精准日历：IPO锁定/定增/员工持股）
2. 融资拥挤度（杠杆集中在哪）
3. 预期差风险（高PE+高预期=地雷）
4. 基本面深度（三年收入/利润/现金流/ROE）
5. 大宗交易（该股大股东出货迹象）
输出：个股综合风险评分卡
"""
import json
import os
import argparse
import pandas as pd
from datetime import datetime, timedelta
import panda_data

USERNAME = os.environ.get("PANDADATA_USERNAME")
PASSWORD = os.environ.get("PANDADATA_PASSWORD")


def get_fundamental(pd_api, symbol: str, start3yr: str, end: str) -> dict:
    """基本面深度分析：三年财务趋势"""
    result = {}

    # 财务报表（利润表+资产负债表+现金流）
    try:
        df = pd_api.get_fina_reports(symbol=[symbol], start_date=start3yr, end_date=end, fields=[])
        if df is not None and len(df) > 0:
            df = df.sort_values("date" if "date" in df.columns else df.columns[0])
            result["fina_cols"] = df.columns.tolist()
            result["fina_latest"] = df.iloc[-1].to_dict()
            result["fina_3yr"] = df.tail(12).to_dict("records")  # 季报约12期=3年
    except Exception as e:
        result["fina_error"] = str(e)

    # 业绩数据（EPS、ROE）
    try:
        df2 = pd_api.get_fina_performance(symbol=[symbol], start_date=start3yr, end_date=end, fields=[])
        if df2 is not None and len(df2) > 0:
            df2 = df2.sort_values("date" if "date" in df2.columns else df2.columns[0])
            result["perf_cols"] = df2.columns.tolist()
            result["perf_latest"] = df2.iloc[-1].to_dict()
            result["perf_trend"] = df2.tail(8).to_dict("records")
    except Exception as e:
        result["perf_error"] = str(e)

    # 经营性指标
    try:
        df3 = pd_api.get_stock_operating_indicator(symbol=[symbol], start_date=start3yr, end_date=end, fields=[])
        if df3 is not None and len(df3) > 0:
            result["operating_cols"] = df3.columns.tolist()
            result["operating_latest"] = df3.sort_values(df3.columns[0]).iloc[-1].to_dict()
    except Exception as e:
        result["operating_error"] = str(e)

    # 估值指标
    try:
        df4 = pd_api.get_stock_mktfin_indicator(symbol=[symbol], start_date=start3yr, end_date=end, fields=[])
        if df4 is not None and len(df4) > 0:
            df4 = df4.sort_values("date" if "date" in df4.columns else df4.columns[0])
            result["valuation_cols"] = df4.columns.tolist()
            latest_val = df4.iloc[-1].to_dict()
            pe = pd.to_numeric(latest_val.get("pe_ttm"), errors="coerce")
            pb = pd.to_numeric(latest_val.get("pb_lf"), errors="coerce")
            # 历史分位
            hist_pe = pd.to_numeric(df4["pe_ttm"], errors="coerce").dropna()
            pe_pct = round((hist_pe < float(pe)).mean() * 100, 1) if not pd.isna(pe) and len(hist_pe) > 10 else None
            result["valuation"] = {
                "pe_ttm": round(float(pe), 1) if not pd.isna(pe) else None,
                "pb_lf": round(float(pb), 2) if not pd.isna(pb) else None,
                "pe_3yr_pct": pe_pct,
            }
    except Exception as e:
        result["valuation_error"] = str(e)

    # 行业中位数对比
    try:
        df5 = pd_api.get_stock_industry_median(symbol=[symbol], fields=[])
        if df5 is not None and len(df5) > 0:
            result["industry_median"] = df5.to_dict("records")
    except Exception as e:
        result["industry_median_error"] = str(e)

    return result


def get_unlock_risk(pd_api, symbol: str, end: str, future: str) -> dict:
    """解禁压力分析"""
    try:
        df = pd_api.get_restricted_list(symbol=[symbol], start_date=end, end_date=future, fields=[])
        if df is None or len(df) == 0:
            return {"status": "无即将解禁", "level": "GREEN", "detail": "未来90天无解禁记录"}

        df_dict = df.to_dict("records")
        # 计算解禁风险
        total_value = sum(float(r.get("restrict_value", 0) or 0) for r in df_dict)
        level = "RED" if total_value > 5e8 else "YELLOW" if total_value > 1e8 else "GREEN"
        return {
            "level": level,
            "events": df_dict,
            "total_value_billion": round(total_value / 1e8, 2),
            "detail": f"未来90天解禁{len(df_dict)}批次，合计{round(total_value/1e8,2)}亿"
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "level": "UNKNOWN"}


def get_margin_risk(pd_api, symbol: str, start: str, end: str) -> dict:
    """融资拥挤度和连续净卖出"""
    try:
        df = pd_api.get_margin(symbol=[symbol], start_date=start, end_date=end, fields=[])
        if df is None or len(df) == 0:
            return {"status": "无融资数据", "level": "UNKNOWN"}

        df = df.drop_duplicates(subset=["date"]).sort_values("date")
        df["net"] = pd.to_numeric(df["buy_on_margin_value"], errors="coerce") - pd.to_numeric(df["margin_repayment"], errors="coerce")
        df["balance"] = pd.to_numeric(df["margin_balance"], errors="coerce")

        # 连续净卖出
        consecutive = 0
        for val in reversed(df["net"].tolist()):
            if val < 0:
                consecutive += 1
            else:
                break

        peak = df["balance"].max()
        current = df["balance"].iloc[-1]
        shrink = (peak - current) / peak * 100 if peak > 0 else 0

        level = "RED" if consecutive >= 5 or shrink > 20 else "YELLOW" if consecutive >= 3 or shrink > 10 else "GREEN"

        return {
            "level": level,
            "consecutive_sell_days": consecutive,
            "balance_billion": round(current / 1e8, 2),
            "peak_billion": round(peak / 1e8, 2),
            "shrink_pct": round(shrink, 1),
            "net_7d_billion": round(df["net"].tail(7).sum() / 1e8, 2),
            "detail": f"融资余额{round(current/1e8,2)}亿（峰值萎缩{round(shrink,1)}%），连续净卖出{consecutive}天"
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "level": "UNKNOWN"}


def get_block_trade_risk(pd_api, symbol: str, start: str, end: str) -> dict:
    """个股大宗交易（大股东出货迹象）"""
    try:
        df = pd_api.get_block_trade(symbol=[symbol], start_date=start, end_date=end, fields=[])
        if df is None or len(df) == 0:
            return {"status": "无大宗交易记录", "level": "GREEN", "detail": "近期无大宗交易"}

        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        total = df["amount"].sum()
        count = len(df)
        level = "RED" if total > 1e8 else "YELLOW" if total > 2e7 else "GREEN"

        return {
            "level": level,
            "count": count,
            "total_billion": round(total / 1e8, 2),
            "trades": df.to_dict("records"),
            "detail": f"共{count}笔大宗交易，合计{round(total/1e8,2)}亿"
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "level": "UNKNOWN"}


def score_stock(unlock, margin, block, valuation) -> tuple:
    """综合评分"""
    levels = []
    for sig in [unlock, margin, block]:
        lv = sig.get("level", "UNKNOWN")
        if lv != "UNKNOWN":
            levels.append(lv)

    # 估值加分
    pe_pct = valuation.get("pe_3yr_pct") if valuation else None
    if pe_pct and pe_pct > 85:
        levels.append("RED")
    elif pe_pct and pe_pct > 70:
        levels.append("YELLOW")

    red = levels.count("RED")
    yellow = levels.count("YELLOW")
    if red >= 2:
        return "RED", "高风险：多个维度同时亮红灯，持仓需谨慎"
    elif red == 1 or yellow >= 2:
        return "YELLOW", "中等风险：存在局部压力，密切跟踪"
    else:
        return "GREEN", "当前风险可控"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbol", help="股票代码，如 688808.SH")
    p.add_argument("--out", default="/tmp/stock_risk.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    end = datetime.now().strftime("%Y%m%d")
    start_30 = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
    start_3yr = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
    future_90 = (datetime.now() + timedelta(days=90)).strftime("%Y%m%d")

    symbol = args.symbol
    if "." not in symbol:
        if symbol.startswith(("600", "601", "603", "605", "688")):
            symbol += ".SH"
        else:
            symbol += ".SZ"

    print(f"🔬 个股全维度风险扫描：{symbol}")

    print("  [1/5] 解禁压力...")
    unlock = get_unlock_risk(panda_data, symbol, end, future_90)

    print("  [2/5] 融资拥挤度...")
    margin = get_margin_risk(panda_data, symbol, start_30, end)

    print("  [3/5] 大宗交易异动...")
    block = get_block_trade_risk(panda_data, symbol, start_30, end)

    print("  [4/5] 基本面深度...")
    funda = get_fundamental(panda_data, symbol, start_3yr, end)
    valuation = funda.get("valuation", {})

    print("  [5/5] 综合评分...")
    overall_level, summary = score_stock(unlock, margin, block, valuation)

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "layer": "L5_个股风险",
        "symbol": symbol,
        "overall_level": overall_level,
        "summary": summary,
        "unlock_risk": unlock,
        "margin_risk": margin,
        "block_trade_risk": block,
        "fundamental": funda,
        "valuation": valuation,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    icon = "🔴" if overall_level == "RED" else "🟡" if overall_level == "YELLOW" else "🟢"
    print(f"\n{icon} {symbol} 综合风险：{overall_level}")
    print(f"   {summary}")
    for name, sig in [("解禁", unlock), ("融资盘", margin), ("大宗交易", block)]:
        detail = sig.get("detail", "")
        if detail:
            lv = sig.get("level", "")
            ic = "🔴" if lv == "RED" else "🟡" if lv == "YELLOW" else "🟢"
            print(f"   {ic} [{name}] {detail}")
    if valuation:
        pe = valuation.get("pe_ttm")
        pe_pct = valuation.get("pe_3yr_pct")
        if pe:
            icon_v = "🔴" if (pe_pct or 0) > 85 else "🟡" if (pe_pct or 0) > 70 else "🟢"
            print(f"   {icon_v} [估值] PE={pe}（历史3年{pe_pct}%分位）")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
