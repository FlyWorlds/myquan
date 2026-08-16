"""A 股 Buffett 点时回测运行器（可视化配套）。

安全边界：凭证只从子进程环境变量 `PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD`
读取，读取后立即从 `os.environ` 删除；不会写入代码、日志、JSON 或 HTML。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


_CACHED_CREDENTIALS: tuple[str, str, str | None] | None = None


def _reauth() -> None:
    global _CACHED_CREDENTIALS
    if _CACHED_CREDENTIALS is None:
        return
    import panda_data
    from panda_data.client import init as client_init

    u, p, b = _CACHED_CREDENTIALS
    kwargs: dict[str, Any] = {"username": u, "password": p}
    if b:
        kwargs["base_url"] = b
    panda_data.init_token(**kwargs)
    client_init(**kwargs)


def _consume_credentials() -> tuple[str, str, str | None]:
    username = os.environ.pop("PANDA_DATA_USERNAME", "")
    password = os.environ.pop("PANDA_DATA_PASSWORD", "")
    base_url = os.environ.pop("PANDA_DATA_BASE_URL", "") or None
    if not username or not password:
        raise RuntimeError("PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD must be set in the child process env")
    return username, password, base_url


def _login(username: str, password: str, base_url: str | None) -> None:
    import panda_data
    from panda_data.client import init as client_init

    global _CACHED_CREDENTIALS
    _CACHED_CREDENTIALS = (username, password, base_url)

    kwargs: dict[str, Any] = {"username": username, "password": password}
    if base_url:
        kwargs["base_url"] = base_url
    panda_data.init_token(**kwargs)
    client_init(**kwargs)
    # 确保 skill 内部路径也能拿到凭证，不再要求重新读取环境变量
    if __package__ in {None, ""}:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from scripts.panda_adapter import configure_process_credentials
    else:
        from .panda_adapter import configure_process_credentials
    configure_process_credentials(username, password, base_url)


def _slice_ranges(start: str, end: str, max_years: int = 4) -> list[tuple[str, str]]:
    """把 [start,end] 切成 <= max_years 年的窗口（panda_data 价格接口有 5 年限制）。"""
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    windows: list[tuple[str, str]] = []
    cursor = start_ts
    while cursor < end_ts:
        nxt = min(cursor + pd.DateOffset(years=max_years) - pd.Timedelta(days=1), end_ts)
        windows.append((cursor.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cursor = nxt + pd.Timedelta(days=1)
    return windows


def _fetch_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    from scripts.dp_cache import cached_call

    fields = ["symbol", "date", "close"]
    frames: list[pd.DataFrame] = []
    step = 40
    windows = _slice_ranges(start, end)
    for w_start, w_end in windows:
        for offset in range(0, len(symbols), step):
            chunk = sorted(set(symbols[offset : offset + step]))
            try:
                df = cached_call("get_stock_daily_post", symbol=chunk, start_date=w_start, end_date=w_end, fields=fields)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] price fetch failed for {chunk[:2]}... {w_start}-{w_end}: {exc}", file=sys.stderr)
                continue
            if df is not None and not df.empty:
                frames.append(df)
    if not frames:
        return pd.DataFrame(columns=fields)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"].astype(str), errors="coerce")
    out = out.dropna(subset=["date"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna(subset=["close"]).drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def _fetch_index(symbol: str, start: str, end: str) -> pd.DataFrame:
    from scripts.dp_cache import cached_call

    frames: list[pd.DataFrame] = []
    for w_start, w_end in _slice_ranges(start, end):
        try:
            df = cached_call("get_index_daily", symbol=symbol, start_date=w_start, end_date=w_end, fields=["symbol", "date", "close"])
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] index fetch failed for {symbol} {w_start}-{w_end}: {exc}", file=sys.stderr)
            continue
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["date", "close"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"].astype(str), errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _equal_weight_nav(prices: pd.DataFrame) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    pivot = prices.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    pivot = pivot.ffill().dropna(how="all")
    returns = pivot.pct_change().fillna(0.0)
    # equal weight rebalance annually (jan first trading day)
    weights = pd.DataFrame(0.0, index=pivot.index, columns=pivot.columns)
    active = ~pivot.isna()
    weights = active.div(active.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    portfolio_returns = (returns * weights.shift().fillna(weights.iloc[0])).sum(axis=1)
    nav = (1.0 + portfolio_returns).cumprod()
    nav.iloc[0] = 1.0
    return nav


def _index_nav(index_df: pd.DataFrame) -> pd.Series:
    if index_df.empty:
        return pd.Series(dtype=float)
    prices = index_df.set_index("date")["close"].astype(float)
    return prices / prices.iloc[0]


def _perf(nav: pd.Series) -> dict[str, float]:
    if nav.empty or len(nav) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "annual_volatility": 0.0, "sharpe": 0.0}
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-6)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)
    daily = nav.pct_change().dropna()
    vol = float(daily.std() * np.sqrt(252)) if not daily.empty else 0.0
    sharpe = float((daily.mean() * 252) / (daily.std() * np.sqrt(252))) if daily.std() > 0 else 0.0
    running_max = nav.cummax()
    dd = float((nav / running_max - 1.0).min())
    return {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": dd,
        "annual_volatility": vol,
        "sharpe": sharpe,
    }


CACHE_DIR = ROOT / "output" / "screen_cache"


STOCK_NAMES_CACHE: dict[str, str] = {}


def _load_stock_names(symbols: list[str]) -> dict[str, str]:
    """一次性拉股票中文名映射，缓存到内存与 output/stock_names.json。"""
    cache_file = ROOT / "output" / "stock_names.json"
    if cache_file.exists() and not STOCK_NAMES_CACHE:
        try:
            STOCK_NAMES_CACHE.update(json.loads(cache_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    missing = [s for s in symbols if s not in STOCK_NAMES_CACHE]
    if not missing:
        return {s: STOCK_NAMES_CACHE.get(s, s) for s in symbols}
    try:
        from scripts.dp_cache import cached_call

        detail = cached_call("get_stock_detail", symbol=sorted(missing), fields=["symbol", "name"], status=None)
        if detail is not None and not detail.empty:
            for _, row in detail.iterrows():
                STOCK_NAMES_CACHE[str(row["symbol"])] = str(row.get("name") or row["symbol"])
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(STOCK_NAMES_CACHE, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] stock name fetch failed: {exc}", file=sys.stderr)
    return {s: STOCK_NAMES_CACHE.get(s, s) for s in symbols}


def _hit_gates(payload: dict[str, Any]) -> dict[str, Any]:
    """从 payload 抽取本次筛选中每个 buffett_strict 硬门槛的实际值 + 是否达标。"""
    metrics = payload.get("metrics") or {}
    m = lambda k: metrics.get(k)  # noqa: E731
    return {
        "quality_score": {"value": payload.get("quality_score"), "min": 75.0},
        "roe_latest_pct": {"value": m("roe_latest_pct"), "min": 15.0},
        "roe_floor_pct": {"value": m("roe_floor_pct"), "min": 12.0},
        "gross_margin_latest_pct": {"value": m("gross_margin_latest_pct"), "min": 40.0},
        "gross_margin_std_pct_points": {"value": m("gross_margin_std_pct_points"), "max": 10.0},
        "capex_to_profit_5y": {"value": m("capex_to_profit_5y"), "max": 0.30},
        "long_term_debt_to_profit": {"value": m("long_term_debt_to_profit"), "max": 4.0},
        "normalized_pe": {"value": m("normalized_pe"), "max": 25.0},
        "cash_conversion_5y": {"value": m("cash_conversion_5y"), "min": 0.60},
        "share_dilution_5y": {"value": m("implied_share_dilution_5y"), "max": 0.05},
    }


def _explain_reject(gates: dict[str, Any]) -> list[str]:
    """返回具体哪些硬门槛没通过。空 = 全部通过。"""
    reasons: list[str] = []
    label = {
        "quality_score": "质量分",
        "roe_latest_pct": "最新ROE",
        "roe_floor_pct": "10年ROE下限",
        "gross_margin_latest_pct": "毛利率",
        "gross_margin_std_pct_points": "毛利率标准差",
        "capex_to_profit_5y": "五年CapEx/净利润",
        "long_term_debt_to_profit": "长期有息负债/净利润",
        "normalized_pe": "正常化PE",
        "cash_conversion_5y": "五年现金收益/净利润",
        "share_dilution_5y": "五年隐含稀释",
    }
    for key, spec in gates.items():
        val = spec.get("value")
        if val is None:
            reasons.append(f"{label[key]}: 缺数据")
            continue
        if "min" in spec and val < spec["min"]:
            reasons.append(f"{label[key]}: {val:.2f} < {spec['min']}")
        if "max" in spec and val > spec["max"]:
            reasons.append(f"{label[key]}: {val:.2f} > {spec['max']}")
    return reasons


def _cache_key(as_of: str, symbols: list[str], preset: str, selection_method: str) -> Path:
    from hashlib import sha256

    payload = f"soft-five-dimension-v1|{selection_method}|{preset}|{as_of}|" + "|".join(sorted(symbols))
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{as_of}-{preset}-{digest}.json"


def _screen_a_shares(
    as_of: str,
    symbols: list[str],
    preset: str,
    *,
    selection_method: str = "soft",
    use_cache: bool = True,
    raw_financials: pd.DataFrame | None = None,
    memberships: pd.DataFrame | None = None,
    price_frame: pd.DataFrame | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """筛选 A 股候选。

    返回 (通过 entry_eligible 的候选列表, 全部 payload 列表)。全部 payload 用于
    上游解释某只股票具体因为哪个门槛被淘汰（缺 ROE / 缺现金转换 / 毛利率不足等）。
    命中缓存时不再调用 panda_data，规避套餐限额。
    """
    if __package__ in {None, ""}:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from scripts.core import BUFFETT_STRICT_THRESHOLDS, DEFAULT_THRESHOLDS
        from scripts.screener import screen_symbols
    else:
        from .core import BUFFETT_STRICT_THRESHOLDS, DEFAULT_THRESHOLDS
        from .screener import screen_symbols

    cache_file = _cache_key(as_of, symbols, preset, selection_method)
    if use_cache and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            payloads = data["payloads"]
            print(f"[cache] hit {cache_file.name}", file=sys.stderr)
            if selection_method == "soft":
                eligible = [p for p in payloads if p.get("soft_eligible")]
            else:
                eligible = [p for p in payloads if p.get("decision") == "research_candidate" and p.get("entry_eligible")]
            return eligible, payloads
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] read failed {cache_file.name}: {exc}", file=sys.stderr)

    thresholds = BUFFETT_STRICT_THRESHOLDS if selection_method == "hard" and preset == "buffett_strict" else DEFAULT_THRESHOLDS
    payloads, _ = screen_symbols(
        symbols,
        as_of,
        thresholds=thresholds,
        batch_size=40,
        raw_financials=raw_financials,
        memberships=memberships,
        price_frame=price_frame,
        audit_gate=False,
        quarterly_gate=False,
    )
    if selection_method == "soft":
        from scripts.soft_scorer import score_payloads

        source = {str(payload.get("target_id")): payload for payload in payloads}
        scored = score_payloads(payloads)
        payloads = []
        for score in scored:
            original = source.get(score["symbol"], {})
            payloads.append({
                **original,
                **score,
                "target_id": score["symbol"],
                "soft_score": score["total_score"],
            })
    if use_cache:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"as_of": as_of, "preset": preset, "payloads": payloads}, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] write failed {cache_file.name}: {exc}", file=sys.stderr)
    if selection_method == "soft":
        eligible = [p for p in payloads if p.get("soft_eligible")]
    else:
        eligible = [p for p in payloads if p.get("decision") == "research_candidate" and p.get("entry_eligible")]
    return eligible, payloads


def _point_in_time_index_snapshots(
    index_symbol: str, signal_dates: list[str], top_symbols: int | None
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Fetch the last index composition visible on each signal date."""
    from scripts.dp_cache import cached_call

    limit = 300 if top_symbols is None else int(top_symbols)
    if limit < 1 or limit > 300:
        raise ValueError("top_symbols must be between 1 and 300 for CSI 300")
    snapshots: dict[str, list[str]] = {}
    source_dates: dict[str, str] = {}
    for signal_date in signal_dates:
        end_ts = pd.to_datetime(signal_date)
        start_date = (end_ts - pd.DateOffset(days=45)).strftime("%Y%m%d")
        frame = cached_call(
            "get_index_weights",
            index_symbol=index_symbol,
            start_date=start_date,
            end_date=signal_date,
            fields=["index_symbol", "stock_symbol", "date", "weight"],
        )
        if frame is None or frame.empty:
            raise RuntimeError(f"empty index weights for {index_symbol} at {signal_date}")
        work = frame.copy()
        work["date"] = work["date"].astype(str).str.replace("-", "", regex=False)
        work = work[work["date"] <= signal_date]
        if work.empty:
            raise RuntimeError(f"no point-in-time index snapshot for {index_symbol} at {signal_date}")
        source_date = str(work["date"].max())
        snapshot = work[work["date"] == source_date]
        if "weight" in snapshot:
            snapshot = snapshot.sort_values("weight", ascending=False)
        symbols = snapshot["stock_symbol"].astype(str).drop_duplicates().head(limit).tolist()
        if len(symbols) < min(limit, 300):
            raise RuntimeError(
                f"incomplete {index_symbol} snapshot at {source_date}: {len(symbols)}/{limit} symbols"
            )
        snapshots[signal_date] = symbols
        source_dates[signal_date] = source_date
    return snapshots, source_dates


