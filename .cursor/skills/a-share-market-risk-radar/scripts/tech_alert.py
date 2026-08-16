"""
第六层：技术面预警系统
覆盖：
1. 均线系统（MA5/10/20/60/120 排列与破位）
2. MACD（金叉/死叉/顶底背离/绿柱加速）
3. RSI（超买/超卖/历史分位）
4. KDJ（超买/超卖/交叉）
5. 布林带（突破上下轨/%B极值）
6. 量价结构（放量大跌/缩量上涨/量价背离）
7. 综合预警评分

使用方式：
  python3.11 tech_alert.py 603986.SH
  python3.11 tech_alert.py 603986.SH 688256.SH 002230.SZ
  python3.11 tech_alert.py --watchlist watchlist.txt
"""

import json
import os
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import panda_data

USERNAME = os.environ.get("PANDADATA_USERNAME")
PASSWORD = os.environ.get("PANDADATA_PASSWORD")


# ─────────────────────────────────────────────
# 指标计算
# ─────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]

    # 均线
    for n in [5, 10, 20, 30, 60, 120]:
        df[f"ma{n}"] = c.rolling(n).mean()

    # MACD(12,26,9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = (df["dif"] - df["dea"]) * 2

    # RSI
    def _rsi(s, n):
        d = s.diff()
        g = d.clip(lower=0).rolling(n).mean()
        l = (-d.clip(upper=0)).rolling(n).mean()
        rs = g / l.replace(0, np.nan)
        return 100 - 100 / (1 + rs)
    df["rsi6"] = _rsi(c, 6)
    df["rsi14"] = _rsi(c, 14)

    # KDJ(9,3,3)
    lo9 = df["low"].rolling(9).min()
    hi9 = df["high"].rolling(9).max()
    df["rsv"] = (c - lo9) / (hi9 - lo9 + 1e-9) * 100
    df["K"] = df["rsv"].ewm(com=2, adjust=False).mean()
    df["D"] = df["K"].ewm(com=2, adjust=False).mean()
    df["J"] = 3 * df["K"] - 2 * df["D"]

    # 布林带(20,2)
    df["bb_mid"] = c.rolling(20).mean()
    df["bb_std"] = c.rolling(20).std()
    df["bb_up"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lo"] = df["bb_mid"] - 2 * df["bb_std"]
    df["bb_pct"] = (c - df["bb_lo"]) / (df["bb_up"] - df["bb_lo"] + 1e-9) * 100
    df["bb_width"] = (df["bb_up"] - df["bb_lo"]) / df["bb_mid"] * 100

    # 成交量
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, np.nan)

    # 日涨跌幅
    df["pct"] = (c - df["pre_close"]) / df["pre_close"].replace(0, np.nan) * 100

    # ATR14
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["pre_close"]).abs(),
        (df["low"] - df["pre_close"]).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = df["tr"].rolling(14).mean()

    return df


# ─────────────────────────────────────────────
# 预警规则
# ─────────────────────────────────────────────

