"""回测数据包装层 —— 在 backtest.run_backtest() 基础上保留时序数据，供 HTML 报告使用

为什么需要这个模块：
    backtest.run_backtest() 内部其实计算了 daily_ic / curve / drawdown / signal_timeline
    等关键时序数据，但只返回聚合 dict，丢掉了所有时间维度。
    HTML 报告需要画净值曲线、每日 IC 时序、信号分布图等，必须保留这些中间产物。

设计原则：
    - 不修改 backtest.py（保持原契约）
    - 复用 backtest.py 的纯函数（build_forward_returns / pearson_ic / rank_ic /
      information_ratio / annualized_return），避免重复实现
    - 复用 validate.py 的 _load_fixture_or_network，离线/联网行为与项目一致
    - 输出 JSON 友好（所有 numpy/pandas 类型显式转原生）
"""
from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

# 兼容 Python embed 版本：把脚本所在目录注入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd


def _is_offline(offline: bool | None) -> bool:
    """判断是否离线模式：显式参数优先，其次看环境变量"""
    if offline is not None:
        return offline
    return os.getenv("PANDA_DATA_OFFLINE", "0") == "1"


def _inject_panda_data_stub_for_offline() -> None:
    """panda_data SDK 缺失时注入 stub 模块，绕过 factor.py 顶层 import

    factor.py 顶层无条件 `import panda_data`，本地未安装 SDK 时会直接 ImportError，
    导致 backtest.py / validate.py 都无法 import。离线流程走 fixtures 不调任何 SDK API，
    所以注入 stub 让 import 链通过即可。

    行为约定：
    - SDK 已装：跳过注入（不覆盖真实模块）
    - SDK 缺失：注入 stub；联网模式下若意外调到 stub 函数，返回空 DataFrame，
      上层会报"未获取到期货持仓数据"，错误可追溯
    """
    if "panda_data" in sys.modules:
        return  # 已加载（真实 SDK 或已有 stub），不覆盖
    try:
        import panda_data  # noqa: F401
        return  # 真实 SDK 已装
    except ImportError:
        pass
    stub = types.ModuleType("panda_data")
    stub.init_token = lambda **kw: None  # type: ignore[attr-defined]
    stub.get_future_netposi_rank = lambda **kw: pd.DataFrame()  # type: ignore[attr-defined]
    stub.get_future_daily = lambda **kw: pd.DataFrame()  # type: ignore[attr-defined]
    sys.modules["panda_data"] = stub
    print("[INFO] panda_data SDK 未安装，已注入 stub 模块（离线模式可用；联网会报错）")


# 必须在 import backtest / factor 之前完成 stub 注入
_inject_panda_data_stub_for_offline()


def _patch_pd_read_parquet_fallback() -> None:
    """patch pd.read_parquet，pyarrow 失败时 fallback 到 fastparquet

    pyarrow ≥18 与部分旧版 parquet 文件存在 "Repetition level histogram size mismatch"
    兼容性问题。fallback 到 fastparquet 即可绕过。仅当 fastparquet 已装时启用。
    """
    try:
        import fastparquet  # noqa: F401
    except ImportError:
        return  # 没装就不打补丁，让 pyarrow 错误原样抛出
    if getattr(pd.read_parquet, "_is_patched", False):
        return  # 已打补丁，避免重复
    orig = pd.read_parquet

    def patched(path, *args, **kwargs):
        engine = kwargs.get("engine")
        if engine is None:
            try:
                return orig(path, *args, **kwargs)
            except Exception:
                kwargs["engine"] = "fastparquet"
                return orig(path, *args, **kwargs)
        return orig(path, *args, **kwargs)

    patched._is_patched = True  # type: ignore[attr-defined]
    pd.read_parquet = patched  # type: ignore[assignment]
    print("[INFO] 已为 pd.read_parquet 打补丁：pyarrow 失败时自动 fallback fastparquet")


_patch_pd_read_parquet_fallback()

from backtest import (  # noqa: E402
    annualized_return,
    build_forward_returns,
    information_ratio,
    pearson_ic,
    rank_ic,
)
from factor import calculate_factor, load_price_data  # noqa: E402
from validate import _load_fixture_or_network, _make_update_time  # noqa: E402


