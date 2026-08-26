"""科创综指ETF(589680) · 因子14 MACD 买图标准回测。

口径：
  · 收盘确认信号 → 次日开盘成交（无未来函数）
  · T+1；ETF 印花税 0；佣金万0.86+杂费万0.10；滑点 0.1%×2
  · 一次打满 / 一次清仓；初始资金 10 万
  · 对照买入持有

模式网格（买图标准变体）：
  · cross / zero_cross / hist_flip / zero_hist
  · MACD(12,26,9) 默认；另扫 (8,17,9)(5,34,5) 作稳健对照

研究用途，不构成投资建议。
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE,
    ETF_STAMP_TAX_RATE,
    SLIPPAGE_VALUE,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.macd_timing import Mode, macd_rules_text, macd_signals  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _MYQUAN / "data_cache" / "sh589680_daily_qfq.parquet"
NAME = "科创综指ETF鹏华"
CODE = "589680"
SYMBOL = "sh589680"
START = "20250305"
CASH = 100_000.0
LOT = 100


def _load_daily() -> pd.DataFrame:
    today = pd.Timestamp.today().strftime("%Y%m%d")
    try:
        df = fetch_daily(
            SYMBOL, START, today, cache_path=CACHE, force_refresh=False
        )
    except Exception as exc:
        print(f"远程失败，用缓存: {exc}")
        df = pd.read_parquet(CACHE)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    else:
        df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _exec_px(raw: float, *, side: str) -> float:
    """开盘价加减滑点。"""
    slip = SLIPPAGE_VALUE
    if side == "buy":
        return float(raw) * (1.0 + slip)
    return float(raw) * (1.0 - slip)


def _fee(notional: float, *, side: str) -> float:
    fee = abs(notional) * ENGINE_COMMISSION_RATE
    if side == "sell":
        fee += abs(notional) * ETF_STAMP_TAX_RATE
    return fee


def simulate(
    daily: pd.DataFrame,
    *,
    mode: Mode,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    initial_cash: float = CASH,
    t1: bool = True,
) -> dict[str, Any]:
    """收盘出信号，次日开盘成交。"""
    close = daily.set_index("date")["close"].astype(float)
    open_ = daily.set_index("date")["open"].astype(float)
    sig = macd_signals(close, fast=fast, slow=slow, signal=signal, mode=mode)
    # 次日执行：把信号 shift(1) 对齐到执行日
    buy_exec = sig["buy"].shift(1).fillna(False).astype(bool)
    sell_exec = sig["sell"].shift(1).fillna(False).astype(bool)

    cash = float(initial_cash)
    shares = 0
    buy_day: pd.Timestamp | None = None
    equity = []
    trades: list[dict[str, Any]] = []
    open_lot: dict[str, Any] | None = None

    dates = list(close.index)
    for i, dt in enumerate(dates):
        o = float(open_.loc[dt])
        c = float(close.loc[dt])

        # 卖
        if shares > 0 and bool(sell_exec.loc[dt]):
            if t1 and buy_day is not None and dt.normalize() <= buy_day.normalize():
                pass  # T+1 禁卖
            else:
                px = _exec_px(o, side="sell")
                notional = shares * px
                fee = _fee(notional, side="sell")
                cash += notional - fee
                ret = (px / float(open_lot["买入价"]) - 1.0) * 100.0 if open_lot else 0.0
                trades.append(
                    {
                        **(open_lot or {}),
                        "卖出日": dt.strftime("%Y-%m-%d"),
                        "卖出价": round(px, 4),
                        "收益%": round(ret, 2),
                        "状态": "已平仓",
                        "模式": mode,
                    }
                )
                shares = 0
                buy_day = None
                open_lot = None

        # 买
        if shares <= 0 and bool(buy_exec.loc[dt]) and cash > 0:
            px = _exec_px(o, side="buy")
            # 95% 仓位打满，按手数
            budget = cash * 0.95
            qty = int(budget / px / LOT) * LOT
            if qty >= LOT:
                notional = qty * px
                fee = _fee(notional, side="buy")
                if notional + fee <= cash:
                    cash -= notional + fee
                    shares = qty
                    buy_day = dt
                    open_lot = {
                        "序号": len(trades) + 1,
                        "买入日": dt.strftime("%Y-%m-%d"),
                        "买入价": round(px, 4),
                        "数量": qty,
                    }

        mtm = cash + shares * c
        equity.append({"date": dt, "equity": mtm, "shares": shares, "close": c})

    if open_lot is not None and shares > 0:
        last = dates[-1]
        px = float(close.loc[last])
        ret = (px / float(open_lot["买入价"]) - 1.0) * 100.0
        trades.append(
            {
                **open_lot,
                "卖出日": "",
                "卖出价": round(px, 4),
                "收益%": round(ret, 2),
                "状态": "持有中",
                "模式": mode,
            }
        )

    eq = pd.DataFrame(equity).set_index("date")["equity"]
    bh0 = float(close.iloc[0])
    bh = initial_cash * (close / bh0)
    ret_s = (float(eq.iloc[-1]) / initial_cash - 1.0) * 100.0
    ret_h = (float(close.iloc[-1]) / bh0 - 1.0) * 100.0
    peak = eq.cummax()
    dd = float((eq / peak - 1.0).min() * 100.0)
    bh_peak = bh.cummax()
    bh_dd = float((bh / bh_peak - 1.0).min() * 100.0)
    rets = eq.pct_change().dropna()
    sharpe = float("nan")
    if len(rets) > 5 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(252))

    # 分月
    m_rows = []
    for period, part in eq.groupby(eq.index.to_period("M")):
        if part.empty:
            continue
        prev = eq[eq.index < part.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else initial_cash
        s_ret = (float(part.iloc[-1]) / base - 1.0) * 100.0
        px_part = close[close.index.to_period("M") == period]
        px_prev = close[close.index < px_part.index[0]] if len(px_part) else close.iloc[:0]
        pbase = float(px_prev.iloc[-1]) if len(px_prev) else float(px_part.iloc[0])
        h_ret = (float(px_part.iloc[-1]) / pbase - 1.0) * 100.0
        mdd = float((part / part.cummax() - 1.0).min() * 100.0)
        m_rows.append(
            {
                "月份": str(period),
                "策略%": round(s_ret, 2),
                "持有%": round(h_ret, 2),
                "超额%": round(s_ret - h_ret, 2),
                "月末权益": round(float(part.iloc[-1]), 2),
                "月内回撤%": round(mdd, 2),
            }
        )

    closed = [t for t in trades if t.get("状态") == "已平仓"]
    wins = [t for t in closed if float(t.get("收益%", 0)) > 0]
    return {
        "mode": mode,
        "fast": fast,
        "slow": slow,
        "signal": signal,
        "累计策略%": round(ret_s, 2),
        "累计持有%": round(ret_h, 2),
        "累计超额%": round(ret_s - ret_h, 2),
        "夏普": round(sharpe, 3) if sharpe == sharpe else None,
        "策略回撤%": round(abs(dd), 2),
        "持有回撤%": round(abs(bh_dd), 2),
        "闭环": len(closed),
        "胜率%": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "当前持仓": any(t.get("状态") == "持有中" for t in trades),
        "equity": eq,
        "monthly": pd.DataFrame(m_rows),
        "trades": pd.DataFrame(trades),
        "signals": sig,
    }


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    daily = _load_daily()
    d0 = str(daily["date"].min().date())
    d1 = str(daily["date"].max().date())
    print(f"日线 {len(daily)} · {d0}→{d1}")
    print(macd_rules_text())

    jobs: list[tuple[str, Mode, int, int, int]] = []
    for mode in ("zero_cross", "cross", "hist_flip", "zero_hist"):
        jobs.append((f"{mode}_12_26_9", mode, 12, 26, 9))  # type: ignore[arg-type]
    # 稳健参数对照（仍用教科书零轴金叉）
    for fast, slow, sig in ((8, 17, 9), (5, 34, 5), (10, 20, 8)):
        jobs.append((f"zero_cross_{fast}_{slow}_{sig}", "zero_cross", fast, slow, sig))

    rows = []
    arts: dict[str, dict[str, Any]] = {}
    for label, mode, fast, slow, sig in jobs:
        print(f"  run {label} ...", flush=True)
        r = simulate(daily, mode=mode, fast=fast, slow=slow, signal=sig)
        arts[label] = r
        rows.append(
            {
                "方案": label,
                "模式": mode,
                "参数": f"({fast},{slow},{sig})",
                "累计策略%": r["累计策略%"],
                "累计持有%": r["累计持有%"],
                "累计超额%": r["累计超额%"],
                "夏普": r["夏普"],
                "策略回撤%": r["策略回撤%"],
                "持有回撤%": r["持有回撤%"],
                "闭环": r["闭环"],
                "胜率%": r["胜率%"],
                "当前持仓": r["当前持仓"],
            }
        )

    sweep = pd.DataFrame(rows).sort_values(
        ["累计超额%", "夏普", "累计策略%"], ascending=False
    )
    sweep.to_csv(DIR / "param_sweep.csv", index=False, encoding="utf-8-sig")

    best_label = str(sweep.iloc[0]["方案"])
    best = arts[best_label]
    # 默认教科书也单独存
    textbook = arts["zero_cross_12_26_9"]

    for tag, pack in (("best", best), ("textbook", textbook)):
        pack["monthly"].to_csv(
            DIR / f"monthly_{tag}.csv", index=False, encoding="utf-8-sig"
        )
        if not pack["trades"].empty:
            pack["trades"].to_csv(
                DIR / f"holdings_{tag}.csv", index=False, encoding="utf-8-sig"
            )

    # 2026 切片
    def oos_block(pack: dict[str, Any]) -> dict[str, float]:
        eq = pack["equity"]
        close = daily.set_index("date")["close"].astype(float)
        eq6 = eq[eq.index.year >= 2026]
        c6 = close[close.index.year >= 2026]
        if len(eq6) < 2:
            return {}
        pre_e = eq[eq.index.year < 2026]
        pre_c = close[close.index.year < 2026]
        base_e = float(pre_e.iloc[-1]) if len(pre_e) else CASH
        base_c = float(pre_c.iloc[-1]) if len(pre_c) else float(c6.iloc[0])
        s = (float(eq6.iloc[-1]) / base_e - 1.0) * 100.0
        h = (float(c6.iloc[-1]) / base_c - 1.0) * 100.0
        dd = float((eq6 / eq6.cummax() - 1.0).min() * 100.0)
        return {
            "策略%": round(s, 2),
            "持有%": round(h, 2),
            "超额%": round(s - h, 2),
            "回撤%": round(abs(dd), 2),
        }

    summary = {
        "标的": NAME,
        "代码": CODE,
        "区间": f"{d0} → {d1}",
        "因子": "factor14·MACD",
        "最优方案": best_label,
        "最优": {k: best[k] for k in (
            "mode", "fast", "slow", "signal",
            "累计策略%", "累计持有%", "累计超额%", "夏普",
            "策略回撤%", "持有回撤%", "闭环", "胜率%", "当前持仓",
        )},
        "教科书zero_cross_12_26_9": {
            k: textbook[k] for k in (
                "累计策略%", "累计持有%", "累计超额%", "夏普",
                "策略回撤%", "闭环", "胜率%", "当前持仓",
            )
        },
        "2026_最优": oos_block(best),
        "2026_教科书": oos_block(textbook),
        "口径": "收盘确认次日开盘；T+1；ETF无印花；对照买入持有",
    }
    (DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    m2026 = best["monthly"][
        best["monthly"]["月份"].astype(str).str.startswith("2026")
    ]
    lines = [
        f"# {NAME}({CODE}) 因子14 · MACD 买图标准回测",
        "",
        "> 研究回测，不构成投资建议。收盘确认 → 次日开盘；T+1。",
        "",
        "## 买图规则",
        "",
        "```",
        macd_rules_text(
            fast=int(best["fast"]),
            slow=int(best["slow"]),
            signal=int(best["signal"]),
            mode=best["mode"],
        ),
        "```",
        "",
        f"## 最优方案：`{best_label}`",
        "",
        f"| 累计策略 | 累计持有 | 超额 | 夏普 | 策略回撤 | 持有回撤 | 闭环 | 胜率 |",
        f"|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {best['累计策略%']:.2f}% | {best['累计持有%']:.2f}% | "
            f"{best['累计超额%']:.2f}% | {best['夏普']} | "
            f"{best['策略回撤%']:.2f}% | {best['持有回撤%']:.2f}% | "
            f"{best['闭环']} | {best['胜率%']:.1f}% |"
        ),
        "",
        "## 教科书默认 zero_cross(12,26,9)",
        "",
        f"| 累计策略 | 累计持有 | 超额 | 夏普 | 回撤 | 闭环 |",
        f"|---:|---:|---:|---:|---:|---:|",
        (
            f"| {textbook['累计策略%']:.2f}% | {textbook['累计持有%']:.2f}% | "
            f"{textbook['累计超额%']:.2f}% | {textbook['夏普']} | "
            f"{textbook['策略回撤%']:.2f}% | {textbook['闭环']} |"
        ),
        "",
        "## 2026（相对 2025 年末）",
        "",
        f"- 最优：{json.dumps(summary['2026_最优'], ensure_ascii=False)}",
        f"- 教科书：{json.dumps(summary['2026_教科书'], ensure_ascii=False)}",
        "",
        "## 最优方案 · 分月",
        "",
        best["monthly"].to_markdown(index=False),
        "",
        "## 最优方案 · 2026 分月",
        "",
        m2026.to_markdown(index=False) if len(m2026) else "_无_",
        "",
        "## 最优方案 · 持仓",
        "",
        best["trades"].to_markdown(index=False)
        if not best["trades"].empty
        else "_无成交_",
        "",
        "## 全网格",
        "",
        sweep.to_markdown(index=False),
        "",
    ]
    (DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n========== 网格 ==========")
    print(sweep.to_string(index=False))
    print(f"\n最优: {best_label}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"产出: {DIR}")


if __name__ == "__main__":
    main()
