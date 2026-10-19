"""板块轮动：行业/概念 × 涨幅/涨停数/资金，前10/后10，近N日热力表。

缓存与每日快照全部存入 MySQL `app_documents`（`sectors/store.py`），不再写本地 .json 文件。
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import akshare as ak
import pandas as pd
import requests

from .data import fetch_board_members_by_name, fetch_board_spot
from .store import get_doc, make_doc_key, set_doc
from .ths import (
    THS_CONCEPT_SKIP,
    candidate_concept_names,
    fetch_ths_board_members,
    fetch_ths_concept_history,
    fetch_ths_concept_spot,
    fetch_ths_industry_history,
    fetch_ths_industry_spot,
    ths_availability,
)

METRICS = ("涨幅", "涨停数", "资金")
METRIC_FIELD = {"涨幅": "涨跌幅", "涨停数": "涨停数", "资金": "资金"}

_EM_CONCEPT_SKIP_RE = re.compile(
    r"风格|指数|昨日|新高|破净|破发|红利|趋势|价值|成长|微盘|大盘|小盘|中盘|权重|"
    r"MSCI|富时|标普|HS300|深成500|上证|深证|创业板综|创业成份|"
    r"融资融券|深股通|沪股通|打板|连板|涨停|触板|炸板|振幅|换手|"
    r"东方财富热股|券商金股|密集调研|ST股|B股|AB股|AH股"
)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _session_label(d: str) -> str:
    """2026-07-30 -> 07月30日"""
    d = str(d)
    if len(d) >= 10:
        return f"{d[5:7]}月{d[8:10]}日"
    return d


def _clean(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _http() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
    )
    return s


def _is_pure_concept_name(name: str) -> bool:
    name = str(name or "").strip()
    if not name or name in THS_CONCEPT_SKIP:
        return False
    return _EM_CONCEPT_SKIP_RE.search(name) is None


def _filter_pure_concepts(boards: pd.DataFrame) -> pd.DataFrame:
    if boards is None or boards.empty:
        return boards
    mask = boards["板块"].astype(str).map(_is_pure_concept_name)
    return boards.loc[mask].reset_index(drop=True)


def _ths_ready() -> bool:
    try:
        return bool(ths_availability().get("ok"))
    except Exception:
        return False


_EM_FAIL_UNTIL = 0.0
_EM_RETRY_SEC = 180.0


def em_available() -> bool:
    """东财接口是否可用（检测到 SSL/连接重置后进入 180s 熔断冷却，避免每次请求卡顿数秒）。"""
    return time.time() >= _EM_FAIL_UNTIL


def _mark_em_down() -> None:
    global _EM_FAIL_UNTIL
    _EM_FAIL_UNTIL = time.time() + _EM_RETRY_SEC


def _mark_em_up() -> None:
    global _EM_FAIL_UNTIL
    _EM_FAIL_UNTIL = 0.0


def fetch_em_board_spot(kind: str) -> pd.DataFrame:
    """东财 delay 实时板块（带 180s 熔断保护，单页 pz=500 一次拉全）。"""
    if not em_available():
        return pd.DataFrame()
    kind = str(kind).strip()
    fs = "m:90+t:2+f:!50" if kind == "行业" else "m:90+t:3+f:!50"
    sess = _http()
    rows: list[dict[str, Any]] = []
    pn = 1
    try:
        while pn <= 3:
            r = sess.get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn,
                    "pz": 500,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": fs,
                    "fields": "f12,f14,f2,f3,f4,f5,f6,f104,f105,f128,f136,f62",
                },
                timeout=1.5,
            )
            r.raise_for_status()
            diff = ((r.json() or {}).get("data") or {}).get("diff") or []
            if not diff:
                break
            for x in diff:
                name = str(x.get("f14") or "").strip()
                if not name:
                    continue
                rows.append(
                    {
                        "板块": name,
                        "label": str(x.get("f12") or ""),
                        "涨跌幅": _clean(x.get("f3")),
                        "总成交额": _clean(x.get("f6")),
                        "资金": _clean(x.get("f62")) if x.get("f62") is not None else _clean(x.get("f6")),
                        "主力净额": _clean(x.get("f62")),
                        "资金口径": "主力净流入" if x.get("f62") is not None else "成交额",
                        "现价": _clean(x.get("f2")),
                        "领涨名称": str(x.get("f128") or ""),
                        "领涨涨幅": _clean(x.get("f136")),
                        "涨停数": 0,
                    }
                )
            if len(diff) < 500:
                break
            pn += 1
        if rows:
            _mark_em_up()
    except Exception:
        _mark_em_down()
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.sort_values("涨跌幅", ascending=False, na_position="last")
    out = out.drop_duplicates(subset=["板块"], keep="first").reset_index(drop=True)
    return out


_EM_CODE_MAP: dict[str, str] = {}
_EM_CODE_MAP_TS = 0.0
_EM_CODE_MAP_TTL = 3600.0


def em_concept_code_of(name: str) -> str | None:
    """东财板块名称 → BK 代码（支持概念 + 行业 + 同义词映射）。"""
    global _EM_CODE_MAP, _EM_CODE_MAP_TS
    name = str(name or "").strip()
    if not name:
        return None
    if name.upper().startswith("BK") and len(name) >= 6:
        return name.upper()
    if not em_available() and not _EM_CODE_MAP:
        return None
    now = time.time()
    if (now - _EM_CODE_MAP_TS > _EM_CODE_MAP_TTL or not _EM_CODE_MAP) and em_available():
        merged_map: dict[str, str] = {}
        for k in ("概念", "行业"):
            try:
                df = fetch_em_board_spot(k)
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        n = str(r.get("板块") or "").strip()
                        c = str(r.get("label") or "").strip().upper()
                        if n and c:
                            merged_map[n] = c
            except Exception:
                continue
        if merged_map:
            _EM_CODE_MAP = merged_map
            _EM_CODE_MAP_TS = now

    for cand in candidate_concept_names(name):
        if cand in _EM_CODE_MAP:
            return _EM_CODE_MAP[cand]
    # 子串匹配兜底
    stripped = name.replace("概念", "").strip()
    if len(stripped) >= 2:
        hits = [v for k, v in _EM_CODE_MAP.items() if stripped in k or k.replace("概念", "") in stripped]
        if len(hits) == 1:
            return hits[0]
    return None


def fetch_em_concept_kline(code: str, *, count: int = 130) -> list[dict[str, Any]]:
    """东财板块指数日 K（OHLC），带熔断保护。"""
    if not em_available():
        return []
    code = str(code or "").strip().upper()
    if not code.startswith("BK"):
        return []
    sess = _http()
    try:
        r = sess.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": f"90.{code}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": 101,
                "fqt": 0,
                "end": "20500101",
                "lmt": max(int(count), 2),
            },
            timeout=1.5,
        )
        r.raise_for_status()
        _mark_em_up()
    except Exception:
        _mark_em_down()
        return []
    klines = ((r.json() or {}).get("data") or {}).get("klines") or []
    out: list[dict[str, Any]] = []
    for raw in klines:
        parts = str(raw).split(",")
        if len(parts) < 7:
            continue
        dt = parts[0][:10]
        o, c, h, lo = _clean(parts[1]), _clean(parts[2]), _clean(parts[3]), _clean(parts[4])
        vol, amt = _clean(parts[5]), _clean(parts[6])
        if not dt or c is None:
            continue
        out.append(
            {
                "date": dt,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "amount": amt,
                "vol": vol,
            }
        )
    return out


def fetch_em_concept_members(code: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """东财概念/行业成分股（按涨幅排序，带熔断保护）。"""
    if not em_available():
        return []
    code = str(code or "").strip().upper()
    if not code.startswith("BK"):
        return []
    sess = _http()
    rows: list[dict[str, Any]] = []
    pn = 1
    try:
        while pn <= 10 and len(rows) < limit:
            r = sess.get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn,
                    "pz": 100,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": f"b:{code}+f:!50",
                    "fields": "f12,f14,f2,f3,f8,f6",
                },
                timeout=1.5,
            )
            r.raise_for_status()
            diff = ((r.json() or {}).get("data") or {}).get("diff") or []
            if not diff:
                break
            for x in diff:
                c = str(x.get("f12") or "").strip().zfill(6)
                if len(c) != 6 or not c.isdigit():
                    continue
                rows.append(
                    {
                        "代码": c,
                        "纯代码": c,
                        "名称": str(x.get("f14") or c),
                        "现价": _clean(x.get("f2")),
                        "涨跌幅": _clean(x.get("f3")),
                        "成交额": _clean(x.get("f6")),
                        "换手率": _clean(x.get("f8")),
                    }
                )
            if len(diff) < 100:
                break
            pn += 1
        if rows:
            _mark_em_up()
    except Exception:
        _mark_em_down()
        return []
    return rows[:limit]


def fetch_fund_flow_map() -> dict[str, float]:
    try:
        df = ak.stock_board_change_em()
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    name_col = "板块名称" if "板块名称" in df.columns else df.columns[0]
    flow_col = "主力净流入" if "主力净流入" in df.columns else None
    if not flow_col:
        return {}
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        name = str(r.get(name_col) or "").strip()
        flow = _clean(r.get(flow_col))
        if name and flow is not None:
            out[name] = flow
    return out


def _limitup_doc_key(kind: str, session: str) -> str:
    return make_doc_key("sectors_limitup", f"{session}_{kind}")


def _count_limitup(members: pd.DataFrame) -> int:
    if members is None or members.empty or "涨跌幅" not in members.columns:
        return 0
    chg = pd.to_numeric(members["涨跌幅"], errors="coerce").dropna()
    return int(((chg >= 9.5) | (chg >= 19.5)).sum())


def compute_limitup_map(
    boards: pd.DataFrame,
    *,
    kind: str,
    session: str | None = None,
    max_workers: int = 8,
    force: bool = False,
    only_names: set[str] | None = None,
) -> dict[str, int]:
    session = session or _today()
    doc_key = _limitup_doc_key(kind, session)
    cached: dict[str, int] = {}
    if not force:
        raw = get_doc(doc_key, ttl_sec=300)
        if isinstance(raw, dict):
            cached = {str(k): int(v) for k, v in raw.items() if v is not None}

    need = []
    for _, r in boards.iterrows():
        name = str(r.get("板块") or "")
        if not name or name in cached:
            continue
        if only_names is not None and name not in only_names:
            continue
        need.append(name)

    def _one(name: str) -> tuple[str, int]:
        try:
            members = fetch_board_members_by_name(kind, name)
            return name, _count_limitup(members)
        except Exception:
            return name, 0

    if need:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [pool.submit(_one, x) for x in need]
            for fut in as_completed(futs):
                name, n = fut.result()
                cached[name] = int(n)
        set_doc(doc_key, cached, async_write=True)
    return cached


def build_board_metrics(
    kind: str,
    *,
    with_limitup: bool = True,
    session: str | None = None,
    limitup_names: set[str] | None = None,
) -> pd.DataFrame:
    """当日板块指标：优先同花顺，失败再回退东财/新浪。"""
    session = session or _today()
    boards = pd.DataFrame()
    if kind == "行业":
        try:
            boards = fetch_ths_industry_spot()
        except Exception:
            boards = pd.DataFrame()
    elif kind == "概念":
        try:
            boards = fetch_ths_concept_spot()
        except Exception:
            boards = pd.DataFrame()
    if boards.empty:
        try:
            boards = fetch_em_board_spot(kind)
            if kind == "概念":
                boards = _filter_pure_concepts(boards)
        except Exception:
            boards = pd.DataFrame()
    if boards.empty:
        boards = fetch_board_spot(kind)
        if kind == "概念":
            boards = _filter_pure_concepts(boards)
        if boards.empty:
            return boards
        boards = boards.copy()
        flow_map = fetch_fund_flow_map()
        funds, fund_src = [], []
        for _, r in boards.iterrows():
            name = str(r.get("板块") or "")
            if name in flow_map:
                funds.append(flow_map[name])
                fund_src.append("主力净流入")
            else:
                funds.append(_clean(r.get("总成交额")))
                fund_src.append("成交额")
        boards["资金"] = funds
        boards["资金口径"] = fund_src
        boards["涨停数"] = 0

    if with_limitup:
        lim = compute_limitup_map(
            boards, kind=kind, session=session, only_names=limitup_names
        )
        boards["涨停数"] = boards["板块"].map(lambda x: int(lim.get(str(x), 0)))
    else:
        boards["涨停数"] = 0

    boards["涨跌幅"] = pd.to_numeric(boards["涨跌幅"], errors="coerce")
    boards["资金"] = pd.to_numeric(boards["资金"], errors="coerce")
    boards["涨停数"] = pd.to_numeric(boards["涨停数"], errors="coerce").fillna(0).astype(int)
    return boards.reset_index(drop=True)


def save_snapshot(kind: str, boards: pd.DataFrame, session: str | None = None) -> str:
    session = session or _today()
    rows = []
    for _, r in boards.iterrows():
        rows.append(
            {
                "板块": str(r.get("板块") or ""),
                "label": str(r.get("label") or ""),
                "涨跌幅": _clean(r.get("涨跌幅")),
                "涨停数": int(r.get("涨停数") or 0),
                "资金": _clean(r.get("资金")),
                "资金口径": str(r.get("资金口径") or ""),
                "领涨名称": str(r.get("领涨名称") or ""),
                "领涨涨幅": _clean(r.get("领涨涨幅")),
            }
        )
    payload = {
        "date": session,
        "kind": kind,
        "boards": rows,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    doc_key = make_doc_key("sectors_snap", kind)
    bundle = get_doc(doc_key, ttl_sec=60)
    by_date = dict(bundle) if isinstance(bundle, dict) else {}
    by_date[session] = payload
    # 只保留最近 30 个交易日快照，防止超过 2MB
    for old_k in sorted(by_date.keys())[:-30]:
        by_date.pop(old_k, None)
    set_doc(doc_key, by_date, async_write=True)
    return doc_key


def load_snapshots(kind: str, days: int = 5) -> list[dict[str, Any]]:
    doc_key = make_doc_key("sectors_snap", kind)
    bundle = get_doc(doc_key, ttl_sec=300)
    if not isinstance(bundle, dict):
        return []
    dates = sorted(bundle.keys())[-days:]
    return [bundle[d] for d in dates if isinstance(bundle.get(d), dict)]


def _merge_snaps(
    hist: list[dict[str, Any]],
    today_snap: dict[str, Any] | None,
    days: int,
) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for s in hist:
        d = str(s.get("date") or "")
        if d:
            by_date[d] = s
    if today_snap and today_snap.get("date"):
        by_date[str(today_snap["date"])] = today_snap
    dates = sorted(by_date.keys())[-days:]
    return [by_date[d] for d in dates]


def _rank_day(
    boards: list[dict[str, Any]],
    metric: str,
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    field = METRIC_FIELD[metric]
    rows = [b for b in boards if b.get(field) is not None]
    rows.sort(key=lambda x: float(x.get(field) or 0), reverse=True)

    def cell(b: dict[str, Any], rank: int) -> dict[str, Any]:
        return {
            "name": b.get("板块") or "",
            "value": b.get(field),
            "rank": rank,
            "label": b.get("label") or "",
            "metric": metric,
        }

    top = [cell(b, i + 1) for i, b in enumerate(rows[:top_n])]
    weak = rows[-top_n:] if len(rows) >= top_n else rows
    bottom = [cell(b, top_n - i) for i, b in enumerate(weak)]
    return top, bottom


def _collect_ranked_names(boards_rows: list[dict[str, Any]], top_n: int) -> set[str]:
    names: set[str] = set()
    for metric in METRICS:
        t, b = _rank_day(boards_rows, metric, top_n=top_n)
        for cell in t + b:
            if cell.get("name"):
                names.add(str(cell["name"]))
    return names


def _fetch_members_map(kind: str, names: set[str]) -> dict[str, list[dict[str, Any]]]:
    from .stock_names import stock_name_of

    members: dict[str, list[dict[str, Any]]] = {}
    if not names:
        return members

    def _mem(name: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            if _ths_ready():
                df = fetch_ths_board_members(kind, name)
            else:
                df = fetch_board_members_by_name(kind, name)
        except Exception:
            return name, []
        rows = []
        code_col = "纯代码" if "纯代码" in df.columns else (
            "代码" if "代码" in df.columns else None
        )
        for _, m in df.head(50).iterrows():
            code = str(m.get(code_col) or "") if code_col else ""
            if code_col == "代码" and code.startswith(("sh", "sz")):
                code = code[2:]
            rows.append(
                {
                    "代码": code,
                    "名称": stock_name_of(code, fallback=str(m.get("名称") or "")),
                    "现价": _clean(m.get("现价")),
                    "涨跌幅": _clean(m.get("涨跌幅")),
                    "换手率": _clean(m.get("换手率")),
                    "成交额": _clean(m.get("成交额")),
                }
            )
        return name, rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_mem, n) for n in sorted(names)]
        for fut in as_completed(futs):
            name, rows = fut.result()
            members[name] = rows
    return members


def build_rotation_payload(
    *,
    days: int = 5,
    top_n: int = 10,
    with_limitup: bool = True,
    with_members: bool = True,
) -> dict[str, Any]:
    """生成板块轮动完整数据（近 N 日）。"""
    session = _today()
    payload: dict[str, Any] = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(METRICS),
        "kinds": {},
    }

    use_ths = _ths_ready()
    ind_hist = fetch_ths_industry_history(days=days) if use_ths else []
    concept_hist = fetch_ths_concept_history(days=days) if use_ths else []

    for kind in ("行业", "概念"):
        boards_df = build_board_metrics(
            kind, with_limitup=False, session=session
        )
        today_rows = [
            {
                "板块": str(r.get("板块") or ""),
                "label": str(r.get("label") or ""),
                "涨跌幅": _clean(r.get("涨跌幅")),
                "涨停数": 0,
                "资金": _clean(r.get("资金")),
                "资金口径": str(r.get("资金口径") or ""),
                "领涨名称": str(r.get("领涨名称") or ""),
                "领涨涨幅": _clean(r.get("领涨涨幅")),
            }
            for _, r in boards_df.iterrows()
        ]
        ranked_names = _collect_ranked_names(today_rows, top_n)

        if with_limitup and not boards_df.empty:
            lim = compute_limitup_map(
                boards_df, kind=kind, session=session, only_names=ranked_names
            )
            boards_df["涨停数"] = boards_df["板块"].map(lambda x: int(lim.get(str(x), 0)))
            for row in today_rows:
                row["涨停数"] = int(lim.get(str(row["板块"]), 0))

        save_snapshot(kind, boards_df, session=session)
        source = "同花顺行业" if kind == "行业" else "同花顺概念"
        today_snap = {"date": session, "kind": kind, "boards": today_rows, "source": source}

        if kind == "行业":
            snaps = _merge_snaps(ind_hist, today_snap, days=days)
        else:
            snaps = _merge_snaps(concept_hist, today_snap, days=days)

        snaps_desc = list(reversed(snaps))
        dates = [_session_label(str(s.get("date") or "")) for s in snaps_desc]
        by_metric: dict[str, Any] = {}
        for metric in METRICS:
            tops, bottoms = [], []
            for s in snaps_desc:
                t, b = _rank_day(s.get("boards") or [], metric, top_n=top_n)
                tops.append(t)
                bottoms.append(b)
            by_metric[metric] = {"top": tops, "bottom": bottoms}

        members: dict[str, list[dict[str, Any]]] = {}
        if with_members:
            names = set(ranked_names)
            for s in snaps_desc[: min(3, len(snaps_desc))]:
                t, b = _rank_day(s.get("boards") or [], "涨幅", top_n=top_n)
                for cell in t + b:
                    if cell.get("name"):
                        names.add(str(cell["name"]))
            members = _fetch_members_map(kind, names)

        note = "行业/概念=同花顺（数据库持久化）；行业资金=主力净流入，概念资金=成交额。"

        payload["kinds"][kind] = {
            "dates": dates,
            "by_metric": by_metric,
            "members": members,
            "fund_note": note,
            "board_count": int(len(boards_df)),
        }

    return payload
