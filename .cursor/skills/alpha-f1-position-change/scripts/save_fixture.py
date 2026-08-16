"""联网拉取一份固定持仓与价格数据样本，保存为 Parquet fixture 供离线 validate 使用

用法：
    export PANDA_DATA_USERNAME=...
    export PANDA_DATA_PASSWORD=...
    python save_fixture.py

生成的文件：
    fixtures/sample_positions.parquet  — 持仓数据（多品种 × 多日 × long/short）
    fixtures/sample_prices.parquet     — 价格数据（用于 IC 稳定性检查）

后续运行 validate.py 时设置 PANDA_DATA_OFFLINE=1 即可使用 fixtures，无需联网。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor import load_position_data, load_price_data


FIXTURE_DIR = Path(__file__).parent / "fixtures"
POSITIONS_FIXTURE = FIXTURE_DIR / "sample_positions.parquet"
PRICES_FIXTURE = FIXTURE_DIR / "sample_prices.parquet"


def main() -> None:
    """拉取数据并保存为 fixture"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Step 1/2: 拉取持仓数据")
    print("=" * 60)
    positions = load_position_data()
    print(f"[OK] 持仓数据 {len(positions)} 行，涉及品种 {positions['underlying_symbol'].nunique()} 个")

    print()
    print("=" * 60)
    print("Step 2/2: 拉取价格数据")
    print("=" * 60)
    symbols = positions["underlying_symbol"].unique().tolist()
    dates = positions["date"].astype(str).unique()
    start_date_8 = min(dates)
    end_date_8 = max(dates)
    start_date = f"{start_date_8[:4]}-{start_date_8[4:6]}-{start_date_8[6:8]}"
    end_date = f"{end_date_8[:4]}-{end_date_8[4:6]}-{end_date_8[6:8]}"

    try:
        prices = load_price_data(symbols=symbols, start_date=start_date, end_date=end_date)
        print(f"[OK] 价格数据 {len(prices)} 行")
    except Exception as e:
        print(f"[WARN] 价格数据拉取失败: {e}")
        print("[WARN] 仅保存持仓 fixture，离线模式 check_ic_stability 将被跳过")
        prices = None

    # 保存 fixture
    positions.to_parquet(POSITIONS_FIXTURE, index=False)
    print(f"\n[SAVE] {POSITIONS_FIXTURE} ({POSITIONS_FIXTURE.stat().st_size / 1024:.1f} KB)")

    if prices is not None and not prices.empty:
        prices.to_parquet(PRICES_FIXTURE, index=False)
        print(f"[SAVE] {PRICES_FIXTURE} ({PRICES_FIXTURE.stat().st_size / 1024:.1f} KB)")

    print()
    print("=" * 60)
    print("Fixture 生成完成。后续离线验证：")
    print("  export PANDA_DATA_OFFLINE=1")
    print("  python validate.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