def _fmt_date(d: Any) -> str:
    """把 pandas Timestamp / numpy datetime / 字符串统一转 YYYY-MM-DD"""
    if isinstance(d, str):
        return d
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _json_default(obj: Any) -> Any:
    """JSON 序列化兜底：numpy 整型/浮点/Timestamp → 原生类型"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if not np.isnan(v) else None
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if pd.isna(obj):  # NaN / NaT
        return None
    return str(obj)


def run_backtest_with_series(offline: bool | None = None) -> dict:
    """复刻 backtest.run_backtest() 主流程，但保留全部时序数据

    Args:
        offline: 强制离线/联网模式；None 时按 PANDA_DATA_OFFLINE 环境变量

    Returns:
        在 backtest.run_backtest() 返回 dict 的基础上新增字段：
            meta: dict                — 生成时间、数据版本、样本区间等
            timeseries: dict          — daily_ic / curve / drawdown / signal_timeline / layered_curve
            symbol_distribution: list — Top 20 品种信号分布
    """
    is_offline = _is_offline(offline)
    data_version = "offline-fixture" if is_offline else "real-v1"

    # === 1. 加载数据 ===
    # _load_fixture_or_network 在联网模式会自动调 load_price_data 拉价格，
    # 离线模式从 fixtures 读 parquet；返回 (positions, prices)，prices 可能为 None
    raw_positions, raw_prices = _load_fixture_or_network(positions_only=False)

    # === 2. 计算因子 ===
    factor = calculate_factor(
        input_data=raw_positions,
        update_time=_make_update_time(raw_positions),
    )

    # === 3. 兜底价格数据（离线模式 fixture 缺价格时从联网拉） ===
    if raw_prices is None:
        factor_symbols = factor["symbol"].unique().tolist()
        start_date = factor["trade_date"].min()
        end_date = factor["trade_date"].max()
        prices = load_price_data(symbols=factor_symbols, start_date=start_date, end_date=end_date)
    else:
        prices = raw_prices

    # === 4. forward_return + 合并面板 ===
    forward = build_forward_returns(prices)
    panel = factor.merge(forward, on=["trade_date", "symbol"], how="inner")
    if panel.empty:
        raise ValueError("回测样本为空（因子表与价格数据无交集）")

    # === 5. 每日 IC（与 backtest.run_backtest 完全一致） ===
    daily_ic_series = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
    daily_rank_ic_series = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
    ic = float(daily_ic_series.mean()) if not daily_ic_series.empty else 0.0
    icir = (
        float(daily_ic_series.mean() / daily_ic_series.std())
        if len(daily_ic_series) > 1 and daily_ic_series.std()
        else 0.0
    )
    rank_ic_value = float(daily_rank_ic_series.mean()) if not daily_rank_ic_series.empty else 0.0
    rank_icir = (
        float(daily_rank_ic_series.mean() / daily_rank_ic_series.std())
        if len(daily_rank_ic_series) > 1 and daily_rank_ic_series.std()
        else 0.0
    )

    # === 6. 分层收益（按日 qcut 成 low/high 两组） ===
    panel["group"] = panel.groupby("trade_date")["factor_value"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 2, labels=["low", "high"], duplicates="drop")
    )
    group_return = (
        panel.groupby("group", observed=False)["forward_return"].mean().round(6).to_dict()
    )
    # 分层时序累计净值（用于画 high vs low 对比线）
    layered_daily = (
        panel.groupby(["trade_date", "group"], observed=False)["forward_return"]
        .mean()
        .unstack(fill_value=0)
    )
    layered_curve: dict[str, list] = {}
    for col in layered_daily.columns:
        s = layered_daily[col].fillna(0)
        cum = (1.0 + s).cumprod() - 1.0  # 累计收益率，从 0 开始
        layered_curve[str(col)] = [
            {"date": _fmt_date(d), "cum_return": float(v)}
            for d, v in cum.items()
        ]

    # === 7. 买入信号策略收益（与 backtest.run_backtest 一致） ===
    buy_return = panel[panel["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
    if buy_return.empty:
        # 没有 buy 信号时退化为全样本平均
        buy_return = panel.groupby("trade_date")["forward_return"].mean().fillna(0)

    curve = (1.0 + buy_return).cumprod()  # 累计净值，从 1 开始
    cumulative_return = float(curve.iloc[-1] - 1) if not curve.empty else 0.0
    drawdown = curve / curve.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = cumulative_return / abs(max_drawdown) if max_drawdown else 0.0

    # === 8. 换手率 ===
    signal_changes = (panel["signal"] != panel.groupby("symbol")["signal"].shift(1)).sum()
    turnover = float(signal_changes / len(panel)) if len(panel) > 0 else 0.0

    # === 9. 信号统计 ===
    total_records = len(panel)
    buy_signals = int((panel["signal"] == "buy").sum())
    sell_signals = int((panel["signal"] == "sell").sum())
    hold_signals = int((panel["signal"] == "hold").sum())

    # === 10. 品种信号分布（Top 20） ===
    sym_pivot = (
        panel.groupby("symbol")["signal"]
        .value_counts()
        .unstack(fill_value=0)
    )
    for col in ["buy", "sell", "hold"]:
        if col not in sym_pivot.columns:
            sym_pivot[col] = 0
    sym_pivot["total"] = sym_pivot.sum(axis=1)
    sym_pivot = sym_pivot.sort_values("total", ascending=False).head(20).reset_index()

    symbol_distribution = [
        {
            "symbol": str(row["symbol"]),
            "buy": int(row.get("buy", 0)),
            "sell": int(row.get("sell", 0)),
            "hold": int(row.get("hold", 0)),
            "total": int(row.get("total", 0)),
        }
        for _, row in sym_pivot.iterrows()
    ]

    # === 11. 信号时序分布（按日期） ===
    sig_pivot = (
        panel.groupby("trade_date")["signal"]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ["buy", "sell", "hold"]:
        if col not in sig_pivot.columns:
            sig_pivot[col] = 0

    signal_timeline = [
        {
            "date": _fmt_date(row["trade_date"]),
            "buy": int(row.get("buy", 0)),
            "sell": int(row.get("sell", 0)),
            "hold": int(row.get("hold", 0)),
        }
        for _, row in sig_pivot.iterrows()
    ]

    # === 12. 时序数据序列化 ===
    daily_ic_list = []
    # 对齐两个 IC 序列的索引
    rank_ic_lookup = daily_rank_ic_series.to_dict() if not daily_rank_ic_series.empty else {}
    for d, ic_v in daily_ic_series.items():
        ric_v = rank_ic_lookup.get(d, 0.0)
        daily_ic_list.append({
            "date": _fmt_date(d),
            "ic": float(ic_v) if not pd.isna(ic_v) else 0.0,
            "rank_ic": float(ric_v) if not pd.isna(ric_v) else 0.0,
        })

    curve_list = [
        {"date": _fmt_date(d), "cum_return": float(v - 1.0)}  # 转为累计收益率（0 基准）
        for d, v in curve.items()
    ]
    drawdown_list = [
        {"date": _fmt_date(d), "drawdown": float(v)}
        for d, v in drawdown.items()
    ]
    buy_return_list = [
        {"date": _fmt_date(d), "daily_return": float(v)}
        for d, v in buy_return.items()
    ]

    # === 13. meta 信息 ===
    sample_dates = sorted(panel["trade_date"].unique())
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_version": data_version,
        "sample_start": _fmt_date(sample_dates[0]) if sample_dates else None,
        "sample_end": _fmt_date(sample_dates[-1]) if sample_dates else None,
        "trade_days": len(sample_dates),
        "symbol_count": int(panel["symbol"].nunique()),
    }

    # 分层收益 dict 的 key 可能是 pandas Categorical，统一转 str
    layered_return_native = {str(k): float(v) for k, v in group_return.items()}

    return {
        # 原 backtest.run_backtest 字段（保持兼容）
        "IC": round(ic, 6),
        "ICIR": round(icir, 6),
        "Rank IC": round(rank_ic_value, 6),
        "Rank ICIR": round(rank_icir, 6),
        "IR(SHR*)": round(information_ratio(buy_return), 6),
        "CR": round(calmar, 6),
        "ARR(%)": round(annualized_return(buy_return) * 100, 6),
        "MDD(%)": round(max_drawdown * 100, 6),
        "分层收益": layered_return_native,
        "换手率": round(turnover, 6),
        "样本数": int(total_records),
        "买入信号": buy_signals,
        "卖出信号": sell_signals,
        "持仓信号": hold_signals,
        "评估口径": (
            "因子在 t 日形成（基于 t 日及以前的持仓数据）；收益采用严格口径 "
            "forward_return = close_{t+1}/open_{t+1} - 1，即信号 t 日收盘后产生，"
            "t+1 日开盘成交、t+1 日收盘平仓，避免偷价；价格数据来源于 get_future_daily 主力合约。"
        ),
        # 新增字段（HTML 报告专用）
        "meta": meta,
        "timeseries": {
            "daily_ic": daily_ic_list,
            "curve": curve_list,
            "drawdown": drawdown_list,
            "buy_return_daily": buy_return_list,
            "signal_timeline": signal_timeline,
            "layered_curve": layered_curve,
        },
        "symbol_distribution": symbol_distribution,
    }


def save_backtest_result(data: dict, json_path: Path) -> None:
    """保存回测结果到 JSON（自动创建父目录）"""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)


if __name__ == "__main__":
    # 直接运行此模块：生成 reports/backtest_result.json，便于离线调试
    result = run_backtest_with_series()
    out_path = Path(__file__).parent.parent / "reports" / "backtest_result.json"
    save_backtest_result(result, out_path)
    print(f"[OK] 回测结果已保存到 {out_path}")
    print(f"     样本区间: {result['meta']['sample_start']} ~ {result['meta']['sample_end']}")
    print(f"     交易日数: {result['meta']['trade_days']}, 品种数: {result['meta']['symbol_count']}")
    print(f"     IC={result['IC']}, ICIR={result['ICIR']}, ARR={result['ARR(%)']}%, MDD={result['MDD(%)']}%")
