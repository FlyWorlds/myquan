"""同花顺板块：行业 / 概念（Mac、Windows 通用，走 q.10jqka.com.cn 接口）。

不依赖本地同花顺安装路径；仅需网络 + akshare（含 py_mini_racer / ths.js 反爬）。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import py_mini_racer
import requests
from akshare.datasets import get_ths_js
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"

THS_CONCEPT_SKIP = frozenset({"沪股通", "深股通", "融资融券", "同花顺果指数"})

_INDUSTRY_CODE_CACHE = CACHE_DIR / "ths_industry_codes.json"
_CONCEPT_CODE_CACHE = CACHE_DIR / "ths_concept_codes.json"
_CONCEPT_CLID_CACHE = CACHE_DIR / "ths_concept_clids.json"

_THSHY = "thshy"
_GN = "gn"


def _clean(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _parse_amount(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("--", "-"):
        return None
    mul = 1.0
    if s.endswith("亿"):
        mul = 1e8
        s = s[:-1]
    elif s.endswith("万"):
        mul = 1e4
        s = s[:-1]
    try:
        return float(s) * mul
    except ValueError:
        return _clean(v)


def _ths_js() -> py_mini_racer.MiniRacer:
    js = py_mini_racer.MiniRacer()
    with open(get_ths_js("ths.js"), encoding="utf-8") as f:
        js.eval(f.read())
    return js


def _ths_headers(*, referer: str | None = None) -> dict[str, str]:
    js = _ths_js()
    v = js.call("v")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Cookie": f"v={v}",
        "hexin-v": v,
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _load_json_cache(path: Path, *, max_age_days: int = 7) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        ts = str(obj.get("updated_at") or "")
        items = obj.get("items") or {}
        if not items:
            return None
        if ts:
            age = datetime.now() - datetime.fromisoformat(ts)
            if age.days >= max_age_days:
                return None
        return {str(k): str(v) for k, v in items.items()}
    except Exception:
        return None


def _save_json_cache(path: Path, items: dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"updated_at": datetime.now().isoformat(timespec="seconds"), "items": items},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_industry_code_map(*, force: bool = False) -> dict[str, str]:
    """同花顺行业名 → 板块代码（881xxx）。"""
    if not force:
        cached = _load_json_cache(_INDUSTRY_CODE_CACHE)
        if cached:
            return cached
    df = ak.stock_board_industry_name_ths()
    mapping = {
        str(r["name"]).strip(): str(r["code"]).strip()
        for _, r in df.iterrows()
        if str(r.get("name") or "").strip()
    }
    _save_json_cache(_INDUSTRY_CODE_CACHE, mapping)
    return mapping


def load_concept_code_map(*, force: bool = False) -> dict[str, str]:
    """同花顺概念名 → 详情页 code（用于成分股分页）。"""
    if not force:
        cached = _load_json_cache(_CONCEPT_CODE_CACHE)
        if cached:
            return cached
    df = ak.stock_board_concept_name_ths()
    mapping = {
        str(r["name"]).strip(): str(r["code"]).strip()
        for _, r in df.iterrows()
        if str(r.get("name") or "").strip() and str(r["name"]).strip() not in THS_CONCEPT_SKIP
    }
    _save_json_cache(_CONCEPT_CODE_CACHE, mapping)
    return mapping


def load_concept_clid_map(*, force: bool = False) -> dict[str, str]:
    """同花顺概念名 → 指数 clid（用于 last.js 行情）。"""
    if not force:
        cached = _load_json_cache(_CONCEPT_CLID_CACHE)
        if cached:
            return cached

    code_map = load_concept_code_map(force=force)
    sess = requests.Session()
    sess.trust_env = False
    mapping: dict[str, str] = {}

    def _clid(name_code: tuple[str, str]) -> tuple[str, str | None]:
        name, detail = name_code
        base = f"http://q.10jqka.com.cn/gn/detail/code/{detail}/"
        try:
            r = sess.get(base, headers=_ths_headers(referer=base), timeout=15)
            r.encoding = "gbk"
            m = re.search(r'id=["\']clid["\'][^>]*value=["\'](\d+)["\']', r.text)
            if not m:
                m = re.search(r'value=["\'](\d+)["\'][^>]*id=["\']clid["\']', r.text)
            return name, m.group(1) if m else None
        except Exception:
            return name, None

    items = list(code_map.items())
    print(f"  同花顺概念 clid 映射: {len(items)} 个…")
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(_clid, it) for it in items]
        done = 0
        for fut in as_completed(futs):
            name, clid = fut.result()
            if name and clid:
                mapping[name] = clid
            done += 1
            if done % 50 == 0 or done == len(items):
                print(f"    概念 clid 进度 {done}/{len(items)} · 有效 {len(mapping)}")
    _save_json_cache(_CONCEPT_CLID_CACHE, mapping)
    return mapping


def _parse_ths_last_js(text: str) -> list[tuple[str, float, float | None]]:
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


def _fetch_last_series(
    items: list[tuple[str, str]],
    *,
    tail: int,
) -> dict[str, list[tuple[str, float, float | None]]]:
    if not items:
        return {}
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update(
        {
            "Referer": "http://q.10jqka.com.cn",
            "Host": "d.10jqka.com.cn",
        }
    )

    def _one(item: tuple[str, str]) -> tuple[str, list[tuple[str, float, float | None]]]:
        name, code = item
        try:
            r = sess.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/last.js",
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
            return name, out[-tail:]
        except Exception:
            return name, []

    out: dict[str, list[tuple[str, float, float | None]]] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(_one, it) for it in items]
        for fut in as_completed(futs):
            name, series = fut.result()
            if series:
                out[name] = series
    return out


def fetch_ths_industry_spot() -> pd.DataFrame:
    """同花顺行业一览（涨跌幅 / 净流入 / 领涨）。"""
    code_map = load_industry_code_map()
    df = ak.stock_board_industry_summary_ths()
    if df is None or df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        name = str(r.get("板块") or "").strip()
        if not name:
            continue
        amt = _clean(r.get("总成交额"))
        fund = amt * 1e8 if amt is not None else None
        inflow = _clean(r.get("净流入"))
        inflow_yuan = inflow * 1e8 if inflow is not None else None
        rows.append(
            {
                "板块": name,
                "label": code_map.get(name, ""),
                "涨跌幅": _clean(r.get("涨跌幅")),
                "总成交额": fund,
                "资金": inflow_yuan if inflow_yuan is not None else fund,
                "资金口径": "主力净流入" if inflow_yuan is not None else "成交额",
                "领涨名称": str(r.get("领涨股") or ""),
                "领涨涨幅": _clean(r.get("领涨股-涨跌幅")),
                "涨停数": 0,
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)


def fetch_ths_concept_spot() -> pd.DataFrame:
    """同花顺概念实时（last.js，剔除通道类）。"""
    clid_map = load_concept_clid_map()
    clid_map = {k: v for k, v in clid_map.items() if k not in THS_CONCEPT_SKIP}
    if not clid_map:
        return pd.DataFrame()
    code_map = load_concept_code_map()
    items = list(clid_map.items())
    print(f"  拉取同花顺概念今日: {len(items)} 个…")
    series_map = _fetch_last_series(items, tail=1)
    rows: list[dict[str, Any]] = []
    for name, clid in items:
        series = series_map.get(name) or []
        if not series:
            continue
        _, chg, amt = series[-1]
        rows.append(
            {
                "板块": name,
                "label": code_map.get(name, clid),
                "涨跌幅": _clean(chg),
                "总成交额": _clean(amt),
                "资金": _clean(amt),
                "资金口径": "成交额",
                "领涨名称": "",
                "领涨涨幅": None,
                "涨停数": 0,
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)


def _history_from_series(
    series_map: dict[str, list[tuple[str, float, float | None]]],
    *,
    kind: str,
    label_map: dict[str, str],
    source: str,
    days: int,
) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for name, series in series_map.items():
        for d, chg, amt in series:
            by_date.setdefault(d, {})[name] = {
                "涨跌幅": chg,
                "资金": amt,
                "label": label_map.get(name, ""),
            }
    dates = sorted(by_date.keys())[-days:]
    snaps: list[dict[str, Any]] = []
    for d in dates:
        boards = []
        for name, vals in by_date[d].items():
            boards.append(
                {
                    "板块": name,
                    "label": vals.get("label") or "",
                    "涨跌幅": _clean(vals.get("涨跌幅")),
                    "涨停数": 0,
                    "资金": _clean(vals.get("资金")),
                    "资金口径": "成交额",
                    "领涨名称": "",
                    "领涨涨幅": None,
                }
            )
        snaps.append({"date": d, "kind": kind, "boards": boards, "source": source})
    return snaps


def fetch_ths_industry_history(days: int = 5) -> list[dict[str, Any]]:
    code_map = load_industry_code_map()
    if not code_map:
        return []
    items = list(code_map.items())
    print(f"  拉取同花顺行业近{days}日: {len(items)} 个…")
    series_map = _fetch_last_series(items, tail=days + 1)
    return _history_from_series(
        series_map,
        kind="行业",
        label_map=code_map,
        source="同花顺行业",
        days=days,
    )


def fetch_ths_concept_history(days: int = 5) -> list[dict[str, Any]]:
    clid_map = load_concept_clid_map()
    clid_map = {k: v for k, v in clid_map.items() if k not in THS_CONCEPT_SKIP}
    if not clid_map:
        print("  同花顺概念 clid 为空，跳过概念历史")
        return []
    code_map = load_concept_code_map()
    items = list(clid_map.items())
    print(f"  拉取同花顺概念近{days}日: {len(items)} 个…")
    series_map = _fetch_last_series(items, tail=days + 1)
    done = 0
    for _ in series_map:
        done += 1
    print(f"    概念行情有效 {len(series_map)}/{len(items)}")
    return _history_from_series(
        series_map,
        kind="概念",
        label_map=code_map,
        source="同花顺概念",
        days=days,
    )


def _member_path_prefix(kind: str) -> str:
    return _THSHY if kind == "行业" else _GN


def _fetch_member_pages(path_prefix: str, code: str) -> pd.DataFrame:
    base = f"http://q.10jqka.com.cn/{path_prefix}/detail/code/{code}/"
    headers = _ths_headers(referer=base)
    r = requests.get(base, headers=headers, timeout=20)
    r.encoding = "gbk"
    m = re.search(r"page_info[^>]*>([^<]+)", r.text)
    pages = 1
    if m:
        try:
            pages = max(1, int(str(m.group(1)).split("/")[-1].strip()))
        except ValueError:
            pages = 1
    frames: list[pd.DataFrame] = []
    for page in range(1, pages + 1):
        url = base if page == 1 else f"{base}page/{page}/"
        rr = requests.get(url, headers=headers, timeout=20)
        rr.encoding = "gbk"
        try:
            frames.append(pd.read_html(StringIO(rr.text))[0])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_ths_board_members(kind: str, name: str, *, limit: int = 200) -> pd.DataFrame:
    """按同花顺板块名称拉成分股（与 App 行业/概念分类一致）。"""
    kind = str(kind).strip()
    name = str(name).strip()
    if kind == "行业":
        code_map = load_industry_code_map()
    elif kind == "概念":
        code_map = load_concept_code_map()
    else:
        raise ValueError("kind 仅支持 行业 / 概念")
    code = code_map.get(name)
    if not code:
        return pd.DataFrame()

    raw = _fetch_member_pages(_member_path_prefix(kind), code)
    if raw is None or raw.empty:
        return pd.DataFrame()

    rename = {
        "代码": "纯代码",
        "名称": "名称",
        "现价": "现价",
        "涨跌幅(%)": "涨跌幅",
        "换手(%)": "换手率",
        "成交额": "成交额",
    }
    out = raw.rename(columns={k: v for k, v in rename.items() if k in raw.columns})
    if "纯代码" in out.columns:
        out["纯代码"] = out["纯代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    if "涨跌幅" in out.columns:
        out["涨跌幅"] = pd.to_numeric(out["涨跌幅"], errors="coerce")
    if "成交额" in out.columns:
        out["成交额"] = out["成交额"].map(_parse_amount)
    if "涨跌幅" in out.columns:
        out = out.sort_values("涨跌幅", ascending=False, na_position="last")
    return out.head(limit).reset_index(drop=True)


def ths_availability() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": "web"}
    try:
        ind = load_industry_code_map()
        info["industry_count"] = len(ind)
        info["industry_samples"] = list(ind.keys())[:6]
    except Exception as e:
        info["industry_error"] = str(e)
    try:
        concepts = load_concept_code_map()
        info["concept_count"] = len(concepts)
        info["concept_samples"] = list(concepts.keys())[:6]
    except Exception as e:
        info["concept_error"] = str(e)
    info["ok"] = bool(info.get("industry_count")) and bool(info.get("concept_count"))
    return info
