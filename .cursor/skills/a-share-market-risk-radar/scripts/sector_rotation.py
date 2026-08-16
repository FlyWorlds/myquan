"""
板块轮动追踪
核心逻辑（机构切换方向信号）：
1. 近5/10/20日各申万一级行业涨跌幅排名
2. 从涨到跌、从跌到涨的行业（轮动拐点）
3. 防御（银行/医药/红利）vs 进攻（科技/成长）的资金倾向
4. 行业PE历史分位（高分位=拥挤，低分位=机会）
输出：板块轮动热图 + 机构可能切换方向的判断
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

SW_INDEX_MAP = {
    "电子":    "399811.SZ",   # CSSW电子
    "医药生物": "000808.SH",   # 医药生物
    "银行":    "399986.SZ",   # 中证银行
    "通信":    "399389.SZ",   # 国证通信
    "国防军工": "399368.SZ",   # 国证军工
    "有色金属": "399395.SZ",   # 国证有色
    "钢铁":    "399440.SZ",   # 国证钢铁
    "汽车":    "399432.SZ",   # 智能汽车
    "煤炭":    "399436.SZ",   # 绿色煤炭
    "食品饮料": "399396.SZ",   # 国证食品
    "房地产":  "399393.SZ",   # 国证地产
    "非银金融": "399394.SZ",   # 国证非银
    "有色金属B": "399395.SZ",  # 国证有色
    "沪深300": "000300.SH",
    "创业板":  "399006.SZ",
    "中证1000": "000852.SH",
}

# 行业分类：进攻 vs 防御
OFFENSIVE = {"电子", "计算机", "通信", "电力设备", "国防军工", "医药生物"}
DEFENSIVE = {"银行", "公用事业", "食品饮料", "煤炭", "石油石化", "交通运输"}


def get_industry_perf(pd_api, windows=[5, 10, 20]):
    """获取各行业近N日涨跌幅"""
    end = datetime.now().strftime("%Y%m%d")
    max_days = max(windows) * 2 + 5
    start = (datetime.now() - timedelta(days=max_days)).strftime("%Y%m%d")

    results = {}
    for name, code in SW_INDEX_MAP.items():
        df = pd_api.get_index_daily(symbol=[code], start_date=start, end_date=end, fields=[])
        if df is None or len(df) < 5:
            continue
        df = df.sort_values("date")
        df["pct"] = (df["close"] - df["pre_close"]) / df["pre_close"] * 100

        perfs = {}
        for w in windows:
            if len(df) >= w:
                perfs[f"pct_{w}d"] = round(df["pct"].tail(w).sum(), 2)

        # 最新PE分位（用行业指数PE接口）
        pe_df = pd_api.get_index_indicator(symbol=[code], start_date=start, end_date=end, fields=[])
        if pe_df is not None and len(pe_df) > 0:
            pe_df = pe_df.sort_values("date")
            current_pe = pe_df["pe_ttm"].iloc[-1]
            # 3年PE分位
            hist_start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
            hist_pe_df = pd_api.get_index_indicator(symbol=[code], start_date=hist_start, end_date=end, fields=[])
            if hist_pe_df is not None and len(hist_pe_df) > 50:
                hist_pe = pd.to_numeric(hist_pe_df["pe_ttm"], errors="coerce").dropna()
                current_pe = float(current_pe)
                pct = round((hist_pe < current_pe).mean() * 100, 1)
                perfs["pe_ttm"] = round(current_pe, 1)
                perfs["pe_3yr_pct"] = pct

        results[name] = perfs

    return results


def find_rotation_signals(industry_perfs):
    """识别轮动信号：短期涨幅排名 vs 中期涨幅排名的错位"""
    records = []
    for name, perfs in industry_perfs.items():
        rec = {"name": name, **perfs}
        rec["type"] = "进攻" if name in OFFENSIVE else "防御" if name in DEFENSIVE else "中性"
        records.append(rec)

    if not records:
        return [], {}

    df = pd.DataFrame(records)
    if "pct_5d" in df.columns and "pct_20d" in df.columns:
        df["rank_5d"] = df["pct_5d"].rank(ascending=False)
        df["rank_20d"] = df["pct_20d"].rank(ascending=False)
        df["rotation_signal"] = df["rank_20d"] - df["rank_5d"]  # 正值=近期补涨，负值=近期回落

    # 进攻vs防御汇总
    off_5d = df[df["type"] == "进攻"]["pct_5d"].mean() if "pct_5d" in df.columns else 0
    def_5d = df[df["type"] == "防御"]["pct_5d"].mean() if "pct_5d" in df.columns else 0
    spread = round(off_5d - def_5d, 2)

    if spread > 3:
        style = "进攻主导（科技/成长>防御），风险偏好偏高"
        style_level = "AGGRESSIVE"
    elif spread < -3:
        style = "防御主导（红利/价值>科技），避险情绪升温"
        style_level = "DEFENSIVE"
    else:
        style = "风格均衡/切换中"
        style_level = "BALANCED"

    summary = {
        "offensive_5d_avg": round(off_5d, 2),
        "defensive_5d_avg": round(def_5d, 2),
        "spread": spread,
        "market_style": style,
        "style_level": style_level,
    }

    records_out = df.to_dict("records") if len(df) > 0 else []
    return records_out, summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--windows", nargs="+", type=int, default=[5, 10, 20], help="统计窗口（交易日）")
    p.add_argument("--out", default="/tmp/sector_rotation.json")
    args = p.parse_args()

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    print(f"🔄 板块轮动分析（窗口：{args.windows}日）...")
    print(f"  扫描行业数: {len(SW_INDEX_MAP)}")

    perfs = get_industry_perf(panda_data, args.windows)
    records, summary = find_rotation_signals(perfs)

    # 按5日涨幅排序
    records_sorted = sorted(records, key=lambda x: x.get("pct_5d", 0), reverse=True)

    result = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "windows": args.windows,
        "market_style": summary,
        "top5_5d": records_sorted[:5],
        "bottom5_5d": records_sorted[-5:],
        "all_industries": records_sorted,
        "rotation_signals": [
            r for r in records_sorted
            if abs(r.get("rotation_signal", 0)) > 5
        ],
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    style = summary.get("market_style", "")
    style_level = summary.get("style_level", "")
    icon = "⚔️" if style_level == "AGGRESSIVE" else "🛡️" if style_level == "DEFENSIVE" else "⚖️"
    print(f"\n{icon} 市场风格：{style}")
    print(f"   进攻板块5日均涨幅：{summary.get('offensive_5d_avg',0)}%")
    print(f"   防御板块5日均涨幅：{summary.get('defensive_5d_avg',0)}%")
    print(f"   利差：{summary.get('spread',0)}%")

    print("\n📈 近5日领涨行业TOP5：")
    for r in records_sorted[:5]:
        pe_info = f"PE={r.get('pe_ttm','?')}（{r.get('pe_3yr_pct','?')}%分位）" if r.get("pe_ttm") else ""
        print(f"  {r['name']:8s} {r.get('pct_5d',0):+.2f}%  {pe_info}")

    print("\n📉 近5日领跌行业：")
    for r in records_sorted[-5:]:
        print(f"  {r['name']:8s} {r.get('pct_5d',0):+.2f}%")

    print(f"\n📁 已保存: {args.out}")


if __name__ == "__main__":
    main()
