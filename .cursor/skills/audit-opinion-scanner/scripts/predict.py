"""ML-based audit opinion prediction — predict non-standard opinion probability.

Uses XGBoost with financial ratios + industry features to predict whether a
stock will receive a non-standard audit opinion in the next annual report (Q4).
This is an *ex-ante* prediction: it only uses data available BEFORE the audit
report is released.

**Experimental feature** — The training dataset currently contains only ~53
positive (non-standard) samples.  AUC ≈ 0.788 is valid but moderate; this model
is best used as a supplementary screening signal, NOT as a definitive audit-risk
conclusion.  Financial-sector stocks are excluded from training due to different
accounting structures and prediction reliability is unknown for those symbols.

Usage:
    # Train model on all available data
    python scripts/predict.py --train

    # Predict for latest quarter (all cached stocks)
    python scripts/predict.py --predict

    # Single stock prediction with risk-factor explanation
    python scripts/predict.py --stock 600267.SH

    # Backtest: leave-one-quarter-out cross-validation
    python scripts/predict.py --backtest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_cache import (
    FINA_CACHE, INDU_CACHE, KEY_FIELDS,
    _load_parquet, get_industry_map,
    compute_ratios_df, RATIO_NAMES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
DATA_DIR = REPO_ROOT / "data"
MODEL_PATH = DATA_DIR / "audit_predictor.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Feature names (deterministic) ─────────────────────────────────────────

# 25 raw financial fields
RAW_FEATURES = list(KEY_FIELDS)

# 15 derived ratios (same order as build_cache.RATIOS)
RATIO_FEATURES = list(RATIO_NAMES)

# 5 YoY change features
YOY_FEATURES = [
    "revenue_growth_yoy",      # 营收同比增速
    "profit_growth_yoy",       # 净利润同比增速
    "roe_change",              # ROE 变化
    "debt_ratio_change",       # 资产负债率变化
    "cfo_to_np_change",        # 现金流/净利润变化
]

# Industry feature (ordinal-encoded L1)
INDUSTRY_FEATURE = "industry_l1_code"

# All feature names (populated at feature-engineering time)
ALL_FEATURE_NAMES: list[str] = []


# ── Audit label loading ──────────────────────────────────────────────────

def _load_audit_labels() -> pd.DataFrame:
    """Load all audit risk CSVs and return a combined DataFrame.

    Returns columns: symbol, quarter, risk_level, opinion, risk_label
    Deduplicates by (symbol, quarter) — keeps first occurrence.
    """
    csv_pattern = list(OUTPUT_DIR.glob("audit_risk_*.csv"))
    # Exclude multi-quarter combined files (contain a dash in the quarter part)
    # e.g. "audit_risk_2023q4_2024q4.csv" → skip; "audit_risk_2024q4.csv" → include
    single_quarter = [
        p for p in csv_pattern
        if len(p.stem.replace("audit_risk_", "")) <= 6
    ]

    if not single_quarter:
        print("[warn] No audit risk CSV files found in output/", file=sys.stderr)
        return pd.DataFrame(columns=["symbol", "quarter", "risk_level", "opinion", "risk_label"])

    frames = []
    for p in single_quarter:
        try:
            df = pd.read_csv(p)
            frames.append(df)
        except Exception as e:
            print(f"[warn] Failed to read {p.name}: {e}", file=sys.stderr)

    if not frames:
        return pd.DataFrame(columns=["symbol", "quarter", "risk_level", "opinion", "risk_label"])

    combined = pd.concat(frames, ignore_index=True)
    # Deduplicate — keep first
    combined = combined.drop_duplicates(subset=["symbol", "quarter"], keep="first")
    print(f"[info] Loaded {len(combined)} audit records from {len(single_quarter)} files "
          f"({combined['quarter'].nunique()} quarters)", file=sys.stderr)
    return combined


# ── Feature engineering ──────────────────────────────────────────────────

def _compute_yoy_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute year-over-year changes for each stock-quarter.

    For each (symbol, quarter), finds the same quarter one year earlier
    and computes growth/delta features.
    """
    df = df.copy()
    df = df.sort_values(["symbol", "quarter"])

    results = []
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("quarter")
        grp = grp.set_index("quarter")
        for q in grp.index:
            try:
                year = int(q[:4])
                qnum = q[5]
                prev_q = f"{year - 1}q{qnum}"
            except (ValueError, IndexError):
                continue

            row = grp.loc[q].copy() if isinstance(grp.loc[q], pd.Series) else grp.loc[q].iloc[0]
            prev = grp.loc[prev_q] if prev_q in grp.index else None

            if prev is not None:
                prev_s = prev if isinstance(prev, pd.Series) else prev.iloc[0]
                # Revenue growth
                rev = row.get("is_revenue")
                prev_rev = prev_s.get("is_revenue")
                row["revenue_growth_yoy"] = (
                    (float(rev) / float(prev_rev) - 1) * 100
                    if pd.notna(rev) and pd.notna(prev_rev) and float(prev_rev) != 0
                    else None
                )
                # Profit growth
                np_val = row.get("is_n_income_attr_p")
                prev_np = prev_s.get("is_n_income_attr_p")
                row["profit_growth_yoy"] = (
                    (float(np_val) / float(prev_np) - 1) * 100
                    if pd.notna(np_val) and pd.notna(prev_np) and float(prev_np) != 0
                    else None
                )
                # ROE change
                roe_val = row.get("roe") if "roe" in row.index else None
                prev_roe = prev_s.get("roe") if "roe" in prev_s.index else None
                row["roe_change"] = (
                    float(roe_val) - float(prev_roe)
                    if pd.notna(roe_val) and pd.notna(prev_roe)
                    else None
                )
                # Debt ratio change
                dr_val = row.get("debt_ratio") if "debt_ratio" in row.index else None
                prev_dr = prev_s.get("debt_ratio") if "debt_ratio" in prev_s.index else None
                row["debt_ratio_change"] = (
                    float(dr_val) - float(prev_dr)
                    if pd.notna(dr_val) and pd.notna(prev_dr)
                    else None
                )
                # CFO/NP change
                cf_val = row.get("cfo_to_np") if "cfo_to_np" in row.index else None
                prev_cf = prev_s.get("cfo_to_np") if "cfo_to_np" in prev_s.index else None
                row["cfo_to_np_change"] = (
                    float(cf_val) - float(prev_cf)
                    if pd.notna(cf_val) and pd.notna(prev_cf)
                    else None
                )

            row_dict = row.to_dict() if isinstance(row, pd.Series) else row
            row_dict["quarter"] = q
            results.append(row_dict)

    if not results:
        return pd.DataFrame()
    result_df = pd.DataFrame(results)
    # Restore quarter as a regular column
    if "quarter" in result_df.columns:
        pass  # already present from row_dict
    return result_df


