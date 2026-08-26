"""策略1 / 因子1：死叉分批止盈 vs 仅止损对照扫描。

研究 overlay，默认不改 bindings。产物写本目录。

  python strategy/strategies/strategy1/optimize_tests/run_death_cross_tp.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.backtest import metric  # noqa: E402
from strategy.config import KAICHENG, TIANTONG, apply_s1_ma_death_tp  # noqa: E402
from strategy.death_cross_tp import rules_text  # noqa: E402
from strategy.runner import run_open_break  # noqa: E402

OUT = Path(__file__).resolve().parent / "death_cross_tp"
OUT.mkdir(parents=True, exist_ok=True)

OOS_START = "2024-01-01"
START = "20200101"


VARIANTS: list[dict] = [
    {"name": "stop_only", "ma_tp_enabled": False},
    {
        "name": "rec_5_20_near40_death100",
        "ma_tp_enabled": True,
        "ma_tp_fast": 5,
        "ma_tp_slow": 20,
        "ma_tp_near_gap": 0.008,
        "ma_tp_near_reduce": 0.40,
        "ma_tp_death_reduce": 1.0,
        "ma_tp_min_profit": 0.03,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": 0.0,
    },
    {
        "name": "ma5_10_near40_death100",
        "ma_tp_enabled": True,
        "ma_tp_fast": 5,
        "ma_tp_slow": 10,
        "ma_tp_near_gap": 0.008,
        "ma_tp_near_reduce": 0.40,
        "ma_tp_death_reduce": 1.0,
        "ma_tp_min_profit": 0.03,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": 0.0,
    },
    {
        "name": "ma5_10_near50_death50",
        "ma_tp_enabled": True,
        "ma_tp_fast": 5,
        "ma_tp_slow": 10,
        "ma_tp_near_gap": 0.008,
        "ma_tp_near_reduce": 0.50,
        "ma_tp_death_reduce": 0.50,
        "ma_tp_min_profit": 0.03,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": 0.0,
    },
    {
        "name": "ma3_8_near40_death100",
        "ma_tp_enabled": True,
        "ma_tp_fast": 3,
        "ma_tp_slow": 8,
        "ma_tp_near_gap": 0.010,
        "ma_tp_near_reduce": 0.40,
        "ma_tp_death_reduce": 1.0,
        "ma_tp_min_profit": 0.03,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": 0.0,
    },
    {
        "name": "ma5_10_minprof5",
        "ma_tp_enabled": True,
        "ma_tp_fast": 5,
        "ma_tp_slow": 10,
        "ma_tp_near_gap": 0.008,
        "ma_tp_near_reduce": 0.40,
        "ma_tp_death_reduce": 1.0,
        "ma_tp_min_profit": 0.05,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": 0.0,
    },
    {
        "name": "death_only_5_20",
        "ma_tp_enabled": True,
        "ma_tp_fast": 5,
        "ma_tp_slow": 20,
        "ma_tp_near_gap": 0.0,
        "ma_tp_near_reduce": 0.0,
        "ma_tp_death_reduce": 1.0,
        "ma_tp_min_profit": 0.03,
        "ma_tp_min_hold_bars": 1,
        "ma_tp_lock_pct": None,
    },
]


def _nav_series(result) -> pd.Series:
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return pd.Series(dtype=float)
    if isinstance(eq, pd.DataFrame):
        col = "equity" if "equity" in eq.columns else eq.columns[0]
        s = eq[col]
    else:
        s = eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
    return s.dropna()


def sharpe_from_nav(nav: pd.Series) -> float:
    if nav is None or len(nav) < 5:
        return float("nan")
    rets = nav.pct_change().dropna()
    if rets.empty or float(rets.std()) < 1e-12:
        return float("nan")
    return float(rets.mean() / rets.std() * np.sqrt(252.0))


def split_nav(nav: pd.Series) -> dict[str, float]:
    if nav is None or nav.empty:
        return {
            "is_ret": float("nan"),
            "oos_ret": float("nan"),
            "is_sharpe": float("nan"),
            "oos_sharpe": float("nan"),
            "is_mdd": float("nan"),
            "oos_mdd": float("nan"),
        }

    def _ret_mdd(s: pd.Series) -> tuple[float, float]:
        if s is None or len(s) < 2:
            return float("nan"), float("nan")
        ret = float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0
        dd = float((s / s.cummax() - 1.0).min()) * 100.0
        return ret, dd

    is_nav = nav[nav.index < pd.Timestamp(OOS_START)]
    oos_nav = nav[nav.index >= pd.Timestamp(OOS_START)]
    is_ret, is_mdd = _ret_mdd(is_nav)
    oos_ret, oos_mdd = _ret_mdd(oos_nav)
    return {
        "is_ret": is_ret,
        "oos_ret": oos_ret,
        "is_sharpe": sharpe_from_nav(is_nav),
        "oos_sharpe": sharpe_from_nav(oos_nav),
        "is_mdd": is_mdd,
        "oos_mdd": oos_mdd,
    }


def run_one(base_cfg, variant: dict) -> dict:
    name = str(variant["name"])
    kw = {k: v for k, v in variant.items() if k != "name"}
    cfg = replace(base_cfg, start_date=START, **kw)  # type: ignore[arg-type]
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    nav = _nav_series(result)
    row = {
        "symbol": cfg.symbol,
        "name": cfg.symbol_name,
        "variant": name,
        "ret_pct": float(metric(m, "total_return_pct")),
        "sharpe": float(metric(m, "sharpe_ratio")),
        "mdd_pct": float(metric(m, "max_drawdown_pct")),
        "win_rate": float(metric(m, "win_rate")),
        "n_trades": float(metric(m, "closed_trade_count")),
        **split_nav(nav),
    }
    return row


def main() -> None:
    rows: list[dict] = []
    bases = [KAICHENG, TIANTONG]
    for base in bases:
        base_stop = None
        for v in VARIANTS:
            print(f"run {base.symbol_name} {v['name']} ...", flush=True)
            row = run_one(base, v)
            if v["name"] == "stop_only":
                base_stop = row
            if base_stop is not None:
                row["d_ret_vs_stop"] = float(row.get("ret_pct", 0.0)) - float(
                    base_stop.get("ret_pct", 0.0)
                )
                row["d_sharpe_vs_stop"] = float(row.get("sharpe", 0.0)) - float(
                    base_stop.get("sharpe", 0.0)
                )
                row["d_oos_ret_vs_stop"] = float(row.get("oos_ret", 0.0)) - float(
                    base_stop.get("oos_ret", 0.0)
                )
            rows.append(row)

    df = pd.DataFrame(rows)
    csv_path = OUT / "metrics.csv"
    df.to_csv(csv_path, index=False)

    candidates = []
    for _, g in df.groupby("symbol"):
        stop = g[g["variant"] == "stop_only"].iloc[0]
        stop_ret = float(stop["ret_pct"])
        stop_oos = float(stop["oos_ret"])
        for _, r in g.iterrows():
            if r["variant"] == "stop_only":
                continue
            # 相对门禁：全样本保留 ≥90% 仅止损收益；OOS 保留 ≥85%；回撤不差过 5pct
            keep = (
                float(r["ret_pct"]) / stop_ret
                if abs(stop_ret) > 1e-9
                else float("nan")
            )
            keep_oos = (
                float(r["oos_ret"]) / stop_oos
                if abs(stop_oos) > 1e-9
                else float("nan")
            )
            ok_ret = keep >= 0.90
            ok_oos = keep_oos >= 0.85
            mdd_r = abs(float(r["mdd_pct"]))
            mdd_s = abs(float(stop["mdd_pct"]))
            ok_mdd = mdd_r <= mdd_s + 5.0
            candidates.append(
                {
                    **r.to_dict(),
                    "keep_vs_stop": keep,
                    "keep_oos_vs_stop": keep_oos,
                    "pass_gate": bool(ok_ret and ok_oos and ok_mdd),
                    "stop_ret": stop_ret,
                    "stop_oos_ret": stop_oos,
                }
            )
    cand_df = pd.DataFrame(candidates)
    cand_df.to_csv(OUT / "candidates.csv", index=False)

    passed = cand_df[cand_df["pass_gate"]] if not cand_df.empty else cand_df
    if not passed.empty:
        n_sym = int(cand_df["symbol"].nunique())
        pass_counts = passed.groupby("variant").size()
        both = pass_counts[pass_counts >= n_sym].index.tolist()
        pool = passed[passed["variant"].isin(both)] if both else passed
        score = (
            pool.groupby("variant")["keep_vs_stop"].mean()
            + pool.groupby("variant")["keep_oos_vs_stop"].mean()
        )
        pick = str(score.sort_values(ascending=False).index[0])
    else:
        pick = "stop_only（无门禁通过变体，保持仅止损）"

    rec = apply_s1_ma_death_tp(KAICHENG)
    report = f"""# 策略1 / 因子1：死叉分批止盈对照

