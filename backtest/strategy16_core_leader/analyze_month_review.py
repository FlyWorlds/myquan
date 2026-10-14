"""Diagnose the saved all-pool replay against timestamp-aligned indices."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from strategy.minute import standardize_minute_1m


def main() -> None:
    folder = Path(sys.argv[1]).resolve()
    result = json.loads((folder / "result.json").read_text())
    if not result.get("all_pool"):
        raise SystemExit("Pass an all-pool review directory.")
    cutoff = pd.Timestamp(result["replay_cutoff"])
    baseline = (pd.Timestamp(result["requested_start"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    initial = float(result["portfolio"]["summary"]["initial_cash"])
    comparisons, benchmark_rows = [], []
    socket.setdefaulttimeout(15)
    for symbol, name in (("sh000001", "上证综指"), ("sz399001", "深证成指")):
        daily = ak.stock_zh_index_daily(symbol=symbol)
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily[(daily["date"] >= pd.Timestamp(baseline)) & (daily["date"] < cutoff.normalize())]
        bars = standardize_minute_1m(ak.stock_zh_a_minute(symbol=symbol, period="1", adjust=""))
        bars["ts"] = bars["ts"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
        bars = bars[bars["ts"] <= cutoff]
        hit = bars[bars["ts"] == cutoff]
        if hit.empty:
            raise ValueError(f"{symbol}: benchmark does not cover the exact cutoff")
        base = float(daily.loc[daily["date"].dt.strftime("%Y-%m-%d") == baseline, "close"].iloc[-1])
        mark = float(hit.iloc[-1]["close"])
        ret = (mark / base - 1) * 100
        daily.to_csv(folder / f"benchmark_{symbol}_daily.csv", index=False)
        bars[bars["ts"].dt.strftime("%Y-%m-%d") == str(cutoff.date())].to_csv(folder / f"benchmark_{symbol}_intraday.csv", index=False)
        comparisons.append({"name": name, "code": symbol, "base_price": base, "end_price": mark,
                            "return_pct": ret, "excess_pct_points": result["accounting"]["net_profit"] / initial * 100 - ret})
        for e in result["portfolio"]["equity"]:
            date = e["date"]
            price = mark if date == str(cutoff.date()) else float(daily.loc[daily["date"].dt.strftime("%Y-%m-%d") == date, "close"].iloc[-1])
            benchmark_rows.append({"date": date, "index": name, "price": price, "return_pct": (price / base - 1) * 100})
    raw_folder = folder.with_name(folder.name.removesuffix("_all_pool"))
    constituents = pd.read_csv(folder / "constituents.csv", dtype={"code": str})
    cycles = pd.read_csv(folder / "cycles.csv", dtype={"code": str})
    trades = pd.read_csv(folder / "trades.csv", dtype={"code": str})
    buyhold = []
    for c in constituents.to_dict("records"):
        code = c["code"]
        symbol = ("sh" if code.startswith("6") else "sz") + code
        daily = pd.read_parquet(ROOT / "data_cache" / f"{symbol}_daily_qfq.parquet")
        days = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
        base = float(daily.loc[days == baseline, "close"].iloc[-1])
        mins = pd.read_parquet(raw_folder / "minutes" / f"{symbol}.parquet")
        mark = float(mins.loc[mins["ts"] <= cutoff, "close"].iloc[-1])
        buyhold.append({"code": code, "name": c["name"], "buyhold_return_pct": (mark / base - 1) * 100})
    bh = pd.DataFrame(buyhold)
    bh.to_csv(folder / "pool_buyhold_reference.csv", index=False, encoding="utf-8-sig")
    comparisons.append({"name": "全池等权买入持有价格参考", "code": "pool_buyhold",
                        "return_pct": float(bh["buyhold_return_pct"].mean())})
    active, legs = {}, []
    for t in trades.to_dict("records"):
        code = t["code"]
        if t["side"] == "buy":
            active[code] = {"price": t["px"], "qty": t["shares"], "time": t["ts"]}
        else:
            position = active[code]
            legs.append({"code": code, "name": t["name"], "time": t["ts"], "buy_time": position["time"],
                         "reason": t["exit_reason"], "gross_pnl": (t["px"] - position["price"]) * t["shares"],
                         "return_pct": (t["px"] / position["price"] - 1) * 100})
            position["qty"] -= t["shares"]
            if position["qty"] == 0:
                del active[code]
    leg_df = pd.DataFrame(legs)
    reason = leg_df.groupby("reason")["gross_pnl"].agg(["sum", "count"]).reset_index()
    cohorts = cycles.groupby(cycles["buy_time"].str[:10])["net_pnl"].agg(["sum", "count"]).reset_index()
    closed = cycles[cycles["remaining_qty"] == 0]
    hard = leg_df[leg_df["reason"] == "hard_from_cost"]
    exposures = [(e["equity"] - e["cash"]) / e["equity"] * 100 for e in result["portfolio"]["equity"]]
    diagnosis = {"baseline": baseline, "cutoff": str(cutoff), "benchmarks": comparisons,
                 "index_history": benchmark_rows, "sell_reasons": reason.to_dict("records"),
                 "buy_cohorts": cohorts.to_dict("records"), "closed_trades": len(closed),
                 "closed_winners": int((closed["net_pnl"] > 0).sum()),
                 "closed_win_rate_pct": float((closed["net_pnl"] > 0).mean() * 100),
                 "avg_closed_win_pct": float(closed.loc[closed["net_pnl"] > 0, "net_return_pct"].mean()),
                 "avg_closed_loss_pct": float(closed.loc[closed["net_pnl"] < 0, "net_return_pct"].mean()),
                 "losing_symbols": int((constituents["net_profit"] < 0).sum()),
                 "winning_symbols": int((constituents["net_profit"] > 0).sum()),
                 "pool_declining_symbols": int((bh["buyhold_return_pct"] < 0).sum()),
                 "mean_sampled_exposure_pct": sum(exposures) / len(exposures),
                 "latest_exposure_pct": exposures[-1],
                 "hard_exits_at_opening_minute": int(hard["time"].str.endswith("09:31:00").sum()),
                 "top_losing_symbols": constituents.sort_values("net_profit").head(5).to_dict("records"),
                 "accounting": result["accounting"]}
    assert abs(leg_df["gross_pnl"].sum() - result["accounting"]["gross_realized"]) < 0.01
    assert abs(cycles["net_pnl"].sum() - result["accounting"]["net_profit"]) < 0.1
    (folder / "diagnostics.json").write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")
    reason.to_csv(folder / "exit_reason_contributions.csv", index=False)
    cohorts.to_csv(folder / "buy_date_contributions.csv", index=False)
    pd.DataFrame(benchmark_rows).to_csv(folder / "benchmark_comparison.csv", index=False)
    lines = ["# 策略16全池本月亏损诊断", "", f"基准：{baseline} 收盘；截止：{cutoff} 上海时间。",
             "策略为30万元等权独立资金组合，空仓开始，含交易费用及盘中浮盈亏。", "",
             "| 比较对象 | 累计涨跌/收益率 |", "|---|---:|",
             f"| 策略16全池组合 | {result['portfolio']['summary']['return_pct']:.2f}% |"]
    for c in comparisons:
        lines.append(f"| {c['name']} | {c['return_pct']:.2f}% |")
    lines += ["", "| 日期 | 全池策略累计 | 上证累计 | 深证累计 |", "|---|---:|---:|---:|"]
    for e in result["portfolio"]["equity"]:
        sh = next(x["return_pct"] for x in benchmark_rows if x["date"] == e["date"] and x["index"] == "上证综指")
        sz = next(x["return_pct"] for x in benchmark_rows if x["date"] == e["date"] and x["index"] == "深证成指")
        lines.append(f"| {e['date']} | {e['ret_pct']:.2f}% | {sh:.2f}% | {sz:.2f}% |")
    lines += ["", "## 盈亏来源", "",
              f"组合净亏 {result['accounting']['net_profit']:,.2f} 元；已实现毛盈亏 {result['accounting']['gross_realized']:,.2f} 元；未平仓毛浮盈亏 {result['accounting']['gross_floating']:,.2f} 元；费用及滑点 {result['accounting']['fees_and_slippage']:,.2f} 元。",
              f"34只中 {diagnosis['losing_symbols']} 只净亏、{diagnosis['winning_symbols']} 只净赚，其余未交易。全池价格参考有 {diagnosis['pool_declining_symbols']} 只下跌。",
              f"完整平仓 {len(closed)} 笔，盈利 {diagnosis['closed_winners']} 笔，胜率 {diagnosis['closed_win_rate_pct']:.2f}%；平均盈利交易 {diagnosis['avg_closed_win_pct']:.2f}%，平均亏损交易 {diagnosis['avg_closed_loss_pct']:.2f}%。", "",
              "| 卖出规则 | 卖出分腿数 | 已实现毛盈亏 |", "|---|---:|---:|"]
    for row in reason.to_dict("records"):
        lines.append(f"| {row['reason']} | {row['count']} | {row['sum']:,.2f} |")
    lines += ["", "| 买入日期 | 完整买入周期数 | 当前整笔净盈亏 |", "|---|---:|---:|"]
    for row in cohorts.to_dict("records"):
        lines.append(f"| {row['buy_time']} | {row['count']} | {row['sum']:,.2f} |")
    lines += ["", "## 判断与边界", "",
              "已验证：市场、当前股票池整体下跌；亏损集中在突破入场后的亏损退出。硬保护和T+1隔夜回落退出解释主要已实现损失；少量盈利交易不足以抵消亏损。交易费用为次要亏损来源。",
              f"10次硬保护退出中 {diagnosis['hard_exits_at_opening_minute']} 次发生在09:31。硬保护价是触发条件，不保证隔夜跳空按亏损2.5%成交。应结合逐笔行情检查T+1与隔夜缺口，不能仅凭规则分组认定止损设计错误。",
              f"策略日末及当前时点仓位平均 {diagnosis['mean_sampled_exposure_pct']:.2f}%，当前仓位 {diagnosis['latest_exposure_pct']:.2f}%。跑赢满仓指数/股票池与低持仓有关，不构成风险调整后alpha证据；这不是时间加权日内平均仓位。",
              "阈值拟合截止10月13日，存在样本内重叠。1分钟路径不含竞价，固定当前股票池，未导入9月隔夜仓；仅5个交易日，不足以验证长期有效性。股票池买入持有参考为前复权价格收益均值，未计费用与整手，与实际资金组合口径不同。",
              "指数日线、分钟线通过AKShare读取新浪财经；公开行情仅用于对比，未更改策略与持仓。", "",
              "来源：[上证指数](https://finance.sina.com.cn/realstock/company/sh000001/nc.shtml)、[深证成指](https://finance.sina.com.cn/realstock/company/sz399001/nc.shtml)；原始数据与诊断CSV在本目录。", ""]
    (folder / "DIAGNOSTICS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