def check_alerts(df: pd.DataFrame, symbol: str) -> dict:
    if len(df) < 30:
        return {"symbol": symbol, "overall": "UNKNOWN", "alerts": [], "error": "数据不足30日"}

    r = df.iloc[-1]    # 最新
    p = df.iloc[-2]    # 前一日
    p2 = df.iloc[-3]   # 前两日

    alerts = []

    # ── 1. 均线系统 ──
    close = r["close"]

    # 跌破MA60（长期趋势破位）
    ma60 = r["ma60"]
    if not pd.isna(ma60):
        if close < ma60 and p["close"] >= p["ma60"]:
            alerts.append({"cat": "均线", "level": "RED", "name": "跌破MA60",
                           "detail": f"今日首次跌破MA60({ma60:.1f})，长期趋势破位"})
        elif close < ma60:
            deviation = (close - ma60) / ma60 * 100
            alerts.append({"cat": "均线", "level": "RED", "name": "MA60下方",
                           "detail": f"价格在MA60下方，偏离{deviation:.1f}%"})

    # 跌破MA20
    ma20 = r["ma20"]
    if not pd.isna(ma20) and close < ma20:
        if p["close"] >= p["ma20"]:
            alerts.append({"cat": "均线", "level": "RED", "name": "跌破MA20",
                           "detail": f"今日首次跌破MA20({ma20:.1f})，中期趋势破位"})
        else:
            alerts.append({"cat": "均线", "level": "YELLOW", "name": "MA20下方",
                           "detail": f"持续运行于MA20({ma20:.1f})下方"})

    # 空头排列（MA5 < MA10 < MA20）
    ma5, ma10 = r["ma5"], r["ma10"]
    if not any(pd.isna(x) for x in [ma5, ma10, ma20]):
        if ma5 < ma10 < ma20:
            alerts.append({"cat": "均线", "level": "YELLOW", "name": "空头排列",
                           "detail": f"MA5({ma5:.1f}) < MA10({ma10:.1f}) < MA20({ma20:.1f})，短中期均线空头排列"})
        elif ma5 > ma10 > ma20:
            alerts.append({"cat": "均线", "level": "GREEN", "name": "多头排列",
                           "detail": f"MA5({ma5:.1f}) > MA10({ma10:.1f}) > MA20({ma20:.1f})，均线多头排列"})

    # ── 2. MACD ──
    dif, dea, bar = r["dif"], r["dea"], r["macd"]
    pdif, pdea = p["dif"], p["dea"]

    # 死叉（今日触发）
    if dif < dea and pdif >= pdea:
        alerts.append({"cat": "MACD", "level": "RED", "name": "MACD死叉",
                       "detail": f"今日DIF({dif:.2f})下穿DEA({dea:.2f})，死叉触发"})
    # 金叉（今日触发）
    elif dif > dea and pdif <= pdea:
        alerts.append({"cat": "MACD", "level": "GREEN", "name": "MACD金叉",
                       "detail": f"今日DIF({dif:.2f})上穿DEA({dea:.2f})，金叉触发"})
    # 绿柱持续扩大（连续3天）
    elif dif < dea:
        bars_recent = df["macd"].tail(4).tolist()
        if len(bars_recent) == 4 and all(b < 0 for b in bars_recent):
            if bars_recent[-1] < bars_recent[-2] < bars_recent[-3]:
                alerts.append({"cat": "MACD", "level": "RED", "name": "绿柱加速扩大",
                               "detail": f"MACD绿柱连续3日扩大（{bars_recent[-3]:.1f}→{bars_recent[-2]:.1f}→{bars_recent[-1]:.1f}），下跌加速"})
            else:
                alerts.append({"cat": "MACD", "level": "YELLOW", "name": "MACD空头区间",
                               "detail": f"DIF({dif:.2f}) < DEA({dea:.2f})，处于空头区间"})

    # 顶背离检测（价格创新高但MACD柱减弱）
    if len(df) >= 40:
        recent40 = df.tail(40)
        peak_idx = recent40["close"].idxmax()
        peak_pos = list(recent40.index).index(peak_idx)
        if 5 < peak_pos < 35:  # 高点不在最边缘
            pre_peak = recent40.iloc[:peak_pos]
            if len(pre_peak) > 5:
                pre_peak_idx = pre_peak["close"].idxmax()
                pre_peak_pos = list(recent40.index).index(pre_peak_idx)
                # 价格：新高 > 前高
                # MACD BAR：新高时 < 前高时
                if (recent40.loc[peak_idx, "close"] > recent40.loc[pre_peak_idx, "close"] and
                        recent40.loc[peak_idx, "macd"] < recent40.loc[pre_peak_idx, "macd"]):
                    alerts.append({"cat": "MACD", "level": "RED", "name": "MACD顶背离",
                                   "detail": f"价格在{recent40.loc[peak_idx,'date']}创新高({recent40.loc[peak_idx,'close']:.1f})，但MACD柱较前高减弱，顶背离信号"})

    # 底背离检测（价格创新低但MACD柱收窄）
    if len(df) >= 40:
        recent40 = df.tail(40)
        trough_idx = recent40["close"].idxmin()
        trough_pos = list(recent40.index).index(trough_idx)
        if 5 < trough_pos < 35:
            pre_trough = recent40.iloc[:trough_pos]
            if len(pre_trough) > 5:
                pre_trough_idx = pre_trough["close"].idxmin()
                if (recent40.loc[trough_idx, "close"] < recent40.loc[pre_trough_idx, "close"] and
                        recent40.loc[trough_idx, "macd"] > recent40.loc[pre_trough_idx, "macd"]):
                    alerts.append({"cat": "MACD", "level": "GREEN", "name": "MACD底背离",
                                   "detail": f"价格创新低但MACD绿柱收窄，底背离信号，可能企稳"})

    # ── 3. RSI ──
    rsi6 = r["rsi6"]
    rsi14 = r["rsi14"]

    # 历史分位
    hist_rsi14 = df["rsi14"].dropna()
    rsi14_pct = round((hist_rsi14 < rsi14).mean() * 100, 0) if len(hist_rsi14) > 20 else None

    if not pd.isna(rsi6):
        if rsi6 < 15:
            alerts.append({"cat": "RSI", "level": "RED", "name": "RSI极度超卖",
                           "detail": f"RSI6={rsi6:.1f}，极度超卖（<15），短期强反弹概率高"})
        elif rsi6 < 25:
            alerts.append({"cat": "RSI", "level": "YELLOW", "name": "RSI超卖",
                           "detail": f"RSI6={rsi6:.1f}，进入超卖区间，留意短期反弹"})
        elif rsi6 > 85:
            alerts.append({"cat": "RSI", "level": "RED", "name": "RSI极度超买",
                           "detail": f"RSI6={rsi6:.1f}，极度超买（>85），注意顶部风险"})
        elif rsi6 > 75:
            alerts.append({"cat": "RSI", "level": "YELLOW", "name": "RSI超买",
                           "detail": f"RSI6={rsi6:.1f}，进入超买区间，注意获利了结"})

    if rsi14_pct is not None:
        if rsi14_pct < 10:
            alerts.append({"cat": "RSI", "level": "YELLOW", "name": "RSI历史低位",
                           "detail": f"RSI14历史分位{rsi14_pct:.0f}%，近1年罕见低位"})
        elif rsi14_pct > 90:
            alerts.append({"cat": "RSI", "level": "YELLOW", "name": "RSI历史高位",
                           "detail": f"RSI14历史分位{rsi14_pct:.0f}%，近1年罕见高位"})

    # ── 4. KDJ ──
    K, D, J = r["K"], r["D"], r["J"]
    pK, pD = p["K"], p["D"]

    if not any(pd.isna(x) for x in [K, D, J]):
        if J < 0:
            alerts.append({"cat": "KDJ", "level": "YELLOW", "name": "KDJ超卖",
                           "detail": f"J={J:.1f}<0，进入超卖区间"})
        elif J > 100:
            alerts.append({"cat": "KDJ", "level": "YELLOW", "name": "KDJ超买",
                           "detail": f"J={J:.1f}>100，进入超买区间"})

        # 今日死叉/金叉
        if K < D and pK >= pD:
            alerts.append({"cat": "KDJ", "level": "RED", "name": "KDJ死叉",
                           "detail": f"今日K({K:.1f})下穿D({D:.1f})，KDJ死叉"})
        elif K > D and pK <= pD:
            alerts.append({"cat": "KDJ", "level": "GREEN", "name": "KDJ金叉",
                           "detail": f"今日K({K:.1f})上穿D({D:.1f})，KDJ金叉"})

    # ── 5. 布林带 ──
    bb_pct = r["bb_pct"]
    bb_up = r["bb_up"]
    bb_lo = r["bb_lo"]
    bb_width = r["bb_width"]

    if not pd.isna(bb_pct):
        if bb_pct < 5:
            alerts.append({"cat": "布林带", "level": "RED", "name": "跌破布林下轨",
                           "detail": f"%B={bb_pct:.1f}%，价格({close:.1f})触及/突破布林下轨({bb_lo:.1f})"})
        elif bb_pct < 20:
            alerts.append({"cat": "布林带", "level": "YELLOW", "name": "布林带下区间",
                           "detail": f"%B={bb_pct:.1f}%，价格处于布林带下沿（技术超卖）"})
        elif bb_pct > 95:
            alerts.append({"cat": "布林带", "level": "RED", "name": "突破布林上轨",
                           "detail": f"%B={bb_pct:.1f}%，价格({close:.1f})突破布林上轨({bb_up:.1f})，注意回调"})
        elif bb_pct > 80:
            alerts.append({"cat": "布林带", "level": "YELLOW", "name": "布林带上区间",
                           "detail": f"%B={bb_pct:.1f}%，价格处于布林带上沿"})

    # 布林带收窄（即将变盘）
    if not pd.isna(bb_width):
        hist_width = df["bb_width"].dropna()
        if len(hist_width) > 20:
            width_pct = (hist_width < bb_width).mean() * 100
            if width_pct < 20:
                alerts.append({"cat": "布林带", "level": "YELLOW", "name": "布林带收窄",
                               "detail": f"带宽处于历史{width_pct:.0f}%低位，行情即将突破变盘"})

    # ── 6. 量价结构 ──
    pct_today = r["pct"]
    vol_ratio = r["vol_ratio"]

    # 跌停
    if not pd.isna(pct_today) and pct_today <= -9.9:
        alerts.append({"cat": "量价", "level": "RED", "name": "跌停板",
                       "detail": f"今日跌停-10%，成交量{r['volume']/1e6:.1f}百万股"})
    # 涨停
    elif not pd.isna(pct_today) and pct_today >= 9.9:
        alerts.append({"cat": "量价", "level": "YELLOW", "name": "涨停板",
                       "detail": f"今日涨停+10%，注意次日高开低走风险"})

    # 放量大跌（量比>1.5 + 跌幅>5%）
    if not pd.isna(vol_ratio) and not pd.isna(pct_today):
        if vol_ratio > 1.5 and pct_today < -5:
            alerts.append({"cat": "量价", "level": "RED", "name": "放量大跌",
                           "detail": f"量比{vol_ratio:.2f}x，跌幅{pct_today:.1f}%，主力加速出逃"})
        elif vol_ratio < 0.5 and pct_today > 3:
            alerts.append({"cat": "量价", "level": "YELLOW", "name": "缩量上涨",
                           "detail": f"量比{vol_ratio:.2f}x，涨幅{pct_today:.1f}%，缩量反弹可信度低"})

    # 量价背离：涨停但MACD绿柱（游资骗线）
    if not pd.isna(pct_today) and pct_today >= 9.9 and not pd.isna(bar) and bar < -10:
        alerts.append({"cat": "量价", "level": "RED", "name": "涨停量价背离",
                       "detail": f"涨停但MACD绿柱({bar:.1f})，上涨不可持续，警惕次日反转"})

    # 连续下跌天数
    recent_pcts = df["pct"].tail(5).tolist()
    consec_down = 0
    for v in reversed(recent_pcts):
        if not pd.isna(v) and v < 0:
            consec_down += 1
        else:
            break
    if consec_down >= 4:
        alerts.append({"cat": "量价", "level": "RED", "name": "连续下跌",
                       "detail": f"已连续{consec_down}日收跌，趋势性下跌信号"})
    elif consec_down >= 3:
        alerts.append({"cat": "量价", "level": "YELLOW", "name": "连续下跌",
                       "detail": f"已连续{consec_down}日收跌，注意趋势"})

    # ── 综合评分 ──
    red_cnt = sum(1 for a in alerts if a["level"] == "RED")
    yellow_cnt = sum(1 for a in alerts if a["level"] == "YELLOW")
    green_cnt = sum(1 for a in alerts if a["level"] == "GREEN")

    if red_cnt >= 3:
        overall = "RED"
        summary = f"技术面高风险：{red_cnt}项红色预警，趋势向下，建议规避"
    elif red_cnt >= 1 or yellow_cnt >= 3:
        overall = "YELLOW"
        summary = f"技术面偏弱：{red_cnt}红{yellow_cnt}黄，短期承压"
    elif green_cnt >= 2 and red_cnt == 0:
        overall = "GREEN"
        summary = f"技术面向好：{green_cnt}项绿色信号，可以关注"
    else:
        overall = "YELLOW"
        summary = f"技术面中性：{green_cnt}绿{yellow_cnt}黄{red_cnt}红，观望为主"

    # 关键支撑/压力位（MA60 + 斐波）
    all_closes = df["close"].dropna()
    period_low = all_closes.min()
    period_high = all_closes.max()
    fib_50 = period_high - (period_high - period_low) * 0.5
    fib_618 = period_high - (period_high - period_low) * 0.618

    supports = []
    ma60_val = r["ma60"]
    if not pd.isna(ma60_val) and ma60_val < close:
        supports.append({"label": "MA60", "price": round(ma60_val, 2)})
    supports.append({"label": "斐波50%", "price": round(fib_50, 2)})
    supports.append({"label": "斐波61.8%", "price": round(fib_618, 2)})
    if not pd.isna(bb_lo):
        supports.append({"label": "布林下轨", "price": round(bb_lo, 2)})

    resistances = []
    for ma_n in [5, 10, 20, 30]:
        ma_val = r[f"ma{ma_n}"]
        if not pd.isna(ma_val) and ma_val > close:
            resistances.append({"label": f"MA{ma_n}", "price": round(ma_val, 2)})

    return {
        "symbol": symbol,
        "date": str(r["date"]),
        "close": round(close, 2),
        "pct_today": round(pct_today, 2) if not pd.isna(pct_today) else None,
        "overall": overall,
        "summary": summary,
        "alert_count": {"red": red_cnt, "yellow": yellow_cnt, "green": green_cnt},
        "alerts": alerts,
        "key_indicators": {
            "ma60": round(float(ma60_val), 2) if not pd.isna(ma60_val) else None,
            "macd_bar": round(float(bar), 2) if not pd.isna(bar) else None,
            "rsi6": round(float(rsi6), 1) if not pd.isna(rsi6) else None,
            "rsi14": round(float(rsi14), 1) if not pd.isna(rsi14) else None,
            "kdj_j": round(float(J), 1) if not pd.isna(J) else None,
            "bb_pct": round(float(bb_pct), 1) if not pd.isna(bb_pct) else None,
            "vol_ratio": round(float(vol_ratio), 2) if not pd.isna(vol_ratio) else None,
            "atr14_pct": round(float(r["atr14"] / close * 100), 1) if not pd.isna(r["atr14"]) else None,
        },
        "supports": sorted(supports, key=lambda x: x["price"], reverse=True),
        "resistances": sorted(resistances, key=lambda x: x["price"]),
    }


