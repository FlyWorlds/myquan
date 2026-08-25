"""多策略共用：akquant 回测骨架。

新策略只需实现：
  1. rules.py   — 纯函数 / 常量 / STRATEGY_RULES / 盯盘 signal（可选）
  2. backtest.py — akquant Strategy 子类
  3. config.py  — dataclass 配置 + 标的预设
  4. runner.py  — prepare + run_xxx()，内部调用 run_akquant_backtest
  5. backtest/xxx.py — 薄 CLI

然后在 registry.py 注册即可。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Type

import akquant as aq
import pandas as pd
from akquant import BacktestResult, CurrentClose, Strategy

from strategy.costs import COMMISSION_RATE, MISC_FEE_RATE, SLIPPAGE_VALUE, STAMP_TAX_RATE
from strategy.data import fetch_daily

_FILL = CurrentClose()


@dataclass
class CommonBacktestParams:
    """各策略 config 建议包含的公共字段。"""

    symbol: str
    symbol_name: str
    start_date: str
    end_date: str
    initial_cash: float = 100_000.0
    lot_size: int = 100
    commission_rate: float = COMMISSION_RATE
    misc_fee_rate: float = MISC_FEE_RATE
    stamp_tax_rate: float = STAMP_TAX_RATE
    slippage_value: float = SLIPPAGE_VALUE
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}

    @property
    def engine_commission_rate(self) -> float:
        return float(self.commission_rate) + float(self.misc_fee_rate or 0.0)


def run_akquant_backtest(
    *,
    daily: pd.DataFrame,
    strategy_cls: Type[Strategy],
    symbol: str,
    params: CommonBacktestParams | Any,
    configure: Callable[[Strategy, Any], None] | None = None,
    extra: dict[str, Any] | None = None,
) -> BacktestResult:
    """通用 akquant 回测。

    configure 若提供：先 `strategy_cls()` 得到**实例**再写入参数，避免类属性串扰。
    """
    kw = extra or {}
    strategy: Strategy | Type[Strategy] = strategy_cls
    if configure is not None:
        inst = strategy_cls()
        configure(inst, params)
        strategy = inst
    comm = getattr(params, "engine_commission_rate", None)
    if comm is None:
        comm = float(params.commission_rate) + float(
            getattr(params, "misc_fee_rate", 0.0) or 0.0
        )
    return aq.run_backtest(
        data=daily,
        strategy=strategy,
        symbols=symbol,
        initial_cash=params.initial_cash,
        commission_rate=float(comm),
        stamp_tax_rate=params.stamp_tax_rate,
        t_plus_one=kw.get("t_plus_one", True),
        lot_size=params.lot_size,
        fill_policy=kw.get("fill_policy", _FILL),
        slippage=params.slippage,
        timezone=kw.get("timezone", "Asia/Shanghai"),
        show_progress=kw.get("show_progress", False),
    )


def _open_trades_from_executions(result: BacktestResult) -> pd.DataFrame:
    """从未配对成交推断期末未平仓，补成 trades 行（仅有 entry，无 exit）。

    akquant 原生 K 线买卖点只读 ``trades_df``（闭环），期末仍持仓的买入会漏画。
    """
    exec_df = getattr(result, "executions_df", None)
    if exec_df is None or getattr(exec_df, "empty", True):
        return pd.DataFrame()
    if "side" not in exec_df.columns or "timestamp" not in exec_df.columns:
        return pd.DataFrame()

    df = exec_df.copy()
    df["side"] = df["side"].astype(str).str.lower().str.strip()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for sym, g in df.groupby(df["symbol"].astype(str), sort=False):
        pos = 0.0
        entry_time = None
        entry_price = None
        entry_qty = 0.0
        entry_comm = 0.0
        for _, ex in g.iterrows():
            side = str(ex["side"])
            qty = float(pd.to_numeric(ex.get("quantity"), errors="coerce") or 0.0)
            px = float(pd.to_numeric(ex.get("price"), errors="coerce") or float("nan"))
            comm = float(
                pd.to_numeric(ex.get("commission"), errors="coerce") or 0.0
            )
            if qty <= 0 or px != px:
                continue
            if side == "buy":
                if pos <= 1e-12:
                    entry_time = ex["timestamp"]
                    entry_price = px
                    entry_qty = qty
                    entry_comm = comm
                else:
                    # 加仓：按数量加权均价
                    new_qty = entry_qty + qty
                    entry_price = (entry_price * entry_qty + px * qty) / new_qty
                    entry_qty = new_qty
                    entry_comm += comm
                pos += qty
            elif side == "sell":
                pos -= qty
                if pos <= 1e-12:
                    pos = 0.0
                    entry_time = None
                    entry_price = None
                    entry_qty = 0.0
                    entry_comm = 0.0
        if pos > 1e-12 and entry_time is not None and entry_price is not None:
            rows.append(
                {
                    "symbol": str(sym),
                    "entry_time": entry_time,
                    "exit_time": pd.NaT,
                    "entry_price": float(entry_price),
                    "exit_price": float("nan"),
                    "quantity": float(pos),
                    "side": "Long",
                    "pnl": float("nan"),
                    "net_pnl": float("nan"),
                    "return_pct": float("nan"),
                    "commission": float(entry_comm),
                    "duration_bars": float("nan"),
                    "duration": pd.NaT,
                    "mae": float("nan"),
                    "mfe": float("nan"),
                    "entry_tag": "open",
                    "exit_tag": "持仓中",
                    "entry_portfolio_value": float("nan"),
                    "max_drawdown_pct": float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _install_report_open_trade_patches() -> None:
    """分析图只统计闭环；K 线卖点跳过无 exit 的持仓行。"""
    try:
        from akquant.plot import analysis as analysis_mod
        from akquant.plot import strategy as strategy_mod
    except ImportError:
        return

    if getattr(analysis_mod, "_myquan_closed_only_patch", False):
        return

    def _closed_only(trades_df: pd.DataFrame | None) -> pd.DataFrame | None:
        if trades_df is None or getattr(trades_df, "empty", True):
            return trades_df
        if "exit_time" not in trades_df.columns:
            return trades_df
        return trades_df[pd.to_datetime(trades_df["exit_time"], errors="coerce").notna()]

    _dist = analysis_mod.plot_trades_distribution
    _dur = analysis_mod.plot_pnl_vs_duration

    def _dist_patched(trades_df, *args, **kwargs):
        return _dist(_closed_only(trades_df), *args, **kwargs)

    def _dur_patched(trades_df, *args, **kwargs):
        return _dur(_closed_only(trades_df), *args, **kwargs)

    analysis_mod.plot_trades_distribution = _dist_patched  # type: ignore[assignment]
    analysis_mod.plot_pnl_vs_duration = _dur_patched  # type: ignore[assignment]
    analysis_mod._myquan_closed_only_patch = True

    _plot_strategy = strategy_mod.plot_strategy

    def _plot_strategy_patched(result, symbol, data, **kwargs):
        # 让卖点 scatter 丢掉未平仓行（exit_time 为空）
        trades = getattr(result, "trades_df", None)
        restore = None
        if (
            isinstance(trades, pd.DataFrame)
            and not trades.empty
            and "exit_time" in trades.columns
        ):
            # plot_strategy 读 result.trades_df；临时换成「买点含开仓、卖点仅闭环」
            # 买点：全部（含开仓）；卖点：仅有 exit 的行 → 通过两次绘制不好拆，
            # 这里保持 trades_df 含开仓，并在内部对 exit 过滤靠 NaT 跳过。
            # Plotly 对 NaT x 会丢点；再保险地预过滤：复制一份把开仓 exit 留 NaT。
            restore = trades
        fig = _plot_strategy(result, symbol, data, **kwargs)
        if restore is not None and fig is not None:
            # 去掉误画的 NaT 卖点（若有）
            try:
                for tr in fig.data:
                    name = str(getattr(tr, "name", "") or "")
                    if name.lower() == "exit" and hasattr(tr, "x"):
                        xs = list(tr.x or [])
                        ys = list(tr.y or [])
                        keep_x, keep_y = [], []
                        keep_text, keep_cd = [], []
                        texts = list(getattr(tr, "text", None) or [None] * len(xs))
                        cds = list(getattr(tr, "customdata", None) or [None] * len(xs))
                        for i, x in enumerate(xs):
                            if x is None or (isinstance(x, float) and x != x):
                                continue
                            if pd.isna(x):
                                continue
                            keep_x.append(x)
                            keep_y.append(ys[i] if i < len(ys) else None)
                            keep_text.append(texts[i] if i < len(texts) else None)
                            keep_cd.append(cds[i] if i < len(cds) else None)
                        tr.x = keep_x
                        tr.y = keep_y
                        if getattr(tr, "text", None) is not None:
                            tr.text = keep_text
                        if getattr(tr, "customdata", None) is not None:
                            tr.customdata = keep_cd
            except Exception:
                pass
        return fig

    strategy_mod.plot_strategy = _plot_strategy_patched  # type: ignore[assignment]


def attach_open_trades_for_report(result: BacktestResult) -> int:
    """把未平仓买入并入 ``trades_df``，供报告 K 线画出最后买点。返回补入笔数。"""
    opens = _open_trades_from_executions(result)
    if opens.empty:
        return 0
    closed = getattr(result, "trades_df", pd.DataFrame())
    if closed is None or getattr(closed, "empty", True):
        merged = opens.copy()
    else:
        # 对齐列
        for col in closed.columns:
            if col not in opens.columns:
                opens[col] = pd.NA
        opens = opens.reindex(columns=list(closed.columns), fill_value=pd.NA)
        merged = pd.concat([closed, opens], ignore_index=True)
    # cached_property：写入 __dict__ 覆盖
    result.__dict__["trades_df"] = merged
    _install_report_open_trade_patches()
    return int(len(opens))


def run_backtest_pipeline(
    *,
    params: CommonBacktestParams | Any,
    strategy_cls: Type[Strategy],
    configure: Callable[[Strategy, Any], None],
    prepare: Callable[[Any, pd.DataFrame], Any] | None = None,
    print_summary_fn: Callable[..., None] | None = None,
    summary_kwargs: dict[str, Any] | None = None,
    report_title: str | None = None,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    extra: dict[str, Any] | None = None,
) -> tuple[BacktestResult, pd.DataFrame]:
    """拉日线 → 可选 prepare → 回测 → 摘要 → 可选 HTML。"""
    if verbose:
        print(f"akquant={getattr(aq, '__version__', '?')}")
        print(
            f"拉取 {params.symbol_name}({params.symbol}) "
            f"日线 {params.start_date} → {params.end_date} ..."
        )

    daily = fetch_daily(
        params.symbol,
        params.start_date,
        params.end_date,
        cache_path=getattr(params, "daily_cache", None),
        force_refresh=force_daily_refresh,
    )
    if verbose:
        print(
            f"日线数: {len(daily)}，"
            f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
        )

    if prepare is not None:
        prepare(params, daily)

    result = run_akquant_backtest(
        daily=daily,
        strategy_cls=strategy_cls,
        symbol=params.symbol,
        params=params,
        configure=configure,
        extra=extra,
    )

    if verbose and print_summary_fn is not None:
        print("\n=== Backtest Result ===")
        print(result)
        sk = summary_kwargs or {}
        print_summary_fn(result, daily, **sk)

    if params.report_path is not None:
        title = report_title or f"{params.symbol_name} ({params.start_date}~{params.end_date})"
        n_open = attach_open_trades_for_report(result)
        if verbose:
            print(f"\n生成 HTML: {params.report_path}")
            if n_open:
                print(f"报告补画未平仓买入 {n_open} 笔")
        result.viz.report(
            title=title,
            filename=str(params.report_path),
            show=show_report,
            market_data=daily,
            plot_symbol=params.symbol,
            curve_freq="D",
        )
        if verbose:
            print(f"报告已生成: {params.report_path}")

    return result, daily
