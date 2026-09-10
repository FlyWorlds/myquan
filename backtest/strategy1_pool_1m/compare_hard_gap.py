"""低开破硬保护：立刻卖 vs 开盘再下杀 1% 才卖（全池 1m 一周对照）。

A) immediate（生产）：次日开盘已 ≤ 成本×(1−2.5%) → 开盘价 hard_from_cost
B) open_dump_1pct（研究）：同上低开时不立刻砍，等从开盘再下杀 1% 才卖（hard_open_dump）

「池子所有票进」：槽位=池大小、当日最多买=池大小、每槽等权 1/N，避免三槽筛掉对照差异。

用法：
  PYTHONPATH=. python backtest/strategy1_pool_1m/compare_hard_gap.py --pool strategy16 --days 7
  PYTHONPATH=. python backtest/strategy1_pool_1m/compare_hard_gap.py --pool strategy1 --days 7

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import DEFAULT_ACCOUNT_TOTAL  # noqa: E402
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_HARD_GAP_DUMP_PCT,
    DEFAULT_PULLBACK_PCT,
    HARD_GAP_IMMEDIATE,
    HARD_GAP_OPEN_DUMP,
)

from backtest.strategy1_pool_1m.run import (  # noqa: E402
    POOL_STRATEGY1,
    POOL_STRATEGY16,
    _daily,
    _load_pool,
    _minutes,
    _sina,
    simulate_portfolio_3slots,
)

OUT_S1 = Path(__file__).resolve().parent
OUT_S16 = _ROOT / "backtest" / "strategy16_core_leader"


def _summarize(port: dict[str, Any]) -> dict[str, Any]:
    ps = port.get("summary") or {}
    trades = list(port.get("trades") or [])
    sells = [t for t in trades if t.get("side") == "sell"]
    reasons = Counter(str(t.get("exit_reason") or "") for t in sells)
    hard_gap = [
        t
        for t in sells
        if str(t.get("exit_reason") or "") in ("hard_from_cost", "hard_open_dump")
    ]
    return {
        "return_pct": ps.get("return_pct"),
        "max_dd_pct": ps.get("max_dd_pct"),
        "final_equity": ps.get("final_equity"),
        "n_buys": ps.get("n_buys"),
        "n_sells": ps.get("n_sells"),
        "n_closed": ps.get("n_closed"),
        "avg_closed_pnl_pct": ps.get("avg_closed_pnl_pct"),
        "n_open": ps.get("n_open"),
        "calendar": ps.get("calendar") or [],
        "exit_reasons": dict(reasons),
        "n_hard_gap_exits": len(hard_gap),
        "hard_gap_avg_pnl_pct": (
            round(
                sum(float(t.get("pnl_pct") or 0) for t in hard_gap) / len(hard_gap) * 100.0,
                2,
            )
            if hard_gap
            else None
        ),
        "hard_gap_trades": [
            {
                "ts": t.get("ts"),
                "code": t.get("code"),
                "name": t.get("name"),
                "px": t.get("px"),
                "pnl_pct": t.get("pnl_pct"),
                "exit_reason": t.get("exit_reason"),
            }
            for t in hard_gap
        ],
    }


def run(
    *,
    pool: str = POOL_STRATEGY16,
    days: int = 7,
    source: str = "auto",
    refresh: bool = False,
    codes: list[str] | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    pool_id = str(pool or POOL_STRATEGY16).strip().lower()
    if pool_id in ("s16", "core_leader"):
        pool_id = POOL_STRATEGY16
    pool_rows = _load_pool(pool_id)
    want = {str(c).zfill(6) for c in (codes or []) if str(c).strip()}
    if want:
        pool_rows = [
            w
            for w in pool_rows
            if str(w.get("code") or "").zfill(6) in want
        ]
        missing = want - {str(w.get("code") or "").zfill(6) for w in pool_rows}
        if missing:
            # 池外手工补入（天通/凯盛一般已在池内）
            from holdingStocks.watch_config import meta_for_code, load_strategy16_thr_map

            thrs = load_strategy16_thr_map()
            for code in sorted(missing):
                item = dict(meta_for_code(code, {"positions": []}))
                thr = thrs.get(code)
                if thr is not None:
                    item["entry_pct"] = float(thr)
                    item["pct"] = float(thr)
                    item["stop_pct"] = float(DEFAULT_PULLBACK_PCT)
                pool_rows.append(item)
    n = len(pool_rows)
    if n <= 0:
        raise SystemExit("池为空（检查 --codes）")
    out_dir = OUT_S16 if pool_id == POOL_STRATEGY16 else OUT_S1
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = str(tag or "").strip()
    if not stem and want:
        stem = "codes_" + "_".join(sorted(want))
    suffix = f"_{stem}" if stem else ""

    print(
        f"加载 {pool_id} {n} 只"
        + (f"（筛选 {','.join(sorted(want))}）" if want else "")
        + f" · 近 {days} 日 1m · 等权进场 …",
        flush=True,
    )
    stock_payload: list[dict[str, Any]] = []
    for w in pool_rows:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or DEFAULT_ENTRY_PCT)
        sp = float(w.get("stop_pct") or w.get("pct") or DEFAULT_PULLBACK_PCT)
        if pool_id == POOL_STRATEGY16:
            sp = float(DEFAULT_PULLBACK_PCT)
        print(f"· {code} {name} 开盘±{ep*100:.1f}%", flush=True)
        daily = _daily(sina, lookback_cal_days=90)
        mins = _minutes(sina, refresh=refresh, days=int(days), source=source)
        stock_payload.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": sp,
                "daily": daily,
                "minutes": mins,
            }
        )

    slot_w = 1.0 / float(n)
    policies = [
        (
            "immediate",
            "低开已破硬保护→开盘立刻卖（生产）",
            HARD_GAP_IMMEDIATE,
            DEFAULT_HARD_GAP_DUMP_PCT,
        ),
        (
            "open_dump_1pct",
            "低开已破硬保护→再下杀1%才卖（研究）",
            HARD_GAP_OPEN_DUMP,
            0.01,
        ),
    ]
    results: dict[str, Any] = {}
    for key, label, mode, dump in policies:
        print(f"\n组合回放 · {key} …", flush=True)
        port = simulate_portfolio_3slots(
            stock_payload,
            days=int(days),
            max_slots=int(n),
            max_buys_per_day=int(n),
            initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
            slot_weight=float(slot_w),
            hard_gap_mode=mode,
            hard_gap_dump_pct=float(dump),
        )
        results[key] = {
            "label": label,
            "hard_gap_mode": mode,
            "hard_gap_dump_pct": float(dump),
            "portfolio": _summarize(port),
            "trades": port.get("trades") or [],
            "equity": port.get("equity") or [],
            "open_positions": port.get("open_positions") or [],
        }

    a = results["immediate"]["portfolio"]
    b = results["open_dump_1pct"]["portfolio"]
    delta_ret = None
    if a.get("return_pct") is not None and b.get("return_pct") is not None:
        delta_ret = round(float(b["return_pct"]) - float(a["return_pct"]), 2)
    delta_dd = None
    if a.get("max_dd_pct") is not None and b.get("max_dd_pct") is not None:
        delta_dd = round(float(b["max_dd_pct"]) - float(a["max_dd_pct"]), 2)

    summary = {
        "pool": pool_id,
        "codes": [str(s["code"]) for s in stock_payload],
        "n_pool": n,
        "days": int(days),
        "slot_weight": slot_w,
        "max_slots": n,
        "max_buys_per_day": n,
        "note": "等权进场；仅改低开已破硬保护时的卖法",
        "delta_return_pct_open_dump_minus_immediate": delta_ret,
        "delta_max_dd_pct_open_dump_minus_immediate": delta_dd,
        "policies": {k: v["portfolio"] for k, v in results.items()},
        "disclaimer": "研究用途，非投资建议；1m 近数日；未计费/滑点。",
    }

    out_json = out_dir / f"COMPARE_HARD_GAP{suffix}.json"
    out_md = out_dir / f"COMPARE_HARD_GAP{suffix}.md"
    out_json.write_text(
        json.dumps(
            {"summary": summary, "results": results},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    names = "、".join(f"{s['code']}{s['name']}" for s in stock_payload)
    title_scope = f"{names}" if want or n <= 5 else f"{pool_id} 全池等权"
    cal = a.get("calendar") or b.get("calendar") or []
    lines = [
        f"# 低开硬保护对照 · {title_scope} · 近 {days} 日 1m",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 设定",
        "",
        f"- 标的：**{n}** 只等权进场（槽={n}，日最多买={n}，每槽等权 {slot_w*100:.2f}%）：{names}",
        f"- 窗：{', '.join(str(x) for x in cal) if cal else '—'}",
        "- **A immediate（生产）**：次日开盘已 ≤ 成本×(1−2.5%) → 开盘价 `hard_from_cost`",
        "- **B open_dump_1pct（研究）**：同上低开时不立刻砍，等从开盘再下杀 **1%** → `hard_open_dump`",
        "- 其余规则同因子26（T1 峰值回落 2.5%、中段止盈、阶梯等不变）",
        "",
        "## 组合摘要",
        "",
        "| 口径 | 期末收益% | 最大回撤% | 买/卖 | 已平仓均收益% | 硬保护类卖出 | 硬保护类均盈亏% |",
        "|------|-----------|-----------|-------|---------------|--------------|-----------------|",
    ]
    for key in ("immediate", "open_dump_1pct"):
        p = results[key]["portfolio"]
        lines.append(
            f"| {key} | {p.get('return_pct')} | {p.get('max_dd_pct')} | "
            f"{p.get('n_buys')}/{p.get('n_sells')} | {p.get('avg_closed_pnl_pct')} | "
            f"{p.get('n_hard_gap_exits')} | {p.get('hard_gap_avg_pnl_pct')} |"
        )
    lines.extend(
        [
            "",
            f"- **B−A 收益差**：{delta_ret if delta_ret is not None else '—'} 个百分点",
            f"- **B−A 回撤差**：{delta_dd if delta_dd is not None else '—'} 个百分点（回撤为负，差值为正表示回撤更深）",
            "",
            "## 卖出原因分布",
            "",
        ]
    )
    for key in ("immediate", "open_dump_1pct"):
        p = results[key]["portfolio"]
        lines.append(f"### {key}")
        lines.append("")
        rs = p.get("exit_reasons") or {}
        if not rs:
            lines.append("（无卖出）")
        else:
            lines.append("| 原因 | 次数 |")
            lines.append("|------|------|")
            for r, c in sorted(rs.items(), key=lambda x: (-x[1], x[0])):
                lines.append(f"| `{r}` | {c} |")
        lines.append("")

    lines.extend(["## 硬保护类成交明细", ""])
    for key in ("immediate", "open_dump_1pct"):
        p = results[key]["portfolio"]
        lines.append(f"### {key}")
        lines.append("")
        rows = p.get("hard_gap_trades") or []
        if not rows:
            lines.append("（无）")
            lines.append("")
            continue
        lines.append("| 时间 | 代码 | 名称 | 价 | 盈亏% | 原因 |")
        lines.append("|------|------|------|----|-------|------|")
        for t in rows:
            pp = t.get("pnl_pct")
            pp_s = "" if pp is None else f"{float(pp)*100:.2f}"
            lines.append(
                f"| {t.get('ts')} | {t.get('code')} | {t.get('name')} | {t.get('px')} | "
                f"{pp_s} | {t.get('exit_reason')} |"
            )
        lines.append("")

    lines.extend(["## 全部成交（对照）", ""])
    for key in ("immediate", "open_dump_1pct"):
        lines.append(f"### {key}")
        lines.append("")
        lines.append("| 时间 | 方向 | 代码 | 名称 | 价 | 股 | 盈亏% | 备注 |")
        lines.append("|------|------|------|------|----|----|-------|------|")
        for t in results[key].get("trades") or []:
            pp = t.get("pnl_pct")
            pp_s = "" if pp is None else f"{float(pp)*100:.2f}"
            note = t.get("exit_reason") or t.get("kind") or t.get("source") or ""
            lines.append(
                f"| {t.get('ts')} | {t.get('side')} | {t.get('code')} | {t.get('name')} | "
                f"{t.get('px')} | {t.get('shares')} | {pp_s} | {note} |"
            )
        if not results[key].get("trades"):
            lines.append("| — | — | — | — | — | — | — | 无成交 |")
        lines.append("")

    lines.extend(
        [
            f"产物：`{out_json.name}` / `{out_md.name}`",
            "",
            summary["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n写入 {out_md}")
    print(f"写入 {out_json}")
    print(
        f"immediate {a.get('return_pct')}% / dd {a.get('max_dd_pct')}%  vs  "
        f"open_dump_1pct {b.get('return_pct')}% / dd {b.get('max_dd_pct')}%  "
        f"Δret={delta_ret}"
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="低开硬保护：立刻卖 vs 开盘下杀1%")
    ap.add_argument("--pool", default=POOL_STRATEGY16, choices=(POOL_STRATEGY1, POOL_STRATEGY16))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--source", default="auto", choices=("auto", "panda", "ak"))
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument(
        "--codes",
        default=None,
        help="只回测这些代码，逗号分隔，如 600330,600552（天通/凯盛）",
    )
    ap.add_argument("--tag", default=None, help="产物后缀；筛选代码时默认用 codes_xxx")
    args = ap.parse_args()
    code_list = None
    if args.codes:
        code_list = [c.strip() for c in str(args.codes).split(",") if c.strip()]
    run(
        pool=str(args.pool),
        days=int(args.days),
        source=str(args.source),
        refresh=bool(args.refresh),
        codes=code_list,
        tag=args.tag,
    )


if __name__ == "__main__":
    main()