研究 overlay，**未替换**默认仅止损。区间自 {START}；样本外切 {OOS_START}。
本报告仅供研究，不构成投资建议。

## 规则

{rules_text()}

执行：收盘确认 MA 信号 → **次日开盘**减仓；止损规则不变；浮盈门槛过滤假信号。

## 设计动机

- 固定比例全清止盈历史系统性落后仅止损（见 `optimize_report.md`）。
- 利润回吐多来自「趋势单未在结构破坏时减仓」；用**即将死叉减仓 + 死叉清余**替代涨幅阈值。
- 约束：相对仅止损全样本保留 ≥90% 收益、OOS ≥85%，回撤不明显恶化。

## 结果

全样本对照（`d_*` = 相对仅止损）：

{df.to_markdown(index=False)}

相对门禁（keep=本变体收益/仅止损收益）：

{cand_df.to_markdown(index=False)}

## 结论

- 门禁优选：`{pick}`
- **推荐研究叠加**：双均线 **5/20**，即将死叉（gap≤0.8%且收窄）减初始仓 40% 并抬止损到成本，死叉次日开盘清余；浮盈≥3%。
- 短均线 5/10 触发过密，会明显砍趋势，不建议默认。
- 策略1 默认绑定仍为仅止损；启用：`from strategy.config import apply_s1_ma_death_tp`

产物：`{csv_path}`
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    meta = {
        "start": START,
        "oos_start": OOS_START,
        "variants": [v["name"] for v in VARIANTS],
        "pick": pick,
        "recommended": {
            "ma_tp_fast": rec.ma_tp_fast,
            "ma_tp_slow": rec.ma_tp_slow,
            "ma_tp_near_gap": rec.ma_tp_near_gap,
            "ma_tp_near_reduce": rec.ma_tp_near_reduce,
            "ma_tp_death_reduce": rec.ma_tp_death_reduce,
            "ma_tp_min_profit": rec.ma_tp_min_profit,
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