# ─────────────────────────────────────────────
# 数据拉取
# ─────────────────────────────────────────────

def fetch_daily(symbol: str, days: int = 250) -> pd.DataFrame:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 60)).strftime("%Y%m%d")
    df = panda_data.get_stock_daily(
        symbol=[symbol], start_date=start, end_date=end, fields=[]
    )
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume", "amount", "pre_close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "pre_close"]).reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# 输出打印
# ─────────────────────────────────────────────

ICON = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢", "UNKNOWN": "⚪"}


def print_single_report(result: dict):
    overall = result["overall"]
    icon = ICON.get(overall, "⚪")
    print(f"\n{'─'*55}")
    pct_str = f"{result['pct_today']:+.2f}%" if result.get("pct_today") else ""
    print(f"{icon} {result['symbol']}  {result['close']:.2f}  {pct_str}  →  {overall}")
    print(f"   {result['summary']}")

    # 关键指标一行
    ind = result.get("key_indicators", {})
    parts = []
    if ind.get("rsi6") is not None:
        parts.append(f"RSI6={ind['rsi6']:.0f}")
    if ind.get("kdj_j") is not None:
        parts.append(f"J={ind['kdj_j']:.0f}")
    if ind.get("macd_bar") is not None:
        parts.append(f"MACD={ind['macd_bar']:+.0f}")
    if ind.get("bb_pct") is not None:
        parts.append(f"%B={ind['bb_pct']:.0f}%")
    if ind.get("vol_ratio") is not None:
        parts.append(f"量比={ind['vol_ratio']:.1f}x")
    if parts:
        print(f"   {'  '.join(parts)}")

    # 预警详情
    if result.get("alerts"):
        print()
        for a in result["alerts"]:
            ic = ICON.get(a["level"], "⚪")
            print(f"   {ic} [{a['cat']}·{a['name']}] {a['detail']}")

    # 关键位
    sup = result.get("supports", [])
    res = result.get("resistances", [])
    if sup or res:
        print()
        if res:
            print(f"   ↑ 压力: " + "  ".join([f"{r['label']}={r['price']}" for r in res[:3]]))
        if sup:
            print(f"   ↓ 支撑: " + "  ".join([f"{s['label']}={s['price']}" for s in sup[:3]]))


