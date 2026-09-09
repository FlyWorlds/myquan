"""因子27 / 策略十六·核心龙头：通达信概念活跃度偏高 → 概念内龙头（滚动近 3 个月冻结）。

规则（研究用途，非投资建议）：
  · 活跃度：通达信概念现价成交额（资金）≥ 截面中位数，再取成交额 TopN 概念
  · 每个概念至多 K 只：成分过滤后按涨跌幅、成交额取前 K
  · 过滤：非创业 / 非科创 / 非北交 / 非 ST / 现价 < 100
  · 选股周期：滚动近 3 个月（非自然季度 Q1/Q2/Q3）；默认写 backtest/strategy16_core_leader/picks_quarter.json
"""

from __future__ import annotations

import calendar
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PICKS_PATH = ROOT / "backtest" / "strategy16_core_leader" / "picks_quarter.json"
_LAST_SPOT_SOURCE = "tdx_concept_activity"

DEFAULT_MAX_CONCEPTS = 40
DEFAULT_PER_CONCEPT = 2
DEFAULT_TARGET_POOL = 30
DEFAULT_PRICE_MAX = 100.0
DEFAULT_HORIZON_MONTHS = 3

# 风格/宽基样本，不是「活跃龙头」题材
_STYLE_CONCEPTS = {
    "基金重仓",
    "标准普尔",
    "高市净率",
    "低市净率",
    "高市盈率",
    "低市盈率",
    "融资融券",
    "沪股通",
    "深股通",
    "深成500",
    "上证50",
    "沪深300样本",
    "中证500",
    "中证1000",
    "中证2000",
    "机构重仓",
    "社保重仓",
    "QFII重仓",
    "券商重仓",
}


def is_theme_concept(name: str) -> bool:
    n = str(name or "").strip()
    if not n or n in _STYLE_CONCEPTS:
        return False
    if "市净" in n or "市盈" in n or "样本" in n:
        return False
    if "预增" in n or "预减" in n:
        return False
    if n.startswith("中证") or n.startswith("上证") or n.startswith("沪深"):
        return False
    if "重仓" in n:
        return False
    return True


def add_months(d: date, months: int) -> date:
    m0 = int(d.month) - 1 + int(months)
    y = int(d.year) + m0 // 12
    m = m0 % 12 + 1
    day = min(int(d.day), calendar.monthrange(y, m)[1])
    return date(y, m, day)


def rolling_3m_window(today: date | None = None) -> dict[str, str]:
    """滚动近 3 个月：窗口 [as_of-3m, as_of]，名单有效至 as_of+3m。"""
    end = today or date.today()
    start = add_months(end, -DEFAULT_HORIZON_MONTHS)
    until = add_months(end, DEFAULT_HORIZON_MONTHS)
    label = f"{start.isoformat()}~{end.isoformat()}"
    return {
        "horizon": "rolling_3m",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "valid_until": until.isoformat(),
        "label": label,
    }


def is_st_name(name: str) -> bool:
    n = str(name or "").strip().upper().replace(" ", "")
    if not n:
        return False
    return "ST" in n or n.startswith("*")


def is_core_leader_board(code: str) -> bool:
    """主板（剔创业 300/301、科创 688/689、北交 8/4）。"""
    c = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    if c.startswith(("688", "689", "300", "301")):
        return False
    if c.startswith(("8", "4", "92", "43", "83", "87")):
        return False
    return True


def passes_stock_filter(
    code: str,
    name: str = "",
    price: float | None = None,
    *,
    price_max: float = DEFAULT_PRICE_MAX,
) -> bool:
    if not is_core_leader_board(code):
        return False
    if is_st_name(name):
        return False
    if price is None:
        return False
    try:
        px = float(price)
    except (TypeError, ValueError):
        return False
    return 0 < px < float(price_max)


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def select_hot_concepts(
    spot: pd.DataFrame,
    *,
    max_concepts: int = DEFAULT_MAX_CONCEPTS,
    activity_cols: tuple[str, ...] = ("总成交额", "资金", "成交额"),
) -> list[dict[str, Any]]:
    """成交额 ≥ 中位数（偏高）后取 TopN。"""
    if spot is None or spot.empty:
        return []
    df = spot.copy()
    activity: list[float | None] = []
    for _, row in df.iterrows():
        val = None
        for col in activity_cols:
            if col in df.columns:
                val = _num(row.get(col))
                if val is not None:
                    break
        activity.append(val)
    df = df.assign(_activity=activity)
    valid = df[df["_activity"].notna() & (df["_activity"] > 0)].copy()
    if valid.empty:
        return []
    median = float(valid["_activity"].median())
    # 已是短名单（如轮动缓存 TopN）则不再砍半
    if len(valid) <= int(max_concepts):
        hot = valid.sort_values("_activity", ascending=False)
    else:
        hot = valid[valid["_activity"] >= median].copy()
        hot = hot.sort_values("_activity", ascending=False)
    out: list[dict[str, Any]] = []
    for rec in hot.to_dict("records"):
        if len(out) >= int(max_concepts):
            break
        name = str(rec.get("板块") or rec.get("name") or rec.get("概念") or "").strip()
        if not name or not is_theme_concept(name):
            continue
        out.append(
            {
                "rank": len(out) + 1,
                "name": name,
                "code": str(rec.get("label") or rec.get("code") or ""),
                "activity": _num(rec.get("_activity")),
                "chg_pct": _num(rec.get("涨跌幅")),
                "median": median,
            }
        )
    return out


