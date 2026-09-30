"""通达信板块：本地 Mac/Windows 安装目录 + pytdx 行情。

- 行业 I：`breedconst.xml` → ConstID=TdxHY（与 App「行业 I」一致）
- 纯概念：`tdxzs.cfg` 类别 4（不含类别 5 风格）
- 成分股：行业=tdxhy.cfg；概念=block_gn.dat（新格式）
- 行情：pytdx `get_index_bars` / `get_security_quotes`
- 跨平台：优先 `sectors/cache` 共享缓存；Mac/Windows 安装目录仅作同步源
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"

MAC_TDX_HOME = (
    Path.home()
    / "Library/Containers/com.tdx.mac2022/Data/Library/Caches/home"
)
BREEDCONST_PATH = MAC_TDX_HOME / "config/breedconst.xml"

TDX_ZS_CACHE = CACHE_DIR / "tdxzs.cfg"
TDX_ZS_META = CACHE_DIR / "tdxzs_meta.json"
TDX_ZIP_CACHE = CACHE_DIR / "zhb.zip"
TDX_BLOCK_GN_CACHE = CACHE_DIR / "block_gn.dat"
TDX_BLOCK_GN_META = CACHE_DIR / "block_gn_meta.json"
TDX_HY_CACHE = CACHE_DIR / "tdxhy.cfg"
TDX_HY_META = CACHE_DIR / "tdxhy_meta.json"
TDX_MEMBERS_INDEX = CACHE_DIR / "tdx_members_index.json"
TDX_MEMBERS_META = CACHE_DIR / "tdx_members_meta.json"

TDX_SERVERS: tuple[tuple[str, int], ...] = (
    ("218.75.126.9", 7709),
    ("124.74.236.94", 7709),
    ("119.147.212.81", 7709),
    ("114.80.63.12", 7709),
)

# 连不上时短路一段时间，避免盯盘每轮卡在 pytdx 超时上
_TDX_FAIL_UNTIL = 0.0
_TDX_RETRY_SEC = 600.0  # 全挂后 10 分钟内不再重试（实时列走东财对齐通达信名单）
_TDX_LAST_OK_TS = 0.0
_TDX_LAST_ERR = ""


def tdx_hq_available() -> bool:
    """通达信行情是否可试连。失败冷却期内直接 False，禁止每轮扫服务器。"""
    return time.time() >= _TDX_FAIL_UNTIL


def tdx_hq_state() -> dict[str, Any]:
    now = time.time()
    return {
        "available": now >= _TDX_FAIL_UNTIL,
        "fail_until": _TDX_FAIL_UNTIL,
        "retry_in_sec": max(0.0, round(_TDX_FAIL_UNTIL - now, 1)),
        "last_ok_ts": _TDX_LAST_OK_TS,
        "last_error": _TDX_LAST_ERR or None,
    }


def _mark_tdx_down(err: str | None = None) -> None:
    global _TDX_FAIL_UNTIL, _TDX_LAST_ERR
    _TDX_FAIL_UNTIL = time.time() + _TDX_RETRY_SEC
    if err:
        _TDX_LAST_ERR = str(err)[:200]


def _mark_tdx_up() -> None:
    global _TDX_FAIL_UNTIL, _TDX_LAST_OK_TS, _TDX_LAST_ERR
    _TDX_FAIL_UNTIL = 0.0
    _TDX_LAST_OK_TS = time.time()
    _TDX_LAST_ERR = ""


def _windows_tdx_homes() -> list[Path]:
    homes: list[Path] = []
    for env in ("TDX_HOME", "TONGDAXIN_HOME", "通达信"):
        raw = os.environ.get(env) or ""
        if raw.strip():
            homes.append(Path(raw.strip()))
    drive_letters = "CDEF"
    names = ("new_tdx", "tdx", "通达信", "TdxW", "new_tdxw")
    for drive in drive_letters:
        for name in names:
            homes.append(Path(f"{drive}:/{name}"))
            homes.append(Path(f"{drive}:/Program Files/{name}"))
            homes.append(Path(f"{drive}:/Program Files (x86)/{name}"))
    # 去重保序
    seen: set[str] = set()
    out: list[Path] = []
    for p in homes:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def discover_tdx_homes() -> list[Path]:
    """本机可能的通达信根目录（Mac Container / Windows 安装目录）。"""
    found: list[Path] = []
    if MAC_TDX_HOME.is_dir():
        found.append(MAC_TDX_HOME)
    if sys.platform.startswith("win"):
        for p in _windows_tdx_homes():
            if p.is_dir() and (
                (p / "T0002").is_dir()
                or (p / "vipdoc").is_dir()
                or (p / "tdxw.exe").is_file()
                or (p / "TdxW.exe").is_file()
            ):
                found.append(p)
    return found


def _sync_local_file(src: Path, dest: Path, meta_path: Path, *, source: str) -> bool:
    if not src.is_file() or src.stat().st_size < 100:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size == src.stat().st_size:
        # 已有同尺寸缓存则不覆盖（避免 Win/Mac 来回抖动）
        return True
    dest.write_bytes(src.read_bytes())
    meta_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "source": source,
                "src": str(src),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return True


def sync_local_tdx_into_cache() -> dict[str, str]:
    """把本机通达信配置同步进 sectors/cache，保证 Mac/Win 共用同一份概念表。"""
    synced: dict[str, str] = {}
    for home in discover_tdx_homes():
        # Mac: config/；Windows: T0002/hq_cache 或根目录
        candidates = {
            "tdxzs.cfg": [
                home / "config" / "tdxzs.cfg",
                home / "T0002" / "hq_cache" / "tdxzs.cfg",
                home / "tdxzs.cfg",
            ],
            "block_gn.dat": [
                home / "config" / "block_gn.dat",
                home / "T0002" / "hq_cache" / "block_gn.dat",
                home / "block_gn.dat",
            ],
            "tdxhy.cfg": [
                home / "config" / "tdxhy.cfg",
                home / "T0002" / "hq_cache" / "tdxhy.cfg",
                home / "tdxhy.cfg",
            ],
            "breedconst.xml": [
                home / "config" / "breedconst.xml",
            ],
        }
        dest_map = {
            "tdxzs.cfg": (TDX_ZS_CACHE, TDX_ZS_META),
            "block_gn.dat": (TDX_BLOCK_GN_CACHE, TDX_BLOCK_GN_META),
            "tdxhy.cfg": (TDX_HY_CACHE, TDX_HY_META),
            "breedconst.xml": (CACHE_DIR / "breedconst.xml", CACHE_DIR / "breedconst_meta.json"),
        }
        for key, srcs in candidates.items():
            dest, meta = dest_map[key]
            for src in srcs:
                if _sync_local_file(src, dest, meta, source=f"local:{home}"):
                    synced[key] = str(src)
                    break
    return synced


def mac_tdx_installed() -> bool:
    return MAC_TDX_HOME.is_dir() and (
        BREEDCONST_PATH.is_file() or (MAC_TDX_HOME / "config").is_dir()
    )


def local_tdx_installed() -> bool:
    return bool(discover_tdx_homes())


def _breedconst_path() -> Path:
    cached = CACHE_DIR / "breedconst.xml"
    if cached.is_file():
        return cached
    return BREEDCONST_PATH


# tdxzs.cfg: 2=行业 3=地域 4=概念 5=风格；第5列 0=一级
CAT_INDUSTRY = "2"
CAT_CONCEPT = "4"
CAT_STYLE = "5"


def _clean(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _connect_api():
    if time.time() < _TDX_FAIL_UNTIL:
        raise ConnectionError(_TDX_LAST_ERR or "无法连接通达信行情服务器")
    try:
        from pytdx.hq import TdxHq_API
    except ImportError as e:
        _mark_tdx_down("未安装 pytdx，请 pip install pytdx")
        raise ImportError("未安装 pytdx，请 pip install pytdx") from e

    api = TdxHq_API()
    last_err = "无法连接通达信行情服务器"
    for ip, port in TDX_SERVERS:
        try:
            if api.connect(ip, port, time_out=1.2):
                _mark_tdx_up()
                return api
        except Exception as e:  # noqa: BLE001
            last_err = f"{ip}:{port} {e}"
            continue
    _mark_tdx_down(last_err)
    raise ConnectionError(last_err)


def _parse_breedconst(path: Path) -> dict[str, list[dict[str, str]]]:
    tree = ET.parse(path)
    out: dict[str, list[dict[str, str]]] = {}
    for nodes in tree.getroot().findall("ConstNodes"):
        cid = str(nodes.get("ConstID") or "").strip()
        if not cid:
            continue
        rows = []
        for node in nodes.findall("Node"):
            name = str(node.get("Name") or "").strip()
            code = str(node.get("BKCode") or "").strip()
            nid = str(node.get("ID") or "").strip()
            if name and code:
                rows.append({"name": name, "code": code, "id": nid})
        if rows:
            out[cid] = rows
    return out


def load_industry_l1() -> list[dict[str, str]]:
    """通达信行业 I（TdxHY）。"""
    bc = _breedconst_path()
    if not bc.is_file():
        return _load_industry_l1_from_tdxzs()
    data = _parse_breedconst(bc)
    return data.get("TdxHY") or _load_industry_l1_from_tdxzs()


def _load_industry_l1_from_tdxzs() -> list[dict[str, str]]:
    df = _load_tdxzs_df()
    if df.empty:
        return []
    sub = df[(df["category"] == CAT_INDUSTRY) & (df["level"] == "0")]
    return [
        {"name": str(r["name"]), "code": str(r["code"]), "id": str(r.get("ref") or "")}
        for _, r in sub.iterrows()
    ]


def ensure_tdxzs_cfg(*, force: bool = False, max_age_days: int = 7) -> Path:
    """确保本地有 tdxzs.cfg（优先共享 cache ← 本机安装，否则 pytdx 拉 zhb.zip）。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sync_local_tdx_into_cache()
    if TDX_ZS_CACHE.is_file() and not force:
        try:
            meta = json.loads(TDX_ZS_META.read_text(encoding="utf-8"))
            ts = str(meta.get("updated_at") or "")
            if ts:
                age = datetime.now() - datetime.fromisoformat(ts)
                if age.days < max_age_days:
                    return TDX_ZS_CACHE
        except Exception:
            if TDX_ZS_CACHE.stat().st_size > 1000:
                return TDX_ZS_CACHE

    api = _connect_api()
    try:
        meta = api.get_block_info_meta("zhb.zip")
        size = int((meta or {}).get("size") or 0)
        if size <= 0:
            raise RuntimeError("通达信 zhb.zip 大小为 0")
        raw = api.get_report_file_by_size("zhb.zip", size)
    finally:
        api.disconnect()

    if not raw:
        raise RuntimeError("下载 zhb.zip 失败")
    TDX_ZIP_CACHE.write_bytes(raw)
    with zipfile.ZipFile(TDX_ZIP_CACHE) as zf:
        names = [n for n in zf.namelist() if n.endswith("tdxzs.cfg")]
        if not names:
            raise RuntimeError("zhb.zip 中无 tdxzs.cfg")
        TDX_ZS_CACHE.write_bytes(zf.read(names[0]))
    TDX_ZS_META.write_text(
        json.dumps(
            {"updated_at": datetime.now().isoformat(timespec="seconds"), "source": "zhb.zip"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return TDX_ZS_CACHE


def _load_tdxzs_df() -> pd.DataFrame:
    try:
        path = ensure_tdxzs_cfg()
    except Exception:
        return pd.DataFrame()
    text = path.read_bytes().decode("gbk", errors="replace")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "name": parts[0].strip(),
                "code": parts[1].strip(),
                "category": parts[2].strip(),
                "level": parts[4].strip(),
                "ref": parts[5].strip() if len(parts) > 5 else "",
            }
        )
    return pd.DataFrame(rows)


def load_concepts() -> list[dict[str, str]]:
    """通达信纯概念（tdxzs 类别 4 一级，排除风格 5）。"""
    df = _load_tdxzs_df()
    if df.empty:
        return []
    sub = df[(df["category"] == CAT_CONCEPT) & (df["level"] == "0")]
    return [
        {"name": str(r["name"]), "code": str(r["code"]), "id": str(r.get("ref") or "")}
        for _, r in sub.iterrows()
    ]


def _parse_index_bar(bar: dict[str, Any]) -> dict[str, Any] | None:
    dt = str(bar.get("datetime") or "")
    if len(dt) >= 10:
        dt = dt[:10]
    close = _clean(bar.get("close"))
    if not dt or close is None:
        return None
    return {
        "date": dt,
        "open": _clean(bar.get("open")),
        "high": _clean(bar.get("high")),
        "low": _clean(bar.get("low")),
        "close": close,
        "amount": _clean(bar.get("amount")),
        "vol": _clean(bar.get("vol")),
    }


def fetch_tdx_index_kline(code: str, *, count: int = 130) -> list[dict[str, Any]]:
    """通达信板块指数日 K（OHLC）。"""
    api = _connect_api()
    try:
        bars = api.get_index_bars(9, 1, str(code), 0, max(count, 2)) or []
    finally:
        api.disconnect()
    out: list[dict[str, Any]] = []
    for bar in bars:
        row = _parse_index_bar(bar)
        if row:
            out.append(row)
    return out


def fetch_tdx_stock_klines(
    codes: list[str],
    *,
    count: int = 160,
) -> dict[str, list[dict[str, Any]]]:
    """批量拉个股日 K（通达信优先，单连接）。返回 code → bars。"""
    uniq = []
    seen: set[str] = set()
    for c in codes:
        code = str(c or "").zfill(6)
        if code.isdigit() and code not in seen:
            seen.add(code)
            uniq.append(code)
    if not uniq:
        return {}
    api = _connect_api()
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        for code in uniq:
            market = 1 if code.startswith(("5", "6", "9")) else 0
            try:
                bars = api.get_security_bars(9, market, code, 0, max(count, 2)) or []
            except Exception:
                bars = []
            rows: list[dict[str, Any]] = []
            for bar in bars:
                row = _parse_index_bar(bar)
                if row:
                    rows.append(row)
            if rows:
                out[code] = rows
    finally:
        api.disconnect()
    return out


def resolve_concept_by_name(name: str) -> dict[str, str] | None:
    """概念名 → 通达信指数项；支持去「概念」后缀与唯一子串模糊（对齐 Mac/Win 命名差）。"""
    target = str(name or "").strip()
    if not target:
        return None
    concepts = load_concepts()
    by_name = {str(item.get("name") or "").strip(): item for item in concepts}
    if target in by_name:
        return by_name[target]
    stripped = target.replace("概念", "").strip()
    if stripped and stripped in by_name:
        return by_name[stripped]
    if stripped and (stripped + "概念") in by_name:
        return by_name[stripped + "概念"]
    fuzzy: list[dict[str, str]] = []
    for item in concepts:
        key = str(item.get("name") or "").strip()
        k2 = key.replace("概念", "").strip()
        if not stripped:
            continue
        if stripped == k2 or stripped in key or k2 in target:
            fuzzy.append(item)
    if len(fuzzy) == 1:
        return fuzzy[0]
    return None


def _fetch_index_series(code: str, tail: int) -> list[dict[str, Any]]:
    bars = fetch_tdx_index_kline(code, count=tail + 1)
    out: list[dict[str, Any]] = []
    for i in range(1, len(bars)):
        cur = bars[i]
        prev = bars[i - 1]
        pc, cc = _clean(prev.get("close")), _clean(cur.get("close"))
        if not pc or not cc:
            continue
        out.append(
            {
                "date": cur["date"],
                "涨跌幅": (cc / pc - 1.0) * 100.0,
                "资金": _clean(cur.get("amount")),
                "close": cc,
            }
        )
    return out[-tail:]


def _boards_to_df(
    boards: list[dict[str, str]],
    series_map: dict[str, list[dict[str, Any]]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for b in boards:
        name, code = b["name"], b["code"]
        series = series_map.get(code) or []
        if not series:
            continue
        last = series[-1]
        rows.append(
            {
                "板块": name,
                "label": code,
                "涨跌幅": _clean(last.get("涨跌幅")),
                "总成交额": _clean(last.get("资金")),
                "资金": _clean(last.get("资金")),
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


def _parallel_series(
    boards: list[dict[str, str]], *, tail: int, label: str
) -> dict[str, list[dict[str, Any]]]:
    if not boards:
        return {}
    print(f"  通达信拉取 {label}: {len(boards)} 个…")
    out: dict[str, list[dict[str, Any]]] = {}

    def _one(b: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
        try:
            return b["code"], _fetch_index_series(b["code"], tail)
        except Exception:
            return b["code"], []

    done = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(_one, b) for b in boards]
        for fut in as_completed(futs):
            code, series = fut.result()
            if series:
                out[code] = series
            done += 1
            if done % 40 == 0 or done == len(boards):
                print(f"    通达信进度 {done}/{len(boards)}")
    return out


def fetch_tdx_industry_l1_spot() -> pd.DataFrame:
    boards = load_industry_l1()
    if not boards:
        return pd.DataFrame()
    series_map = _parallel_series(boards, tail=1, label="行业 I 今日")
    return _boards_to_df(boards, series_map)


def fetch_tdx_concept_spot() -> pd.DataFrame:
    boards = load_concepts()
    if not boards:
        return pd.DataFrame()
    series_map = _parallel_series(boards, tail=1, label="概念今日")
    return _boards_to_df(boards, series_map)


def fetch_tdx_industry_l1_history(days: int = 5) -> list[dict[str, Any]]:
    boards = load_industry_l1()
    if not boards:
        return []
    series_map = _parallel_series(boards, tail=days + 1, label=f"行业 I 近{days}日")
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    code_name = {b["code"]: b["name"] for b in boards}
    for code, series in series_map.items():
        name = code_name.get(code, code)
        for pt in series:
            by_date.setdefault(str(pt["date"]), {})[name] = {
                "涨跌幅": pt.get("涨跌幅"),
                "资金": pt.get("资金"),
                "code": code,
            }
    dates = sorted(by_date.keys())[-days:]
    snaps: list[dict[str, Any]] = []
    for d in dates:
        boards_rows = []
        for name, vals in by_date[d].items():
            boards_rows.append(
                {
                    "板块": name,
                    "label": vals.get("code") or "",
                    "涨跌幅": _clean(vals.get("涨跌幅")),
                    "涨停数": 0,
                    "资金": _clean(vals.get("资金")),
                    "资金口径": "成交额",
                    "领涨名称": "",
                    "领涨涨幅": None,
                }
            )
        snaps.append({"date": d, "kind": "行业", "boards": boards_rows, "source": "通达信行业I"})
    return snaps


def fetch_tdx_concept_history(days: int = 5) -> list[dict[str, Any]]:
    boards = load_concepts()
    if not boards:
        return []
    series_map = _parallel_series(boards, tail=days + 1, label=f"概念近{days}日")
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    code_name = {b["code"]: b["name"] for b in boards}
    for code, series in series_map.items():
        name = code_name.get(code, code)
        for pt in series:
            by_date.setdefault(str(pt["date"]), {})[name] = {
                "涨跌幅": pt.get("涨跌幅"),
                "资金": pt.get("资金"),
                "code": code,
            }
    dates = sorted(by_date.keys())[-days:]
    snaps: list[dict[str, Any]] = []
    for d in dates:
        boards_rows = []
        for name, vals in by_date[d].items():
            boards_rows.append(
                {
                    "板块": name,
                    "label": vals.get("code") or "",
                    "涨跌幅": _clean(vals.get("涨跌幅")),
                    "涨停数": 0,
                    "资金": _clean(vals.get("资金")),
                    "资金口径": "成交额",
                    "领涨名称": "",
                    "领涨涨幅": None,
                }
            )
        snaps.append({"date": d, "kind": "概念", "boards": boards_rows, "source": "通达信概念"})
    return snaps


def _download_report_file(filename: str, *, cache: Path, meta_path: Path, max_age_days: int = 7) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if cache.is_file() and not meta_path.is_file():
        meta_path.write_text(
            json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8",
        )
    def _usable_cache() -> Path | None:
        if cache.is_file() and cache.stat().st_size > 1000:
            return cache
        return None

    if cache.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ts = str(meta.get("updated_at") or "")
            if ts:
                age = datetime.now() - datetime.fromisoformat(ts)
                if age.days < max_age_days and cache.stat().st_size > 1000:
                    return cache
        except Exception:
            if cache.stat().st_size > 1000:
                return cache

    if not tdx_hq_available():
        hit = _usable_cache()
        if hit is not None:
            return hit
        raise ConnectionError(_TDX_LAST_ERR or "无法连接通达信行情服务器")

    try:
        api = _connect_api()
        try:
            info = api.get_block_info_meta(filename)
            size = int((info or {}).get("size") or 0)
            if size <= 0:
                raise RuntimeError(f"{filename} 大小为 0")
            raw = api.get_report_file_by_size(filename, size)
        finally:
            api.disconnect()
        if not raw:
            raise RuntimeError(f"下载 {filename} 失败")
        cache.write_bytes(raw)
        meta_path.write_text(
            json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "size": len(raw)}),
            encoding="utf-8",
        )
        return cache
    except Exception:
        hit = _usable_cache()
        if hit is not None:
            return hit
        raise


def ensure_block_gn_dat(*, force: bool = False, max_age_days: int = 7) -> Path:
    if force and TDX_BLOCK_GN_CACHE.is_file():
        TDX_BLOCK_GN_CACHE.unlink(missing_ok=True)
    return _download_report_file(
        "block_gn.dat",
        cache=TDX_BLOCK_GN_CACHE,
        meta_path=TDX_BLOCK_GN_META,
        max_age_days=max_age_days,
    )


def ensure_tdxhy_cfg(*, force: bool = False, max_age_days: int = 7) -> Path:
    if force and TDX_HY_CACHE.is_file():
        TDX_HY_CACHE.unlink(missing_ok=True)
    return _download_report_file(
        "tdxhy.cfg",
        cache=TDX_HY_CACHE,
        meta_path=TDX_HY_META,
        max_age_days=max_age_days,
    )


def _load_tdxbk_short2full() -> dict[str, str]:
    try:
        ensure_tdxzs_cfg()
        with zipfile.ZipFile(TDX_ZIP_CACHE) as zf:
            text = zf.read("tdxbk.cfg").decode("gbk", errors="replace")
    except Exception:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        ps = [p.strip() for p in line.split("|")]
        if len(ps) >= 3 and ps[1] and ps[2]:
            out[ps[1]] = ps[2]
    return out


def _load_tdxhy_l1_id_map() -> dict[str, tuple[str, str]]:
    """TdxHY 节点 ID → (名称, BKCode)。"""
    bc = _breedconst_path()
    if not bc.is_file():
        return {}
    data = _parse_breedconst(bc)
    out: dict[str, tuple[str, str]] = {}
    for row in data.get("TdxHY") or []:
        nid = str(row.get("id") or "").strip()
        if nid:
            out[nid] = (str(row["name"]), str(row["code"]))
    return out


def _hy_id_to_l1_bk(hy_id: str, l1_map: dict[str, tuple[str, str]]) -> str | None:
    hy_id = str(hy_id or "").strip()
    if not hy_id:
        return None
    if hy_id in l1_map:
        return l1_map[hy_id][1]
    for i in range(len(hy_id) - 1, 4, -1):
        prefix = hy_id[:i]
        if prefix in l1_map:
            return l1_map[prefix][1]
    return None


def _read_block_gn_stock_codes(data: bytes, pos: int, count: int) -> tuple[list[str], int]:
    codes: list[str] = []
    while len(codes) < count and pos < len(data):
        if data[pos] == 0:
            pos += 1
            continue
        if not 48 <= data[pos] <= 57:
            break
        seg = data[pos : pos + 6]
        if len(seg) < 6 or not all(48 <= b <= 57 for b in seg):
            break
        codes.append(seg.decode())
        pos += 6
        while pos < len(data) and data[pos] == 0:
            pos += 1
    return codes, pos


def _parse_block_gn_at(data: bytes, idx: int) -> tuple[str, list[str]] | None:
    if idx + 13 > len(data):
        return None
    name = data[idx : idx + 9].decode("gbk", errors="ignore").rstrip("\x00").strip()
    stock_count, _block_type = struct.unpack("<HH", data[idx + 9 : idx + 13])
    if stock_count <= 0 or stock_count > 3000:
        return None
    if not name or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", name):
        return None
    codes, _ = _read_block_gn_stock_codes(data, idx + 13, stock_count)
    if len(codes) < max(1, stock_count // 4):
        return None
    return name, codes


def _build_concept_members_index() -> dict[str, list[str]]:
    path = ensure_block_gn_dat()
    raw = path.read_bytes()
    short2full = _load_tdxbk_short2full()
    out: dict[str, list[str]] = {}

    for concept in load_concepts():
        full = str(concept["name"])
        aliases = {full}
        for short, fname in short2full.items():
            if fname == full:
                aliases.add(short)
        found: list[str] | None = None
        for alias in aliases:
            key = alias.encode("gbk")
            idx = 0
            while True:
                idx = raw.find(key, idx)
                if idx < 0:
                    break
                if raw[idx : idx + 9].decode("gbk", errors="ignore").rstrip("\x00").strip() != alias:
                    idx += 1
                    continue
                parsed = _parse_block_gn_at(raw, idx)
                if parsed and len(parsed[1]) >= 3:
                    found = parsed[1]
                    break
                idx += 1
            if found:
                break
        if found:
            out[full] = found
    return out


def _build_industry_members_index() -> dict[str, list[str]]:
    path = ensure_tdxhy_cfg()
    raw = path.read_bytes()
    start = raw.find(b"0|")
    if start < 0:
        return {}
    text = raw[start:].decode("gbk", errors="replace")
    l1_map = _load_tdxhy_l1_id_map()
    code_name = {code: name for name, code in ((v[0], v[1]) for v in l1_map.values())}
    # 反向：880xxx -> 行业名
    bk_to_name = {code: name for name, code in ((b["name"], b["code"]) for b in load_industry_l1())}
    by_name: dict[str, list[str]] = {name: [] for name in bk_to_name.values()}

    for line in text.splitlines():
        ps = line.strip().split("|")
        if len(ps) < 3:
            continue
        stk = str(ps[1]).zfill(6)
        bk = _hy_id_to_l1_bk(ps[2], l1_map)
        if not bk:
            continue
        name = bk_to_name.get(bk) or code_name.get(bk)
        if name:
            by_name.setdefault(name, []).append(stk)
    return {k: v for k, v in by_name.items() if v}


def _members_index_stale(max_age_days: int = 7) -> bool:
    if not TDX_MEMBERS_INDEX.is_file():
        return True
    try:
        meta = json.loads(TDX_MEMBERS_META.read_text(encoding="utf-8"))
        ts = str(meta.get("updated_at") or "")
        if not ts:
            return True
        return (datetime.now() - datetime.fromisoformat(ts)).days >= max_age_days
    except Exception:
        return True


_MEMBERS_INDEX_LOCK = threading.Lock()


def _read_members_index_file() -> dict[str, dict[str, list[str]]] | None:
    if not TDX_MEMBERS_INDEX.is_file():
        return None
    try:
        data = json.loads(TDX_MEMBERS_INDEX.read_text(encoding="utf-8"))
        # Windows 无 tdxhy 时「行业」可为空；有概念成分即可复用缓存
        if data.get("概念"):
            return {
                "行业": data.get("行业") or {},
                "概念": data["概念"],
            }
    except Exception:
        return None
    return None


def load_members_index(*, force: bool = False) -> dict[str, dict[str, list[str]]]:
    """板块名称 → 成分股代码（6位）。kind: 行业 / 概念。"""
    with _MEMBERS_INDEX_LOCK:
        cached = _read_members_index_file()
        # 有概念成分就复用；过期刷新另走 force=True，避免盘中因 HQ 超时把选股打成 0 票
        if cached and not force:
            return cached

        try:
            print("  构建通达信成分股索引（行业 tdxhy + 概念 block_gn）…")
            try:
                industry = _build_industry_members_index()
            except Exception:
                industry = (cached or {}).get("行业") or {}
            try:
                concept = _build_concept_members_index()
            except Exception:
                concept = {}
            if not concept and cached:
                concept = cached.get("概念") or {}
            payload = {"行业": industry, "概念": concept}
            if concept:
                TDX_MEMBERS_INDEX.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                TDX_MEMBERS_META.write_text(
                    json.dumps(
                        {
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "industry_boards": len(industry),
                            "concept_boards": len(concept),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            print(f"    行业 {len(industry)} · 概念 {len(concept)}")
            if payload.get("概念"):
                return payload
        except Exception:
            if cached:
                return cached
            raise
        if cached:
            return cached
        return payload


def _stock_market(code: str) -> int:
    c = str(code).zfill(6)
    if c.startswith(("92", "43", "83", "87")):
        return 2
    if c.startswith(("5", "6")):
        return 1
    return 0


def _fetch_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    pairs = [(_stock_market(c), str(c).zfill(6)) for c in codes]
    out: dict[str, dict[str, Any]] = {}

    def _consume(quotes: list[Any] | None) -> None:
        if not quotes:
            return
        for q in quotes:
            code = str(q.get("code") or "").zfill(6)
            price = _clean(q.get("price"))
            prev = _clean(q.get("last_close"))
            chg = ((price / prev - 1.0) * 100.0) if price and prev else None
            out[code] = {"现价": price, "涨跌幅": chg, "成交额": _clean(q.get("amount"))}

    api = _connect_api()
    try:
        step = 40
        for i in range(0, len(pairs), step):
            batch = pairs[i : i + step]
            quotes = api.get_security_quotes(batch)
            if quotes:
                _consume(quotes)
                continue
            for mkt, code in batch:
                one = api.get_security_quotes([(mkt, code)])
                _consume(one)
    finally:
        api.disconnect()
    return out


def lookup_member_codes(kind: str, name: str) -> list[str]:
    """板块名 → 成分代码。概念支持去掉「概念」后缀、唯一子串模糊匹配。"""
    kind = str(kind).strip()
    name = str(name or "").strip()
    if not name or kind not in ("行业", "概念"):
        return []
    index = load_members_index().get(kind) or {}
    hit = index.get(name)
    if hit:
        return [str(c).zfill(6) for c in hit if str(c).strip()]
    if kind != "概念":
        return []
    stripped = name.replace("概念", "").strip()
    if stripped and stripped != name:
        alt = index.get(stripped) or index.get(stripped + "概念")
        if alt:
            return [str(c).zfill(6) for c in alt if str(c).strip()]
    fuzzy: list[str] = []
    for key, codes in index.items():
        k2 = str(key).replace("概念", "").strip()
        if not stripped:
            continue
        if stripped == k2 or stripped in str(key) or k2 in name:
            fuzzy.append(str(key))
    if len(fuzzy) == 1:
        return [str(c).zfill(6) for c in index[fuzzy[0]] if str(c).strip()]
    return []


def fetch_tdx_board_members(
    kind: str,
    name: str,
    *,
    with_quotes: bool = True,
    limit: int = 200,
) -> pd.DataFrame:
    """按通达信板块名称拉成分股（含可选实时行情）。"""
    kind = str(kind).strip()
    name = str(name).strip()
    if kind not in ("行业", "概念"):
        raise ValueError("kind 仅支持 行业 / 概念")

    codes = lookup_member_codes(kind, name)
    if not codes:
        return pd.DataFrame()

    codes = [str(c).zfill(6) for c in codes[:limit]]
    quotes = _fetch_quotes(codes) if with_quotes else {}
    from .stock_names import stock_name_of

    rows: list[dict[str, Any]] = []
    for code in codes:
        q = quotes.get(code) or {}
        rows.append(
            {
                "纯代码": code,
                "代码": code,
                "名称": stock_name_of(code),
                "现价": q.get("现价"),
                "涨跌幅": q.get("涨跌幅"),
                "成交额": q.get("成交额"),
                "换手率": None,
            }
        )
    out = pd.DataFrame(rows)
    if "涨跌幅" in out.columns:
        out = out.sort_values("涨跌幅", ascending=False, na_position="last")
    return out.reset_index(drop=True)


def tdx_availability() -> dict[str, Any]:
    info: dict[str, Any] = {
        "mac_installed": mac_tdx_installed(),
        "local_installed": local_tdx_installed(),
        "tdx_homes": [str(p) for p in discover_tdx_homes()],
        "breedconst": str(_breedconst_path()) if _breedconst_path().is_file() else None,
    }
    try:
        synced = sync_local_tdx_into_cache()
        if synced:
            info["synced_from_local"] = synced
    except Exception as e:
        info["sync_error"] = str(e)
    try:
        ind = load_industry_l1()
        info["industry_l1_count"] = len(ind)
        info["industry_samples"] = [x["name"] for x in ind[:8]]
    except Exception as e:
        info["industry_error"] = str(e)
    try:
        ensure_tdxzs_cfg()
        concepts = load_concepts()
        info["concept_count"] = len(concepts)
        info["concept_samples"] = [x["name"] for x in concepts[:8]]
        info["tdxzs_cache"] = str(TDX_ZS_CACHE)
    except Exception as e:
        info["concept_error"] = str(e)
    try:
        # 冷却期内不要真连，避免 /api/sectors/status 卡死 HTTP 线程
        from .tdx import tdx_hq_available, tdx_hq_state

        st = tdx_hq_state()
        info["pytdx"] = st
        if not tdx_hq_available():
            info["pytdx_ok"] = False
            info["pytdx_error"] = st.get("last_error") or "行情冷却中（跳过重连）"
        else:
            api = _connect_api()
            api.disconnect()
            info["pytdx_ok"] = True
    except Exception as e:
        info["pytdx_ok"] = False
        info["pytdx_error"] = str(e)
    try:
        # 有概念表即可建索引；不强制要求 pytdx 在线（Windows 常见）
        if info.get("concept_count"):
            idx = load_members_index()
            info["members_industry"] = len(idx.get("行业") or {})
            info["members_concept"] = len(idx.get("概念") or {})
    except Exception as e:
        info["members_error"] = str(e)
    # 概念表就绪即视为可用；行情另看 pytdx_ok（热力实时列）
    info["ok"] = bool(info.get("concept_count"))
    info["prefer"] = "通达信"
    return info
