"""凯盛科技 · 策略五 / 因子3 动量 单因子回测。"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import replace
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG, get_strategy  # noqa: E402
from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS  # noqa: E402

_WINDOW_START = {
    "2020+": "20200101",
    "2022+": "20220101",
    "2023+": "20230101",
    "2023-07+": "20230701",
    "2024+": "20240101",
}


def _load_best() -> tuple[str, dict, str]:
    p = Path(__file__).with_name("_momentum_mine_best.txt")
    kind = DEFAULT_KIND
    params = dict(DEFAULT_PARAMS)
    window = "2022+"
    if not p.exists():
        return kind, params, window
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("kind="):
            kind = line.split("=", 1)[1].strip()
        elif line.startswith("params="):
            params = ast.literal_eval(line.split("=", 1)[1].strip())
        elif line.startswith("window="):
            window = line.split("=", 1)[1].strip()
    return kind, params, window


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="凯盛 因子3·动量（策略五）")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--kind", default=None)
    parser.add_argument("--params", default=None, help="Python dict 字面量")
    parser.add_argument(
        "--from",
        dest="start_date",
        default=None,
        help="起始日 YYYYMMDD；默认用挖参窗口",
    )
    args = parser.parse_args(argv)

    if args.rules:
        print(get_strategy("strategy5").print_rules())
        return

    kind, params, window = _load_best()
    if args.kind:
        kind = args.kind
    if args.params:
        params = ast.literal_eval(args.params)
    start = args.start_date or _WINDOW_START.get(window, "20230101")

    cfg = replace(
        KAICHENG,
        start_date=start,
        mom_kind=kind,
        mom_params=params,
        report_path=Path(__file__).resolve().parent / "凯盛科技_因子3动量_report.html",
    )
    print(
        f"运行 因子3·动量 kind={kind} params={params} "
        f"start={start} (mine_window={window})"
    )
    # 单票动量走 run_momentum；策略五默认是截面组合
    from strategy.runner import run_momentum

    run_momentum(
        cfg,
        show_report=not args.no_open,
        force_daily_refresh=bool(args.force_refresh),
    )


if __name__ == "__main__":
    main()
