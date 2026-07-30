"""板块轮动：行业/概念 × 涨幅/涨停数/资金，前10/后10，近N日热力表。"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests

from .data import fetch_board_members_by_name, fetch_board_spot

ROOT = Path(__file__).resolve().parent
SNAP_DIR = ROOT / "snapshots"
CACHE_DIR = ROOT / "cache"

METRICS = ("涨幅", "涨停数", "资金")
METRIC_FIELD = {"涨幅": "涨跌幅", "涨停数": "涨停数", "资金": "资金"}


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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
    )
    return s


def fetch_em_board_spot(kind: str) -> pd.DataFrame:
    """东财 delay 实时板块（行业/概念），名称口径接近常见轮动 App。"""
    kind = str(kind).strip()
    fs = "m:90+t:2+f:!50" if kind == "行业" else "m:90+t:3+f:!50"
    sess = _http()
    rows: list[dict[str, Any]] = []
    pn = 1
    while pn <= 20:
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
                "fs": fs,
                "fields": "f12,f14,f2,f3,f4,f5,f6,f104,f105,f128,f136,f62",
            },
            timeout=15,
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
                    "资金口径": "主力净流入" if x.get("f62") is not None else "成交额",
                    "领涨名称": str(x.get("f128") or ""),
                    "领涨涨幅": _clean(x.get("f136")),
                    "涨停数": 0,
                }
            )
        if len(diff) < 100:
            break
        pn += 1
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    # 同名保留涨幅更高的一条（白酒Ⅱ/Ⅲ 等）
    out = out.sort_values("涨跌幅", ascending=False, na_position="last")
    out = out.drop_duplicates(subset=["板块"], keep="first").reset_index(drop=True)
    return out


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


def _limitup_cache_path(kind: str, session: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"limitup_{session}_{kind}.json"


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
    path = _limitup_cache_path(kind, session)
    cached: dict[str, int] = {}
    if path.exists() and not force:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

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
        done = 0
        total = len(need)
        print(f"  统计涨停数 {kind}: 待拉取 {total} 个板块…")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [pool.submit(_one, x) for x in need]
            for fut in as_completed(futs):
                name, n = fut.result()
                cached[name] = int(n)
                done += 1
                if done % 20 == 0 or done == total:
                    print(f"    {kind} 涨停进度 {done}/{total}")
        path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


def build_board_metrics(
    kind: str,
    *,
    with_limitup: bool = True,
    session: str | None = None,
    limitup_names: set[str] | None = None,
) -> pd.DataFrame:
    """当日板块指标：优先东财 delay，失败回退新浪。"""
    session = session or _today()
    try:
        boards = fetch_em_board_spot(kind)
    except Exception:
        boards = pd.DataFrame()
    if boards.empty:
        boards = fetch_board_spot(kind)
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


def _snap_path(kind: str, session: str):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    return SNAP_DIR / f"{session}_{kind}.json"


def save_snapshot(kind: str, boards: pd.DataFrame, session: str | None = None):
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
    path = _snap_path(kind, session)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_snapshots(kind: str, days: int = 5) -> list[dict[str, Any]]:
    if not SNAP_DIR.exists():
        return []
    files = sorted(SNAP_DIR.glob(f"*_{kind}.json"), reverse=True)
    out = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("kind") != kind:
            continue
        out.append(data)
        if len(out) >= days:
            break
    out.sort(key=lambda x: str(x.get("date") or ""))
    return out


def fetch_sw_industry_history(days: int = 5) -> list[dict[str, Any]]:
    """申万二级行业近 N 个交易日涨跌（用于行业历史列）。"""
    end = datetime.now()
    start = end - timedelta(days=max(days * 3, 14))
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    try:
        df = ak.index_analysis_daily_sw(
            symbol="二级行业", start_date=start_s, end_date=end_s
        )
    except Exception as e:
        print(f"  申万二级行业历史拉取失败: {e}")
        return []
    if df is None or df.empty:
        return []

    date_col = next((c for c in df.columns if "日期" in str(c)), None)
    name_col = next((c for c in df.columns if "名称" in str(c)), None)
    chg_col = "涨跌幅" if "涨跌幅" in df.columns else None
    amt_col = next((c for c in df.columns if c == "成交额"), None)
    if not date_col or not name_col or not chg_col:
        return []

    work = df.copy()
    work["_date"] = pd.to_datetime(work[date_col]).dt.strftime("%Y-%m-%d")
    work["_name"] = work[name_col].astype(str).str.strip()
    work["_chg"] = pd.to_numeric(work[chg_col], errors="coerce")
    if amt_col:
        # 申万成交额单位多为亿元
        work["_amt"] = pd.to_numeric(work[amt_col], errors="coerce") * 1e8
    else:
        work["_amt"] = pd.NA

    dates = sorted(work["_date"].dropna().unique().tolist())
    if not dates:
        return []
    dates = dates[-days:]
    snaps: list[dict[str, Any]] = []
    for d in dates:
        sub = work[work["_date"] == d]
        boards = []
        for _, r in sub.iterrows():
            boards.append(
                {
                    "板块": r["_name"],
                    "label": "",
                    "涨跌幅": _clean(r["_chg"]),
                    "涨停数": 0,
                    "资金": _clean(r["_amt"]),
                    "资金口径": "成交额",
                    "领涨名称": "",
                    "领涨涨幅": None,
                }
            )
        snaps.append({"date": d, "kind": "行业", "boards": boards, "source": "申万二级"})
    return snaps


def _ths_concept_clid_cache() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "ths_concept_clids.json"


def load_ths_concept_clid_map(*, force: bool = False) -> dict[str, str]:
    """同花顺概念名 → 指数 clid（如 885728），带本地缓存。"""
    path = _ths_concept_clid_cache()
    if path.exists() and not force:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            items = cached.get("items") or {}
            # 缓存超过 7 天则刷新
            ts = str(cached.get("updated_at") or "")
            if items and ts:
                try:
                    age = datetime.now() - datetime.fromisoformat(ts)
                    if age.days < 7:
                        return {str(k): str(v) for k, v in items.items()}
                except Exception:
                    if items:
                        return {str(k): str(v) for k, v in items.items()}
        except Exception:
            pass

    sess = _http()
    sess.headers["Referer"] = "https://q.10jqka.com.cn/"
    r = sess.get("https://q.10jqka.com.cn/gn/", timeout=20)
    r.encoding = "gbk"
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(r.text, "lxml")
    box = soup.find("div", class_="cate_inner")
    if not box:
        if path.exists():
            try:
                return {
                    str(k): str(v)
                    for k, v in (json.loads(path.read_text(encoding="utf-8")).get("items") or {}).items()
                }
            except Exception:
                return {}
        return {}

    detail_pairs: list[tuple[str, str]] = []
    for a in box.find_all("a", href=True):
        href = a["href"]
        name = a.get_text(strip=True)
        if "/gn/detail/code/" in href and name:
            detail_pairs.append((name, href.rstrip("/").split("/")[-1]))

    def _clid(item: tuple[str, str]) -> tuple[str, str | None]:
        name, detail = item
        try:
            rr = sess.get(
                f"https://q.10jqka.com.cn/gn/detail/code/{detail}/",
                timeout=15,
            )
            rr.encoding = "gbk"
            m = re.search(r'id=["\']clid["\'][^>]*value=["\'](\d+)["\']', rr.text)
            if not m:
                m = re.search(r'value=["\'](\d+)["\'][^>]*id=["\']clid["\']', rr.text)
            return name, m.group(1) if m else None
        except Exception:
            return name, None

    print(f"  同花顺概念代码映射: {len(detail_pairs)} 个…")
    mapping: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(_clid, p) for p in detail_pairs]
        done = 0
        for fut in as_completed(futs):
            name, clid = fut.result()
            if name and clid:
                mapping[name] = clid
            done += 1
            if done % 50 == 0 or done == len(detail_pairs):
                print(f"    概念代码进度 {done}/{len(detail_pairs)} · 有效 {len(mapping)}")

    path.write_text(
        json.dumps(
            {"updated_at": datetime.now().isoformat(timespec="seconds"), "items": mapping},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return mapping


def _parse_ths_last_js(text: str) -> list[tuple[str, float, float | None]]:
    """解析 last.js → [(date, close, amount), ...]"""
    m = re.search(r"last\((.*)\)\s*$", text, re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(1))
    except Exception:
        return []
    rows: list[tuple[str, float, float | None]] = []
    for part in str(obj.get("data") or "").split(";"):
        cols = part.split(",")
        if len(cols) < 5 or not cols[4]:
            continue
        try:
            close = float(cols[4])
        except ValueError:
            continue
        amt = None
        if len(cols) > 6 and cols[6]:
            try:
                amt = float(cols[6])
            except ValueError:
                amt = None
        d = cols[0]
        if len(d) == 8:
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        rows.append((d, close, amt))
    return rows


def fetch_ths_concept_history(days: int = 5) -> list[dict[str, Any]]:
    """同花顺概念近 N 个交易日涨跌（用于概念历史列）。"""
    mapping = load_ths_concept_clid_map()
    if not mapping:
        print("  同花顺概念代码为空，跳过概念历史")
        return []

    sess = _http()
    sess.headers.update(
        {
            "Referer": "http://q.10jqka.com.cn",
            "Host": "d.10jqka.com.cn",
        }
    )

    # date -> {name: {涨跌幅, 资金}}
    by_date: dict[str, dict[str, dict[str, Any]]] = {}

    def _one(item: tuple[str, str]) -> tuple[str, list[tuple[str, float, float | None]]]:
        name, clid = item
        try:
            r = sess.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{clid}/01/last.js",
                timeout=12,
            )
            closes = _parse_ths_last_js(r.text)
            out: list[tuple[str, float, float | None]] = []
            for i in range(1, len(closes)):
                d, c, a = closes[i]
                prev = closes[i - 1][1]
                if not prev:
                    continue
                out.append((d, (c / prev - 1.0) * 100.0, a))
            return name, out[-(days + 1) :]
        except Exception:
            return name, []

    items = list(mapping.items())
    print(f"  拉取同花顺概念近几日: {len(items)} 个…")
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(_one, it) for it in items]
        for fut in as_completed(futs):
            name, series = fut.result()
            for d, chg, amt in series:
                by_date.setdefault(d, {})[name] = {
                    "涨跌幅": chg,
                    "资金": amt,
                }
            done += 1
            if done % 80 == 0 or done == len(items):
                print(f"    概念行情进度 {done}/{len(items)}")

    dates = sorted(by_date.keys())
    if not dates:
        return []
    dates = dates[-days:]
    snaps: list[dict[str, Any]] = []
    for d in dates:
        boards = []
        for name, vals in by_date[d].items():
            boards.append(
                {
                    "板块": name,
                    "label": mapping.get(name, ""),
                    "涨跌幅": _clean(vals.get("涨跌幅")),
                    "涨停数": 0,
                    "资金": _clean(vals.get("资金")),
                    "资金口径": "成交额",
                    "领涨名称": "",
                    "领涨涨幅": None,
                }
            )
        snaps.append({"date": d, "kind": "概念", "boards": boards, "source": "同花顺概念"})
    return snaps


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
    members: dict[str, list[dict[str, Any]]] = {}
    if not names:
        return members

    def _mem(name: str) -> tuple[str, list[dict[str, Any]]]:
        try:
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
                    "名称": str(m.get("名称") or ""),
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
    """生成前端板块轮动完整数据（近 N 日）。"""
    session = _today()
    payload: dict[str, Any] = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(METRICS),
        "kinds": {},
    }

    print("  拉取申万二级行业近几日…")
    sw_hist = fetch_sw_industry_history(days=days)
    print("  拉取同花顺概念近几日…")
    ths_concept_hist = fetch_ths_concept_history(days=days)

    for kind in ("行业", "概念"):
        print(f"  刷新今日 {kind}…")
        # 先拿今日榜，涨停只统计今日前/后榜出现的板块，加快速度
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
        today_snap = {"date": session, "kind": kind, "boards": today_rows, "source": "东财"}

        if kind == "行业":
            snaps = _merge_snaps(sw_hist, today_snap, days=days)
        else:
            snaps = _merge_snaps(ths_concept_hist, today_snap, days=days)

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
            # 今日榜 + 近几日前榜板块，便于点选下钻
            names = set(ranked_names)
            for s in snaps_desc[: min(3, len(snaps_desc))]:
                t, b = _rank_day(s.get("boards") or [], "涨幅", top_n=top_n)
                for cell in t + b:
                    if cell.get("name"):
                        names.add(str(cell["name"]))
            print(f"  拉取 {kind} 成分股 {len(names)} 个…")
            members = _fetch_members_map(kind, names)

        note = "行业历史=申万二级；今日=东财实时。资金优先净流入/成交额。"
        if kind == "概念":
            note = "概念历史=同花顺；今日=东财实时。资金优先净流入/成交额。"

        payload["kinds"][kind] = {
            "dates": dates,
            "by_metric": by_metric,
            "members": members,
            "fund_note": note,
            "board_count": int(len(boards_df)),
        }

    return payload