def pick_leaders_from_members(
    members: pd.DataFrame | list[dict[str, Any]],
    *,
    concept: str,
    per_concept: int = DEFAULT_PER_CONCEPT,
    price_max: float = DEFAULT_PRICE_MAX,
) -> list[dict[str, Any]]:
    """概念内过滤后按涨跌幅、成交额取前 K。"""
    if members is None:
        return []
    if isinstance(members, pd.DataFrame):
        rows = members.to_dict("records")
    else:
        rows = list(members)
    scored: list[dict[str, Any]] = []
    for raw in rows:
        code = "".join(ch for ch in str(raw.get("纯代码") or raw.get("代码") or raw.get("code") or "") if ch.isdigit())
        code = code.zfill(6)[-6:] if code else ""
        name = str(raw.get("名称") or raw.get("name") or "").strip()
        price = _num(raw.get("现价") or raw.get("price"))
        if not code or not passes_stock_filter(code, name, price, price_max=price_max):
            continue
        scored.append(
            {
                "code": code,
                "name": name,
                "concept": concept,
                "price": price,
                "chg_pct": _num(raw.get("涨跌幅") or raw.get("chg_pct")),
                "amount": _num(raw.get("成交额") or raw.get("amount")),
            }
        )
    scored.sort(
        key=lambda x: (
            x["chg_pct"] is None,
            -(x["chg_pct"] or 0.0),
            x["amount"] is None,
            -(x["amount"] or 0.0),
            x["code"],
        )
    )
    out: list[dict[str, Any]] = []
    for i, item in enumerate(scored[: int(per_concept)], 1):
        item = dict(item)
        item["rank_in_concept"] = i
        out.append(item)
    return out


