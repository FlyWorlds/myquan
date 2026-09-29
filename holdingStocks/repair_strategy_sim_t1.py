"""修复 Strategy Simulator 旧版无 T+1 造成的账本污染（同日买卖 / 逐 tick 翻转）。

用法（先 dry-run 看结果；--apply 前须停掉盯盘，否则进程内存态会覆盖写回）::

    python repair_strategy_sim_t1.py
    python repair_strategy_sim_t1.py --apply

受影响账本 = 事件中出现同一交易日 BUY→SELL 的 (strategy_id, symbol)。
- 原账本已 bootstrap：按**原 bootstrap_cutoff** 重跑同一段日线 bootstrap（与生产同参数、
  同 T+1，历史段不变），再按新规则重放 cutoff 之后的 live 事件——只修被污染的 live 段。
- 未 bootstrap（账本本就从 live 起步）：空仓起按新规则重放全部事件。
被拒事件移入 strategy_signal_events.voided.json（保留审计），不直接删除。
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_HOLD = Path(__file__).resolve().parent
_ROOT = _HOLD.parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import strategy_simulator as sim  # noqa: E402

VOIDED_FILE = _HOLD / "strategy_signal_events.voided.json"


def _session(ts: Any) -> str:
    return str(ts or "")[:10]


def _affected_keys(events: list[dict[str, Any]]) -> set[tuple[str, str]]:
    by: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for e in events:
        by[(str(e["strategy_id"]), str(e["symbol"]))].append(e)
    out: set[tuple[str, str]] = set()
    for k, lst in by.items():
        lst.sort(key=lambda e: str(e["trigger_time"]))
        for a, b in zip(lst, lst[1:]):
            if a["side"] == "BUY" and b["side"] == "SELL" and _session(
                a["trigger_time"]
            ) == _session(b["trigger_time"]):
                out.add(k)
                break
    return out


def _replay(
    book: dict[str, Any], evs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    voided: list[dict[str, Any]] = []
    for e in sorted(evs, key=lambda x: str(x["trigger_time"])):
        side = str(e["side"])
        ts = str(e["trigger_time"])
        r = sim.evaluate_live_transition(
            strategy_id=str(e["strategy_id"]),
            symbol=str(e["symbol"]),
            live_last=float(e["trigger_price"]),
            quote_ts=ts,
            buy_level=e.get("buy_level") if side == "BUY" else None,
            sell_level=e.get("sell_level") if side == "SELL" else None,
            allow_entry=side == "BUY",
            reason=str(e.get("reason") or "replay"),
            persist=False,
            force_book=book,
            now=datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S"),
            stale_after=1e12,
        )
        if r["transition"] == side:
            kept.append(e)
        else:
            voided.append({**e, "void_reason": f"t1_repair:{r.get('skipped') or 'state'}"})
    return kept, voided


def _watch_item(code: str) -> dict[str, Any]:
    import index
    from watch_config import meta_for_code

    for w in index._scan_watchlist(full=True):
        if index._code_key(w["code"]) == code:
            return w
    return meta_for_code(code)


def _bootstrap_until(book: dict[str, Any], code: str, cutoff: str) -> str | None:
    import index
    import pandas as pd

    w = _watch_item(code)
    daily = index._watch_daily(w["sina"])
    if daily is not None and not daily.empty:
        d = pd.to_datetime(daily["date"]).dt.tz_localize(None).dt.normalize()
        daily = daily[d <= pd.Timestamp(cutoff)]
    info = sim.bootstrap_book_from_daily_ohlc(
        book,
        daily,
        start_date=str(index.STRATEGY_PNL_START),
        entry_pct=float(index._watch_pct(w)),
        stop_pct=float(index._watch_stop_pct(w)),
        tick=float(index._watch_tick(w)),
        prev_entry_mode=str(w.get("prev_entry_mode") or "yin_or_small_yang"),
        persist=False,
    )
    return info.get("cutoff")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="写回（默认 dry-run）")
    args = ap.parse_args()

    import index
    from watch_config import STRATEGY_ID

    if args.apply and index._read_watch_lock():
        raise SystemExit("盯盘仍在运行：先停掉（python start_watch.py --stop）再 --apply")

    today = str(index.trading_session_date())
    raw_ev = json.loads(sim.EVENTS_FILE.read_text(encoding="utf-8"))
    events: list[dict[str, Any]] = list(raw_ev.get("events") or [])
    state = json.loads(sim.STATE_FILE.read_text(encoding="utf-8"))
    positions: dict[str, Any] = state.setdefault("positions", {})

    affected = _affected_keys(events)
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    untouched: list[dict[str, Any]] = []
    for e in events:
        k = (str(e["strategy_id"]), str(e["symbol"]))
        (by_key[k] if k in affected else untouched).append(e)

    kept_all: list[dict[str, Any]] = []
    voided_all: list[dict[str, Any]] = []
    print(f"session={today} · 事件 {len(events)} · 受影响账本 {len(affected)}")
    for sid, code in sorted(affected):
        key = f"{sid}:{code}"
        old = positions.get(key) or {}
        book = sim.empty_book(strategy_id=sid, symbol=code)
        evs = by_key[(sid, code)]
        prior: list[dict[str, Any]] = []
        old_cutoff = str(old.get("bootstrap_cutoff") or "")
        if sid == str(STRATEGY_ID) and old.get("bootstrapped") and old_cutoff:
            cutoff = _bootstrap_until(book, code, old_cutoff)
            after = [e for e in evs if cutoff is None or _session(e["trigger_time"]) > cutoff]
            prior = [
                {**e, "void_reason": f"t1_repair:superseded_by_bootstrap<={cutoff}"}
                for e in evs
                if e not in after
            ]
            evs = after
        kept, voided = _replay(book, evs)
        voided = prior + voided
        kept_all.extend(kept)
        voided_all.extend(voided)
        positions[key] = book
        print(
            f"  {key}: {old.get('state')} 累计{old.get('cumulative_return_pct')}% "
            f"笔数{old.get('trades')} → {book['state']} 累计{book['cumulative_return_pct']}% "
            f"笔数{book['trades']} 入场{book.get('entry_time')}@{book.get('entry_price')} "
            f"· 保留事件{len(kept)} 作废{len(voided)}"
        )

    print(f"合计：保留 {len(untouched) + len(kept_all)} · 作废 {len(voided_all)}")
    if not args.apply:
        print("dry-run：未写文件。停盯盘后加 --apply 写回。")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in (sim.STATE_FILE, sim.EVENTS_FILE):
        shutil.copy2(f, f.with_name(f"{f.name}.bak_{stamp}"))
    raw_ev["events"] = sorted(untouched + kept_all, key=lambda e: str(e["trigger_time"]))
    raw_ev["updated_at"] = sim._now_str()
    sim.EVENTS_FILE.write_text(json.dumps(raw_ev, ensure_ascii=False, indent=2), encoding="utf-8")
    prev_void: list[dict[str, Any]] = []
    if VOIDED_FILE.is_file():
        prev_void = list(json.loads(VOIDED_FILE.read_text(encoding="utf-8")).get("events") or [])
    VOIDED_FILE.write_text(
        json.dumps(
            {"updated_at": sim._now_str(), "events": prev_void + voided_all},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sim.save_state(state)
    print(f"已写回（备份后缀 .bak_{stamp}）；作废事件 → {VOIDED_FILE.name}")


if __name__ == "__main__":
    main()
