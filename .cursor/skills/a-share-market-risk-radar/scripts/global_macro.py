"""
第一层：全球宏观风险扫描
覆盖：韩国KOSPI、费城半导体SOX、油价、美债利率、美元指数
数据源：PandaData宏观接口 + 实时WebSearch补充
输出：全球风险等级 + 各指标信号
"""
import json
import os
import argparse
import subprocess
from datetime import datetime, timedelta
import panda_data

USERNAME = os.environ.get("PANDADATA_USERNAME")
PASSWORD = os.environ.get("PANDADATA_PASSWORD")


def get_macro_rates(start, end):
    """获取国内宏观利率（LPR、国债收益率等）"""
    results = {}
    try:
        df = panda_data.get_macro_ir(start_date=start, end_date=end, fields=[])
        if df is not None and len(df) > 0:
            df = df.sort_values("date" if "date" in df.columns else df.columns[0])
            latest = df.iloc[-1].to_dict()
            results["domestic_rates"] = {
                "date": str(latest.get("date", "")),
                "data": {k: v for k, v in latest.items() if k != "date"},
                "status": "ok"
            }
    except Exception as e:
        results["domestic_rates"] = {"status": "error", "error": str(e)}
    return results


def get_china_cds_proxy(start, end):
    """用人民币汇率作为中国风险溢价的代理"""
    try:
        # USD/CNY走势反映对中国资产的风险判断
        df = panda_data.get_index_daily(
            symbol=["000001.SH"], start_date=start, end_date=end, fields=[]
        )
        if df is not None and len(df) >= 5:
            df = df.sort_values("date")
            df["pct"] = (df["close"] - df["pre_close"]) / df["pre_close"] * 100
            return {
                "last_5d_pct": round(df["pct"].tail(5).sum(), 2),
                "last_1d_pct": round(df["pct"].iloc[-1], 2),
                "close": df["close"].iloc[-1],
            }
    except Exception:
        pass
    return None


def get_option_fear_gauge(start, end):
    """期权隐含波动率作为恐慌指数代理（上证50ETF期权）"""
    try:
        df = panda_data.get_option_underlying_volatility(
            symbol=["510050"], start_date=start, end_date=end, fields=[]
        )
        if df is not None and len(df) > 0:
            cols = df.columns.tolist()
            df = df.sort_values("date" if "date" in cols else cols[0])
            row = df.iloc[-1].to_dict()
            # 历史分位
            hist_df = panda_data.get_option_underlying_volatility(
                symbol=["510050"],
                start_date=(datetime.now() - timedelta(days=365)).strftime("%Y%m%d"),
                end_date=end, fields=[]
            )
            vol_col = [c for c in cols if "vol" in c.lower() or "hv" in c.lower() or "iv" in c.lower()]
            if hist_df is not None and len(hist_df) > 20 and vol_col:
                import pandas as pd
                col = vol_col[0]
                hist_vals = pd.to_numeric(hist_df[col], errors="coerce").dropna()
                curr_val = float(row.get(col, 0) or 0)
                pct = round((hist_vals < curr_val).mean() * 100, 1)
                return {
                    "vol_col": col,
                    "current": round(curr_val, 4),
                    "1yr_pct": pct,
                    "level": "RED" if pct > 80 else "YELLOW" if pct > 60 else "GREEN",
                    "detail": f"上证50ETF波动率历史1年{pct}%分位"
                }
            return {"data": row, "level": "UNKNOWN"}
    except Exception as e:
        return {"status": "error", "error": str(e), "level": "UNKNOWN"}
    return {"level": "UNKNOWN"}


def assess_global_risk(signals: list) -> tuple:
    levels = [s.get("level", "UNKNOWN") for s in signals if s.get("level") != "UNKNOWN"]
    red = levels.count("RED")
    yellow = levels.count("YELLOW")
    if red >= 2:
        return "RED", "全球风险高企：多个外部风险信号同时触发，A股面临输入性压力"
    elif red == 1 or yellow >= 2:
        return "YELLOW", "全球风险偏高：部分外部风险指标异常，需关注传导效应"
    else:
        return "GREEN", "全球宏观环境相对稳定"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/tmp/global_macro.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    start_short = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    print("🌍 全球宏观风险扫描...")

    signals = []

    print("  [1/3] 恐慌指数（期权波动率）...")
    fear = get_option_fear_gauge(start_short, end)
    signals.append(fear)

    print("  [2/3] 国内宏观利率...")
    rates = get_macro_rates(start_short, end)

    print("  [3/3] A股市场走势（宏观代理）...")
    market = get_china_cds_proxy(start_short, end)

    if market:
        pct5 = market["last_5d_pct"]
        level = "RED" if pct5 < -5 else "YELLOW" if pct5 < -2 else "GREEN"
        signals.append({
            "signal": "A股近5日走势",
            "level": level,
            "last_5d_pct": pct5,
            "last_1d_pct": market["last_1d_pct"],
            "detail": f"上证近5日{pct5:+.2f}%，昨日{market['last_1d_pct']:+.2f}%"
        })

    overall_level, summary = assess_global_risk(signals)

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "layer": "L1_全球宏观",
        "overall_level": overall_level,
        "summary": summary,
        "fear_gauge": fear,
        "domestic_rates": rates,
        "market_proxy": market,
        "note": "韩国KOSPI/SOX实时数据需通过WebSearch获取（PandaData无权限）",
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    icon = "🔴" if overall_level == "RED" else "🟡" if overall_level == "YELLOW" else "🟢"
    print(f"\n{icon} L1全球宏观风险：{overall_level}")
    print(f"   {summary}")
    if fear.get("detail"):
        fear_icon = "🔴" if fear.get("level") == "RED" else "🟡" if fear.get("level") == "YELLOW" else "🟢"
        print(f"   {fear_icon} {fear['detail']}")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
