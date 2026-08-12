"""中证500+1000 · 反转因子拟合度验证：SPSS风格因子检验 + CFA + 样本内外过拟合。

验证对象：策略五默认 rev 族（多窗口作为观测指标 → 潜在「反转」因子）
股票池：zz500_1000_mainboard
无未来函数：因子用当日及历史；预测力用次日开盘持有 hold 日远期收益。
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix, simulate_fast  # noqa: E402
from backtest.zz1000_momentum_select import PANEL_PATH_ZZ500_1000  # noqa: E402
from strategy.strategies.strategy5.portfolio import PORTFOLIO_DEFAULTS  # noqa: E402

OUT = Path(__file__).resolve().parent / "factor4_out"
WINDOWS = (20, 40, 60, 90, 120)
HOLD = int(PORTFOLIO_DEFAULTS["hold_days"])
TOP_K = int(PORTFOLIO_DEFAULTS["top_k"])
N_MAIN = int(PORTFOLIO_DEFAULTS["n"])

TRAIN = ("20200101", "20221231")
VALID = ("20230101", "20231231")
TEST = ("20240101", None)
FULL = ("20200101", None)


def _tz(s: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _slice(df: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    a = _tz(start, df.index)
    out = df.loc[df.index >= a]
    if end is not None:
        b = _tz(end, df.index)
        out = out.loc[out.index <= b]
    return out


def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def kmo_bartlett(corr: np.ndarray) -> dict:
    """SPSS 风格：KMO 与 Bartlett 球形检验。"""
    from factor_analyzer.factor_analyzer import calculate_bartlett_sphericity, calculate_kmo

    # factor_analyzer 要原始数据或相关；用相关矩阵构造伪数据不稳，改用样本矩阵
    # 这里接收相关矩阵时用公式手算 KMO，Bartlett 用手算
    p = corr.shape[0]
    # Bartlett
    n_eff = None  # 由调用方传入更好；此处只算基于相关的近似，真实 n 外传
    det = float(np.linalg.det(corr))
    # KMO via partial correlations
    try:
        inv = np.linalg.inv(corr)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(corr)
    # partial corr
    d = np.sqrt(np.diag(inv))
    partial = -inv / np.outer(d, d)
    np.fill_diagonal(partial, 1.0)
    corr2 = corr**2
    part2 = partial**2
    np.fill_diagonal(corr2, 0.0)
    np.fill_diagonal(part2, 0.0)
    kmo_num = corr2.sum()
    kmo_den = kmo_num + part2.sum()
    kmo = float(kmo_num / kmo_den) if kmo_den > 0 else float("nan")
    # per-item KMO
    kmo_vars = []
    for i in range(p):
        num = corr2[i].sum()
        den = num + part2[i].sum()
        kmo_vars.append(float(num / den) if den > 0 else float("nan"))
    return {
        "kmo_overall": kmo,
        "kmo_vars": kmo_vars,
        "corr_det": det,
        "n_vars": p,
    }


def bartlett_test(corr: np.ndarray, n: int) -> dict:
    p = corr.shape[0]
    det = max(float(np.linalg.det(corr)), 1e-300)
    chi2 = -((n - 1) - (2 * p + 5) / 6) * np.log(det)
    df = p * (p - 1) / 2
    pval = float(1 - stats.chi2.cdf(chi2, df))
    return {"chi2": float(chi2), "df": float(df), "p_value": pval, "n": n}


def efa_loadings(data: pd.DataFrame, n_factors: int = 1) -> dict:
    """探索性因子分析（主成分/最大似然近似，兼容新版 sklearn）。"""
    from numpy.linalg import eigvalsh
    from sklearn.decomposition import FactorAnalysis

    X = data.to_numpy(dtype=float)
    # 特征值（相关阵）用于碎石图判读
    corr = np.corrcoef(X, rowvar=False)
    ev = eigvalsh(corr)[::-1]
    fa = FactorAnalysis(n_components=n_factors, max_iter=1000, random_state=0)
    fa.fit(X)
    loads = fa.components_.T  # (n_features, n_factors)
    # 共同度 ≈ 载荷平方和
    commun = np.sum(loads**2, axis=1)
    ss = np.sum(loads**2, axis=0)
    prop = ss / corr.shape[0]
    cum = np.cumsum(prop)
    return {
        "method": "sklearn.FactorAnalysis",
        "loadings": loads.tolist(),
        "variables": list(data.columns),
        "eigenvalues": [float(x) for x in ev[:5]],
        "variance": {
            "ss_loadings": [float(x) for x in ss],
            "prop_var": [float(x) for x in prop],
            "cum_var": [float(x) for x in cum],
        },
        "communalities": [float(x) for x in commun],
    }


def cfa_one_factor(data: pd.DataFrame) -> dict:
    """单因子 CFA：Reversal =~ rev20+...+rev120"""
    import semopy

    cols = list(data.columns)
    model = "Reversal =~ " + " + ".join(cols)
    mod = semopy.Model(model)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod.fit(data)
    insp = mod.inspect()
    stats_df = semopy.calc_stats(mod)
    loads: dict[str, dict] = {}
    # inspect 常见列：lval, op, rval, Estimate, Std. Err, z-value, p-value
    cols_map = {c.lower(): c for c in insp.columns}
    lval_c = cols_map.get("lval") or insp.columns[0]
    op_c = cols_map.get("op")
    rval_c = cols_map.get("rval") or (insp.columns[2] if len(insp.columns) > 2 else None)
    est_c = cols_map.get("estimate") or "Estimate"
    z_c = cols_map.get("z-value") or cols_map.get("z value")
    p_c = cols_map.get("p-value") or cols_map.get("p value")
    for _, row in insp.iterrows():
        lval = str(row[lval_c])
        rval = str(row[rval_c]) if rval_c is not None else ""
        op = str(row[op_c]) if op_c is not None else "~"
        if op not in ("~", "=~") and "Reversal" not in (lval, rval):
            continue
        ind = None
        if lval in cols and rval == "Reversal":
            ind = lval
        elif rval in cols and lval == "Reversal":
            ind = rval
        if ind is None:
            continue
        def _f(v):
            try:
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return None
                if isinstance(v, str) and v.strip() in ("-", "", "nan", "None"):
                    return None
                return float(v)
            except (TypeError, ValueError):
                return None

        est = _f(row[est_c]) if est_c in insp.columns else None
        z = _f(row[z_c]) if z_c and z_c in insp.columns else None
        p = _f(row[p_c]) if p_c and p_c in insp.columns else None
        loads[ind] = {"est": est, "z": z, "p": p}

    fit: dict[str, float] = {}
    if isinstance(stats_df, pd.DataFrame) and len(stats_df):
        # calc_stats 常返回 index=指标名
        if stats_df.shape[0] > stats_df.shape[1]:
            series = stats_df.iloc[:, 0]
            for k, v in series.items():
                try:
                    fit[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
        else:
            row = stats_df.iloc[0]
            for k, v in row.items():
                try:
                    if pd.notna(v):
                        fit[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
    return {"model": model, "loadings": loads, "fit": fit}


def ic_series(fac: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    rows = []
    for d in fac.index:
        if d not in fwd.index:
            continue
        x, y = fac.loc[d], fwd.loc[d]
        m = x.notna() & y.notna()
        if int(m.sum()) < 80:
            continue
        ic = float(x[m].corr(y[m], method="spearman"))
        if np.isfinite(ic):
            rows.append((d, ic))
    return pd.Series({d: v for d, v in rows})


def summarize_ic(s: pd.Series) -> dict:
    arr = s.to_numpy(dtype=float)
    if len(arr) < 5:
        return {"n": len(arr)}
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    ir = mean / std if std > 1e-12 else 0.0
    t = mean / (std / np.sqrt(len(arr))) if std > 1e-12 else 0.0
    p = float(2 * (1 - stats.t.cdf(abs(t), len(arr) - 1)))
    return {
        "n": int(len(arr)),
        "IC_mean": mean,
        "IC_std": std,
        "IC_IR": ir,
        "t_stat": float(t),
        "p_value": p,
        "IC_pos": float((arr > 0).mean()),
        "IC_median": float(np.median(arr)),
    }


def _sim(fac, opens, closes, start, end, hold=HOLD, top_k=TOP_K):
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        bt_end = _tz(end, closes.index)
        m = closes.index <= bt_end
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
    return simulate_fast(
        f,
        op,
        cl,
        bt_start=bt_start,
        top_k=top_k,
        hold_days=hold,
        min_score=None,
        require_above_ma=None,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PANEL_PATH_ZZ500_1000.exists():
        raise FileNotFoundError(
            f"缺少面板 {PANEL_PATH_ZZ500_1000}，请先: python factor4.py --universe zz500_1000_mainboard"
        )
    wide = pd.read_parquet(PANEL_PATH_ZZ500_1000)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    print(f"panel {closes.shape}")

    # ---- 多窗口反转因子（截面 z）----
    raw = {}
    zfac = {}
    for n in WINDOWS:
        r = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        raw[n] = r
        zfac[n] = _cs_z(r)
        print(f"  rev{n} ready")

    # 构造 CFA/EFA 样本：抽样交易日，堆叠股票截面 z 分数
    rng = np.random.default_rng(42)
    dates = [d for d in closes.index if d >= _tz("20200101", closes.index)]
    # 每隔约 5 日抽一天，降低序列相关
    sample_dates = dates[::5]
    frames = []
    for d in sample_dates:
        cols = {}
        ok = True
        for n in WINDOWS:
            s = zfac[n].loc[d]
            cols[f"rev{n}"] = s
            if s.notna().sum() < 100:
                ok = False
                break
        if not ok:
            continue
        part = pd.DataFrame(cols).dropna()
        if len(part) < 50:
            continue
        # 每日最多抽 200 只，控制样本规模
        if len(part) > 200:
            part = part.sample(200, random_state=int(rng.integers(0, 1_000_000)))
        frames.append(part)
    data = pd.concat(frames, ignore_index=True)
    # CFA/EFA 对超大 N 很慢且卡方易膨胀，随机抽 8000
    if len(data) > 8000:
        data = data.sample(8000, random_state=42).reset_index(drop=True)
    print(f"CFA/EFA sample rows={len(data)} cols={list(data.columns)}")

    corr = data.corr(method="pearson").to_numpy()
    kmo = kmo_bartlett(corr)
    # 用 factor_analyzer 官方 KMO（更贴近 SPSS）
    from factor_analyzer.factor_analyzer import calculate_bartlett_sphericity, calculate_kmo

    kmo_fa, kmo_model = calculate_kmo(data)
    chi2_b, p_b = calculate_bartlett_sphericity(data)
    bart = {
        "chi2": float(chi2_b),
        "p_value": float(p_b),
        "n": int(len(data)),
        "df": float(data.shape[1] * (data.shape[1] - 1) / 2),
    }
    spss = {
        "kmo_overall": float(kmo_model),
        "kmo_vars": {
            c: float(v) for c, v in zip(data.columns, np.atleast_1d(kmo_fa).ravel())
        },
        "bartlett": bart,
        "corr": data.corr().round(4).to_dict(),
        "kmo_hand": kmo,
        "interpretation": {
            "kmo": (
                "极适合做因子分析"
                if kmo_model >= 0.9
                else "适合"
                if kmo_model >= 0.8
                else "一般"
                if kmo_model >= 0.7
                else "勉强"
                if kmo_model >= 0.6
                else "不适合"
            ),
            "bartlett": "拒绝单位相关阵（适合因子分析）"
            if bart["p_value"] < 0.05
            else "不能拒绝单位相关阵",
        },
    }
    print(
        f"KMO={spss['kmo_overall']:.3f} ({spss['interpretation']['kmo']})  "
        f"Bartlett p={bart['p_value']:.2e}"
    )

    efa = efa_loadings(data, n_factors=1)
    print("EFA eigenvalues", efa["eigenvalues"][:3], "cum_var", efa["variance"]["cum_var"])

    cfa = cfa_one_factor(data)
    print("CFA fit", {k: cfa["fit"].get(k) for k in ("CFI", "TLI", "RMSEA", "chi2")})

    # 非重叠窗口 CFA（更干净的验证性模型）
    data_sparse = data[["rev20", "rev60", "rev120"]].copy()
    cfa_sparse = cfa_one_factor(data_sparse)
    print(
        "CFA sparse(20/60/120) fit",
        {k: cfa_sparse["fit"].get(k) for k in ("CFI", "TLI", "RMSEA", "chi2")},
    )

    # ---- 预测效度 / 过拟合：IC + 策略（对齐当前默认 mode）----
    fwd = opens.shift(-HOLD) / opens.shift(-1) - 1.0
    mode = str(PORTFOLIO_DEFAULTS.get("mode") or "plain")
    n2 = PORTFOLIO_DEFAULTS.get("n2")
    w = float(PORTFOLIO_DEFAULTS.get("w") or 1.0)
    vmax = PORTFOLIO_DEFAULTS.get("vol_max_pct")

    def _rev(n: int) -> pd.DataFrame:
        if n in raw:
            return raw[n]
        r = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        raw[n] = r
        return r

    if mode in ("dual", "dual_w") and n2:
        main_fac = _cs_z(_rev(N_MAIN)) + w * _cs_z(_rev(int(n2)))
        main_label = f"dual(rev{N_MAIN}+rev{int(n2)}*w{w:g})"
    elif mode == "vol_mask":
        rev = _rev(N_MAIN)
        vol = closes.pct_change().rolling(20, min_periods=10).std()
        rnk = vol.rank(axis=1, pct=True, method="average")
        vv = float(vmax or 0.75)
        main_fac = rev.where(rnk <= vv)
        main_label = f"vol_mask(rev{N_MAIN},vmax={vv:g})"
    else:
        main_fac = _rev(N_MAIN)
        main_label = f"rev(n={N_MAIN})"
    print(f"predictive factor = {main_label}, hold={HOLD}, top_k={TOP_K}")

    # 等权买入持有基准（收盘链），用于超额
    def _ew_bh(start: str, end: str | None) -> float:
        a = _tz(start, closes.index)
        cl = closes.loc[closes.index >= a]
        if end is not None:
            b = _tz(end, closes.index)
            cl = cl.loc[cl.index <= b]
        daily = cl.pct_change().mean(axis=1).dropna()
        if daily.empty:
            return float("nan")
        return float((1.0 + daily).prod() - 1.0)

    bh = {lab: _ew_bh(a, b) for lab, (a, b) in {
        "train": TRAIN, "valid": VALID, "test": TEST, "full": FULL
    }.items()}
    print("EW-BH", {k: round(v, 4) for k, v in bh.items()})
    ic_all = {}
    for label, (a, b) in {
        "train": TRAIN,
        "valid": VALID,
        "test": TEST,
        "full": FULL,
    }.items():
        fac_p = _slice(main_fac, a, b)
        fwd_p = _slice(fwd, a, b)
        ic_all[label] = summarize_ic(ic_series(fac_p, fwd_p))
        print(f"IC {label}: {ic_all[label]}")

    strat = {}
    for label, (a, b) in {
        "train": TRAIN,
        "valid": VALID,
        "test": TEST,
        "full": FULL,
    }.items():
        m = _sim(main_fac, opens, closes, a, b)
        strat[label] = {
            "sharpe": m["sharpe"],
            "ret": m["ret"],
            "dd": m["dd"],
            "n_buys": m["n_buys"],
            "bh": bh[label],
            "excess": float(m["ret"] - bh[label]),
        }
        print(
            f"STRAT {label}: sharpe={m['sharpe']:.3f} ret={m['ret']*100:.1f}% "
            f"excess={strat[label]['excess']*100:.1f}% dd={m['dd']*100:.1f}%"
        )

    # 过拟合指标
    is_sharpe = float(np.mean([strat["train"]["sharpe"], strat["valid"]["sharpe"]]))
    oos_sharpe = float(strat["test"]["sharpe"])
    decay = 1.0 - (oos_sharpe / is_sharpe) if abs(is_sharpe) > 1e-9 else float("nan")
    ic_is = float(np.mean([ic_all["train"]["IC_mean"], ic_all["valid"]["IC_mean"]]))
    ic_oos = float(ic_all["test"]["IC_mean"])
    ic_decay = 1.0 - (ic_oos / ic_is) if abs(ic_is) > 1e-9 else float("nan")

    overfitting = {
        "is_sharpe_avg_train_valid": is_sharpe,
        "oos_sharpe_test": oos_sharpe,
        "sharpe_decay": decay,
        "is_ic_avg": ic_is,
        "oos_ic": ic_oos,
        "ic_decay": ic_decay,
        "verdict": (
            "轻度衰减，可接受"
            if decay < 0.35 and oos_sharpe > 0.2
            else "明显衰减，存在过拟合风险"
            if decay < 0.6
            else "严重衰减，过拟合显著"
        ),
    }
    print("overfitting", overfitting)

    # CFA 拟合判读（常见阈值）
    fit = cfa["fit"]
    cfi = fit.get("CFI") or fit.get("cfi")
    rmsea = fit.get("RMSEA") or fit.get("rmsea")
    cfa_verdict = []
    if cfi is not None:
        cfa_verdict.append("CFI良好(≥0.90)" if cfi >= 0.90 else "CFI偏低(<0.90)")
    if rmsea is not None:
        cfa_verdict.append(
            "RMSEA良好(≤0.08)" if rmsea <= 0.08 else "RMSEA偏高(>0.08)"
        )
    cfa["verdict"] = "；".join(cfa_verdict) if cfa_verdict else "见原始拟合指数"

    fit_s = cfa_sparse["fit"]
    cfi_s = fit_s.get("CFI") or fit_s.get("cfi")
    rmsea_s = fit_s.get("RMSEA") or fit_s.get("rmsea")
    sparse_verdict = []
    if cfi_s is not None:
        sparse_verdict.append("CFI良好(≥0.90)" if cfi_s >= 0.90 else "CFI偏低(<0.90)")
    if rmsea_s is not None:
        sparse_verdict.append(
            "RMSEA良好(≤0.08)" if rmsea_s <= 0.08 else "RMSEA偏高(>0.08)"
        )
    cfa_sparse["verdict"] = "；".join(sparse_verdict) if sparse_verdict else "见原始拟合指数"

    out = {
        "universe": "zz500_1000_mainboard",
        "panel_shape": list(closes.shape),
        "windows": list(WINDOWS),
        "main_factor": main_label,
        "mode": mode,
        "n2": n2,
        "top_k": TOP_K,
        "hold_days": HOLD,
        "sample_n": int(len(data)),
        "spss_factor": spss,
        "efa": efa,
        "cfa": {
            "model": cfa["model"],
            "loadings": cfa["loadings"],
            "fit": cfa["fit"],
            "verdict": cfa["verdict"],
        },
        "cfa_sparse": {
            "model": cfa_sparse["model"],
            "loadings": cfa_sparse["loadings"],
            "fit": cfa_sparse["fit"],
            "verdict": cfa_sparse["verdict"],
        },
        "predictive_ic": ic_all,
        "strategy": strat,
        "overfitting": overfitting,
    }
    path = OUT / "factor_validity_cfa.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # 简表
    pd.DataFrame(
        [
            {"metric": "KMO", "value": spss["kmo_overall"]},
            {"metric": "Bartlett_p", "value": bart["p_value"]},
            {"metric": "EFA_cum_var_f1", "value": efa["variance"]["cum_var"][0]},
            {"metric": "CFI", "value": cfi},
            {"metric": "RMSEA", "value": rmsea},
            {"metric": "CFI_sparse", "value": cfi_s},
            {"metric": "RMSEA_sparse", "value": rmsea_s},
            {"metric": "IC_train", "value": ic_all["train"].get("IC_mean")},
            {"metric": "IC_valid", "value": ic_all["valid"].get("IC_mean")},
            {"metric": "IC_test", "value": ic_all["test"].get("IC_mean")},
            {"metric": "Sharpe_train", "value": strat["train"]["sharpe"]},
            {"metric": "Sharpe_valid", "value": strat["valid"]["sharpe"]},
            {"metric": "Sharpe_test", "value": strat["test"]["sharpe"]},
            {"metric": "Sharpe_decay", "value": decay},
            {"metric": "Excess_full", "value": strat["full"]["excess"]},
            {"metric": "Excess_test", "value": strat["test"]["excess"]},
            {"metric": "BH_full", "value": bh["full"]},
            {"metric": "main_factor", "value": main_label},
            {"metric": "hold_days", "value": HOLD},
        ]
    ).to_csv(OUT / "factor_validity_summary.csv", index=False, encoding="utf-8-sig")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
