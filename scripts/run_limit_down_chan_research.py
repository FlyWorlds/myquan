"""跌停开板缠论因子完整回测、调参与验证执行脚本。

执行流程：
1. 数据集：全A主板非ST股票日线
2. 阶段划分：
   - 2020-2023 (2020-01-01 ~ 2022-12-31): 初始回测 (窗口=1个月/30天)
   - 2023-2025 (2023-01-01 ~ 2024-12-31): 调参对比 (窗口=1个月 vs 2个月 vs 3个月)
   - 2025-至今 (2025-01-01 ~ 2026-11-06): 样本外验证 (最优参数)
3. 分别分析持有 d1 到 d5 交易日收盘收益表现
"""

from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

import pandas as pd

# 加入项目路径
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.limit_down_chan_factor import (
    LimitDownChanConfig,
    batch_run_factor,
    evaluate_summary,
    is_mainboard_code,
)


def run_research():
    print("=" * 70)
    print("跌停板开板买入 + 缠论日线结构因子 全市场主板回测与验证")
    print("=" * 70)

    # 1. 扫描数据目录中的主板股票
    all_files = glob.glob(str(ROOT / "data_cache" / "*_daily_qfq.parquet"))
    mainboard_files = [
        f for f in all_files if is_mainboard_code(Path(f).stem.replace("_daily_qfq", ""))
    ]
    print(f"找到全A主板标的数量: {len(mainboard_files)}")

    # 2. 调参设定：对比 1个月 (30天)、2个月 (60天)、3个月 (90天)
    windows = {
        "1个月(30天)": 30,
        "2个月(60天)": 60,
        "3个月(90天)": 90,
    }

    results_by_param = {}
    
    # 我们运行不同窗口下的全量信号扫描
    for label, w_days in windows.items():
        print(f"\n>>> 正在运行参数: 窗口 = {label} (收盘价买入口径) ...")
        t0 = time.time()
        cfg = LimitDownChanConfig(window_days=w_days, buy_price_type="close")
        df_events = batch_run_factor(mainboard_files, cfg, verbose=False)
        elapsed = time.time() - t0
        print(f"    处理耗时: {elapsed:.2f}秒，共捕获信号事件: {len(df_events)} 个")

        # 划分三个区间
        # 2020-2023 回测期
        stats_train = evaluate_summary(df_events, "2020-01-01", "2022-12-31")
        # 2023-2025 调参期
        stats_tune = evaluate_summary(df_events, "2023-01-01", "2024-12-31")
        # 2025-至今 验证期
        stats_test = evaluate_summary(df_events, "2025-01-01", "2026-12-31")

        results_by_param[label] = {
            "df_events": df_events,
            "train_2020_2023": stats_train,
            "tune_2023_2025": stats_tune,
            "test_2025_now": stats_test,
        }

    # 另外测试跌停价撬板买入口径 (用于对比执行方式)
    print("\n>>> 正在运行对比组: 窗口 = 1个月(30天) (跌停价撬板买入口径) ...")
    cfg_ld = LimitDownChanConfig(window_days=30, buy_price_type="limit_down")
    df_events_ld = batch_run_factor(mainboard_files, cfg_ld, verbose=False)
    results_by_param["1个月(30天)_跌停价买入"] = {
        "df_events": df_events_ld,
        "train_2020_2023": evaluate_summary(df_events_ld, "2020-01-01", "2022-12-31"),
        "tune_2023_2025": evaluate_summary(df_events_ld, "2023-01-01", "2024-12-31"),
        "test_2025_now": evaluate_summary(df_events_ld, "2025-01-01", "2026-12-31"),
    }

    # 输出表格与报告
    print("\n" + "=" * 70)
    print("【阶段一：2020-2023 样本内回测分析 (2020-01-01 ~ 2022-12-31)】")
    print("=" * 70)
    _print_table("基准参数: 1个月(30天) 收盘买入", results_by_param["1个月(30天)"]["train_2020_2023"])
    _print_table("对比参数: 1个月(30天) 跌停价买入", results_by_param["1个月(30天)_跌停价买入"]["train_2020_2023"])

    print("\n" + "=" * 70)
    print("【阶段二：2023-2025 调参区间对比 (2023-01-01 ~ 2024-12-31)】")
    print("=" * 70)
    for label in ["1个月(30天)", "2个月(60天)", "3个月(90天)"]:
        _print_table(f"调参窗口: {label}", results_by_param[label]["tune_2023_2025"])

    print("\n" + "=" * 70)
    print("【阶段三：2025-至今 样本外验证 (2025-01-01 ~ 2026-11-06)】")
    print("=" * 70)
    for label in ["1个月(30天)", "2个月(60天)", "3个月(90天)"]:
        _print_table(f"验证窗口: {label}", results_by_param[label]["test_2025_now"])

    # 保存信号详情到文件供后续查阅
    out_dir = ROOT / "reports" / "limit_down_chan"
    out_dir.mkdir(parents=True, exist_ok=True)
    for label, item in results_by_param.items():
        fname = label.replace("(", "_").replace(")", "").replace("/", "_")
        csv_path = out_dir / f"signals_{fname}.csv"
        item["df_events"].to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"已保存信号明细至: {csv_path}")

    # 保存汇总 JSON
    summary_data = {}
    for label, item in results_by_param.items():
        summary_data[label] = {
            "train_2020_2023": item["train_2020_2023"],
            "tune_2023_2025": item["tune_2023_2025"],
            "test_2025_now": item["test_2025_now"],
        }
    with open(out_dir / "summary_metrics.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    print("\n全流程研究完成！")


def _print_table(title: str, stats_dict: dict[str, dict[str, Any]]):
    print(f"\n--- {title} ---")
    header = f"{'持有期':<8}{'交易数':<8}{'胜率(%)':<10}{'均收益(%)':<12}{'中位数(%)':<12}{'盈亏比':<10}{'最大赢(%)':<12}{'最大亏(%)':<12}"
    print(header)
    print("-" * 80)
    for k in ["d1", "d2", "d3", "d4", "d5"]:
        st = stats_dict.get(k, {})
        line = (
            f"{k:<8}"
            f"{st.get('count', 0):<8}"
            f"{st.get('win_rate_pct', 0.0):<10.2f}"
            f"{st.get('mean_ret_pct', 0.0):<12.2f}"
            f"{st.get('median_ret_pct', 0.0):<12.2f}"
            f"{st.get('profit_factor', 0.0):<10.2f}"
            f"{st.get('max_win_pct', 0.0):<12.2f}"
            f"{st.get('max_loss_pct', 0.0):<12.2f}"
        )
        print(line)


if __name__ == "__main__":
    run_research()
