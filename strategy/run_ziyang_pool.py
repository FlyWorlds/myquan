"""刷新策略十七·紫阳真君池（近 3 个月紫阳东路龙虎榜成交）。"""

from __future__ import annotations

from strategy.ziyang_universe import DEFAULT_PICKS_PATH, refresh_pool


def main() -> None:
    payload = refresh_pool()
    n = int(payload.get("n_picks") or 0)
    print(f"紫阳真君池 {n} 只 → {DEFAULT_PICKS_PATH}")
    print(f"窗口 {payload.get('window_start')} ~ {payload.get('window_end')}")
    print(f"席位 {payload.get('seat_name')} ({payload.get('seat_code')})")


if __name__ == "__main__":
    main()
