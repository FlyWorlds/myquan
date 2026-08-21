"""可审计的单点因子挖掘、相关性门禁与固定评分。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.chan.features import FACTOR_CANDIDATES
from strategy.strategies.strategy2.backtest import (
    ANNUAL_BARS,
    derive_eligibility,
    run_chan_backtest,
)


def primary_score(
    rank_ic_ir: float,
    sharpe: float,
    ann_ret: float,
    max_dd: float,
    mono: float,
    ann_turnover: float,
) -> float:
    clip = lambda x, lo, hi: max(lo, min(hi, float(x)))
    ic_term = clip(rank_ic_ir / 3.0, -2, 2)
    shp_term = clip((sharpe + 0.5) / 1.0, -2, 2)
    ret_term = clip(ann_ret / 0.10, -2, 2)
    mdd_term = clip(1 + max_dd / 0.30, -2, 1)
    mono_term = clip(mono, -1, 1)
    turn_term = -clip(ann_turnover / 30.0 - 1.0, 0, 3)
    return float(
        0.20 * ic_term
        + 0.30 * shp_term
        + 0.30 * ret_term
        + 0.20 * mdd_term
        + 0.10 * mono_term
        + 0.10 * turn_term
    )


def cs_winsorize_zscore(
    frame: pd.DataFrame,
    column: str,
    *,
    min_cross_section: int = 30,
    n_mad: float = 3.0,
    eligible_col: str | None = None,
) -> pd.Series:
    work = frame
    if eligible_col and eligible_col in frame.columns:
        work = frame.copy()
        blocked = ~work[eligible_col].fillna(False).astype(bool)
        work.loc[blocked, column] = np.nan
    wide = (
        work.assign(_value=pd.to_numeric(work[column], errors="coerce"))
        .pivot_table(index="dt", columns="symbol", values="_value", aggfunc="last")
    )
    count = wide.count(axis=1)
    median = wide.median(axis=1)
    mad = wide.sub(median, axis=0).abs().median(axis=1)
    sigma = 1.4826 * mad
    upper = median + n_mad * sigma
    lower = median - n_mad * sigma
    clipped = wide.clip(lower=lower, upper=upper, axis=0)
    mu = clipped.mean(axis=1)
    std = clipped.std(axis=1, ddof=1).replace(0, np.nan)
    z = clipped.sub(mu, axis=0).div(std, axis=0)
    z = z.where(count >= min_cross_section)
    stacked = z.stack(future_stack=True).rename(column)
    stacked.index.names = ["dt", "symbol"]
    keys = frame[["dt", "symbol"]].copy()
    keys["dt"] = pd.to_datetime(keys["dt"])
    aligned = stacked.reindex(pd.MultiIndex.from_frame(keys))
    aligned.index = frame.index
    return aligned.astype(float)


def _forward_open_return(panel: pd.DataFrame) -> pd.Series:
    wide = panel.pivot_table(index="dt", columns="symbol", values="open", aggfunc="last")
    fwd = wide.shift(-2).div(wide.shift(-1)).sub(1.0)
    stacked = fwd.stack(future_stack=True)
    stacked.index.names = ["dt", "symbol"]
    keys = panel[["dt", "symbol"]].copy()
    keys["dt"] = pd.to_datetime(keys["dt"])
    aligned = stacked.reindex(pd.MultiIndex.from_frame(keys))
    aligned.index = panel.index
    return aligned


def _split_window(start: str, end: str, *, config: ChanStrategyConfig, role: str) -> tuple[str, str]:
    begin = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    purge = pd.Timedelta(days=int(config.purge_days))
    if role == "discovery":
        stop = stop - purge
    elif role == "validation":
        begin = begin + purge
    return begin.strftime("%Y%m%d"), stop.strftime("%Y%m%d")


def _rank_ic(signal: pd.Series, target: pd.Series, dates: pd.Series, minimum: int) -> pd.Series:
    temp = pd.DataFrame(
        {
            "dt": pd.to_datetime(dates).to_numpy(),
            "signal": pd.to_numeric(signal, errors="coerce").to_numpy(),
            "target": pd.to_numeric(target, errors="coerce").to_numpy(),
        }
    ).dropna()
    if temp.empty:
        return pd.Series(dtype=float)
    temp["sr"] = temp.groupby("dt")["signal"].rank()
    temp["tr"] = temp.groupby("dt")["target"].rank()
    temp["sr"] = temp["sr"] - temp.groupby("dt")["sr"].transform("mean")
    temp["tr"] = temp["tr"] - temp.groupby("dt")["tr"].transform("mean")
    num = (temp["sr"] * temp["tr"]).groupby(temp["dt"]).sum()
    den = np.sqrt(
        (temp["sr"] ** 2).groupby(temp["dt"]).sum()
        * (temp["tr"] ** 2).groupby(temp["dt"]).sum()
    )
    count = temp.groupby("dt").size()
    ic = num.div(den.replace(0, np.nan))
    return ic.where(count >= minimum).dropna()


def _monotonicity(signal: pd.Series, target: pd.Series, dates: pd.Series) -> float:
    temp = pd.DataFrame(
        {
            "dt": pd.to_datetime(dates).to_numpy(),
            "signal": pd.to_numeric(signal, errors="coerce").to_numpy(),
            "target": pd.to_numeric(target, errors="coerce").to_numpy(),
        }
    ).dropna()
    if temp.empty:
        return 0.0
    temp["rank"] = temp.groupby("dt")["signal"].rank(method="first")
    temp["n"] = temp.groupby("dt")["signal"].transform("size")
    temp["bucket"] = ((temp["rank"] - 1) / temp["n"].clip(lower=1) * 5).clip(upper=4).astype(int)
    bucket_return = temp.groupby("bucket")["target"].mean().dropna()
    if len(bucket_return) < 3:
        return 0.0
    return float(np.corrcoef(bucket_return.index.astype(float), bucket_return.to_numpy())[0, 1])


def _mean_cross_section_correlation(
    panel: pd.DataFrame, left: str, right: str, minimum: int
) -> float:
    left_w = panel.pivot_table(index="dt", columns="symbol", values=left, aggfunc="last")
    right_w = panel.pivot_table(index="dt", columns="symbol", values=right, aggfunc="last")
    cols = left_w.columns.intersection(right_w.columns)
    left_w = left_w[cols]
    right_w = right_w[cols]
    left_z = left_w.sub(left_w.mean(axis=1), axis=0).div(left_w.std(axis=1, ddof=1).replace(0, np.nan), axis=0)
    right_z = right_w.sub(right_w.mean(axis=1), axis=0).div(right_w.std(axis=1, ddof=1).replace(0, np.nan), axis=0)
    prod = (left_z * right_z).mean(axis=1)
    valid = left_w.notna().sum(axis=1).ge(minimum) & right_w.notna().sum(axis=1).ge(minimum)
    values = prod.where(valid).dropna()
    return float(values.mean()) if len(values) else 0.0


@dataclass
class FactorMiningResult:
    journal: pd.DataFrame
    accepted: list[str]
    combined_column: str | None
    panel: pd.DataFrame
    metadata: dict[str, Any]

    def save(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.journal.to_csv(output_dir / "factor_journal.csv", index=False)
        self.panel.to_parquet(output_dir / "mined_feature_panel.parquet", index=False)
        (output_dir / "factor_selection.json").write_text(
            json.dumps(
                self.metadata
                | {
                    "accepted": self.accepted,
                    "combined_column": self.combined_column,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        from strategy.strategies.strategy2.frozen_combo import save_frozen_combo

        save_frozen_combo(
            {
                "members": self.metadata.get("blend_members") or self.accepted,
                "scheme": self.metadata.get("blend_scheme") or "equal",
                "weights": self.metadata.get("blend_weights") or {},
                "meets_target": bool(self.metadata.get("meets_sharpe_target")),
                "validation_sharpe": self.metadata.get("blend_validation_sharpe"),
            }
        )


def evaluate_factor(
    panel: pd.DataFrame,
    factor: str,
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    start: str,
    end: str,
    split_role: str = "discovery",
) -> tuple[dict[str, float], pd.Series]:
    start, end = _split_window(start, end, config=config, role=split_role)
    data = panel.copy()
    min_cs = int(config.min_cross_section)
    if "eligible_long" in data.columns:
        median_n = data.groupby("dt")["eligible_long"].sum().median()
        if pd.notna(median_n):
            min_cs = max(3, min(int(config.min_eligible), int(median_n)))
    normalized = cs_winsorize_zscore(
        data,
        factor,
        min_cross_section=min_cs,
        eligible_col="eligible_long" if "eligible_long" in data.columns else None,
    )
    data["_candidate_signal"] = normalized
    period = data[
        (pd.to_datetime(data["dt"]) >= pd.Timestamp(start))
        & (pd.to_datetime(data["dt"]) <= pd.Timestamp(end) + pd.Timedelta(days=1))
    ].copy()
    target = _forward_open_return(period)
    period["_target"] = target.to_numpy()
    ic_src = period
    if "eligible_long" in period.columns:
        ic_src = period[period["eligible_long"].fillna(False)]
    ic = _rank_ic(
        ic_src["_candidate_signal"],
        ic_src["_target"],
        ic_src["dt"],
        min_cs,
    )
    ic_std = float(ic.std(ddof=1)) if len(ic) > 1 else 0.0
    rank_ic_ir = (
        float(ic.mean() / ic_std * np.sqrt(ANNUAL_BARS)) if ic_std > 0 else 0.0
    )
    monotonicity = _monotonicity(ic_src["_candidate_signal"], ic_src["_target"], ic_src["dt"])
    backtest = run_chan_backtest(
        period,
        factor_column="_candidate_signal",
        config=config,
        fee_rate=config.fee_rate,
    )
    stats = backtest.stats
    score = primary_score(
        rank_ic_ir,
        stats["sharpe"],
        stats["annual_return"],
        stats["max_drawdown"],
        monotonicity,
        stats["annual_turnover"],
    )
    metrics = {
        "rank_ic_mean": float(ic.mean()) if len(ic) else 0.0,
        "rank_ic_ir": rank_ic_ir,
        "monotonicity": monotonicity,
        "sharpe": float(stats["sharpe"]),
        "annual_return": float(stats["annual_return"]),
        "max_drawdown": float(stats["max_drawdown"]),
        "annual_turnover": float(stats["annual_turnover"]),
        "score": score,
    }
    return metrics, normalized


def mine_factors(
    panel: pd.DataFrame,
    *,
    candidates: Iterable[str] = FACTOR_CANDIDATES,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    max_factors: int = 5,
) -> FactorMiningResult:
    data = panel.copy()
    data["dt"] = pd.to_datetime(data["dt"])
    if "eligible_long" not in data.columns:
        data = derive_eligibility(
            data, candidate_timeout_bars=config.candidate_timeout_bars
        )
    journal: list[dict[str, Any]] = []
    accepted: list[str] = []
    normalized_columns: list[str] = []

    baseline_start, baseline_end = _split_window(
        config.validation_start,
        config.validation_end,
        config=config,
        role="validation",
    )
    baseline = run_chan_backtest(
        data,
        factor_column=None,
        config=config,
        start=baseline_start,
        end=baseline_end,
        fee_rate=config.fee_rate,
    )
    journal.append(
        {
            "op_type": "baseline",
            "hypothesis": "一买候选后二买确认、等权持有即可获利",
            "change": "无连续因子排序",
            "expected": "作为后续因子必须超越的对照",
            "factor": "baseline_equal_weight",
            "status": "BASELINE",
            "reason": "reference",
            "max_abs_correlation": 0.0,
            "validation_sharpe": float(baseline.stats["sharpe"]),
            "validation_annual_return": float(baseline.stats["annual_return"]),
            "validation_max_drawdown": float(baseline.stats["max_drawdown"]),
            "validation_score": 0.0,
        }
    )
    baseline_sharpe = float(baseline.stats["sharpe"])

    for factor in candidates:
        note = {
            "op_type": "add_factor",
            "hypothesis": f"{factor} 对二买确认后的下一期开盘收益有增量解释力",
            "change": f"仅加入 {factor}",
            "expected": "验证集固定主分>0且相关性门禁通过",
            "factor": factor,
        }
        if factor not in data:
            journal.append(note | {"status": "CRASH", "reason": "missing_column"})
            continue
        try:
            discovery, normalized = evaluate_factor(
                data,
                factor,
                config=config,
                start=config.discovery_start,
                end=config.discovery_end,
                split_role="discovery",
            )
            col = f"z_{factor}"
            data[col] = normalized
            validation, _ = evaluate_factor(
                data,
                factor,
                config=config,
                start=config.validation_start,
                end=config.validation_end,
                split_role="validation",
            )
            correlations = [
                abs(
                    _mean_cross_section_correlation(
                        data, col, previous, config.min_cross_section
                    )
                )
                for previous in normalized_columns
            ]
            max_corr = max(correlations, default=0.0)
            prefer_corr = max_corr < config.correlation_prefer
            accepted_now = (
                discovery["score"] > 0.0
                and validation["score"] > 0.0
                and validation["sharpe"] > max(0.0, baseline_sharpe)
                and max_corr < config.correlation_reject
                and len(accepted) < max_factors
            )
            status = "ACCEPTED" if accepted_now else "REJECTED"
            if accepted_now:
                reason = "passed"
            elif max_corr >= config.correlation_reject:
                reason = "correlation_gate"
            elif len(accepted) >= max_factors:
                reason = "max_factors"
            elif discovery["score"] <= 0.0:
                reason = "discovery_score"
            else:
                reason = "validation_score"
            journal.append(
                note
                | {
                    "status": status,
                    "reason": reason,
                    "max_abs_correlation": max_corr,
                    "prefer_low_corr": prefer_corr,
                    **{f"discovery_{k}": v for k, v in discovery.items()},
                    **{f"validation_{k}": v for k, v in validation.items()},
                }
            )
            if accepted_now:
                accepted.append(factor)
                normalized_columns.append(col)
        except Exception as exc:
            journal.append(
                note | {"status": "CRASH", "reason": f"{type(exc).__name__}: {exc}"}
            )

    from strategy.chan.blend import blend_accepted_factors

    journal_df = pd.DataFrame(journal)
    blended = blend_accepted_factors(data, journal_df, config=config)
    if blended.scheme_rows:
        journal.extend(blended.scheme_rows)
        journal_df = pd.DataFrame(journal)
    combined_column = blended.combined_column
    metadata = {
        "search_trials": int(len(journal)),
        "discovery": [config.discovery_start, config.discovery_end],
        "validation": [config.validation_start, config.validation_end],
        "final_test": [config.test_start, config.test_end],
        "final_test_touched": False,
        "correlation_reject": config.correlation_reject,
        "research_only": True,
        "blend_scheme": blended.scheme,
        "blend_weights": blended.weights,
        "blend_members": blended.members,
        "blend_validation_sharpe": (
            None
            if blended.validation_sharpe != blended.validation_sharpe
            else float(blended.validation_sharpe)
        ),
        "meets_sharpe_target": blended.meets_target,
        "target_sharpe": 0.8,
    }
    return FactorMiningResult(
        journal=journal_df,
        accepted=blended.members or accepted,
        combined_column=combined_column,
        panel=data,
        metadata=metadata,
    )


__all__ = [
    "FactorMiningResult",
    "cs_winsorize_zscore",
    "evaluate_factor",
    "mine_factors",
    "primary_score",
]