def _annual_rebalance_dates(
    start: str, end: str, trade_dates: list[pd.Timestamp], *, year_step: int = 1
) -> list[str]:
    """Pick the first available trade date in each year window within [start, end]."""
    trade_dates = sorted(set(trade_dates))
    picked: list[str] = []
    seen: set[int] = set()
    for ts in trade_dates:
        if ts.year in seen:
            continue
        picked.append(ts.strftime("%Y%m%d"))
        seen.add(ts.year)
    if year_step > 1:
        picked = picked[::year_step]
    return picked


def _select_soft_portfolio(
    candidates: list[dict[str, Any]],
    current_holdings: list[str],
    *,
    hold_top: int,
) -> list[str]:
    """Keep healthy incumbents, then fill by score within portfolio limits."""
    by_symbol = {str(row.get("target_id")): row for row in candidates}
    severe_exit_reasons = {
        "audit_opinion",
        "normalized_profit_nonpositive",
        "debt_to_profit_at_least_6",
        "quarterly_profit_or_eps_nonpositive",
    }
    selected: list[str] = []
    bank_count = 0
    industry_counts: dict[str, int] = {}

    def add(symbol: str) -> bool:
        nonlocal bank_count
        row = by_symbol.get(symbol)
        if row is None or not row.get("soft_eligible"):
            return False
        if severe_exit_reasons.intersection(row.get("sell_triggers") or []):
            return False
        is_bank = bool(row.get("is_bank"))
        industry = str(row.get("industry") or "").strip()
        if is_bank and bank_count >= 1:
            return False
        if industry and industry_counts.get(industry, 0) >= 2:
            return False
        selected.append(symbol)
        bank_count += int(is_bank)
        if industry:
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
        return True

    for symbol in current_holdings:
        if len(selected) >= hold_top:
            break
        add(symbol)
    for row in candidates:
        symbol = str(row.get("target_id"))
        if len(selected) >= hold_top:
            break
        if symbol not in selected:
            add(symbol)
    return selected


