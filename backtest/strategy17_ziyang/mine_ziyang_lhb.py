"""挖掘国泰海通/国泰君安武汉紫阳东路近3个月龙虎榜成交 → 策略十七·紫阳真君池。

数据源：东方财富营业部统计/明细（akshare 同口径）；席位标签民间映射见 b7。
研究用途，非投资建议。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT_DIR = Path(__file__).resolve().parent
PICKS_PATH = OUT_DIR / "picks_3m.json"
DETAIL_PATH = OUT_DIR / "seat_trades_3m.csv"

SEAT_NAME_KEYS = ("武汉紫阳东路", "紫阳东路")
# 合并后官方全称；历史可能仍出现「国泰君安」
SEAT_FULL_NAMES = (
    "国泰海通证券股份有限公司武汉紫阳东路证券营业部",
    "国泰君安证券股份有限公司武汉紫阳东路证券营业部",
    "国泰海通证券武汉紫阳东路证券营业部",
    "国泰君安证券武汉紫阳东路证券营业部",
)

EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _em_get(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        p = dict(params)
        p["pageNumber"] = str(page)
        r = requests.get(EM_API, params=p, timeout=60)
        r.raise_for_status()
        payload = r.json()
        result = payload.get("result") or {}
        chunk = result.get("data") or []
        if not chunk:
            break
        rows.extend(chunk)
        pages = int(result.get("pages") or 1)
        if page >= pages:
            break
        page += 1
    return rows


def resolve_seat_code() -> tuple[str, str]:
    """近三月营业部统计里定位紫阳东路，返回 (营业部代码, 名称)。"""
    rows = _em_get(
        {
            "sortColumns": "AMOUNT,OPERATEDEPT_CODE",
            "sortTypes": "-1,1",
            "pageSize": "5000",
            "reportName": "RPT_OPERATEDEPT_LIST_STATISTICS",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": '(STATISTICSCYCLE="02")',
        }
    )
    hits = [
        x
        for x in rows
        if any(k in str(x.get("OPERATEDEPT_NAME") or "") for k in SEAT_NAME_KEYS)
        and "南昌" not in str(x.get("OPERATEDEPT_NAME") or "")
    ]
    if not hits:
        raise RuntimeError("未在东财近三月营业部统计中找到武汉紫阳东路")
    hits.sort(key=lambda x: float(x.get("AMOUNT") or 0), reverse=True)
    top = hits[0]
    code = str(top.get("OPERATEDEPT_CODE") or "").strip()
    name = str(top.get("OPERATEDEPT_NAME") or "").strip()
    if not code:
        raise RuntimeError(f"紫阳东路无营业部代码: {top}")
    return code, name


def fetch_seat_trades(seat_code: str) -> pd.DataFrame:
    rows = _em_get(
        {
            "sortColumns": "TRADE_DATE,SECURITY_CODE",
            "sortTypes": "-1,1",
            "pageSize": "500",
            "reportName": "RPT_OPERATEDEPT_TRADE_DETAILSNEW",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(OPERATEDEPT_CODE="{seat_code}")',
        }
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _to_code(symbol: object) -> str:
    text = "" if symbol is None or (isinstance(symbol, float) and pd.isna(symbol)) else str(symbol).strip()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def build_pool(
    detail: pd.DataFrame,
    *,
    seat_code: str,
    seat_name: str,
    window_days: int = 90,
) -> dict[str, Any]:
    end = pd.Timestamp.now(tz="Asia/Shanghai").normalize().tz_localize(None)
    start = end - timedelta(days=window_days)

    df = detail.copy()
    if "TRADE_DATE" not in df.columns:
        raise RuntimeError(f"明细缺 TRADE_DATE 列: {df.columns.tolist()}")

    df["trade_date"] = pd.to_datetime(df["TRADE_DATE"], errors="coerce")
    df = df.dropna(subset=["trade_date"])
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)].copy()

    # 买入侧：BUY_AMT / BUY 相关字段；无则保留全部有成交的记录
    buy_col = next(
        (c for c in ("BUY", "BUY_AMT", "ACT_BUY", "BUY_AMOUNT") if c in df.columns),
        None,
    )
    sell_col = next(
        (c for c in ("SELL", "SELL_AMT", "ACT_SELL", "SELL_AMOUNT") if c in df.columns),
        None,
    )
    if buy_col:
        df["buy_amt"] = pd.to_numeric(df[buy_col], errors="coerce").fillna(0.0)
    else:
        df["buy_amt"] = 0.0
    if sell_col:
        df["sell_amt"] = pd.to_numeric(df[sell_col], errors="coerce").fillna(0.0)
    else:
        df["sell_amt"] = 0.0

    code_col = "SECURITY_CODE" if "SECURITY_CODE" in df.columns else "SECURITY_CODE_OLD"
    name_col = "SECURITY_NAME_ABBR" if "SECURITY_NAME_ABBR" in df.columns else "SECURITY_NAME"
    df["code"] = df[code_col].map(_to_code) if code_col in df.columns else ""
    df["name"] = df[name_col].fillna("").astype(str) if name_col in df.columns else ""
    df = df[df["code"].str.len() == 6].copy()

    # 「交易过」= 买或卖任一出现；池内优先按净买/买入额排序
    df["net"] = df["buy_amt"] - df["sell_amt"]

    g = (
        df.groupby(["code", "name"], as_index=False)
        .agg(
            appearances=("trade_date", "nunique"),
            buy_amt=("buy_amt", "sum"),
            sell_amt=("sell_amt", "sum"),
            net=("net", "sum"),
            last_date=("trade_date", "max"),
            first_date=("trade_date", "min"),
        )
        .sort_values(["appearances", "buy_amt", "net"], ascending=[False, False, False])
        .reset_index(drop=True)
    )
    g["rank"] = g.index + 1
    g["last_date"] = g["last_date"].dt.strftime("%Y-%m-%d")
    g["first_date"] = g["first_date"].dt.strftime("%Y-%m-%d")

    picks = []
    for _, row in g.iterrows():
        picks.append(
            {
                "rank": int(row["rank"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "appearances": int(row["appearances"]),
                "buy_amt": float(row["buy_amt"]),
                "sell_amt": float(row["sell_amt"]),
                "net": float(row["net"]),
                "first_date": row["first_date"],
                "last_date": row["last_date"],
                "category": "紫阳真君",
            }
        )

    payload = {
        "horizon": "rolling_3m",
        "window_days": window_days,
        "window_start": start.strftime("%Y-%m-%d"),
        "window_end": end.strftime("%Y-%m-%d"),
        "as_of": end.strftime("%Y-%m-%d"),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "eastmoney_operate_dept_trade_details",
        "seat_code": seat_code,
        "seat_name": seat_name,
        "seat_aliases": list(SEAT_FULL_NAMES),
        "seat_tag_note": "b7 席位库映射别名「消闲派」（民间观测，非官方认定）",
        "n_trades": int(len(df)),
        "n_picks": len(picks),
        "picks": picks,
        "label": f"{start.strftime('%Y-%m-%d')}~{end.strftime('%Y-%m-%d')} 紫阳东路",
    }
    return payload


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seat_code, seat_name = resolve_seat_code()
    print(f"seat: {seat_name} ({seat_code})")
    detail = fetch_seat_trades(seat_code)
    print(f"raw trades: {len(detail)} cols={detail.columns.tolist()[:12]}")
    if len(detail):
        detail.to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")
    payload = build_pool(detail, seat_code=seat_code, seat_name=seat_name)
    PICKS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {PICKS_PATH} n_picks={payload['n_picks']}")
    for p in payload["picks"][:20]:
        print(
            f"  #{p['rank']:02d} {p['code']} {p['name']} "
            f"n={p['appearances']} buy={p['buy_amt']/1e8:.2f}亿 net={p['net']/1e8:.2f}亿 "
            f"{p['first_date']}~{p['last_date']}"
        )


if __name__ == "__main__":
    main()
