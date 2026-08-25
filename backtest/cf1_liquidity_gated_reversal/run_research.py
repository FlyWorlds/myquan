"""CF1 发现集调参 + 验证集选参 + 测试集一次确认。

python backtest/cf1_liquidity_gated_reversal/run_research.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.cf1_liquidity_gated_reversal.eval_engine import (  # noqa: E402
    DISCOVERY,
    OUT_DIR,
    TEST,
    VALIDATION,
    dump_json,
    evaluate_params,
    load_ohlcv,
    metrics_row,
    split_mask,
)
from strategy.cf1_liquidity_gated_reversal import DEFAULT_PARAMS, compute_cf1  # noqa: E402

OPT = OUT_DIR / "optimize_tests"


def _save_csv(rows: list[dict], path: Path) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def _pick_best(df: pd.DataFrame) -> pd.Series:
    """主分优先，邻域稳健：同等主分取 ICIR，再取夏普。"""
    scored = df.dropna(subset=["score"]).copy()
    return scored.sort_values(["score", "rank_ic_ir", "sharpe"], ascending=False).iloc[0]


def _qa(panel: dict[str, pd.DataFrame]) -> dict:
    cl, vol, op = panel["close"], panel["volume"], panel["open"]
    return {
        "n_dates": int(len(cl.index)),
        "n_symbols": int(cl.shape[1]),
        "start": str(cl.index.min()),
        "end": str(cl.index.max()),
        "open_nan": float(op.isna().mean().mean()),
        "close_nan": float(cl.isna().mean().mean()),
        "volume_nan": float(vol.isna().mean().mean()),
        "volume_nonpos": float((vol.fillna(0) <= 0).mean().mean()),
        "close_nonpos": float((cl.fillna(0) <= 0).mean().mean()),
        "duplicate_index": bool(cl.index.has_duplicates),
    }


def main() -> None:
    OPT.mkdir(parents=True, exist_ok=True)
    print("加载 OHLCV 面板 ...", flush=True)
    panel = load_ohlcv(refresh=False)
    qa = _qa(panel)
    dump_json(OPT / "00_manifest.json", {
        "factor": "cf1",
        "name": "流动性门控反转",
        "universe": "zz500_1000_mainboard 当前成分（幸存者偏差）",
        "timing": "T close signal, T+1 open trade, open[T+1+H]/open[T+1]-1",
        "cost_one_way": 0.0015,
        "splits": {"discovery": DISCOVERY, "validation": VALIDATION, "test": TEST},
        "embargo_bars": 20,
        "primary_score": "evaluation.md v2",
        "data_qa": qa,
        "hypothesis": (
            "短期过度反应在单位成交冲击大（Amihud 高）时更可能是流动性驱动，"
            "反转应被非流动性软门放大；过低成交额分位不可交易故剔除。"
        ),
        "failure_modes": [
            "趋势市中反转失效",
            "门控把因子变成纯小盘/低流动性溢价",
            "幸存者偏差抬高历史 IC",
            "调参过拟合发现集",
        ],
    })
    print("QA", json.dumps(qa, ensure_ascii=False), flush=True)

    close, volume, opens = panel["close"], panel["volume"], panel["open"]

    # --- 1. period sweep on discovery ---
    sweep_rows = []
    phase1 = []
    for rev_n in (1, 3, 5, 10, 20):
        p = {**DEFAULT_PARAMS, "rev_n": rev_n, "horizon": 5}
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=f"rev_n={rev_n}")
        sweep_rows.append(row)
        phase1.append(row)
        print(f"  sweep rev_n={rev_n} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f} sharpe={row['sharpe']:.3f}", flush=True)
    best_n = int(_pick_best(pd.DataFrame(phase1))["rev_n"])

    phase2 = []
    for amihud_n in (10, 20, 60):
        p = {**DEFAULT_PARAMS, "rev_n": best_n, "amihud_n": amihud_n, "adv_n": amihud_n, "horizon": 5}
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=f"amihud_n={amihud_n}")
        sweep_rows.append(row)
        phase2.append(row)
        print(f"  sweep amihud_n={amihud_n} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f}", flush=True)
    best_l = int(_pick_best(pd.DataFrame(phase2))["amihud_n"])

    phase3 = []
    for gate_lo in (0.0, 0.2, 0.3, 0.4, 0.6):
        p = {**DEFAULT_PARAMS, "rev_n": best_n, "amihud_n": best_l, "adv_n": best_l, "gate_lo": gate_lo, "horizon": 5}
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=f"gate_lo={gate_lo}")
        sweep_rows.append(row)
        phase3.append(row)
        print(f"  sweep gate_lo={gate_lo} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f}", flush=True)
    best_g = float(_pick_best(pd.DataFrame(phase3))["gate_lo"])

    phase4 = []
    for h in (1, 5, 10):
        p = {**DEFAULT_PARAMS, "rev_n": best_n, "amihud_n": best_l, "adv_n": best_l, "gate_lo": best_g, "horizon": h}
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=f"horizon={h}")
        sweep_rows.append(row)
        phase4.append(row)
        print(f"  sweep horizon={h} score={row['score']:.3f} icir={row['rank_ic_ir']:.3f}", flush=True)
    best_h = int(_pick_best(pd.DataFrame(phase4))["horizon"])

    sweep_df = _save_csv(sweep_rows, OPT / "period_sweep" / "period_sweep_metrics.csv")
    best_period = {
        "rev_n": best_n,
        "amihud_n": best_l,
        "adv_n": best_l,
        "gate_lo": best_g,
        "horizon": best_h,
        "vol_scale": True,
        "skip_days": 0,
        "gate_mode": "soft_illiquid",
        "adv_floor": 0.10,
    }
    dump_json(OPT / "period_sweep" / "best_period.json", best_period)
    (OPT / "period_sweep" / "period_sweep_summary.md").write_text(
        f"# CF1 period sweep（发现集 {DISCOVERY[0]}–{DISCOVERY[1]}）\n\n"
        f"分阶段扫描，避免全笛卡尔积。选定 `{best_period}`。\n"
        f"主分最高行：{_pick_best(sweep_df).to_dict()}\n",
        encoding="utf-8",
    )

    core = {**DEFAULT_PARAMS, **best_period}

    # --- 2. ablation on discovery ---
    ablations = [
        ("original_defaults", dict(DEFAULT_PARAMS)),
        ("best_period", core),
        ("rev_only", {**core, "gate_mode": "none", "adv_floor": 0.0}),
        ("rev_adv_floor", {**core, "gate_mode": "none"}),
        ("reverse_gate_liquid", {**core, "gate_mode": "soft_liquid"}),
        ("hard_illiquid", {**core, "gate_mode": "hard_illiquid"}),
        ("amihud_as_signal", {**core, "gate_mode": "none", "vol_scale": False, "rev_n": 1}),
        ("no_vol_scale", {**core, "vol_scale": False}),
        ("no_adv_floor", {**core, "adv_floor": 0.0}),
    ]
    # amihud-as-signal: actually need a different compute; skip fake, use none-gate 1d rev as weak proxy
    abl_rows = []
    for name, p in ablations:
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=name)
        abl_rows.append(row)
        print(f"  abl {name}: score={row['score']:.3f} icir={row['rank_ic_ir']:.3f} sharpe={row['sharpe']:.3f}", flush=True)
    abl_df = _save_csv(abl_rows, OPT / "ablation" / "ablation_metrics.csv")

    # --- 3. refinement from core ---
    refinements = [
        ("core", core),
        ("skip1", {**core, "skip_days": 1}),
        ("vol_n_rev", {**core, "vol_n": int(core["rev_n"])}),
        ("gate_lo_neighbor_m01", {**core, "gate_lo": max(0.0, float(core["gate_lo"]) - 0.1)}),
        ("gate_lo_neighbor_p01", {**core, "gate_lo": min(0.8, float(core["gate_lo"]) + 0.1)}),
        ("adv_floor_05", {**core, "adv_floor": 0.05}),
        ("adv_floor_20", {**core, "adv_floor": 0.20}),
        ("hard_core", {**core, "gate_mode": "hard_illiquid"}),
    ]
    ref_rows = []
    for name, p in refinements:
        ev = evaluate_params(close, volume, opens, p, split="discovery")
        row = metrics_row(ev, name=name)
        ref_rows.append(row)
        print(f"  ref {name}: score={row['score']:.3f} icir={row['rank_ic_ir']:.3f}", flush=True)
    ref_df = _save_csv(ref_rows, OPT / "refinement" / "refinement_metrics.csv")
    best_ref_name = str(_pick_best(ref_df)["name"])
    best_ref_params = dict(next(p for n, p in refinements if n == best_ref_name))

    # --- 4. validation selection among frozen shortlist ---
    shortlist = {
        "original_defaults": dict(DEFAULT_PARAMS),
        "best_period": core,
        "core": core,
        "best_refinement": best_ref_params,
        "rev_only": {**core, "gate_mode": "none", "adv_floor": 0.0},
    }
    val_rows = []
    for name, p in shortlist.items():
        ev = evaluate_params(close, volume, opens, p, split="validation")
        row = metrics_row(ev, name=name)
        val_rows.append(row)
        print(f"  valid {name}: score={row['score']:.3f} icir={row['rank_ic_ir']:.3f} sharpe={row['sharpe']:.3f}", flush=True)
    val_df = _save_csv(val_rows, OPT / "validation_metrics.csv")
    frozen_name = str(_pick_best(val_df)["name"])
    frozen = dict(shortlist[frozen_name])

    # --- 5. test once ---
    test_ev = evaluate_params(close, volume, opens, frozen, split="test")
    test_row = metrics_row(test_ev, name="frozen_test_once")
    _save_csv([test_row], OPT / "test_once_metrics.csv")
    print(f"  TEST ONCE score={test_row['score']:.3f} icir={test_row['rank_ic_ir']:.3f} sharpe={test_row['sharpe']:.3f} ret={test_row['ann_ret']:.3f}", flush=True)

    # --- 6. placebo shuffle on discovery ---
    rng = np.random.default_rng(42)
    sig = compute_cf1(close, volume, params=frozen)
    mask = split_mask(opens.index, "discovery")
    sig_d = sig.loc[mask.values].copy()
    shuffled = sig_d.copy()
    for i in range(len(shuffled)):
        row = shuffled.iloc[i].to_numpy()
        idx = np.where(np.isfinite(row))[0]
        if len(idx) > 5:
            perm = rng.permutation(idx)
            new = row.copy()
            new[idx] = row[perm]
            shuffled.iloc[i] = new
    from backtest.cf1_liquidity_gated_reversal.eval_engine import evaluate_split

    placebo = evaluate_split(
        shuffled,
        opens.loc[mask.values],
        split="discovery",
        horizon=int(frozen["horizon"]),
        top_frac=float(frozen["top_frac"]),
    )
    # evaluate_split will re-mask discovery; pass already sliced frames with dummy split
    # simpler: IC of shuffled vs fwd on discovery
    from backtest.cf1_liquidity_gated_reversal.eval_engine import both_ic, forward_open_return

    fwd = forward_open_return(opens.loc[mask.values], int(frozen["horizon"]))
    mn = fwd.sub(fwd.mean(axis=1), axis=0)
    pic = both_ic(shuffled, mn)
    print(f"  placebo shuffle rank_ic_mean={pic['rank_ic_mean']:.4f} ir={pic['rank_ic_ir']:.3f}", flush=True)

    # yearly IC on frozen full sample for report (test years labeled)
    ic_year = []
    ric = test_ev.get("rank_ic_series")
    # compute full IC series on frozen
    full_ev_disc = evaluate_params(close, volume, opens, frozen, split="discovery")
    for split_name in ("discovery", "validation", "test"):
        ev = evaluate_params(close, volume, opens, frozen, split=split_name)
        ser = ev["rank_ic_series"].dropna()
        if ser.empty:
            continue
        g = ser.groupby(ser.index.year).mean()
        for y, v in g.items():
            ic_year.append({"split": split_name, "year": int(y), "rank_ic_mean": float(v)})
    _save_csv(ic_year, OPT / "frozen_ic_by_year.csv")

    summary = {
        "best_period": best_period,
        "best_refinement": {"name": best_ref_name, "params": best_ref_params},
        "frozen_by_validation": {"name": frozen_name, "params": frozen},
        "discovery_best_period_score": float(_pick_best(pd.DataFrame([r for r in sweep_rows if r["name"].startswith("horizon") or True])).get("score", np.nan) if False else metrics_row(evaluate_params(close, volume, opens, core, split="discovery"), name="x")["score"]),
        "validation": val_df.set_index("name")["score"].to_dict(),
        "test_once": test_row,
        "placebo_rank_ic_mean": pic["rank_ic_mean"],
        "placebo_rank_ic_ir": pic["rank_ic_ir"],
        "trials_n": len(sweep_rows) + len(abl_rows) + len(ref_rows) + len(val_rows) + 1,
        "data_end": qa["end"],
    }
    # cleaner discovery score for frozen
    disc_frozen = metrics_row(evaluate_params(close, volume, opens, frozen, split="discovery"), name="frozen_discovery")
    val_frozen = metrics_row(evaluate_params(close, volume, opens, frozen, split="validation"), name="frozen_validation")
    summary["frozen_discovery"] = disc_frozen
    summary["frozen_validation"] = val_frozen
    dump_json(OPT / "frozen_summary.json", summary)

    # correlation vs ungated reversal (discovery)
    ungated = compute_cf1(close, volume, params={**frozen, "gate_mode": "none", "adv_floor": 0.0})
    gated = compute_cf1(close, volume, params=frozen)
    dmask = split_mask(opens.index, "discovery")
    a = gated.loc[dmask.values]
    b = ungated.loc[dmask.values]
    rho = a.corrwith(b, axis=1).mean()
    summary["corr_vs_ungated_rev"] = float(rho) if pd.notna(rho) else None
    dump_json(OPT / "frozen_summary.json", summary)
    print(f"  corr vs ungated rev={rho:.3f}", flush=True)
    print("done", OPT, flush=True)


if __name__ == "__main__":
    main()
