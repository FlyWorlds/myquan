"""刷新策略十六·核心龙头池（滚动近 3 个月）。

用法：
  python strategy/run_core_leader_pool.py
  python strategy/run_core_leader_pool.py --horizon-months 3 --max-concepts 40 --per-concept 2 --target-pool 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.core_leader_universe import (  # noqa: E402
    DEFAULT_MAX_CONCEPTS,
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_PER_CONCEPT,
    DEFAULT_PICKS_PATH,
    DEFAULT_PRICE_MAX,
    DEFAULT_TARGET_POOL,
    build_quarter_pool,
    save_picks,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="刷新核心龙头选股池（滚动近3个月）")
    p.add_argument("--horizon-months", type=int, default=DEFAULT_HORIZON_MONTHS)
    p.add_argument("--max-concepts", type=int, default=DEFAULT_MAX_CONCEPTS)
    p.add_argument("--per-concept", type=int, default=DEFAULT_PER_CONCEPT)
    p.add_argument("--target-pool", type=int, default=DEFAULT_TARGET_POOL)
    p.add_argument("--price-max", type=float, default=DEFAULT_PRICE_MAX)
    p.add_argument("--include-st", action="store_true", help="不排除 ST / *ST")
    p.add_argument("--include-chinext", action="store_true", help="不排除创业板 300/301")
    p.add_argument("--include-star", action="store_true", help="不排除科创板 688/689")
    p.add_argument("--include-bse", action="store_true", help="不排除北交所")
    p.add_argument("--out", type=Path, default=DEFAULT_PICKS_PATH)
    args = p.parse_args(argv)

    payload = build_quarter_pool(
        max_concepts=int(args.max_concepts),
        per_concept=int(args.per_concept),
        target_pool=int(args.target_pool),
        price_max=float(args.price_max),
        horizon_months=int(args.horizon_months),
        exclude_st=not bool(args.include_st),
        exclude_chinext=not bool(args.include_chinext),
        exclude_star=not bool(args.include_star),
        exclude_bse=not bool(args.include_bse),
        fetch=True,
    )
    path = save_picks(payload, args.out)
    print(
        f"近3个月 {payload.get('label')}  有效至 {payload.get('valid_until')}  "
        f"扫概念 {payload.get('n_concepts')}  "
        f"入池概念 {payload.get('n_used_concepts')}  票 {payload.get('n_picks')}"
    )
    print(f"已写 {path}")
    if payload.get("errors"):
        for err in payload["errors"]:
            print(f"注意: {err}")
    for it in payload.get("picks") or []:
        print(
            f"  {it.get('rank'):>2} {it.get('code')} {it.get('name') or ''}  "
            f"{it.get('concept')}  现价 {it.get('price')}  涨跌 {it.get('chg_pct')}"
        )
    return 0 if payload.get("n_picks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