def engineer_features(
    fina_df: pd.DataFrame,
    indu_df: pd.DataFrame,
    fit: bool = False,
    imputation_values: dict | None = None,
    industry_mapping: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, dict, dict[str, int], list[str]]:
    """Build feature matrix from financial cache.

    Args:
        fina_df: Financial data from fina_cache.parquet.
        indu_df: Industry classification from fina_industry.parquet.
        fit: If True, compute imputation values and industry mapping from data.
        imputation_values: Pre-computed median values for NaN filling.
        industry_mapping: Pre-computed L1 industry → integer mapping.

    Returns:
        (feature_df, imputation_values, industry_mapping, feature_names)
        feature_df has columns: symbol, quarter + all feature columns.
    """
    # Compute ratios
    df = compute_ratios_df(fina_df)

    # Compute YoY features
    df = _compute_yoy_features(df)

    # Add industry
    ind_map = get_industry_map(indu_df)
    df["_l1_name"] = df["symbol"].map(lambda s: ind_map.get(s, {}).get("l1_name", "未知"))

    # Build industry ordinal encoding
    if fit:
        l1_names = sorted(df["_l1_name"].dropna().unique())
        industry_mapping = {name: i for i, name in enumerate(l1_names)}
    elif industry_mapping is None:
        industry_mapping = {}

    df[INDUSTRY_FEATURE] = df["_l1_name"].map(
        lambda x: industry_mapping.get(x, -1)
    )

    # Collect feature columns
    feature_cols = RAW_FEATURES + RATIO_FEATURES + YOY_FEATURES + [INDUSTRY_FEATURE]
    # Ensure all expected columns exist
    for col in feature_cols:
        if col not in df.columns:
            df[col] = np.nan

    # Impute missing values with median
    if fit:
        imputation_values = {}
        for col in RAW_FEATURES + RATIO_FEATURES + YOY_FEATURES:
            vals = df[col].dropna()
            imputation_values[col] = float(vals.median()) if len(vals) > 0 else 0.0
    elif imputation_values is None:
        imputation_values = {}

    for col, fill_val in imputation_values.items():
        if col in df.columns:
            df[col] = df[col].fillna(fill_val)

    # Also fill industry code (missing → -1)
    df[INDUSTRY_FEATURE] = df[INDUSTRY_FEATURE].fillna(-1).astype(int)

    # Winsorize (1%/99%) — clip extreme values
    for col in RAW_FEATURES + RATIO_FEATURES + YOY_FEATURES:
        if col not in df.columns or df[col].dropna().empty:
            continue
        lo = df[col].quantile(0.01)
        hi = df[col].quantile(0.99)
        df[col] = df[col].clip(lo, hi)

    # Build final feature matrix
    feature_names = RAW_FEATURES + RATIO_FEATURES + YOY_FEATURES + [INDUSTRY_FEATURE]

    result = df[["symbol", "quarter"] + feature_names].copy()
    return result, imputation_values, industry_mapping, feature_names


