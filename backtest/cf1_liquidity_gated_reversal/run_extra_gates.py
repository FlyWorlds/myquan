"""CF1 额外门控：发现集单点加入，验证集选定。不用测试集选参。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.cf1_liquidity_gated_reversal.eval_engine import (  # noqa: E402
    OUT_DIR,
    dump_json,
    evaluate_params,
    load_ohlcv,
    metrics_row,
)
from strategy.cf1_liquidity_gated_reversal import DEFAULT_PARAMS  # noqa: E402

OPT = OUT_DIR / "optimize_tests" / "extra_gates"


def main() -> None:
    OPT.mkdir(parents=True, exist_ok=True)
    panel = load_ohlcv()
    close, volume, opens = panel["close"], panel["volume"], panel["open"]
    high, low = panel["high"], panel["low"]
    base = {k: DEFAULT_PARAMS[k] for k in DEFAULT_PARAMS}
    # 对照：关掉新门，只留已冻结的 Amihud+成交额
    core = {**base, "limit_gate": False, "trend_gate": "none", "vol_gate": "none"}

    variants = [
        ("core_amihud_adv", core),
        ("+limit", {**core, "limit_gate": True}),
        ("+trend_below_ma", {**core, "trend_gate": "below_ma"}),
        ("+trend_soft_below", {**core, "trend_gate": "soft_below_ma"}),
        ("+vol_soft_high", {**core, "vol_gate": "soft_high"}),
        ("+vol_high", {**core, "vol_gate": "high"}),
        ("+limit+trend_below", {**core, "limit_gate": True, "trend_gate": "below_ma"}),
        ("+limit+vol_soft_high", {**core, "limit_gate": True, "vol_gate": "soft_high"}),
        ("+limit+trend+vol", {**core, "limit_gate": True, "trend_gate": "below_ma", "vol_gate": "soft_high"}),
    ]

    disc_rows = []
    for name, p in variants:
        ev = evaluate_params(
            close, volume, opens, p, split="discovery", high=high, low=low
        )
        row = metrics_row(ev, name=name)
        disc_rows.append(row)
        print(
            f"disc {name:22} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f} "
            f"sharpe={row['sharpe']:.3f} cov={row['coverage']:.3f}",
            flush=True,
        )
    disc = pd.DataFrame(disc_rows)
    disc.to_csv(OPT / "discovery.csv", index=False)

    val_rows = []
    for name, p in variants:
        ev = evaluate_params(
            close, volume, opens, p, split="validation", high=high, low=low
        )
        row = metrics_row(ev, name=name)
        val_rows.append(row)
        print(
            f"valid {name:22} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f} "
            f"sharpe={row['sharpe']:.3f}",
            flush=True,
        )
    val = pd.DataFrame(val_rows)
    val.to_csv(OPT / "validation.csv", index=False)

    # 验证集主分选；并列看发现集不是尖峰
    best = val.sort_values(["score", "rank_ic_ir", "sharpe"], ascending=False).iloc[0]
    frozen_name = str(best["name"])
    frozen = dict(next(p for n, p in variants if n == frozen_name))
    dump_json(
        OPT / "selected.json",
        {
            "selected_on": "validation",
            "name": frozen_name,
            "params": frozen,
            "validation": best.to_dict(),
            "discovery": disc.set_index("name").loc[frozen_name].to_dict(),
            "note": "未用测试集选门。行业门无时点行业数据，未接。",
        },
    )
    print("SELECTED", frozen_name, "valid_score", float(best["score"]), flush=True)


if __name__ == "__main__":
    main()