def _spot_dict_to_df(spot: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, rec in (spot or {}).items():
        fund = rec.get("资金")
        amount = rec.get("总成交额") or rec.get("成交额") or fund
        rows.append(
            {
                "板块": name,
                "label": rec.get("code") or rec.get("label") or "",
                "涨跌幅": rec.get("涨跌幅"),
                "资金": amount,
                "总成交额": amount,
                "成交额": amount,
            }
        )
    return pd.DataFrame(rows)


def _spot_has_activity(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    for col in ("总成交额", "资金", "成交额"):
        if col in df.columns and df[col].notna().any():
            return True
    return False


def _spot_from_rotation_cache() -> pd.DataFrame:
    """盘前/行情空时：用板块轮动缓存最近一日成交额排名（偏高概念）。"""
    path = ROOT / "sectors" / "cache" / "tdx_rotation_api.json"
    if not path.is_file():
        return pd.DataFrame()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return pd.DataFrame()
    kind = ((raw.get("kinds") or {}).get("概念") or {})
    top = ((kind.get("by_metric") or {}).get("成交额") or {}).get("top") or []
    latest = top[0] if top else []
    rows: list[dict[str, Any]] = []
    for it in latest:
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        val = _num(it.get("value"))
        rows.append(
            {
                "板块": name,
                "label": it.get("label") or "",
                "涨跌幅": None,
                "资金": val,
                "总成交额": val,
                "成交额": val,
            }
        )
    return pd.DataFrame(rows)


def fetch_concept_spot() -> pd.DataFrame:
    """活跃度：通达信盘中报价 → 东财现价 → 轮动缓存昨收 → 通达信指数 K。"""
    global _LAST_SPOT_SOURCE
    try:
        from sectors.live import _spot_from_tdx

        df = _spot_dict_to_df(_spot_from_tdx())
        if _spot_has_activity(df):
            _LAST_SPOT_SOURCE = "tdx_quotes"
            return df
    except Exception:
        pass
    try:
        from sectors.rotation import _filter_pure_concepts, fetch_em_board_spot

        df = _filter_pure_concepts(fetch_em_board_spot("概念"))
        if _spot_has_activity(df):
            _LAST_SPOT_SOURCE = "em_concept_spot"
            return df
    except Exception:
        pass
    cached = _spot_from_rotation_cache()
    if _spot_has_activity(cached):
        _LAST_SPOT_SOURCE = "rotation_cache_last_session"
        return cached
    try:
        from sectors.tdx import fetch_tdx_concept_spot

        df = fetch_tdx_concept_spot()
        if _spot_has_activity(df):
            _LAST_SPOT_SOURCE = "tdx_index_kline"
            return df
    except Exception:
        pass
    _LAST_SPOT_SOURCE = "empty"
    return cached if cached is not None else pd.DataFrame()


def _enrich_member_quotes(df: pd.DataFrame) -> pd.DataFrame:
    """补涨跌幅/现价（盘前通达信常缺涨跌幅，改走新浪昨收）。"""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    codes: list[str] = []
    for raw in out.to_dict("records"):
        code = "".join(ch for ch in str(raw.get("纯代码") or raw.get("代码") or raw.get("code") or "") if ch.isdigit())
        code = code.zfill(6)[-6:] if code else ""
        if code:
            codes.append(code)
    if not codes:
        return out
    try:
        from sectors.metrics import fetch_member_quotes_sina

        quotes = fetch_member_quotes_sina(codes)
    except Exception:
        quotes = {}
    if "涨跌幅" not in out.columns:
        out["涨跌幅"] = None
    if "现价" not in out.columns:
        out["现价"] = None
    if "成交额" not in out.columns:
        out["成交额"] = None
    for i, raw in out.iterrows():
        code = "".join(ch for ch in str(raw.get("纯代码") or raw.get("代码") or "") if ch.isdigit())
        code = code.zfill(6)[-6:] if code else ""
        q = quotes.get(code) or {}
        if q.get("chgPct") is not None:
            out.at[i, "涨跌幅"] = q.get("chgPct")
        if q.get("price") is not None and _num(raw.get("现价")) is None:
            out.at[i, "现价"] = q.get("price")
    live_chg = out["涨跌幅"].map(_num)
    if live_chg.notna().any() and (live_chg.abs() > 1e-9).any():
        return out
    # 盘前无当日涨跌：用通达信近 2 日收盘算上一日涨幅（龙头口径）
    need: list[str] = []
    for raw in out.to_dict("records"):
        code = "".join(ch for ch in str(raw.get("纯代码") or raw.get("代码") or "") if ch.isdigit())
        code = code.zfill(6)[-6:] if code else ""
        if code and is_core_leader_board(code) and not is_st_name(str(raw.get("名称") or "")):
            need.append(code)
    if not need:
        return out
    try:
        from sectors.tdx import fetch_tdx_stock_klines

        kl = fetch_tdx_stock_klines(need, count=3)
    except Exception:
        kl = {}
    for i, raw in out.iterrows():
        code = "".join(ch for ch in str(raw.get("纯代码") or raw.get("代码") or "") if ch.isdigit())
        code = code.zfill(6)[-6:] if code else ""
        bars = kl.get(code) or []
        if len(bars) < 2:
            continue
        prev_c = _num(bars[-2].get("close"))
        last_c = _num(bars[-1].get("close"))
        if prev_c and last_c:
            out.at[i, "涨跌幅"] = (last_c / prev_c - 1.0) * 100.0
        if _num(raw.get("现价")) is None and last_c:
            out.at[i, "现价"] = last_c
        amt = _num(bars[-1].get("amount"))
        if amt is not None:
            out.at[i, "成交额"] = amt
    return out


def fetch_concept_members(name: str) -> pd.DataFrame:
    from sectors.live import fetch_concept_member_rows

    payload = fetch_concept_member_rows(name, limit=80)
    df = pd.DataFrame(payload.get("members") or [])
    return _enrich_member_quotes(df)


def build_quarter_pool(
    *,
    today: date | None = None,
    max_concepts: int = DEFAULT_MAX_CONCEPTS,
    per_concept: int = DEFAULT_PER_CONCEPT,
    target_pool: int = DEFAULT_TARGET_POOL,
    price_max: float = DEFAULT_PRICE_MAX,
    spot: pd.DataFrame | None = None,
    members_by_concept: dict[str, Any] | None = None,
    fetch: bool = True,
) -> dict[str, Any]:
    """构建核心龙头池（滚动近 3 个月冻结）。fetch=False 时仅用传入的 spot / members。

    按活跃概念从高到低填池：每概念≤K，去重后凑满 target_pool（默认 30）即停。
    """
    end_d = today or date.today()
    as_of = end_d.isoformat()
    win = rolling_3m_window(end_d)
    errors: list[str] = []
    source = "tdx_concept_activity"
    if spot is None and fetch:
        try:
            spot = fetch_concept_spot()
            source = _LAST_SPOT_SOURCE
        except Exception as e:  # noqa: BLE001
            errors.append(f"概念现价失败: {e}")
            spot = pd.DataFrame()
    if spot is None:
        spot = pd.DataFrame()

    concepts = select_hot_concepts(spot, max_concepts=max_concepts)
    if not concepts and spot.empty:
        errors.append("通达信概念现价为空（未装通达信或拉取失败）")

    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    if members_by_concept is None and fetch and concepts:
        members_by_concept = {}

        def _one(name: str) -> tuple[str, pd.DataFrame]:
            try:
                return name, fetch_concept_members(name)
            except Exception:  # noqa: BLE001
                return name, pd.DataFrame()

        with ThreadPoolExecutor(max_workers=min(8, len(concepts))) as pool:
            futs = [pool.submit(_one, c["name"]) for c in concepts]
            for fut in as_completed(futs):
                name, df = fut.result()
                members_by_concept[name] = df

    members_by_concept = members_by_concept or {}
    for c in concepts:
        name = str(c["name"])
        members = members_by_concept.get(name)
        leaders = pick_leaders_from_members(
            members if members is not None else pd.DataFrame(),
            concept=name,
            per_concept=per_concept,
            price_max=price_max,
        )
        new_leaders: list[dict[str, Any]] = []
        for item in leaders:
            code = item["code"]
            if code in seen:
                item = dict(item)
                item["duplicate"] = True
                for prev in picks:
                    if prev.get("code") == code:
                        extra = str(prev.get("concepts") or prev.get("concept") or "")
                        if name not in extra.split(" / "):
                            prev["concepts"] = f"{extra} / {name}" if extra else name
                        break
                continue
            if target_pool > 0 and len(seen) >= int(target_pool):
                break
            seen.add(code)
            picks.append(item)
            new_leaders.append(item)
        c["picked"] = len(new_leaders)
        if target_pool > 0 and len(seen) >= int(target_pool):
            break

    for i, item in enumerate(picks, 1):
        item["rank"] = i

    used_concepts = [c for c in concepts if int(c.get("picked") or 0) > 0]
    note = (
        f"近3个月 {win['label']} 冻结至 {win['valid_until']}："
        f"活跃概念偏高（成交额≥中位数，最多扫 Top{max_concepts}），"
        f"每概念≤{per_concept}，池约 {int(target_pool)} 只；"
        f"实际 {len(picks)} 只 / {len(used_concepts)} 个概念入池；"
        f"主板非ST非科创创业、现价<{price_max:.0f}。"
        "买卖同策略一（因子26/2/22）。研究用途，非投资建议。"
    )
    if picks and all(it.get("chg_pct") is None for it in picks):
        note += " 本批生成时无个股涨跌幅，概念内未按龙头排序；开盘后请重跑 python strategy/run_core_leader_pool.py。"
    if errors:
        note = "；".join(errors) + "。 " + note

    return {
        "horizon": win["horizon"],
        "window_start": win["window_start"],
        "window_end": win["window_end"],
        "valid_until": win["valid_until"],
        "label": win["label"],
        "quarter": win["label"],
        "as_of": as_of,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "max_concepts": int(max_concepts),
        "per_concept": int(per_concept),
        "target_pool": int(target_pool),
        "price_max": float(price_max),
        "concepts": concepts,
        "used_concepts": used_concepts,
        "picks": picks,
        "n_concepts": len(concepts),
        "n_used_concepts": len(used_concepts),
        "n_picks": len(picks),
        "note": note,
        "errors": errors,
    }


def save_picks(payload: dict[str, Any], path: Path | None = None) -> Path:
    out = path or DEFAULT_PICKS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_picks(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PICKS_PATH
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


def pick_codes(payload: dict[str, Any] | None = None) -> list[str]:
    data = payload if payload is not None else load_picks()
    out: list[str] = []
    seen: set[str] = set()
    for it in data.get("picks") or []:
        code = "".join(ch for ch in str(it.get("code") or "") if ch.isdigit()).zfill(6)[-6:]
        if code and code != "000000" and code not in seen:
            seen.add(code)
            out.append(code)
    return out
