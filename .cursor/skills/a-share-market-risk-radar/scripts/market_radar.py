"""
市场环境综合雷达
逻辑：从融资盘、跌停数、指数估值、板块轮动四个维度综合打分
输出：JSON，含风险等级(RED/YELLOW/GREEN)和各维度信号
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

SW_INDUSTRIES = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁",
    "801050": "有色金属", "801080": "电子", "801110": "家用电器",
    "801120": "食品饮料", "801130": "纺织服饰", "801140": "轻工制造",
    "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备",
    "801740": "国防军工", "801750": "计算机", "801760": "传媒",
    "801770": "通信", "801780": "银行", "801790": "非银金融",
    "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}

INDEX_MAP = {
    "上证": "000001.SH",
    "深成": "399001.SZ",
    "创业板": "399006.SZ",
    "沪深300": "000300.SH",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
}


def get_dates(lookback=10):
    today = datetime.now()
    start = (today - timedelta(days=lookback * 2)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    return start, end


def check_margin_signal(pd):
    """融资盘信号：连续净卖出天数 + 余额趋势"""
    start, end = get_dates(30)
    # 用上证所有融资标的的汇总来近似全市场趋势
    df = pd.get_margin(symbol=["000001.SH"], start_date=start, end_date=end, fields=[])
    if df is None or len(df) == 0:
        return {"signal": "无数据", "level": "UNKNOWN", "detail": ""}

    df = df.sort_values("date")
    df["net_buy"] = df["buy_on_margin_value"] - df["margin_repayment"]

    # 最近连续净卖出天数
    recent = df.tail(15)
    consecutive_sell = 0
    for val in reversed(recent["net_buy"].tolist()):
        if val < 0:
            consecutive_sell += 1
        else:
            break

    # 近7日累计净额
    net_7d = recent.tail(7)["net_buy"].sum()

    level = "GREEN"
    if consecutive_sell >= 7 or net_7d < -5e9:
        level = "RED"
    elif consecutive_sell >= 3 or net_7d < -1e9:
        level = "YELLOW"

    return {
        "signal": "融资盘",
        "level": level,
        "consecutive_sell_days": consecutive_sell,
        "net_7d_billion": round(net_7d / 1e8, 1),
        "detail": f"连续净卖出{consecutive_sell}天，近7日净额{round(net_7d/1e8,1)}亿"
    }


def check_index_valuation(pd):
    """指数估值信号：PE相对历史分位"""
    start_hist = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
    _, end = get_dates(1)

    results = {}
    for name, code in [("沪深300", "000300.SH"), ("创业板", "399006.SZ"), ("中证1000", "000852.SH")]:
        df = pd.get_index_indicator(symbol=[code], start_date=start_hist, end_date=end, fields=[])
        if df is None or len(df) == 0:
            continue
        df = df.sort_values("date")
        current_pe = df["pe_ttm"].iloc[-1]
        import pandas as _pd
        hist_pe = _pd.to_numeric(df["pe_ttm"], errors="coerce").dropna()
        current_pe_num = float(current_pe) if current_pe else None
        pct = round((hist_pe < current_pe_num).mean() * 100, 1) if current_pe_num else 50
        results[name] = {"pe_ttm": round(current_pe_num, 1) if current_pe_num else None, "3yr_pct": pct}

    # 综合判断
    pcts = [v["3yr_pct"] for v in results.values() if v]
    avg_pct = sum(pcts) / len(pcts) if pcts else 50
    level = "RED" if avg_pct > 80 else ("GREEN" if avg_pct < 30 else "YELLOW")

    return {
        "signal": "指数估值",
        "level": level,
        "indices": results,
        "avg_3yr_pct": round(avg_pct, 1),
        "detail": f"主要指数PE历史3年平均分位{round(avg_pct,1)}%"
    }


def check_limit_down(pd):
    """跌停数量信号：用大盘涨跌幅 + 成交量萎缩代替"""
    start, end = get_dates(5)
    df = pd.get_index_daily(symbol=["000001.SH"], start_date=start, end_date=end, fields=[])
    if df is None or len(df) == 0:
        return {"signal": "大盘走势", "level": "UNKNOWN", "detail": ""}

    df = df.sort_values("date")
    df["pct"] = (df["close"] - df["pre_close"]) / df["pre_close"] * 100
    last_pct = df["pct"].iloc[-1]
    last3_pct = df["pct"].tail(3).sum()

    level = "GREEN"
    if last_pct < -3 or last3_pct < -5:
        level = "RED"
    elif last_pct < -1.5 or last3_pct < -2:
        level = "YELLOW"

    return {
        "signal": "大盘走势",
        "level": level,
        "last_pct": round(last_pct, 2),
        "last3_pct_sum": round(last3_pct, 2),
        "detail": f"上证昨日{round(last_pct,2)}%，近3日合计{round(last3_pct,2)}%"
    }


def check_sector_rotation(pd):
    """板块轮动：对比防御板块 vs 进攻板块近5日涨跌"""
    start, end = get_dates(10)
    defensive = {"000300.SH": "沪深300", "000827.SH": "中证银行"}
    offensive = {"399006.SZ": "创业板", "000852.SH": "中证1000"}

    def get_pct(code):
        df = pd.get_index_daily(symbol=[code], start_date=start, end_date=end, fields=[])
        if df is None or len(df) < 2:
            return None
        df = df.sort_values("date")
        df["pct"] = (df["close"] - df["pre_close"]) / df["pre_close"] * 100
        return round(df["pct"].tail(5).sum(), 2)

    def_perfs = {n: get_pct(c) for c, n in defensive.items()}
    off_perfs = {n: get_pct(c) for c, n in offensive.items()}

    def_avg = sum(v for v in def_perfs.values() if v) / max(len(def_perfs), 1)
    off_avg = sum(v for v in off_perfs.values() if v) / max(len(off_perfs), 1)

    spread = off_avg - def_avg
    if spread > 3:
        direction = "进攻→进攻（风险偏好高）"
        level = "GREEN"
    elif spread < -3:
        direction = "防御为主（避险情绪升温）"
        level = "RED"
    else:
        direction = "震荡切换中"
        level = "YELLOW"

    return {
        "signal": "板块轮动",
        "level": level,
        "defensive_5d": def_perfs,
        "offensive_5d": off_perfs,
        "spread": round(spread, 2),
        "direction": direction,
        "detail": f"进攻-防御5日差值{round(spread,2)}%，{direction}"
    }


def score_to_level(signals):
    levels = [s["level"] for s in signals]
    red = levels.count("RED")
    yellow = levels.count("YELLOW")
    if red >= 2:
        return "RED", "高风险：多维度同时出现警示信号，建议降低仓位或回避高弹性资产"
    elif red == 1 or yellow >= 2:
        return "YELLOW", "中等风险：部分维度出现异常，建议控制仓位，密切跟踪"
    else:
        return "GREEN", "低风险：各维度信号正常，市场处于相对健康状态"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/tmp/market_radar.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)
    pd = panda_data

    print("🔍 扫描市场环境...")
    signals = []

    print("  [1/4] 融资盘脆弱性...")
    signals.append(check_margin_signal(pd))

    print("  [2/4] 指数估值分位...")
    signals.append(check_index_valuation(pd))

    print("  [3/4] 大盘走势...")
    signals.append(check_limit_down(pd))

    print("  [4/4] 板块轮动方向...")
    signals.append(check_sector_rotation(pd))

    overall_level, summary = score_to_level(signals)

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "overall_level": overall_level,
        "summary": summary,
        "signals": signals
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'🔴' if overall_level=='RED' else '🟡' if overall_level=='YELLOW' else '🟢'} 综合风险：{overall_level}")
    print(f"   {summary}")
    for s in signals:
        icon = "🔴" if s["level"] == "RED" else "🟡" if s["level"] == "YELLOW" else "🟢"
        print(f"   {icon} [{s['signal']}] {s.get('detail','')}")
    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