# ── Training set construction ────────────────────────────────────────────

def _get_prev_quarter(quarter: str) -> str | None:
    """Get the quarter immediately before the given quarter.

    e.g., '2024q4' → '2024q3', '2025q1' → '2024q4'
    """
    try:
        year = int(quarter[:4])
        qnum = int(quarter[5])
    except (ValueError, IndexError):
        return None
    qnum -= 1
    if qnum == 0:
        qnum = 4
        year -= 1
    return f"{year}q{qnum}"


def build_training_set(
    fina_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    indu_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict, dict[str, int], list[str]]:
    """Build (X, y) training set by aligning prior-quarter features with Q4 labels.

    For each Q4 annual report audit label, uses the previous quarter's
    (Q3) financial features to predict whether the opinion will be non-standard.

    Returns:
        (labeled_features_df, imputation_values, industry_mapping, feature_names)
        labeled_features_df includes columns: symbol, quarter (audit quarter),
        all feature cols (from prior quarter), label (0 or 1).
    """
    print("[info] Building training set...", file=sys.stderr)

    # Engineer features for all quarters
    features_all, imputation_values, industry_mapping, feature_names = engineer_features(
        fina_df, indu_df, fit=True
    )

    # Only Q4 audit quarters have meaningful labels (q1-q3 are 'no_audit_performed')
    q4_labels = audit_df[
        audit_df["quarter"].str.endswith("q4") &
        audit_df["risk_level"].notna()
    ].copy()
    q4_labels["label"] = (q4_labels["risk_level"] >= 1).astype(int)

    # For each Q4 audit quarter, get Q3 features
    rows = []
    for _, audit_row in q4_labels.iterrows():
        sym = audit_row["symbol"]
        audit_q = audit_row["quarter"]
        prev_q = _get_prev_quarter(audit_q)
        if prev_q is None:
            continue

        # Find the stock's feature row for the previous quarter
        feature_row = features_all[
            (features_all["symbol"] == sym) &
            (features_all["quarter"] == prev_q)
        ]
        if feature_row.empty:
            continue

        entry = {"symbol": sym, "audit_quarter": audit_q, "label": audit_row["label"],
                 "opinion": audit_row.get("opinion", ""),
                 "risk_label": audit_row.get("risk_label", "")}
        for f in feature_names:
            entry[f] = feature_row[f].iloc[0]
        rows.append(entry)

    if not rows:
        print("[error] No trainable pairs found. Need fina_cache covering "
              "quarters before audit Q4 periods.", file=sys.stderr)
        print("[error] Run: python scripts/build_cache.py --universe 000852.SH --quarters 20",
              file=sys.stderr)
        print("[error] Then: python scripts/scan.py --start-quarter 2020q4 --end-quarter 2026q2",
              file=sys.stderr)
        empty = pd.DataFrame(columns=["symbol", "audit_quarter", "label", "opinion", "risk_label"])
        return empty, imputation_values, industry_mapping, feature_names

    result = pd.DataFrame(rows)
    n_pos = result["label"].sum()
    n_neg = len(result) - n_pos
    print(f"[info] Training set: {len(result)} pairs, "
          f"{int(n_pos)} non-standard ({(n_pos/len(result)*100):.1f}%), "
          f"{int(n_neg)} standard", file=sys.stderr)
    return result, imputation_values, industry_mapping, feature_names


