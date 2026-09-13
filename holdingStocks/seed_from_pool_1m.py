"""把 pool_1m 三槽回测末日持仓写入本地盯盘账本（holdings.json）。

云环境没有本机实仓；用最近一次对账回测的期末未平仓当纸面起点，
周一 9:15 重置后隔夜仓可卖。研究用途，非投资建议。

holdings.json 被 .gitignore，本脚本只写本地，不提交账本。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from watch_config import (  # noqa: E402
    code_key,
    empty_position,
    effective_watchlist,
    market_of,
    meta_for_code,
)

DEFAULT_POOL_DIR = _ROOT / "backtest" / "strategy16_core_leader"
DEFAULT_TAG = "_week202609"
HOLDINGS_FILE = _HERE / "holdings.json"


@dataclass
class OpenLot:
    code: str
    name: str
    qty: int
    cost: float
    buy_time: str
    orig_qty: int
    tp_stage: int = 0
    last_tp_ts: str | None = None
    last_px: float | None = None


def _as_int(v: Any) -> int:
    return int(float(v or 0))


def _as_float(v: Any) -> float:
    return float(v or 0)


def reconstruct_open_lots(trades: list[dict[str, Any]]) -> dict[str, OpenLot]:
    """按成交顺序回放买卖，得到期末未平仓（含半仓剩余与 tp_stage）。"""
    lots: dict[str, OpenLot] = {}
    for row in trades:
        code = code_key(str(row.get("code") or ""))
        if not code:
            continue
        side = str(row.get("side") or "").strip().lower()
        shares = _as_int(row.get("shares") if row.get("shares") is not None else row.get("qty"))
        if shares <= 0:
            continue
        name = str(row.get("name") or (lots[code].name if code in lots else code))
        ts = str(row.get("ts") or row.get("time") or row.get("date") or "")
        px = _as_float(row.get("px") if row.get("px") is not None else row.get("price"))
        if side == "buy":
            prev = lots.get(code)
            if prev is not None and prev.qty > 0:
                new_qty = prev.qty + shares
                cost = (prev.cost * prev.qty + px * shares) / new_qty
                lots[code] = replace(
                    prev,
                    qty=new_qty,
                    cost=round(cost, 4),
                    name=name or prev.name,
                    orig_qty=prev.orig_qty + shares,
                )
            else:
                lots[code] = OpenLot(
                    code=code,
                    name=name or code,
                    qty=shares,
                    cost=round(px, 4),
                    buy_time=ts,
                    orig_qty=shares,
                )
            continue
        if side != "sell":
            continue
        prev = lots.get(code)
        if prev is None:
            continue
        remain = prev.qty - shares
        if remain <= 0:
            lots.pop(code, None)
            continue
        reason = str(row.get("exit_reason") or row.get("kind") or "")
        half = reason == "ladder_half_10"
        lots[code] = replace(
            prev,
            qty=remain,
            tp_stage=1 if half else prev.tp_stage,
            last_tp_ts=ts if half else prev.last_tp_ts,
        )
    return lots


def load_trades_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_equity_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _tag_stems(tag: str) -> list[str]:
    """对齐 pool_1m：stem = '_' + tag。也接受已带前导 _ 的目录名。"""
    raw = str(tag or "").strip()
    if not raw:
        return [""]
    stems = [f"_{raw}"]
    if raw.startswith("_"):
        stems.append(raw)
    else:
        stems.append(f"__{raw}")
    seen: list[str] = []
    for s in stems:
        if s not in seen:
            seen.append(s)
    return seen


def resolve_artifacts(*, pool_dir: Path, tag: str) -> dict[str, Path]:
    last_missing: list[Path] = []
    for stem in _tag_stems(tag):
        json_path = pool_dir / f"pool_1m_7d{stem}.json"
        trades = pool_dir / f"portfolio_trades{stem}.csv"
        equity = pool_dir / f"portfolio_equity{stem}.csv"
        missing = [p for p in (json_path, trades, equity) if not p.is_file()]
        if not missing:
            return {"json": json_path, "trades": trades, "equity": equity}
        last_missing = missing
    names = ", ".join(str(p.name) for p in last_missing) or "未知"
    raise FileNotFoundError(f"缺少回测产物 {names}（目录 {pool_dir} tag={tag!r}）")


def merge_json_marks(lots: dict[str, OpenLot], payload: dict[str, Any]) -> None:
    for raw in payload.get("open_positions") or []:
        if not isinstance(raw, dict):
            continue
        code = code_key(str(raw.get("code") or ""))
        lot = lots.get(code)
        if lot is None:
            continue
        if raw.get("last_px") is not None:
            lot.last_px = _as_float(raw["last_px"])
        if raw.get("name"):
            lot.name = str(raw["name"])
        if raw.get("shares") is not None and _as_int(raw["shares"]) != lot.qty:
            raise ValueError(
                f"{code} 成交回放股数 {lot.qty} 与 JSON 期末 {raw.get('shares')} 不一致"
            )


def build_holdings(
    *,
    lots: dict[str, OpenLot],
    last_session: str,
    cash: float,
    equity: float,
    prev_equity: float,
    initial_cash: float,
    tag: str,
    artifact: str,
) -> dict[str, Any]:
    positions: dict[str, Any] = {}
    for w in effective_watchlist({}):
        positions[code_key(w["code"])] = empty_position(w)
    open_codes: list[str] = []
    for code, lot in sorted(lots.items()):
        meta = meta_for_code(code, {"positions": {code: {"name": lot.name}}})
        buy_day = str(lot.buy_time)[:10]
        t1_locked = buy_day == last_session
        last_px = lot.last_px if lot.last_px is not None else lot.cost
        pos = empty_position(meta)
        pos.update(
            {
                "name": lot.name or meta.get("name") or code,
                "market": meta.get("market") or market_of(code),
                "qty": int(lot.qty),
                "available": 0 if t1_locked else int(lot.qty),
                "cost": round(float(lot.cost), 4),
                "today_cost": round(float(lot.cost), 4) if t1_locked else None,
                "buy_time": lot.buy_time,
                "tp_stage": int(lot.tp_stage or 0),
                "last_tp_ts": lot.last_tp_ts,
                "peak_high": round(max(float(lot.cost), float(last_px)), 4),
                "note": f"pool_1m{tag} 末日 {last_session}",
            }
        )
        positions[code] = pos
        open_codes.append(code)
    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_total": round(float(equity), 2),
        "account_cash": round(float(cash), 2),
        "account_total_open": round(float(prev_equity), 2),
        "account_total_open_session": last_session,
        "account_init": round(float(initial_cash), 2),
        "portfolio_pool": open_codes,
        "positions": positions,
        "realized_today": {},
        "closed_today": {},
        "alert_sticky": {},
        "seed_source": {
            "kind": "pool_1m",
            "tag": tag,
            "asof": last_session,
            "artifact": artifact,
            "n_open": len(open_codes),
        },
    }


def seed_holdings(
    *,
    pool_dir: Path | None = None,
    tag: str = DEFAULT_TAG,
    out_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    pool_dir = Path(pool_dir or DEFAULT_POOL_DIR)
    paths = resolve_artifacts(pool_dir=pool_dir, tag=tag)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    trades = load_trades_csv(paths["trades"])
    equity_rows = load_equity_csv(paths["equity"])
    if not equity_rows:
        raise ValueError(f"{paths['equity']} 无日末权益")
    last = equity_rows[-1]
    last_session = str(last.get("date") or "")[:10]
    cash = _as_float(last.get("cash"))
    equity = _as_float(last.get("equity"))
    prev_equity = (
        _as_float(equity_rows[-2]["equity"]) if len(equity_rows) >= 2 else _as_float(
            (payload.get("summary") or {}).get("portfolio", {}).get("initial_cash") or 300000
        )
    )
    initial_cash = _as_float(
        ((payload.get("summary") or {}).get("portfolio") or {}).get("initial_cash") or 300000
    )
    lots = reconstruct_open_lots(trades)
    merge_json_marks(lots, payload)
    equity_codes = {
        code_key(c)
        for c in str(last.get("codes") or "").split(",")
        if c.strip()
    }
    if equity_codes and set(lots) != equity_codes:
        raise ValueError(
            f"成交回放未平仓 {sorted(lots)} 与末日权益 codes {sorted(equity_codes)} 不一致"
        )
    data = build_holdings(
        lots=lots,
        last_session=last_session,
        cash=cash,
        equity=equity,
        prev_equity=prev_equity,
        initial_cash=initial_cash,
        tag=tag,
        artifact=str(paths["json"].relative_to(_ROOT)),
    )
    dest = Path(out_path or HOLDINGS_FILE)
    if not dry_run:
        dest.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return data


def _print_summary(data: dict[str, Any]) -> None:
    src = data.get("seed_source") or {}
    print(
        f"种子 {src.get('artifact')} asof={src.get('asof')} "
        f"权益={data.get('account_total')} 现金={data.get('account_cash')}"
    )
    positions = data.get("positions") or {}
    for code in data.get("portfolio_pool") or []:
        pos = positions.get(code) or {}
        print(
            f"  {code} {pos.get('name')}  "
            f"{pos.get('qty')}股 @ {pos.get('cost')}  "
            f"买时 {pos.get('buy_time')}  "
            f"可用 {pos.get('available')}  "
            f"tp_stage={pos.get('tp_stage')}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用 pool_1m 末日持仓覆盖本地 holdings.json")
    ap.add_argument("--tag", default=DEFAULT_TAG, help="回测产物后缀，默认 _week202609")
    ap.add_argument(
        "--pool-dir",
        default=str(DEFAULT_POOL_DIR),
        help="回测产物目录（默认 strategy16_core_leader）",
    )
    ap.add_argument("--out", default=str(HOLDINGS_FILE), help="写出路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写盘")
    args = ap.parse_args(argv)
    data = seed_holdings(
        pool_dir=Path(args.pool_dir),
        tag=args.tag,
        out_path=Path(args.out),
        dry_run=bool(args.dry_run),
    )
    _print_summary(data)
    if args.dry_run:
        print("dry-run：未写入 holdings.json")
    else:
        print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