def _rebuild_a_share_nav(
    start: str,
    end: str,
    universe: list[str] | None,
    preset: str,
    hold_top: int = 8,
    year_step: int = 1,
    *,
    point_in_time_index: str | None = None,
    top_symbols: int | None = None,
    selection_method: str = "soft",
    transaction_cost_bps: float = 15.0,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Annual rebalance: on each Jan first trade date, rescreen and equal-weight top N candidates."""
    from scripts.dp_cache import cached_call

    trade_cal = cached_call("get_trade_cal", exchange="SH", start_date=start, end_date=end)
    if trade_cal is None or trade_cal.empty:
        raise RuntimeError("empty trade calendar")
    trade_cal = trade_cal.copy()
    date_col = "cal_date" if "cal_date" in trade_cal.columns else "nature_date"
    trade_cal[date_col] = pd.to_datetime(trade_cal[date_col].astype(str), errors="coerce")
    open_flag = "is_open" if "is_open" in trade_cal.columns else "is_trade"
    if open_flag in trade_cal.columns:
        trade_cal = trade_cal[trade_cal[open_flag].astype(int) == 1]
    open_dates = sorted(trade_cal[date_col].dropna().tolist())
    rebal_dates = _annual_rebalance_dates(start, end, open_dates, year_step=year_step)

    print(f"[a-shares] rebalance dates: {len(rebal_dates)} - {rebal_dates}", file=sys.stderr)

    if point_in_time_index:
        universe_by_date, index_source_dates = _point_in_time_index_snapshots(
            point_in_time_index, rebal_dates, top_symbols
        )
        universe = sorted({symbol for symbols in universe_by_date.values() for symbol in symbols})
    else:
        universe = sorted(set(universe or []))
        universe_by_date = {date: universe for date in rebal_dates}
        index_source_dates = {date: date for date in rebal_dates}
    if not universe:
        raise RuntimeError("empty A-share universe")

    from scripts import data_pipeline

    years = int(end[:4]) - int(start[:4]) + 12
    print(f"[a-shares] prefetch {len(universe)} point-in-time union symbols", file=sys.stderr)
    raw_financials = data_pipeline.fetch_financial_history(
        universe, end, years=years, batch_size=40
    )
    memberships = data_pipeline.fetch_historical_industries(universe)
    signal_prices, signal_price_failures = data_pipeline.fetch_signal_price_frames(
        universe, rebal_dates, batch_size=40, return_failures=True
    )
    if signal_price_failures:
        print(f"[warn] {len(signal_price_failures)} signal-price batches failed", file=sys.stderr)

    all_prices = _fetch_prices(universe, start, end)
    if all_prices.empty:
        raise RuntimeError("no A-share prices fetched")
    pivot = all_prices.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index().ffill()

    holdings_log: list[dict[str, Any]] = []
    daily_returns = pd.Series(0.0, index=pivot.index, dtype=float)
    current_holdings: list[str] = []

    for i, rebal in enumerate(rebal_dates):
        # 每个信号日前重新 init_token，避免长时间运行时 token 过期
        try:
            _reauth()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] re-auth failed before {rebal}: {exc}", file=sys.stderr)
        current_universe = universe_by_date[rebal]
        candidates, all_payloads = _screen_a_shares(
            rebal,
            current_universe,
            preset,
            selection_method=selection_method,
            raw_financials=raw_financials,
            memberships=memberships,
            price_frame=signal_prices.get(rebal, pd.DataFrame()),
        )
        picks = (
            _select_soft_portfolio(candidates, current_holdings, hold_top=hold_top)
            if selection_method == "soft"
            else [c["target_id"] for c in candidates[:hold_top]]
        )

        # 中文名映射（首次拉取时批量、后续走内存缓存）
        names = _load_stock_names(sorted(set(picks) | set(current_holdings) | {p["target_id"] for p in candidates}))

        prev_set, next_set = set(current_holdings), set(picks)
        new_entries = sorted(next_set - prev_set)
        kept = sorted(next_set & prev_set)
        removed = sorted(prev_set - next_set)

        # 为每只入选股给出命中指标；为剔除的老仓解释是哪个门槛掉了
        by_symbol = {str(p.get("target_id")): p for p in all_payloads}
        entry_details = []
        for sym in picks:
            payload = by_symbol.get(sym, {})
            gates = _hit_gates(payload)
            entry_details.append({
                "symbol": sym,
                "name": names.get(sym, sym),
                "industry": payload.get("industry"),
                "special_case": payload.get("special_case"),
                "quality_score": payload.get("quality_score"),
                "soft_score": payload.get("soft_score"),
                "score_coverage": payload.get("coverage_ratio"),
                "soft_dimensions": payload.get("dimensions", []),
                "conviction_score": payload.get("conviction_score"),
                "gates": gates,
            })
        removed_reasons = []
        for sym in removed:
            payload = by_symbol.get(sym, {})
            gates = _hit_gates(payload)
            removed_reasons.append({
                "symbol": sym,
                "name": names.get(sym, sym),
                "industry": payload.get("industry"),
                "quality_score": payload.get("quality_score"),
                "failed_gates": _explain_reject(gates),
                "decision": payload.get("decision"),
                "sell_triggers": payload.get("sell_triggers", []),
            })

        holdings_log.append({
            "date": rebal,
            "index_source_date": index_source_dates[rebal],
            "point_in_time_universe_size": len(current_universe),
            "candidates": len(candidates),
            "picks": picks,
            "new_entries": new_entries,
            "kept": kept,
            "removed": removed,
            "turnover": 1.0 - len(prev_set & next_set) / max(1, hold_top),
            "transaction_cost_bps": float(transaction_cost_bps),
            "entry_details": entry_details,
            "removed_reasons": removed_reasons,
            "reason_summary": (
                f"共 {len(all_payloads)} 只沪深300点时成分评估，{len(candidates)} 只满足软评分数据覆盖；"
                f"新入 {len(new_entries)}、保留 {len(kept)}、剔除 {len(removed)}。"
            ),
        })
        print(
            f"[a-shares] {rebal}: {len(candidates)} 只可评分 -> 新入 {len(new_entries)} 保留 {len(kept)} 剔除 {len(removed)} 持仓 {picks}",
            file=sys.stderr,
        )
        # apply picks for the interval [rebal, next_rebal)
        try:
            next_rebal = pd.to_datetime(rebal_dates[i + 1]) if i + 1 < len(rebal_dates) else pivot.index[-1] + pd.Timedelta(days=1)
        except Exception:
            next_rebal = pivot.index[-1] + pd.Timedelta(days=1)
        mask = (pivot.index >= pd.to_datetime(rebal)) & (pivot.index < next_rebal)
        if not picks:
            daily_returns.loc[mask] = 0.0
            current_holdings = []
            continue
        cols = [c for c in picks if c in pivot.columns]
        if not cols:
            daily_returns.loc[mask] = 0.0
            current_holdings = []
            continue
        sub = pivot.loc[mask, cols].ffill()
        rets = sub.pct_change().fillna(0.0)
        w = pd.Series(1.0 / len(cols), index=cols)
        daily_returns.loc[mask] = (rets * w).sum(axis=1)
        interval_dates = daily_returns.index[mask]
        if len(interval_dates):
            turnover = 1.0 - len(prev_set & next_set) / max(1, hold_top)
            daily_returns.loc[interval_dates[0]] -= turnover * float(transaction_cost_bps) / 10_000.0
        current_holdings = cols

    nav = (1.0 + daily_returns).cumprod()
    return nav, holdings_log


def run_a_share_backtest(
    start: str,
    end: str,
    preset: str,
    *,
    year_step: int = 1,
    top_symbols: int | None = None,
    mode: str = "strict",
) -> dict[str, Any]:
    """A 股回测。

    - mode="strict": 严格点时 CSI300 股票池 + 五维连续软评分
    - mode="hard": 严格点时 CSI300 股票池 + 旧版 buffett_strict 硬门槛（对照）
    - mode="roster": 名单式（BUFFETT_CN_ROSTER 等权年调仓，配额友好，只用 daily_post）
    """
    if mode == "roster":
        roster = sorted(set(BUFFETT_CN_ROSTER))
        prices = _fetch_prices(roster, start, end)
        covered = sorted(prices["symbol"].unique().tolist()) if not prices.empty else []
        print(f"[a-shares/roster] fetched prices for {len(covered)}/{len(roster)} 中国蓝筹", file=sys.stderr)
        names = _load_stock_names(roster)
        # 用硬编码中文名覆盖 panda_data 的英文/拼音（若有）
        for k, v in BUFFETT_CN_NAMES.items():
            names[k] = v
        nav, log = _roster_nav(
            prices, start, end, year_step, names,
            industry_map=BUFFETT_CN_INDUSTRY, thesis_map=BUFFETT_CN_THESIS,
        )
        bench = _fetch_index("000300.SH", start, end)
        bench_nav = _index_nav(bench).reindex(nav.index).ffill()
        return {
            "market": "a_share",
            "mode": mode,
            "preset": preset,
            "start": start,
            "end": end,
            "roster": roster,
            "covered": covered,
            "universe_size": len(covered),
            "year_step": year_step,
            "nav": {d.strftime("%Y-%m-%d"): float(v) for d, v in nav.items() if pd.notna(v)},
            "benchmark_symbol": "000300.SH",
            "benchmark_nav": {d.strftime("%Y-%m-%d"): float(v) for d, v in bench_nav.items() if pd.notna(v)},
            "performance": _perf(nav),
            "benchmark_performance": _perf(bench_nav.dropna()),
            "holdings_log": log,
        }

    selection_method = "hard" if mode == "hard" else "soft"
    nav, log = _rebuild_a_share_nav(
        start,
        end,
        None,
        preset,
        year_step=year_step,
        point_in_time_index="000300.SH",
        top_symbols=top_symbols,
        selection_method=selection_method,
    )
    bench = _fetch_index("000300.SH", start, end)
    bench_nav = _index_nav(bench).reindex(nav.index).ffill()

    return {
        "market": "a_share",
        "mode": mode,
        "preset": preset,
        "start": start,
        "end": end,
        "universe_size": int(top_symbols or 300),
        "index_symbol": "000300.SH",
        "index_membership_mode": "point_in_time",
        "selection_method": selection_method,
        "financial_threshold_mode": "soft_anchors" if selection_method == "soft" else "hard_gates",
        "portfolio_constraints": {"max_banks": 1, "max_names_per_industry": 2, "hold_top": 8},
        "transaction_cost_bps": 15.0,
        "year_step": year_step,
        "nav": {d.strftime("%Y-%m-%d"): float(v) for d, v in nav.items() if pd.notna(v)},
        "benchmark_symbol": "000300.SH",
        "benchmark_nav": {d.strftime("%Y-%m-%d"): float(v) for d, v in bench_nav.items() if pd.notna(v)},
        "performance": _perf(nav),
        "benchmark_performance": _perf(bench_nav.dropna()),
        "holdings_log": log,
    }


# 中国 A 股经典 Buffett 式蓝筹清单：长期高 ROE、稳定毛利、可理解生意，
# 覆盖消费/白酒/家电/银行/保险/医药/科技龙头，仅用于 A 股名单式诊断。
BUFFETT_CN_ROSTER_META = [
    ("600519.SH", "贵州茅台", "白酒", "长期 ROE 30%+，品牌护城河 + 定价权"),
    ("000858.SZ", "五粮液", "白酒", "浓香白酒龙头，稳定毛利 70%+"),
    ("600036.SH", "招商银行", "股份行", "零售银行龙头，长期 ROA 领先，ROE 15%+"),
    ("601318.SH", "中国平安", "保险", "综合金融龙头，寿险+财险双主业"),
    ("000333.SZ", "美的集团", "白电", "白电三巨头，海外扩张 + ToB 转型"),
    ("000651.SZ", "格力电器", "白电", "空调龙头，长期 ROE 25%+ 但分红波动"),
    ("600276.SH", "恒瑞医药", "创新药", "国内创新药龙头，研发 + 出海"),
    ("600887.SH", "伊利股份", "乳制品", "乳制品全渠道龙头，稳定现金流"),
    ("601166.SH", "兴业银行", "股份行", "同业+投行+零售三足鼎立"),
    ("600030.SH", "中信证券", "证券", "综合券商龙头，投行 + 财富管理"),
    ("600009.SH", "上海机场", "机场", "国际枢纽，长期高毛利 + 免税分成"),
    ("600690.SH", "海尔智家", "白电", "白电全球化 + 智慧家庭"),
    ("300760.SZ", "迈瑞医疗", "医疗器械", "国内医疗器械龙头，出海 + 高端替代"),
    ("600585.SH", "海螺水泥", "建材", "水泥龙头，成本领先 + 稳定现金流"),
    ("601899.SH", "紫金矿业", "有色", "金铜锂矿全球化，逆周期扩张"),
    ("601888.SH", "中国中免", "免税", "国内免税牌照垄断者"),
    ("603288.SH", "海天味业", "调味品", "调味品龙头，品牌 + 渠道 + 定价权"),
    ("000568.SZ", "泸州老窖", "白酒", "浓香老四大名酒，高端化"),
]

BUFFETT_CN_ROSTER = [s for s, *_ in BUFFETT_CN_ROSTER_META]
BUFFETT_CN_NAMES = {s: name for s, name, _, _ in BUFFETT_CN_ROSTER_META}
BUFFETT_CN_INDUSTRY = {s: ind for s, _, ind, _ in BUFFETT_CN_ROSTER_META}
BUFFETT_CN_THESIS = {s: thesis for s, _, _, thesis in BUFFETT_CN_ROSTER_META}


def _roster_nav(
    prices: pd.DataFrame, start: str, end: str, year_step: int, name_map: dict[str, str],
    *, industry_map: dict[str, str] | None = None, thesis_map: dict[str, str] | None = None,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """名单式回测：年度调仓，把当年"有价格覆盖的清单"等权重持有；持仓变动只由
    上市/退市等实际价格覆盖驱动，不做 buffett_strict 硬门槛（配额友好路径）。"""
    industry_map = industry_map or {}
    thesis_map = thesis_map or {}
    if prices.empty:
        return pd.Series(dtype=float), []
    pivot = prices.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index().ffill()
    trade_dates = pivot.index.tolist()
    if not trade_dates:
        return pd.Series(dtype=float), []
    rebal_dates = _annual_rebalance_dates(start, end, trade_dates, year_step=year_step)
    holdings_log: list[dict[str, Any]] = []
    daily_returns = pd.Series(0.0, index=pivot.index, dtype=float)
    prev = set()
    for i, rebal in enumerate(rebal_dates):
        rebal_ts = pd.to_datetime(rebal)
        # 在 rebal 日之前有效的清单：价格已有（不是全 NaN 也不是 0）
        available_row = pivot.loc[pivot.index <= rebal_ts]
        if available_row.empty:
            continue
        latest = available_row.iloc[-1]
        cols = [c for c in pivot.columns if pd.notna(latest.get(c)) and float(latest[c]) > 0]
        cur = set(cols)
        new_entries = sorted(cur - prev)
        kept = sorted(cur & prev)
        removed = sorted(prev - cur)
        old_weights = {symbol: 1.0 / len(prev) for symbol in prev} if prev else {}
        new_weights = {symbol: 1.0 / len(cur) for symbol in cur} if cur else {}
        old_cash = 0.0 if old_weights else 1.0
        new_cash = 0.0 if new_weights else 1.0
        turnover = 0.5 * (
            sum(
                abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
                for symbol in set(old_weights) | set(new_weights)
            )
            + abs(new_cash - old_cash)
        )
        holdings_log.append({
            "date": rebal,
            "candidates": len(cols),
            "picks": cols,
            "new_entries": new_entries,
            "kept": kept,
            "removed": removed,
            "turnover": float(turnover),
            "transaction_cost_bps": 15.0,
            "entry_details": [
                {
                    "symbol": s,
                    "name": name_map.get(s, s),
                    "industry": industry_map.get(s, ""),
                    "reason": thesis_map.get(s, "价格已覆盖，纳入等权清单"),
                }
                for s in new_entries + kept
            ],
            "removed_reasons": [
                {"symbol": s, "name": name_map.get(s, s), "reason": "价格覆盖中断（停牌/退市/数据缺失）"}
                for s in removed
            ],
            "reason_summary": (
                f"名单式：清单当日 {len(cols)} 只有价格；新入 {len(new_entries)}、"
                f"保留 {len(kept)}、剔除 {len(removed)}。"
                + (
                    f" 早期部分股票未上市（如迈瑞医疗 2018 上市、中国中免 2020 免税重组等）会在其上市首年被纳入。"
                    if i == 0 else ""
                )
            ),
        })
        try:
            next_rebal = pd.to_datetime(rebal_dates[i + 1]) if i + 1 < len(rebal_dates) else pivot.index[-1] + pd.Timedelta(days=1)
        except Exception:
            next_rebal = pivot.index[-1] + pd.Timedelta(days=1)
        mask = (pivot.index >= rebal_ts) & (pivot.index < next_rebal)
        if not cols:
            daily_returns.loc[mask] = 0.0
            prev = cur
            continue
        sub = pivot.loc[mask, cols].ffill()
        rets = sub.pct_change().fillna(0.0)
        w = pd.Series(1.0 / len(cols), index=cols)
        daily_returns.loc[mask] = (rets * w).sum(axis=1)
        if rebal_ts in daily_returns.index:
            daily_returns.loc[rebal_ts] -= turnover * 15.0 / 10000.0
        prev = cur
    nav = (1.0 + daily_returns).cumprod()
    return nav, holdings_log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--preset", default="buffett_strict", choices=["default", "buffett_strict"])
    parser.add_argument("--markets", default="a_share", choices=["a_share", "us", "both"], help="运行 A 股、美股或两者")
    parser.add_argument("--year-step", type=int, default=1, help="重扫频率年数（1=每年，2=每两年）")
    parser.add_argument("--top-symbols", type=int, default=None, help="strict/hard 模式：每个信号日按 CSI300 权重取前 N（最大 300）")
    parser.add_argument("--a-mode", default="strict", choices=["strict", "hard", "roster"], help="A 股回测模式：strict=点时 CSI300+软评分；hard=旧硬门槛对照；roster=静态名单")
    parser.add_argument("--output", default=str(ROOT / "生产产物" / "backtest_result.json"))
    args = parser.parse_args()

    username, password, base_url = _consume_credentials()
    _login(username, password, base_url)
    del username, password, base_url

    # 打开 data_pipeline 层的 parquet 缓存：所有 fina_reports/prices/audit 请求
    # 命中缓存后不再消耗套餐配额。
    if __package__ in {None, ""}:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from scripts.data_pipeline import configure_cache
    else:
        from .data_pipeline import configure_cache
    configure_cache(str(ROOT / "output" / "panda_cache_full_a"))

    results: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": args.start,
        "end": args.end,
        "preset": args.preset,
    }
    if args.markets in {"a_share", "both"}:
        try:
            results["a_share"] = run_a_share_backtest(
                args.start, args.end, args.preset,
                year_step=args.year_step, top_symbols=args.top_symbols, mode=args.a_mode,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[error] a_share backtest failed: {exc}", file=sys.stderr)
            results["a_share"] = {"error": str(exc)}

    if args.markets in {"us", "both"}:
        try:
            from scripts.us_strategy import run_us_backtest

            results["us"] = run_us_backtest(args.start, args.end)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] us backtest failed: {exc}", file=sys.stderr)
            results["us"] = {"error": str(exc)}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2)
    , encoding="utf-8")
    print(f"[done] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
