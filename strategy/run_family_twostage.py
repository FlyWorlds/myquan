"""两段式因子组合（z 分数等权已失败）。只看 IS 费用后夏普。

  python strategy/run_family_twostage.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.near_high_hold import limit_fill_masks  # noqa: E402
from strategy.run_family_optimize import (  # noqa: E402
    K,
    OUT,
    STAGE1,
    rank_icir,
    score_f9_energy,
    score_f10_comp,
    score_mom,
    score_near,
    score_persist,
)
from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    IS_END,
    IS_START,
    _norm,
    eval_snap,
    make_snaps,
    md_table,
    pick_is,
)

FWD = None


def main() -> None:
    (OUT / "twostage").mkdir(parents=True, exist_ok=True)
    ohlc = load_combined_ohlc()
    close = _norm(ohlc["close"])
    high = _norm(ohlc["high"]).reindex(index=close.index, columns=close.columns)
    open_px = _norm(ohlc["open"]).reindex(index=close.index, columns=close.columns)
    low = _norm(ohlc["low"]).reindex(index=close.index, columns=close.columns)
    block_buy, block_sell, _ = limit_fill_masks(close, open_px, high, low)
    fwd = close.shift(-6) / close.shift(-1) - 1.0

    mom3 = score_mom(close, 3)
    mom5 = score_mom(close, 5)
    near5 = score_near(close, high, 5)
    f9 = score_f9_energy(close, high, fast=5, slow=20, ma_n=20, up_n=10)
    persist20 = score_persist(close, 20)
    rev20 = -score_mom(close, 20)
    comp_short = score_f10_comp(close, high, high_n=5, trend_n=20, mom_n=5)

    specs = [
        ("ts_f9_near5", f9, near5, False, False, "因子9动能Top20 → 近5日高 Top5"),
        ("ts_f9_persist", f9, persist20, False, False, "因子9动能Top20 → 上涨占比 Top5"),
        ("ts_mom3_f9", mom3, f9, False, False, "3日动量Top20 → 因子9动能 Top5"),
        ("ts_mom3_comp", mom3, comp_short, False, False, "3日动量Top20 → 因子10短窗合成 Top5"),
        ("ts_f9_mom3", f9, mom3, False, False, "因子9动能Top20 → 3日动量 Top5"),
        ("ts_persist_near5", persist20, near5, False, False, "上涨占比Top20 → 近5日高 Top5"),
        ("ts_rev20_near5", rev20, near5, False, False, "20日反转Top20 → 近5日高 Top5"),
        ("ts_near5_f9", near5, f9, False, False, "近5日高Top20 → 因子9动能 Top5"),
        ("ts_f9_mom5inv", f9, mom5, False, True, "因子9动能Top20 → 5日涨幅最低"),
        ("ts_mom3_near5_k5", mom3, near5, False, False, "对照：因子11 默认两段"),
    ]
    rows = []
    for fid, s1, s2, inv1, inv2, logic in specs:
        snap = make_snaps(s1, s2, stage1_k=STAGE1, stage2_k=K, invert1=inv1, invert2=inv2)
        row = eval_snap(
            close,
            snap,
            fid,
            {"logic": logic, "family": "twostage", "kind": "twostage"},
            block_buy=block_buy,
            block_sell=block_sell,
        )
        mu, ir = rank_icir(s2 if not inv2 else -s2, fwd, IS_START, IS_END)
        row["ic_is"] = mu
        row["icir_is"] = ir
        rows.append(row)
        print(f"  {fid:22} IS {row.get('n_is_sharpe', float('nan')):7.3f}  OOS {row.get('n_oos_sharpe', float('nan')):7.3f}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "twostage" / "twostage_metrics.csv", index=False)
    best = pick_is(df)
    cols = [
        "id",
        "logic",
        "ic_is",
        "week_turn",
        "skipped_buy",
        "n_is_sharpe",
        "n_is_ret",
        "n_oos_sharpe",
        "n_oos_ret",
        "n_val_sharpe",
        "n_val_ret",
    ]
    (OUT / "twostage" / "twostage_summary.md").write_text(
        "\n".join(
            [
                "# 两段式因子组合",
                "",
                "z 分数等权混合会把反转和动能对冲掉。这里改成项目有效结构：一段门控 → 二段收到 Top5。",
                f"Best IS = `{best}`。OOS/2026 不参与选择。",
                "",
                md_table(df.sort_values("n_is_sharpe", ascending=False), cols),
                "",
            ]
        ),
        encoding="utf-8",
    )
    frozen_path = OUT / "frozen_params.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8")) if frozen_path.exists() else {}
    frozen["n_trials"] = int(frozen.get("n_trials", 0)) + int(len(df))
    frozen["best_twostage"] = best
    frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print("best_twostage", best, "n", len(df))


if __name__ == "__main__":
    main()
