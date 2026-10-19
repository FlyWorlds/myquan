"""同花顺板块：行业 / 概念 / 热点轮动（Mac、Windows 通用，走同花顺行情接口 + 数据库存储）。

性能优化：
- `_MEM_SUBMAPS` 进程内常驻内存缓存，消除因历史缓存超过 14 天导致每次请求重爬 `ak.stock_board_concept_name_ths` 的卡顿
- `fetch_ths_board_kline` 仅走 `d.10jqka.com.cn` 静态高速 CDN（2s 超时），禁止在详情请求路径同步爬 `q.10jqka.com.cn` 网页或调 `ak.stock_board_concept_index_ths`
- `_fetch_last_series` 使用连接池（HTTPAdapter pool_maxsize=32）与 24 并发复用 TLS 连接
- 存储全部走 `sectors/store.py`（MySQL `app_documents`），不再读写本地 JSON 文件
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import StringIO
from typing import Any

import akshare as ak
import pandas as pd
import py_mini_racer
import requests
from akshare.datasets import get_ths_js
from requests.adapters import HTTPAdapter

from .store import get_doc, set_doc

THS_CONCEPT_SKIP = frozenset({"沪股通", "深股通", "融资融券", "同花顺果指数"})

_THSHY = "thshy"
_GN = "gn"
_THS_DOC_KEY = "sectors_ths_codes"

CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "海工装备": ("海洋经济", "船舶", "高端装备", "航运概念", "国防军工"),
    "海洋经济": ("海工装备", "船舶", "航运概念", "港口", "水产品"),
    "中船系": ("船舶", "海洋经济", "海工装备", "国防军工", "军民融合"),
    "航母概念": ("船舶", "国防军工", "军民融合", "海洋经济"),
    "成飞概念": ("航空", "大飞机", "国防军工", "军民融合", "无人机"),
    "商业航天": ("卫星导航", "航空", "大飞机", "国防军工"),
    "千帆星座": ("卫星导航", "商业航天", "6G概念", "通信设备"),
    "低空经济": ("飞行汽车", "通用航空", "无人机", "航空"),
    "通用航空": ("低空经济", "飞行汽车", "无人机", "航空"),
    "海上丝路": ("一带一路", "航运概念", "自由贸易港", "港口航运", "港口", "水运"),
    "一带一路": ("海上丝路", "中俄贸易", "中俄贸易概念", "西部大开发", "建筑工程"),
    "丝绸之路": ("一带一路", "中俄贸易", "西部大开发"),
    "CPO概念": ("共封装光学(CPO)", "光通信", "光模块", "铜缆高速连接"),
    "共封装光学(CPO)": ("CPO概念", "光通信", "铜缆高速连接", "通信设备"),
    "飞行汽车": ("飞行汽车(eVTOL)", "低空经济", "通用航空", "无人机"),
    "飞行汽车(eVTOL)": ("飞行汽车", "低空经济", "无人机", "航空"),
    "DRG/DIP": ("DRG-DIP", "智慧医疗", "智能医疗", "医疗保健", "软件服务"),
    "DRG-DIP": ("DRG/DIP", "智能医疗", "医疗保健"),
    "兵装重组概念": ("国防军工", "军民融合", "中特估", "高端装备"),
    "短剧互动游戏": ("短剧游戏", "手机游戏", "网络游戏", "传媒娱乐"),
    "短剧游戏": ("短剧互动游戏", "网络游戏", "传媒娱乐"),
    "手机游戏": ("网络游戏", "短剧游戏", "云游戏", "传媒娱乐"),
    "高带宽内存": ("存储芯片", "先进封装", "芯片", "半导体"),
    "人形机器人": ("机器人概念", "减速器", "工业母机", "外骨骼机器人"),
    "东数西算": ("东数西算(算力)", "算力租赁", "数据中心", "云计算"),
    "东数西算(算力)": ("东数西算", "算力租赁", "数据中心", "云计算"),
    "数据中心(AIDC)": ("数据中心", "算力租赁", "液冷服务器", "东数西算"),
    "抖音概念": ("抖音概念(字节概念)", "网红经济", "短剧游戏", "传媒娱乐"),
    "抖音概念(字节概念)": ("抖音概念", "网红经济", "短剧游戏"),
    "车联网": ("车联网(车路协同)", "无人驾驶", "汽车电子", "智能交通"),
    "车联网(车路协同)": ("车联网", "无人驾驶", "汽车电子", "智能交通"),
    "智能座舱": ("汽车电子", "无人驾驶", "车联网", "消费电子概念"),
    "柔性屏": ("柔性屏(折叠屏)", "折叠屏", "OLED概念", "消费电子概念"),
    "柔性屏(折叠屏)": ("折叠屏", "OLED概念", "消费电子概念"),
    "新型烟草": ("新型烟草(电子烟)", "烟草概念"),
    "新型烟草(电子烟)": ("新型烟草", "烟草概念"),
    "化债概念": ("化债概念(AMC概念)", "多元金融", "中特估", "银行"),
    "化债概念(AMC概念)": ("化债概念", "多元金融", "银行"),
    "并购重组": ("股权转让(并购重组)", "中特估", "创投概念", "多元金融"),
    "股权转让(并购重组)": ("并购重组", "创投概念", "多元金融"),
    "央企国企改革": ("中特估", "国资云", "国防军工"),
    "国企改革": ("中特估", "国资云"),
    "AI PC": ("AI手机PC", "消费电子概念", "IT设备"),
    "AI手机": ("AI手机PC", "消费电子概念", "苹果概念"),
    "AI语料": ("AIGC概念", "多模态AI", "ChatGPT概念", "传媒娱乐"),
    "智谱AI": ("AI智能体", "AIGC概念", "ChatGPT概念", "软件服务"),
    "Sora概念(文生视频)": ("多模态AI", "AIGC概念", "短剧游戏"),
    "比亚迪概念": ("新能源车", "汽车配件", "锂电池概念", "高压快充"),
    "宁德时代概念": ("锂电池概念", "固态电池", "储能", "新能源车"),
    "长安汽车概念": ("新能源车", "华为汽车", "汽车整车", "无人驾驶"),
    "华为海思概念股": ("华为海思", "芯片", "半导体"),
    "华为欧拉": ("华为鸿蒙", "操作系统", "国产软件", "信创"),
    "鸿蒙概念": ("华为鸿蒙", "操作系统", "国产软件", "信创"),
    "信创": ("国产软件", "操作系统", "信息安全", "华为鸿蒙"),
    "网络安全": ("信息安全", "信创", "国产软件"),
    "光刻机(胶)": ("光刻机", "芯片", "半导体", "先进封装"),
    "芯片概念": ("芯片", "半导体", "存储芯片", "先进封装"),
    "第三代半导体": ("半导体", "芯片", "汽车芯片"),
    "汽车热管理": ("汽车配件", "新能源车", "热泵概念"),
    "一体化压铸": ("一体压铸", "汽车配件", "新能源车"),
    "光伏概念": ("光伏", "BC电池", "TOPCon电池", "HJT电池", "钙钛矿电池"),
    "风电设备": ("风电", "绿色电力", "电气设备"),
    "光伏设备": ("光伏", "BC电池", "TOPCon电池", "电气设备"),
    "电网设备": ("智能电网", "特高压", "虚拟电厂", "电气设备"),
    "电池": ("锂电池概念", "固态电池", "储能", "钠电池"),
    "能源金属": ("锂矿", "钴金属", "镍金属", "小金属"),
    "贵金属": ("黄金", "黄金概念", "有色"),
    "工业金属": ("铜", "铝", "铅锌", "有色"),
    "小金属概念": ("小金属", "稀土永磁", "稀缺资源", "钛金属"),
    "港口航运": ("港口", "水运", "航运概念", "一带一路"),
    "公路铁路运输": ("公路", "铁路", "路桥", "高铁", "公共交通"),
    "轨交设备": ("高铁", "运输设备", "机械基件"),
    "工程机械": ("工程机械", "专用机械", "工业机械", "高端装备"),
    "通用设备": ("通用机械", "机械基件", "工业母机"),
    "专用设备": ("专用机械", "工业母机", "高端装备"),
    "自动化设备": ("工业母机", "机器人概念", "减速器", "专用机械"),
    "白色家电": ("家用电器", "智能家居"),
    "黑色家电": ("家用电器", "MiniLED", "超清视频"),
    "小家电": ("家用电器", "智能家居"),
    "厨卫电器": ("家用电器", "家居用品"),
    "光学光电子": ("OLED概念", "MiniLED", "MicroLED", "元器件"),
    "消费电子": ("消费电子概念", "苹果概念", "无线耳机", "元器件"),
    "元件": ("元器件", "PCB概念", "MLCC概念"),
    "医疗器械": ("医疗保健", "血氧仪", "辅助生殖", "智能医疗"),
    "医疗服务": ("医疗保健", "CXO概念", "民营医院", "辅助生殖"),
    "中药": ("中成药", "医药", "流感"),
    "生物制品": ("生物制药", "生物疫苗", "创新药", "免疫治疗"),
    "医药商业": ("医药商业", "医药", "冷链物流"),
    "化学原料": ("化工原料", "化工", "氟概念", "磷概念"),
    "化学制品": ("化工", "分散染料", "聚氨酯", "有机硅概念"),
    "农化制品": ("农药化肥", "化肥概念", "草甘膦", "磷概念"),
    "电子化学品": ("光刻机", "半导体", "新材料", "化工"),
    "饮料制造": ("软饮料", "啤酒", "乳制品", "酿酒"),
    "食品加工制造": ("食品", "食品饮料", "预制菜", "乳制品"),
    "养殖业": ("猪肉", "鸡肉", "水产品", "饲料"),
    "农产品加工": ("粮食概念", "种业", "农业综合", "食品"),
}

_MEM_SUBMAPS: dict[str, dict[str, str]] = {}


def candidate_concept_names(name: str) -> list[str]:
    """返回板块名称的候选同义词列表（含原名、去“概念”后缀、加“概念”后缀及别名表）。"""
    raw = str(name or "").strip()
    if not raw:
        return []
    out: list[str] = [raw]

    def _add(val: str) -> None:
        v = str(val or "").strip()
        if v and v not in out:
            out.append(v)

    m = re.match(r"^([^\(（]+)[\(（]([^\)）]+)[\)）]$", raw)
    if m:
        p1, p2 = m.group(1).strip(), m.group(2).strip()
        _add(p1)
        _add(p2)
        _add(p1 + "概念")
        _add(p2 + "概念")

    stripped = raw.replace("概念", "").strip()
    if stripped:
        _add(stripped)
        _add(stripped + "概念")

    for alias in CONCEPT_ALIASES.get(raw, ()):
        _add(alias)
    if stripped and stripped in CONCEPT_ALIASES:
        for alias in CONCEPT_ALIASES[stripped]:
            _add(alias)
    return out


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


def _pooled_session(*, pool_size: int = 32) -> requests.Session:
    sess = requests.Session()
    sess.trust_env = False
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=0)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "http://q.10jqka.com.cn",
        }
    )
    return sess


def _ths_js() -> py_mini_racer.MiniRacer:
    js = py_mini_racer.MiniRacer()
    with open(get_ths_js("ths.js"), encoding="utf-8") as f:
        js.eval(f.read())
    return js


def _ths_headers(*, referer: str | None = None) -> dict[str, str]:
    try:
        js = _ths_js()
        v = js.call("v")
    except Exception:
        v = ""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if v:
        headers["Cookie"] = f"v={v}"
        headers["hexin-v"] = str(v)
    if referer:
        headers["Referer"] = referer
    return headers


def _seed_for_field(field: str) -> dict[str, str]:
    try:
        from .ths_seed import THS_CONCEPT_CLIDS, THS_CONCEPT_CODES, THS_INDUSTRY_CODES

        if field == "industry_codes":
            return dict(THS_INDUSTRY_CODES)
        if field == "concept_codes":
            return dict(THS_CONCEPT_CODES)
        if field == "concept_clids":
            return dict(THS_CONCEPT_CLIDS)
    except Exception:
        pass
    return {}


def _load_ths_submap(field: str) -> dict[str, str] | None:
    """从进程内内存、数据库或内置种子读取同花顺代码表（0ms 命中，永不为空）。"""
    if field in _MEM_SUBMAPS and _MEM_SUBMAPS[field]:
        return _MEM_SUBMAPS[field]
    bundle = get_doc(_THS_DOC_KEY, ttl_sec=3600)
    if isinstance(bundle, dict):
        obj = bundle.get(field)
        if isinstance(obj, dict):
            items = obj.get("items") or {}
            if items and isinstance(items, dict):
                out = {str(k): str(v) for k, v in items.items()}
                _MEM_SUBMAPS[field] = out
                return out
    seed = _seed_for_field(field)
    if seed:
        _MEM_SUBMAPS[field] = seed
        _save_ths_submap(field, seed)
        return seed
    return None


def _save_ths_submap(field: str, items: dict[str, str]) -> None:
    if not items:
        return
    _MEM_SUBMAPS[field] = dict(items)
    bundle = get_doc(_THS_DOC_KEY, ttl_sec=60)
    bundle = dict(bundle) if isinstance(bundle, dict) else {}
    bundle[field] = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    set_doc(_THS_DOC_KEY, bundle, async_write=True)


def load_industry_code_map(*, force: bool = False) -> dict[str, str]:
    """同花顺行业名 → 板块代码（881xxx）。存储于数据库 sectors_ths_codes。"""
    cached = _load_ths_submap("industry_codes")
    if cached and not force:
        return cached
    try:
        df = ak.stock_board_industry_name_ths()
        mapping = {
            str(r["name"]).strip(): str(r["code"]).strip()
            for _, r in df.iterrows()
            if str(r.get("name") or "").strip()
        }
        if mapping:
            _save_ths_submap("industry_codes", mapping)
            return mapping
    except Exception:
        pass
    return cached or {}


def load_concept_code_map(*, force: bool = False) -> dict[str, str]:
    """同花顺概念名 → 详情页 code（30xxxx，用于成分股分页）。存储于数据库 sectors_ths_codes。"""
    cached = _load_ths_submap("concept_codes")
    if cached and not force:
        return cached
    try:
        df = ak.stock_board_concept_name_ths()
        mapping = {
            str(r["name"]).strip(): str(r["code"]).strip()
            for _, r in df.iterrows()
            if str(r.get("name") or "").strip() and str(r["name"]).strip() not in THS_CONCEPT_SKIP
        }
        if mapping:
            _save_ths_submap("concept_codes", mapping)
            return mapping
    except Exception:
        pass
    return cached or {}


def _fetch_single_clid_by_detail_code(detail_code: str) -> str | None:
    detail = str(detail_code or "").strip()
    if not detail:
        return None
    if detail.startswith(("885", "886", "881")) and len(detail) == 6:
        return detail
    base = f"http://q.10jqka.com.cn/gn/detail/code/{detail}/"
    sess = _pooled_session(pool_size=4)
    try:
        r = sess.get(base, headers=_ths_headers(referer=base), timeout=3.0)
        r.encoding = "gbk"
        m = re.search(r'id=["\']clid["\'][^>]*value=["\'](\d+)["\']', r.text)
        if not m:
            m = re.search(r'value=["\'](\d+)["\'][^>]*id=["\']clid["\']', r.text)
        return m.group(1) if m else None
    except Exception:
        return None


def load_concept_clid_map(*, force: bool = False) -> dict[str, str]:
    """同花顺概念名 → 指数 clid（885xxx/886xxx，用于 d.10jqka.com.cn 行情）。"""
    cached = _load_ths_submap("concept_clids")
    if cached and not force:
        return cached
    return cached or {}


def resolve_ths_board_code(
    name: str, *, kind: str = "概念", allow_online_lookup: bool = False
) -> tuple[str | None, str]:
    """解析同花顺板块指数代码（881xxx / 885xxx / 886xxx）与标准名称（纯内存 0ms 查找）。"""
    target = str(name or "").strip()
    if not target:
        return None, ""
    if target.startswith(("881", "885", "886")) and len(target) == 6 and target.isdigit():
        return target, target

    candidates = candidate_concept_names(target)
    ind_map = load_industry_code_map()
    clid_map = load_concept_clid_map()

    search_maps = (
        [(ind_map, "ind"), (clid_map, "clid")]
        if kind == "行业"
        else [(clid_map, "clid"), (ind_map, "ind")]
    )

    for cand in candidates:
        for mp, _tag in search_maps:
            if cand in mp:
                return mp[cand], cand

    for cand in candidates:
        if len(cand) < 2:
            continue
        for mp, _tag in search_maps:
            hits = [(k, v) for k, v in mp.items() if cand in k or k in cand]
            if len(hits) == 1:
                return hits[0][1], hits[0][0]

    if allow_online_lookup:
        code_map = load_concept_code_map()
        for cand in candidates:
            if cand in code_map:
                detail_code = code_map[cand]
                clid = _fetch_single_clid_by_detail_code(detail_code)
                if clid:
                    clid_map[cand] = clid
                    _save_ths_submap("concept_clids", clid_map)
                    return clid, cand
    return None, target


def _parse_ths_last_js_bars(text: str) -> list[dict[str, Any]]:
    """解析 d.10jqka.com.cn/v4/line/bk_{code}/01/last.js 完整 OHLCV 日线。"""
    m = re.search(r"\((.*)\)\s*;?\s*$", str(text or "").strip(), re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(1))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for part in str(obj.get("data") or "").split(";"):
        cols = part.split(",")
        if len(cols) < 5 or not cols[4]:
            continue
        d = str(cols[0]).strip()
        if len(d) == 8 and d.isdigit():
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        o = _clean(cols[1]) if len(cols) > 1 else None
        h = _clean(cols[2]) if len(cols) > 2 else None
        lo = _clean(cols[3]) if len(cols) > 3 else None
        c = _clean(cols[4]) if len(cols) > 4 else None
        vol = _clean(cols[5]) if len(cols) > 5 else None
        amt = _clean(cols[6]) if len(cols) > 6 else None
        if not d or c is None:
            continue
        rows.append(
            {
                "date": d,
                "open": o if o is not None else c,
                "high": h if h is not None else c,
                "low": lo if lo is not None else c,
                "close": c,
                "vol": vol,
                "amount": amt,
            }
        )
    return rows


def _parse_ths_today_js_bar(text: str, code: str) -> dict[str, Any] | None:
    """解析 d.10jqka.com.cn/v4/line/bk_{code}/01/today.js 当日实时 K 线柱。"""
    m = re.search(r"\((.*)\)\s*;?\s*$", str(text or "").strip(), re.S)
    if not m:
        return None
    try:
        outer = json.loads(m.group(1))
    except Exception:
        return None
    inner = outer.get(f"bk_{code}") if isinstance(outer, dict) else None
    if not isinstance(inner, dict):
        for v in (outer or {}).values():
            if isinstance(v, dict):
                inner = v
                break
    if not isinstance(inner, dict):
        return None
    dt = str(inner.get("1") or "").strip()
    if len(dt) == 8 and dt.isdigit():
        dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
    c = _clean(inner.get("11"))
    if not dt or c is None:
        return None
    o = _clean(inner.get("7")) or c
    h = _clean(inner.get("8")) or c
    lo = _clean(inner.get("9")) or c
    vol = _clean(inner.get("13"))
    amt = _clean(inner.get("19"))
    return {
        "date": dt,
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "vol": vol,
        "amount": amt,
    }


def fetch_ths_board_kline(
    name_or_code: str,
    *,
    kind: str = "概念",
    count: int = 130,
) -> tuple[list[dict[str, Any]], str, str]:
    """拉取同花顺板块指数日 K 线（仅走 d.10jqka.com.cn 静态 CDN，2s 超时，不爬网页）。"""
    code, resolved_name = resolve_ths_board_code(
        name_or_code, kind=kind, allow_online_lookup=False
    )
    if not code:
        return [], "", resolved_name or str(name_or_code)

    sess = _pooled_session(pool_size=4)
    bars: list[dict[str, Any]] = []
    try:
        r = sess.get(
            f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/last.js",
            timeout=2.0,
        )
        if r.status_code == 200:
            bars = _parse_ths_last_js_bars(r.text)
    except Exception:
        bars = []

    if bars:
        try:
            rt = sess.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/today.js",
                timeout=1.2,
            )
            if rt.status_code == 200:
                tbar = _parse_ths_today_js_bar(rt.text, code)
                if tbar:
                    if bars[-1]["date"] == tbar["date"]:
                        bars[-1] = tbar
                    elif tbar["date"] > bars[-1]["date"]:
                        bars.append(tbar)
        except Exception:
            pass

    return bars[-count:] if bars else [], code, resolved_name or str(name_or_code)


def _parse_ths_last_js(text: str) -> list[tuple[str, float, float | None]]:
    bars = _parse_ths_last_js_bars(text)
    return [(b["date"], float(b["close"]), b.get("amount")) for b in bars if b.get("close") is not None]


def _fetch_last_series(
    items: list[tuple[str, str]],
    *,
    tail: int,
) -> dict[str, list[tuple[str, float, float | None]]]:
    if not items:
        return {}
    sess = _pooled_session(pool_size=32)
    sess.headers.update({"Host": "d.10jqka.com.cn"})

    def _one(item: tuple[str, str]) -> tuple[str, list[tuple[str, float, float | None]]]:
        name, code = item
        try:
            r = sess.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/last.js",
                timeout=4.0,
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
    with ThreadPoolExecutor(max_workers=24) as pool:
        futs = [pool.submit(_one, it) for it in items]
        for fut in as_completed(futs):
            name, series = fut.result()
            if series:
                out[name] = series
    return out


def fetch_ths_industry_spot() -> pd.DataFrame:
    """同花顺行业一览（优先 last.js 高速接口，避免 akshare 爬虫阻塞）。"""
    code_map = load_industry_code_map()
    if not code_map:
        return pd.DataFrame()
    items = list(code_map.items())
    series_map = _fetch_last_series(items, tail=1)
    rows = []
    for name, code in items:
        series = series_map.get(name) or []
        if not series:
            continue
        _, chg, amt = series[-1]
        rows.append(
            {
                "板块": name,
                "label": code,
                "涨跌幅": _clean(chg),
                "总成交额": _clean(amt),
                "资金": _clean(amt),
                "主力净额": None,
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


def fetch_ths_concept_spot() -> pd.DataFrame:
    """同花顺概念实时（last.js，剔除通道类）。"""
    _, spot_df = fetch_ths_concept_history_and_spot(days=1)
    return spot_df


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


def fetch_ths_concept_history_and_spot(
    days: int = 20,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """单次拉取同花顺概念近 N 日序列，同时返回 (历史快照列表, 今日spot DataFrame)。"""
    clid_map = load_concept_clid_map()
    clid_map = {k: v for k, v in clid_map.items() if k not in THS_CONCEPT_SKIP}
    if not clid_map:
        return [], pd.DataFrame()
    code_map = load_concept_code_map()
    items = list(clid_map.items())
    series_map = _fetch_last_series(items, tail=days + 1)
    hist = _history_from_series(
        series_map,
        kind="概念",
        label_map=code_map,
        source="同花顺概念",
        days=days,
    )
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
                "code": clid,
                "涨跌幅": _clean(chg),
                "总成交额": _clean(amt),
                "资金": _clean(amt),
                "资金口径": "成交额",
                "领涨名称": "",
                "领涨涨幅": None,
                "涨停数": 0,
            }
        )
    spot_df = (
        pd.DataFrame(rows).sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )
    return hist, spot_df


def fetch_ths_industry_history_and_spot(
    days: int = 20,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """单次拉取同花顺行业近 N 日序列与今日排行。"""
    code_map = load_industry_code_map()
    if not code_map:
        return [], pd.DataFrame()
    items = list(code_map.items())
    series_map = _fetch_last_series(items, tail=days + 1)
    hist = _history_from_series(
        series_map,
        kind="行业",
        label_map=code_map,
        source="同花顺行业",
        days=days,
    )
    rows: list[dict[str, Any]] = []
    for name, code in items:
        series = series_map.get(name) or []
        if not series:
            continue
        _, chg, amt = series[-1]
        rows.append(
            {
                "板块": name,
                "label": code,
                "涨跌幅": _clean(chg),
                "总成交额": _clean(amt),
                "资金": _clean(amt),
                "主力净额": None,
                "资金口径": "成交额",
                "领涨名称": "",
                "领涨涨幅": None,
                "涨停数": 0,
            }
        )
    spot_df = (
        pd.DataFrame(rows).sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )
    return hist, spot_df


def fetch_ths_industry_history(days: int = 20) -> list[dict[str, Any]]:
    hist, _ = fetch_ths_industry_history_and_spot(days=days)
    return hist


def fetch_ths_concept_history(days: int = 20) -> list[dict[str, Any]]:
    hist, _ = fetch_ths_concept_history_and_spot(days=days)
    return hist


def _member_path_prefix(kind: str) -> str:
    return _THSHY if kind == "行业" else _GN


def _fetch_member_pages(path_prefix: str, code: str, *, max_pages: int = 1) -> pd.DataFrame:
    base = f"http://q.10jqka.com.cn/{path_prefix}/detail/code/{code}/"
    headers = _ths_headers(referer=base)
    sess = _pooled_session(pool_size=4)
    r = sess.get(base, headers=headers, timeout=3.0)
    r.encoding = "gbk"
    m = re.search(r"page_info[^>]*>([^<]+)", r.text)
    pages = 1
    if m:
        try:
            pages = max(1, min(max_pages, int(str(m.group(1)).split("/")[-1].strip())))
        except ValueError:
            pages = 1
    frames: list[pd.DataFrame] = []
    for page in range(1, pages + 1):
        url = base if page == 1 else f"{base}page/{page}/"
        rr = r if page == 1 else sess.get(url, headers=headers, timeout=3.0)
        rr.encoding = "gbk"
        try:
            frames.append(pd.read_html(StringIO(rr.text))[0])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_ths_board_members(kind: str, name: str, *, limit: int = 80) -> pd.DataFrame:
    """按同花顺板块名称拉成分股（仅抓第 1 页，3s 快速超时，不调慢速 akshare 爬虫）。"""
    kind = str(kind).strip()
    name = str(name).strip()
    if kind not in ("行业", "概念"):
        raise ValueError("kind 仅支持 行业 / 概念")

    code_map = load_industry_code_map() if kind == "行业" else load_concept_code_map()
    candidates = candidate_concept_names(name)

    code = None
    for cand in candidates:
        if cand in code_map:
            code = code_map[cand]
            break

    if not code:
        return pd.DataFrame()

    try:
        raw = _fetch_member_pages(_member_path_prefix(kind), code, max_pages=1)
        if raw is not None and not raw.empty:
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
                out = out.sort_values("涨跌幅", ascending=False, na_position="last")
            if "成交额" in out.columns:
                out["成交额"] = out["成交额"].map(_parse_amount)
            return out.head(limit).reset_index(drop=True)
    except Exception:
        pass

    return pd.DataFrame()


def ths_availability() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": "ths_db"}
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