def print_summary_table(results: list):
    print("\n" + "█" * 60)
    print("█  技术面预警汇总")
    print(f"█  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("█" * 60)
    print(f"\n{'股票':^12}  {'收盘':^8}  {'涨跌':^8}  {'综合':^6}  {'红':^4}  {'黄':^4}  {'绿':^4}  主要预警")
    print("─" * 90)
    for r in results:
        if "error" in r:
            print(f"  {r['symbol']:12}  数据错误: {r['error']}")
            continue
        ic = ICON.get(r["overall"], "⚪")
        pct_str = f"{r['pct_today']:+.1f}%" if r.get("pct_today") is not None else "  N/A "
        cnt = r.get("alert_count", {})
        top_alert = r["alerts"][0]["name"] if r.get("alerts") else "—"
        print(f"  {r['symbol']:12}  {r['close']:7.2f}  {pct_str:>7}  {ic}{r['overall']:6}  "
              f"{cnt.get('red',0):^4}  {cnt.get('yellow',0):^4}  {cnt.get('green',0):^4}  {top_alert}")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="技术面预警系统")
    p.add_argument("symbols", nargs="*", help="股票代码列表（如 603986.SH）")
    p.add_argument("--watchlist", help="监控列表文件（每行一个代码）")
    p.add_argument("--days", type=int, default=250, help="历史数据天数")
    p.add_argument("--out", default="/tmp/tech_alert.json")
    args = p.parse_args()

    # 整合股票列表
    symbols = list(args.symbols)
    if args.watchlist:
        wl = Path(args.watchlist)
        if wl.exists():
            for line in wl.read_text().splitlines():
                # 去掉行内注释，只取第一列（代码）
                code = line.split("#")[0].strip()
                if code:
                    symbols.append(code)

    if not symbols:
        print("请提供至少一个股票代码，或通过 --watchlist 文件指定。")
        print("示例: python3.11 tech_alert.py 603986.SH 688256.SH")
        return

    # 补全交易所后缀
    normalized = []
    for sym in symbols:
        if "." not in sym:
            if sym.startswith(("600", "601", "603", "605", "688")):
                sym += ".SH"
            else:
                sym += ".SZ"
        normalized.append(sym)

    panda_data.init_token(username=USERNAME, password=PASSWORD)

    results = []
    for sym in normalized:
        print(f"\n📊 拉取数据: {sym} ...")
        df_raw = fetch_daily(sym, args.days)
        if df_raw.empty:
            results.append({"symbol": sym, "overall": "UNKNOWN", "error": "无行情数据", "alerts": []})
            continue
        df_ind = calc_indicators(df_raw)
        result = check_alerts(df_ind, sym)
        results.append(result)
        print_single_report(result)

    if len(results) > 1:
        print_summary_table(results)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "layer": "L6_技术预警",
            "overall_level": "RED" if any(r.get("overall") == "RED" for r in results) else "YELLOW",
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📁 完整结果已保存: {args.out}")


if __name__ == "__main__":
    main()