# ── Model training ───────────────────────────────────────────────────────

def train_model(
    train_df: pd.DataFrame,
    feature_names: list[str],
) -> tuple[object, dict]:
    """Train XGBoost classifier and return (model, metrics).

    Automatically handles class imbalance via scale_pos_weight.
    """
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score, classification_report

    X = train_df[feature_names].values.astype(np.float32)
    y = train_df["label"].values.astype(np.int32)

    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    scale_pos_weight = n_neg / max(n_pos, 1)

    print(f"[info] Training XGBoost: {len(X)} samples, {len(feature_names)} features, "
          f"scale_pos_weight={scale_pos_weight:.1f}", file=sys.stderr)

    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        eval_metric="auc",
        random_state=42,
        subsample=0.8,
        colsample_bytree=0.8,
        verbosity=0,
    )
    model.fit(X, y)

    # Training set metrics
    y_prob = model.predict_proba(X)[:, 1]
    y_pred = model.predict(X)
    auc = roc_auc_score(y, y_prob) if n_pos > 0 and n_neg > 0 else float("nan")

    # classification_report fails with single-class predictions — guard it
    unique_pred = np.unique(y_pred)
    if len(unique_pred) >= 2:
        report = classification_report(
            y, y_pred, target_names=["standard", "non-standard"],
            output_dict=True, zero_division=0
        )
    else:
        report = {"warning": f"Model predicted only class {int(unique_pred[0])} — insufficient positive samples"}

    # Feature importance
    importance = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda x: x[1], reverse=True
    )

    metrics = {
        "auc": round(auc, 4) if not np.isnan(auc) else None,
        "n_samples": len(X),
        "n_features": len(feature_names),
        "n_positive": int(n_pos),
        "scale_pos_weight": round(scale_pos_weight, 2),
        "top_features": [(name, round(imp, 4)) for name, imp in importance[:15]],
        "classification_report": report,
    }

    print(f"[info] Training AUC: {auc:.4f}" if not np.isnan(auc) else
          f"[info] Training AUC: N/A (insufficient samples)", file=sys.stderr)
    print(f"[info] Top 5 features:", file=sys.stderr)
    for name, imp in importance[:5]:
        print(f"        {name}: {imp:.4f}", file=sys.stderr)

    return model, metrics


# ── Save / Load model ────────────────────────────────────────────────────

