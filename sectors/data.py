"""板块数据拉取：优先东财，失败回退新浪。"""

from __future__ import annotations

from typing import Any

import akshare as ak
import pandas as pd


BOARD_COLS = [
    "label",
    "板块",
    "公司家数",
    "平均价格",
    "涨跌额",
    "涨跌幅",
    "总成交量",
    "总成交额",
    "领涨代码",
    "领涨涨幅",
    "领涨现价",
    "领涨涨跌额",
    "领涨名称",
]


def _normalize_sina(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {
        "股票代码": "领涨代码",
        "个股-涨跌幅": "领涨涨幅",
        "个股-当前价": "领涨现价",
        "个股-涨跌额": "领涨涨跌额",
        "股票名称": "领涨名称",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    for col in (
        "公司家数",
        "平均价格",
        "涨跌额",
        "涨跌幅",
        "总成交量",
        "总成交额",
        "领涨涨幅",
        "领涨现价",
        "领涨涨跌额",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    keep = [c for c in BOARD_COLS if c in out.columns]
    return out[keep].reset_index(drop=True)


def _normalize_em(df: pd.DataFrame, *, kind: str) -> pd.DataFrame:
    """东财行业/概念 name 列表 → 统一列。"""
    out = pd.DataFrame()
    out["label"] = df.get("板块代码", "")
    out["板块"] = df.get("板块名称", "")
    out["公司家数"] = pd.to_numeric(
        df.get("上涨家数", 0), errors="coerce"
    ).fillna(0) + pd.to_numeric(df.get("下跌家数", 0), errors="coerce").fillna(0)
    out["平均价格"] = pd.to_numeric(df.get("最新价"), errors="coerce")
    out["涨跌额"] = pd.to_numeric(df.get("涨跌额"), errors="coerce")
    out["涨跌幅"] = pd.to_numeric(df.get("涨跌幅"), errors="coerce")
    out["总成交量"] = pd.NA
    out["总成交额"] = pd.to_numeric(df.get("总市值"), errors="coerce")
    out["领涨代码"] = ""
    out["领涨涨幅"] = pd.to_numeric(df.get("领涨股票-涨跌幅"), errors="coerce")
    out["领涨现价"] = pd.NA
    out["领涨涨跌额"] = pd.NA
    out["领涨名称"] = df.get("领涨股票", "")
    out["上涨家数"] = pd.to_numeric(df.get("上涨家数"), errors="coerce")
    out["下跌家数"] = pd.to_numeric(df.get("下跌家数"), errors="coerce")
    out["换手率"] = pd.to_numeric(df.get("换手率"), errors="coerce")
    out["来源"] = f"东财-{kind}"
    return out


def fetch_board_spot(kind: str = "行业") -> pd.DataFrame:
    """拉取板块行情。kind: 行业 | 概念。"""
    kind = str(kind).strip()
    if kind not in ("行业", "概念"):
        raise ValueError("kind 仅支持 行业 / 概念")

    # 1) 东财
    try:
        raw = (
            ak.stock_board_industry_name_em()
            if kind == "行业"
            else ak.stock_board_concept_name_em()
        )
        if raw is not None and not raw.empty:
            out = _normalize_em(raw, kind=kind)
            return out.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(
                drop=True
            )
    except Exception:
        pass

    # 2) 新浪
    raw = ak.stock_sector_spot(indicator=kind)
    out = _normalize_sina(raw)
    out["来源"] = f"新浪-{kind}"
    out["上涨家数"] = pd.NA
    out["下跌家数"] = pd.NA
    out["换手率"] = pd.NA
    return out.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(
        drop=True
    )


def fetch_board_members(label: str) -> pd.DataFrame:
    """按新浪 label 拉成分股；东财代码时尝试东财成分。"""
    label = str(label).strip()
    if not label:
        raise ValueError("label 为空")

    # 东财板块代码形如 BK0475
    if label.upper().startswith("BK"):
        try:
            # 需要板块名称，东财 cons 接口吃名称；这里仅作兼容：失败再抛
            raise RuntimeError("需要板块名称才能用东财成分接口")
        except Exception:
            pass

    raw = ak.stock_sector_detail(sector=label)
    if raw is None or raw.empty:
        return pd.DataFrame()
    out = raw.copy()
    rename = {
        "symbol": "代码",
        "code": "纯代码",
        "name": "名称",
        "trade": "现价",
        "pricechange": "涨跌额",
        "changepercent": "涨跌幅",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "settlement": "昨收",
        "volume": "成交量",
        "amount": "成交额",
        "turnoverratio": "换手率",
        "per": "市盈率",
        "pb": "市净率",
        "mktcap": "总市值",
        "nmc": "流通市值",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    for col in (
        "现价",
        "涨跌额",
        "涨跌幅",
        "开盘",
        "最高",
        "最低",
        "昨收",
        "成交量",
        "成交额",
        "换手率",
        "市盈率",
        "市净率",
        "总市值",
        "流通市值",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "涨跌幅" in out.columns:
        out = out.sort_values("涨跌幅", ascending=False, na_position="last")
    return out.reset_index(drop=True)


def fetch_board_members_by_name(kind: str, name: str) -> pd.DataFrame:
    """按板块名称拉成分：优先同花顺，再东财/新浪。"""
    kind = str(kind).strip()
    name = str(name).strip()
    try:
        from .ths import fetch_ths_board_members, ths_availability

        if ths_availability().get("ok"):
            df = fetch_ths_board_members(kind, name)
            if df is not None and not df.empty:
                return df
    except Exception:
        pass

    try:
        if kind == "行业":
            raw = ak.stock_board_industry_cons_em(symbol=name)
        else:
            raw = ak.stock_board_concept_cons_em(symbol=name)
        if raw is not None and not raw.empty:
            out = raw.copy()
            rename = {
                "代码": "纯代码",
                "名称": "名称",
                "最新价": "现价",
                "涨跌幅": "涨跌幅",
                "涨跌额": "涨跌额",
                "成交量": "成交量",
                "成交额": "成交额",
                "换手率": "换手率",
                "市盈率-动态": "市盈率",
                "市净率": "市净率",
            }
            out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
            if "涨跌幅" in out.columns:
                out["涨跌幅"] = pd.to_numeric(out["涨跌幅"], errors="coerce")
                out = out.sort_values("涨跌幅", ascending=False, na_position="last")
            return out.reset_index(drop=True)
    except Exception:
        pass

    boards = fetch_board_spot(kind)
    hit = boards[boards["板块"].astype(str) == name]
    if hit.empty:
        raise KeyError(f"未找到板块: {kind}/{name}")
    return fetch_board_members(str(hit.iloc[0]["label"]))


def board_summary(df: pd.DataFrame) -> dict[str, Any]:
    """板块列表摘要统计。"""
    if df is None or df.empty:
        return {
            "n": 0,
            "up": 0,
            "down": 0,
            "flat": 0,
            "avg_chg": None,
            "median_chg": None,
            "amount_sum": None,
        }
    chg = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
    amt = pd.to_numeric(df.get("总成交额"), errors="coerce")
    return {
        "n": int(len(df)),
        "up": int((chg > 0).sum()),
        "down": int((chg < 0).sum()),
        "flat": int((chg == 0).sum()),
        "avg_chg": None if chg.empty else round(float(chg.mean()), 3),
        "median_chg": None if chg.empty else round(float(chg.median()), 3),
        "amount_sum": None if amt.dropna().empty else float(amt.sum()),
    }
