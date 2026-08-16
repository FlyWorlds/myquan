#!/usr/bin/env python3
"""
B11 交易日历初始化脚本

拉取 A股交易日历（今天-3 年 到 今天+1 年）并写入 production/trade.parquet，
作为 build.py 运行时的离线缓存，加速 batch_manage 并避免高频调用 panda_data。

用法：
    python3 scripts/build_calendar.py              # 默认区间与输出路径
    python3 scripts/build_calendar.py --years-back 5 --years-forward 2
    python3 scripts/build_calendar.py --output /tmp/trade.parquet

前置：
    pip install panda_data pyarrow
    export PANDA_USERNAME=<your_username>
    export PANDA_PASSWORD=<your_password>

parquet schema（原样保留 panda_data 返回的列）：
    next_trade_date str, pretrade_date str, exchange str,
    is_trade int64, nature_date int64  # YYYYMMDD 格式
    全部 is_trade == 1（is_trading_day=1 已过滤）
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path


# 默认输出路径：与本 scripts/ 目录并列的 production/trade.parquet
# 本脚本:  <skill_root>/scripts/build_calendar.py
# 目标:    <skill_root>/production/trade.parquet
_DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "production" / "trade.parquet"


def _login():
    """从环境变量登录 panda_data，缺失时抛清晰错误。"""
    try:
        import panda_data
    except ImportError as e:
        raise RuntimeError(
            "需要 panda_data：\n"
            "    pip install panda_data"
        ) from e
    username = os.environ.get("PANDA_USERNAME")
    password = os.environ.get("PANDA_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "需要 PANDA_USERNAME / PANDA_PASSWORD 环境变量：\n"
            "    export PANDA_USERNAME=<your_username>\n"
            "    export PANDA_PASSWORD=<your_password>"
        )
    panda_data.init_token(username=username, password=password)
    return panda_data


def build_calendar(years_back=3, years_forward=1, exchange="SH", output_path=None):
    """
    拉取交易日历并写入 parquet。

    Args:
        years_back: 向前回溯年数（默认 3）
        years_forward: 向后延伸年数（默认 1，含未来已发布的交易日历）
        exchange: 交易所代码（默认 SH，A 股）
        output_path: parquet 输出路径；None 时用默认路径

    Returns:
        dict: {output_path, trade_days_count, date_range, file_size}
    """
    panda_data = _login()

    today = date.today()
    start = today - timedelta(days=365 * years_back)
    end = today + timedelta(days=365 * years_forward)

    print(f"拉取交易日历：{start} .. {end} (exchange={exchange})")

    df = panda_data.get_trade_cal(
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        exchange=exchange,
        is_trading_day=1,
        fields=[],
    )
    if df is None or len(df) == 0:
        raise RuntimeError(f"panda_data.get_trade_cal 返回空结果，检查区间与账户权限")

    output = Path(output_path or _DEFAULT_OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)

    # 用 pyarrow 直接写，避免依赖 pandas.to_parquet 的额外配置
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pandas(df)
    # [H3] 原子写入：先写 .tmp，成功后 os.replace 原子替换目标文件。
    # 中途失败（进程被 kill / 磁盘满 / pyarrow 崩溃）时原 parquet 完整保留，
    # 兑现 SKILL.md 承诺"生成过程会覆盖已有 trade.parquet（原子写入，无中间态）"。
    tmp = output.with_suffix(output.suffix + ".tmp")
    try:
        pq.write_table(table, tmp, compression="snappy")
        os.replace(tmp, output)   # POSIX 保证同一文件系统下的原子替换
    except Exception:
        # 清理可能存在的中间 tmp（不影响原文件）
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise

    file_size = output.stat().st_size
    date_min = int(df["nature_date"].min())
    date_max = int(df["nature_date"].max())
    count = len(df)

    print(f"✅ 写入 {output}")
    print(f"   交易日数: {count}")
    print(f"   日期范围: {date_min} .. {date_max}")
    print(f"   文件大小: {file_size} bytes ({file_size/1024:.1f} KB)")

    return {
        "output_path": str(output),
        "trade_days_count": count,
        "date_range": (date_min, date_max),
        "file_size": file_size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years-back", type=int, default=3, help="向前回溯年数（默认 3）")
    parser.add_argument("--years-forward", type=int, default=1, help="向后延伸年数（默认 1）")
    parser.add_argument("--exchange", type=str, default="SH", help="交易所代码（默认 SH）")
    parser.add_argument("--output", type=str, default=None, help=f"输出 parquet 路径（默认 {_DEFAULT_OUTPUT}）")
    args = parser.parse_args()

    try:
        build_calendar(
            years_back=args.years_back,
            years_forward=args.years_forward,
            exchange=args.exchange,
            output_path=args.output,
        )
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