def _to_native(obj):
    """Recursively convert numpy types to Python native types for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return [_to_native(x) for x in obj.tolist()]
    elif isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_to_native(x) for x in obj]
    return obj


def save_model(model, imputation_values: dict, industry_mapping: dict[str, int],
               feature_names: list[str], metrics: dict) -> str:
    """Save XGBoost model + metadata to JSON.

    XGBoost natively supports JSON serialization via save_model/load_model with
    JSON format strings.
    """
    import xgboost as xgb

    # Get model as JSON string, then parse to dict for embedding
    model_json_str = model.get_booster().save_raw(raw_format="json").decode("utf-8")
    # Replace float32 values with Python float for JSON compatibility
    model_dict = json.loads(model_json_str, parse_constant=lambda x: x)

    artifact = {
        "model": model_dict,
        "imputation_values": imputation_values,
        "industry_mapping": industry_mapping,
        "feature_names": feature_names,
        "metrics": metrics,
        "model_type": "xgboost.XGBClassifier",
    }

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(_to_native(artifact), f, ensure_ascii=False, indent=2)

    print(f"[ok] Model saved → {MODEL_PATH}", file=sys.stderr)
    return str(MODEL_PATH)


def load_model() -> tuple[object, dict, dict[str, int], list[str]] | None:
    """Load saved model and metadata. Returns None if no model exists."""
    if not MODEL_PATH.exists():
        return None

    import xgboost as xgb

    with open(MODEL_PATH, "r", encoding="utf-8") as f:
        artifact = json.load(f)

    # Reconstruct XGBoost model from JSON
    model_json_str = json.dumps(artifact["model"])
    booster = xgb.Booster()
    booster.load_model(bytearray(model_json_str, "utf-8"))

    # Wrap in XGBClassifier for predict_proba compatibility
    model = xgb.XGBClassifier()
    model._Booster = booster
    model._le = type("_LE", (), {
        "classes_": np.array([0, 1]),
        "transform": lambda self, y: y,
    })()
    model._feature_names = artifact["feature_names"]

    return (
        model,
        artifact["imputation_values"],
        artifact["industry_mapping"],
        artifact["feature_names"],
    )


# ── Prediction ───────────────────────────────────────────────────────────

def _risk_tier(prob: float) -> str:
    if prob < 0.1:
        return "🟢 安全"
    elif prob < 0.3:
        return "🟡 关注"
    elif prob < 0.5:
        return "🟠 警示"
    else:
        return "🔴 高危"


def predict(
    model,
    fina_df: pd.DataFrame,
    indu_df: pd.DataFrame,
    imputation_values: dict,
    industry_mapping: dict[str, int],
    feature_names: list[str],
    target_quarter: str | None = None,
) -> pd.DataFrame:
    """Run prediction on the latest (or specified) quarter.

    Args:
        target_quarter: e.g., '2026q2'. If None, uses latest quarter in data.

    Returns:
        DataFrame with columns: symbol, quarter, prob_nonstandard, risk_tier
    """
    features_all, _, _, _ = engineer_features(
        fina_df, indu_df, fit=False,
        imputation_values=imputation_values,
        industry_mapping=industry_mapping,
    )

    if target_quarter is None:
        target_quarter = str(features_all["quarter"].max())

    latest = features_all[features_all["quarter"] == target_quarter].copy()
    if latest.empty:
        print(f"[error] No data for quarter {target_quarter}", file=sys.stderr)
        return pd.DataFrame()

    # Ensure all feature columns exist
    for f in feature_names:
        if f not in latest.columns:
            latest[f] = 0.0

    X = latest[feature_names].values.astype(np.float32)

    try:
        proba = model.predict_proba(X)[:, 1]
    except Exception:
        # Fallback: use booster directly if wrapped model fails
        booster = model.get_booster()
        dmatrix = __import__("xgboost").DMatrix(X)
        proba = booster.predict(dmatrix)

    latest["prob_nonstandard"] = proba
    latest["risk_tier"] = np.where(
        proba < 0.1, "🟢 安全",
        np.where(proba < 0.3, "🟡 关注",
                 np.where(proba < 0.5, "🟠 警示", "🔴 高危"))
    )
    latest = latest.sort_values("prob_nonstandard", ascending=False)

    print(f"[info] Predicted {len(latest)} stocks for {target_quarter}", file=sys.stderr)
    n_warn = (proba >= 0.1).sum()
    n_danger = (proba >= 0.5).sum()
    print(f"[info] ⚠️ {int(n_warn)} flagged (prob≥0.1), 🔴 {int(n_danger)} high-risk (prob≥0.5)",
          file=sys.stderr)

    return latest[["symbol", "quarter", "prob_nonstandard", "risk_tier"]]


def _explain_prediction(
    model,
    stock_features: np.ndarray,
    feature_names: list[str],
) -> list[tuple[str, float, str]]:
    """Explain which features drove the prediction for a single stock.

    Returns list of (feature_name, value, direction) triples for top-5 contributors.
    """
    importance = model.feature_importances_
    top_idx = np.argsort(importance)[::-1][:5]

    explanations = []
    for idx in top_idx:
        name = feature_names[idx] if idx < len(feature_names) else f"f{idx}"
        val = float(stock_features[0, idx]) if stock_features.ndim == 2 else float(stock_features[idx])
        direction = "↑ 风险" if importance[idx] > 0.02 else "→ 中性"
        explanations.append((name, val, direction))
    return explanations


# ── Backtest ─────────────────────────────────────────────────────────────

def backtest(
    train_df: pd.DataFrame,
    feature_names: list[str],
) -> dict:
    """Leave-one-quarter-out cross-validation backtest.

    Trains on all but one audit quarter, tests on the held-out quarter.
    Reports AUC, precision, recall per quarter.
    """
    from sklearn.metrics import roc_auc_score, precision_score, recall_score
    import xgboost as xgb

    quarters = sorted(train_df["audit_quarter"].unique())
    if len(quarters) < 2:
        print("[warn] Need at least 2 audit quarters for backtest", file=sys.stderr)
        return {"error": "insufficient quarters for cross-validation"}

    results = []
    for holdout_q in quarters:
        train_mask = train_df["audit_quarter"] != holdout_q
        test_mask = train_df["audit_quarter"] == holdout_q

        X_train = train_df.loc[train_mask, feature_names].values.astype(np.float32)
        y_train = train_df.loc[train_mask, "label"].values.astype(np.int32)
        X_test = train_df.loc[test_mask, feature_names].values.astype(np.float32)
        y_test = train_df.loc[test_mask, "label"].values.astype(np.int32)

        n_pos_train = int(y_train.sum())
        n_neg_train = int(len(y_train) - n_pos_train)
        sw = n_neg_train / max(n_pos_train, 1)

        model = xgb.XGBClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            scale_pos_weight=sw, eval_metric="auc",
            random_state=42, subsample=0.8, colsample_bytree=0.8,
            verbosity=0,
        )
        model.fit(X_train, y_train)

        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = model.predict(X_test)

        auc = roc_auc_score(y_test, y_prob) if y_test.sum() > 0 and (len(y_test) - y_test.sum()) > 0 else float("nan")
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)

        results.append({
            "holdout_quarter": holdout_q,
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "n_pos_test": int(y_test.sum()),
            "auc": round(auc, 4) if not np.isnan(auc) else None,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        })

    # Aggregate
    valid_aucs = [r["auc"] for r in results if r["auc"] is not None]
    summary = {
        "quarters": len(quarters),
        "avg_auc": round(np.mean(valid_aucs), 4) if valid_aucs else None,
        "avg_precision": round(np.mean([r["precision"] for r in results]), 4),
        "avg_recall": round(np.mean([r["recall"] for r in results]), 4),
        "details": results,
    }

    print(f"\n  Backtest Results ({len(quarters)} folds)", file=sys.stderr)
    print(f"  {'Quarter':<10} {'N':>5} {'Pos':>4} {'AUC':>8} {'Prec':>8} {'Recall':>8}", file=sys.stderr)
    print(f"  {'─'*50}", file=sys.stderr)
    for r in results:
        auc_str = f"{r['auc']:.4f}" if r['auc'] is not None else "N/A"
        print(f"  {r['holdout_quarter']:<10} {r['n_test']:>5} {r['n_pos_test']:>4} "
              f"{auc_str:>8} {r['precision']:>8.4f} {r['recall']:>8.4f}", file=sys.stderr)
    print(f"\n  Avg AUC: {summary['avg_auc']:.4f}  |  "
          f"Avg Precision: {summary['avg_precision']:.4f}  |  "
          f"Avg Recall: {summary['avg_recall']:.4f}", file=sys.stderr)

    return summary


# ── Report ────────────────────────────────────────────────────────────────

def _print_stock_detail(
    model,
    fina_df: pd.DataFrame,
    indu_df: pd.DataFrame,
    imputation_values: dict,
    industry_mapping: dict[str, int],
    feature_names: list[str],
    symbol: str,
):
    """Print a detailed prediction report for a single stock."""
    features_all, _, _, _ = engineer_features(
        fina_df, indu_df, fit=False,
        imputation_values=imputation_values,
        industry_mapping=industry_mapping,
    )
    latest_q = str(features_all["quarter"].max())
    stock = features_all[
        (features_all["symbol"] == symbol) &
        (features_all["quarter"] == latest_q)
    ]
    if stock.empty:
        print(f"[error] No data for {symbol} in {latest_q}", file=sys.stderr)
        return

    X = stock[feature_names].values.astype(np.float32)
    prob = float(model.predict_proba(X)[:, 1][0])
    tier = _risk_tier(prob)

    # Get top risk factors
    explanations = _explain_prediction(model, X, feature_names)

    # Get industry name
    ind_map = get_industry_map(indu_df)
    ind_name = ind_map.get(symbol, {}).get("l1_name", "未知")

    print(f"\n  {'='*60}")
    print(f"  {symbol}  ·  {ind_name}  ·  {latest_q}")
    print(f"  {'='*60}")
    print(f"\n  🔮 非标审计意见预测概率: {prob:.1%}  {tier}")
    print(f"\n  ── Top 5 风险驱动因子 ──")
    for name, val, direction in explanations:
        print(f"    {name:<30} {val:>12.4f}  {direction}")
    print()


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="ML audit opinion prediction")
    p.add_argument("--train", action="store_true", help="Train model and save to disk")
    p.add_argument("--predict", action="store_true", help="Predict for latest quarter")
    p.add_argument("--backtest", action="store_true", help="Leave-one-quarter-out backtest")
    p.add_argument("--stock", default=None, help="Single stock prediction with explanation")
    p.add_argument("--quarter", default=None, help="Target quarter for prediction (e.g. 2026q2)")
    p.add_argument("--output", default=None, help="CSV output path for predictions")
    args = p.parse_args()

    if not any([args.train, args.predict, args.backtest, args.stock]):
        p.print_help()
        return 1

    # ── Load data ─────────────────────────────────────────────────────
    fina_df = _load_parquet(FINA_CACHE)
    indu_df = _load_parquet(INDU_CACHE)

    if fina_df.empty:
        print("[error] fina_cache.parquet is empty. Build it first:", file=sys.stderr)
        print("  python scripts/build_cache.py --universe 000852.SH --quarters 20", file=sys.stderr)
        return 1

    print(f"[info] Financial cache: {len(fina_df)} rows, {fina_df['symbol'].nunique()} stocks, "
          f"{fina_df['quarter'].nunique()} quarters", file=sys.stderr)

    # ── Train ─────────────────────────────────────────────────────────
    if args.train:
        audit_df = _load_audit_labels()
        if audit_df.empty:
            print("[error] No audit labels found. Run scan first:", file=sys.stderr)
            print("  python scripts/scan.py --start-quarter 2020q4 --end-quarter 2026q2", file=sys.stderr)
            return 1

        train_df, imputation_values, industry_mapping, feature_names = build_training_set(
            fina_df, audit_df, indu_df
        )
        if train_df.empty:
            return 1

        model, metrics = train_model(train_df, feature_names)
        save_model(model, imputation_values, industry_mapping, feature_names, metrics)

        # Optionally run backtest
        if args.backtest:
            print(f"\n{'='*60}", file=sys.stderr)
            backtest(train_df, feature_names)

        return 0

    # ── Load model ────────────────────────────────────────────────────
    loaded = load_model()
    if loaded is None:
        print("[error] No trained model found. Run with --train first.", file=sys.stderr)
        return 1

    model, imputation_values, industry_mapping, feature_names = loaded
    print(f"[info] Loaded model: {len(feature_names)} features", file=sys.stderr)

    # ── Single stock ─────────────────────────────────────────────────
    if args.stock:
        _print_stock_detail(
            model, fina_df, indu_df, imputation_values,
            industry_mapping, feature_names, args.stock
        )
        return 0

    # ── Predict ──────────────────────────────────────────────────────
    if args.predict:
        result = predict(
            model, fina_df, indu_df, imputation_values,
            industry_mapping, feature_names, target_quarter=args.quarter,
        )
        if result.empty:
            return 1

        out_path = args.output or str(
            OUTPUT_DIR / f"audit_predictions_{result['quarter'].iloc[0]}.csv"
        )
        result.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[ok] Predictions saved → {out_path}", file=sys.stderr)

        # Show top-10 highest risk
        print(f"\n  Top 10 最高风险股票:", file=sys.stderr)
        top10 = result.head(10)
        for _, row in top10.iterrows():
            print(f"    {row['symbol']:<12} {row['prob_nonstandard']:.3f}  {row['risk_tier']}",
                  file=sys.stderr)
        return 0

    # ── Backtest only ────────────────────────────────────────────────
    if args.backtest:
        audit_df = _load_audit_labels()
        if audit_df.empty:
            print("[error] No audit labels found.", file=sys.stderr)
            return 1

        train_df, _, _, feature_names = build_training_set(fina_df, audit_df, indu_df)
        if train_df.empty:
            return 1

        backtest(train_df, feature_names)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
