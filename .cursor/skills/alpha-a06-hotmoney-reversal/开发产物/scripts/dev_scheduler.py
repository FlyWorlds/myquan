from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from factor import DEFAULT_DATA_VERSION
from update_production import DEFAULT_OUTPUT, _compact_date, _three_year_start, update_production


ALPHA_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ALPHA_ROOT / "生产产物" / "logs"
LOG_PATH = LOG_DIR / "a06_dev_scheduler.log"


def _display_path(path: str | Path) -> str:
    try:
        return os.path.relpath(Path(path).resolve(), Path.cwd().resolve())
    except ValueError:
        return Path(path).name


def _check_credentials() -> None:
    if not os.getenv("PANDA_DATA_USERNAME") or not os.getenv("PANDA_DATA_PASSWORD"):
        raise RuntimeError("请先在当前开发终端设置 PANDA_DATA_USERNAME 和 PANDA_DATA_PASSWORD")


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("--time 必须使用 HH:MM 格式，例如 18:30") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("--time 必须使用合法本地时间")
    return hour, minute


def _next_run_time(now: datetime, hhmm: str) -> datetime:
    hour, minute = _parse_hhmm(hhmm)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_update(args: argparse.Namespace) -> None:
    _check_credentials()
    end_date = _compact_date(args.end_date or datetime.now().strftime("%Y%m%d"))
    bootstrap_start_date = args.bootstrap_start_date or _three_year_start(end_date)
    result = update_production(
        output_path=Path(args.output),
        end_date=end_date,
        bootstrap_start_date=bootstrap_start_date,
        lookback_days=args.lookback_days,
        quality_lookback_days=args.quality_lookback_days,
        full_refresh=args.full_refresh,
        data_version=args.data_version,
    )
    _log(
        "update ok "
        f"rows={len(result)} "
        f"date_min={result['trade_date'].min()} "
        f"date_max={result['trade_date'].max()} "
        f"output={_display_path(args.output)}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="开发内直接定时：每日收盘后更新 A06 生产数据库")
    parser.add_argument("--time", default="18:30", help="每天触发时间，本机本地时间，默认 18:30")
    parser.add_argument("--run-once", action="store_true", help="立即执行一次后退出，用于开发验证")
    parser.add_argument("--end-date", default=None, help="覆盖更新截止日期；常驻模式默认使用执行当天")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--bootstrap-start-date", default=None, help="首次全量生成起点；默认 end-date 往前近三年")
    parser.add_argument("--lookback-days", type=int, default=10, help="增量更新回看重算天数")
    parser.add_argument("--quality-lookback-days", type=int, default=260, help="增量更新时额外拉取席位质量历史窗口")
    parser.add_argument("--full-refresh", action="store_true", help="全量刷新近三年数据库")
    parser.add_argument("--data-version", default=DEFAULT_DATA_VERSION)
    parser.add_argument("--retry-seconds", type=int, default=300, help="更新失败后的等待重试秒数")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.run_once:
        run_update(args)
        return

    _check_credentials()
    _parse_hhmm(args.time)
    _log(f"dev scheduler started time={args.time} output={_display_path(args.output)}")
    while True:
        now = datetime.now()
        next_run = _next_run_time(now, args.time)
        sleep_seconds = max(1, int((next_run - now).total_seconds()))
        _log(f"next run at {next_run.isoformat(timespec='seconds')}")
        time.sleep(sleep_seconds)
        while True:
            try:
                args.end_date = None
                args.full_refresh = False
                run_update(args)
                break
            except Exception as exc:
                _log(f"update failed: {exc}; retry in {args.retry_seconds}s")
                time.sleep(max(30, args.retry_seconds))


if __name__ == "__main__":
    main()
