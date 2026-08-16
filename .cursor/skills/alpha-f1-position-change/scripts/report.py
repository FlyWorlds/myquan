"""生成 alpha-f1 因子回测 HTML 报告

用法:
    # 离线模式（用 fixtures 数据，无需凭证）
    python scripts/report.py --offline

    # 联网模式（需要 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD）
    python scripts/report.py

    # 自定义输出路径 / 自动打开浏览器
    python scripts/report.py --offline --html-path reports/custom.html --open

输出:
    reports/backtest_result.json — 中间产物，含全部时序数据
    reports/report.html         — 最终 HTML 报告（self-contained，含 base64 内嵌图表）
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import sys
from pathlib import Path

# 兼容 Python embed 版本：把脚本所在目录注入 sys.path，
# 确保 from backtest_report_data / factor / backtest / validate 可解析
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 必须在 import matplotlib.pyplot 之前设置 Agg 后端，避免无 GUI 环境崩溃
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from backtest_report_data import (  # noqa: E402
    _is_offline,
    run_backtest_with_series,
    save_backtest_result,
)


# === CSS 与配色常量 ============================================================

_COLOR_BUY = "#22c55e"      # 绿
_COLOR_SELL = "#ef4444"     # 红
_COLOR_HOLD = "#94a3b8"     # 灰
_COLOR_PRIMARY = "#3b82f6"  # 蓝
_COLOR_WARN = "#f59e0b"     # 橙

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Microsoft YaHei", "Helvetica Neue", sans-serif;
  line-height: 1.6; color: #1f2937; background: #f9fafb;
  max-width: 1200px; margin: 0 auto; padding: 24px;
}
header { padding: 16px 0 24px; border-bottom: 2px solid #e5e7eb; margin-bottom: 24px; }
h1 { font-size: 24px; color: #111827; margin-bottom: 8px; font-weight: 600; }
h2 {
  font-size: 18px; color: #374151; margin: 32px 0 16px;
  padding-left: 12px; border-left: 4px solid #3b82f6;
}
.meta { font-size: 13px; color: #6b7280; }
section { margin-bottom: 8px; }
.cards-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;
}
.card {
  background: white; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-left: 3px solid #3b82f6;
  transition: transform 0.15s;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.card .label {
  font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;
}
.card .value { font-size: 22px; font-weight: 600; color: #111827; margin-top: 4px; }
.card .unit { font-size: 13px; color: #6b7280; font-weight: normal; margin-left: 2px; }
.card.positive { border-left-color: #22c55e; }
.card.positive .value { color: #16a34a; }
.card.negative { border-left-color: #ef4444; }
.card.negative .value { color: #dc2626; }
img {
  max-width: 100%; height: auto; margin: 12px 0; border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08); display: block;
}
.note {
  font-size: 13px; color: #6b7280; margin: 8px 0; padding: 12px;
  background: #f3f4f6; border-radius: 6px; line-height: 1.7;
}
table {
  width: 100%; border-collapse: collapse; background: white; border-radius: 8px;
  overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin: 16px 0;
}
th {
  background: #f3f4f6; padding: 12px; text-align: left; font-size: 13px;
  color: #374151; font-weight: 600;
}
td { padding: 10px 12px; border-top: 1px solid #e5e7eb; font-size: 13px; color: #4b5563; }
tr:hover td { background: #f9fafb; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
footer {
  margin-top: 40px; padding: 20px 24px; background: #fef3c7; border-radius: 8px;
  border-left: 4px solid #f59e0b;
}
footer h3 { font-size: 14px; color: #92400e; margin-bottom: 8px; font-weight: 600; }
footer p { font-size: 13px; color: #78350f; line-height: 1.7; }
"""


# === 图表生成 =================================================================

def _fig_to_base64(fig, dpi: int) -> str:
    """matplotlib Figure → PNG → base64 字符串"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _format_x_dates(ax, dates: list[str]) -> None:
    """日期过多时稀疏化 x 轴刻度，避免重叠"""
    if len(dates) > 8:
        step = max(1, len(dates) // 8)
        idx = list(range(0, len(dates), step))
        ax.set_xticks(idx)
        ax.set_xticklabels([dates[i] for i in idx], rotation=30, ha="right", fontsize=9)


def plot_equity_curve(curve_data: list[dict], drawdown_data: list[dict], dpi: int) -> str:
    """图 1: 累计收益率（上）+ 回撤（下）"""
    dates = [d["date"] for d in curve_data]
    cum = [d["cum_return"] for d in curve_data]
    dd_dates = [d["date"] for d in drawdown_data]
    dd = [d["drawdown"] for d in drawdown_data]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, sharex=False, figsize=(10, 5),
        gridspec_kw={"height_ratios": [3, 1]},
    )
    ax1.plot(dates, cum, color=_COLOR_PRIMARY, linewidth=1.5, label="Cumulative Return")
    ax1.fill_between(dates, 0, cum, alpha=0.12, color=_COLOR_PRIMARY)
    ax1.axhline(0, color="#9ca3af", linewidth=0.5, linestyle="--")
    ax1.set_ylabel("Cumulative Return")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)
    _format_x_dates(ax1, dates)

    ax2.fill_between(dd_dates, dd, 0, color=_COLOR_SELL, alpha=0.4, label="Drawdown")
    ax2.set_ylabel("Drawdown")
    ax2.legend(loc="lower left", fontsize=9)
    ax2.grid(True, alpha=0.3)
    _format_x_dates(ax2, dd_dates)

    plt.tight_layout()
    return _fig_to_base64(fig, dpi)


def plot_daily_ic(daily_ic_data: list[dict], dpi: int) -> str:
    """图 2: 每日 Pearson IC 与 Rank IC 时序"""
    dates = [d["date"] for d in daily_ic_data]
    ic = [d["ic"] for d in daily_ic_data]
    ric = [d["rank_ic"] for d in daily_ic_data]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(dates, ic, color=_COLOR_PRIMARY, linewidth=1, label="Pearson IC", alpha=0.85)
    ax.plot(dates, ric, color=_COLOR_WARN, linewidth=1, label="Rank IC", alpha=0.85)
    ax.axhline(0, color="#9ca3af", linewidth=0.5, linestyle="--")
    ax.set_ylabel("IC")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    _format_x_dates(ax, dates)

    plt.tight_layout()
    return _fig_to_base64(fig, dpi)


def plot_signal_timeline(signal_timeline: list[dict], dpi: int) -> str:
    """图 3: 信号时间分布（堆叠柱状图）"""
    dates = [d["date"] for d in signal_timeline]
    buy = np.array([d["buy"] for d in signal_timeline])
    sell = np.array([d["sell"] for d in signal_timeline])
    hold = np.array([d["hold"] for d in signal_timeline])

    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(dates))
    ax.bar(x, hold, color=_COLOR_HOLD, label="Hold", width=1.0)
    ax.bar(x, sell, bottom=hold, color=_COLOR_SELL, label="Sell", width=1.0)
    ax.bar(x, buy, bottom=hold + sell, color=_COLOR_BUY, label="Buy", width=1.0)
    ax.set_ylabel("Symbol Count")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    _format_x_dates(ax, dates)

    plt.tight_layout()
    return _fig_to_base64(fig, dpi)


def plot_top_symbols(symbols: list[dict], dpi: int) -> str:
    """图 4: Top 20 品种信号分布（水平堆叠条形图）"""
    # 倒序让 Top 1 显示在最上方
    syms_data = list(reversed(symbols))
    syms = [s["symbol"] for s in syms_data]
    buy = np.array([s["buy"] for s in syms_data])
    sell = np.array([s["sell"] for s in syms_data])
    hold = np.array([s["hold"] for s in syms_data])

    fig, ax = plt.subplots(figsize=(10, max(4, len(syms) * 0.32)))
    y = np.arange(len(syms))
    ax.barh(y, hold, color=_COLOR_HOLD, label="Hold")
    ax.barh(y, sell, left=hold, color=_COLOR_SELL, label="Sell")
    ax.barh(y, buy, left=hold + sell, color=_COLOR_BUY, label="Buy")
    ax.set_yticks(y)
    ax.set_yticklabels(syms, fontsize=9)
    ax.set_xlabel("Signal Count")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="x")

    plt.tight_layout()
    return _fig_to_base64(fig, dpi)


# === HTML 拼接 =================================================================

def _fmt_pct(v: float, digits: int = 4) -> str:
    """0.025 → '2.5000%'"""
    return f"{v * 100:.{digits}f}%"


def render_head(meta: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>alpha-f1 因子回测报告</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>期货前20席位持仓突变因子 (alpha-f1) 回测报告</h1>
  <div class="meta">
    生成时间: {meta['generated_at']}
    &nbsp;|&nbsp; 数据版本: <code>{meta['data_version']}</code>
    &nbsp;|&nbsp; 样本区间: {meta['sample_start']} ~ {meta['sample_end']}
    &nbsp;|&nbsp; 交易日数: {meta['trade_days']}
    &nbsp;|&nbsp; 品种数: {meta['symbol_count']}
  </div>
</header>
"""


def render_summary_cards(data: dict) -> str:
    """8 个核心绩效指标卡片"""
    arr_pct = data["ARR(%)"]
    mdd_pct = data["MDD(%)"]
    metrics = [
        ("IC", str(data["IC"]), ""),
        ("ICIR", str(data["ICIR"]), ""),
        ("Rank IC", str(data["Rank IC"]), ""),
        ("Rank ICIR", str(data["Rank ICIR"]), ""),
        ("IR (SHR*)", str(data["IR(SHR*)"]), ""),
        ("CR (Calmar)", str(data["CR"]), ""),
        ("ARR", f"{arr_pct:.4f}", "%", "positive" if arr_pct > 0 else "negative"),
        ("MDD", f"{mdd_pct:.4f}", "%", "negative" if mdd_pct < 0 else ""),
    ]
    cards = []
    for item in metrics:
        label, value, unit = item[0], item[1], item[2]
        cls = item[3] if len(item) > 3 else ""
        cls_str = f" {cls}" if cls else ""
        unit_html = f'<span class="unit">{unit}</span>' if unit else ""
        cards.append(
            f'<div class="card{cls_str}"><div class="label">{label}</div>'
            f'<div class="value">{value}{unit_html}</div></div>'
        )
    return (
        '<section><h2>核心绩效指标</h2><div class="cards-grid">\n'
        + "\n".join(cards)
        + '\n</div></section>'
    )


def render_counts(data: dict) -> str:
    """样本与信号统计卡片"""
    metrics = [
        ("样本数", f"{data['样本数']:,}"),
        ("买入信号", f"{data['买入信号']:,}"),
        ("卖出信号", f"{data['卖出信号']:,}"),
        ("持仓信号", f"{data['持仓信号']:,}"),
        ("换手率", _fmt_pct(data["换手率"], 2)),
    ]
    cards = [
        f'<div class="card"><div class="label">{lbl}</div><div class="value">{val}</div></div>'
        for lbl, val in metrics
    ]
    return (
        '<section><h2>样本与信号统计</h2><div class="cards-grid">\n'
        + "\n".join(cards)
        + '\n</div></section>'
    )


def render_layered(data: dict) -> str:
    """分层收益对比"""
    layered = data["分层收益"]
    low = layered.get("low", 0.0) or 0.0
    high = layered.get("high", 0.0) or 0.0
    diff = high - low
    cls = "positive" if diff > 0 else "negative"
    cards = [
        f'<div class="card"><div class="label">Low 组平均收益</div><div class="value">{_fmt_pct(low)}</div></div>',
        f'<div class="card"><div class="label">High 组平均收益</div><div class="value">{_fmt_pct(high)}</div></div>',
        f'<div class="card {cls}"><div class="label">High - Low 价差</div><div class="value">{_fmt_pct(diff)}</div></div>',
    ]
    return (
        '<section><h2>分层收益对比</h2><div class="cards-grid">\n'
        + "\n".join(cards)
        + '\n</div></section>'
    )


def render_chart_section(title: str, img_b64: str, note: str | None = None) -> str:
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (
        f'<section><h2>{title}</h2>{note_html}\n'
        f'<img src="data:image/png;base64,{img_b64}" alt="{title}"/></section>'
    )


def render_symbol_table(symbols: list[dict]) -> str:
    rows = [
        f"<tr><td>{s['symbol']}</td>"
        f'<td class="num">{s["buy"]}</td>'
        f'<td class="num">{s["sell"]}</td>'
        f'<td class="num">{s["hold"]}</td>'
        f'<td class="num">{s["total"]}</td></tr>'
        for s in symbols
    ]
    return (
        '<section><h2>Top 20 品种信号明细</h2>\n'
        '<table>\n<thead><tr>'
        '<th>品种</th><th>Buy</th><th>Sell</th><th>Hold</th><th>总计</th>'
        '</tr></thead>\n<tbody>\n'
        + "\n".join(rows)
        + '\n</tbody></table></section>'
    )


def render_footer(evaluation_text: str) -> str:
    return (
        '<footer><h3>评估口径（避免偷价）</h3>\n'
        f'<p>{evaluation_text}</p></footer>\n</body>\n</html>\n'
    )


# === 字段校验 =================================================================

def validate_payload(data: dict) -> None:
    """报告渲染前的字段完整性自检，避免生成残缺报告"""
    required_top = [
        "IC", "ICIR", "Rank IC", "Rank ICIR", "IR(SHR*)", "CR", "ARR(%)", "MDD(%)",
        "样本数", "买入信号", "卖出信号", "持仓信号", "分层收益", "换手率",
        "评估口径", "meta", "timeseries", "symbol_distribution",
    ]
    missing = [k for k in required_top if k not in data]
    if missing:
        raise ValueError(f"报告数据缺少顶层字段: {missing}")

    meta = data["meta"]
    if not meta.get("sample_start") or not meta.get("sample_end"):
        raise ValueError(f"meta.sample_start / sample_end 不能为空: {meta}")
    if not meta.get("trade_days") or meta["trade_days"] < 1:
        raise ValueError(f"meta.trade_days 必须 ≥ 1: {meta}")

    ts = data["timeseries"]
    if not ts.get("curve"):
        raise ValueError("timeseries.curve 不能为空")
    if not ts.get("daily_ic"):
        raise ValueError("timeseries.daily_ic 不能为空")
    if not ts.get("drawdown"):
        raise ValueError("timeseries.drawdown 不能为空")
    if not ts.get("signal_timeline"):
        raise ValueError("timeseries.signal_timeline 不能为空")

    if not data.get("symbol_distribution"):
        raise ValueError("symbol_distribution 不能为空")

    for k in ["IC", "ICIR", "Rank IC", "Rank ICIR", "IR(SHR*)", "CR", "ARR(%)", "MDD(%)"]:
        v = data[k]
        if not isinstance(v, (int, float)):
            raise ValueError(f"标量指标 {k} 必须为数值，实际类型 {type(v).__name__}: {v!r}")


# === 主流程 ===================================================================

def render_html(data: dict, dpi: int = 100) -> str:
    """把回测结果 dict 渲染成完整 HTML 字符串"""
    validate_payload(data)

    meta = data["meta"]
    ts = data["timeseries"]

    # 生成 4 张图（base64 内嵌）
    img_equity = plot_equity_curve(ts["curve"], ts["drawdown"], dpi)
    img_ic = plot_daily_ic(ts["daily_ic"], dpi)
    img_signal = plot_signal_timeline(ts["signal_timeline"], dpi)
    img_symbols = plot_top_symbols(data["symbol_distribution"], dpi)

    parts = [
        render_head(meta),
        render_summary_cards(data),
        render_counts(data),
        render_layered(data),
        render_chart_section(
            "累计收益率与回撤",
            img_equity,
            note=(
                "上图：买入信号 t+1 日开盘成交、t+1 日收盘平仓的累计收益率（严格口径，无偷价）。"
                "下图：同期回撤序列，反映策略最大亏损幅度。"
            ),
        ),
        render_chart_section(
            "每日 IC 时序",
            img_ic,
            note=(
                "Pearson IC 衡量因子值与 forward_return 的线性相关性；"
                "Rank IC 衡量秩相关性（对异常值更稳健）。两者均值越偏离 0，因子预测能力越强。"
            ),
        ),
        render_chart_section(
            "信号时间分布",
            img_signal,
            note=(
                "按交易日统计 buy / sell / hold 信号数量。"
                "若 buy/sell 占比过高，可能意味着因子阈值过松或市场进入高波动期。"
            ),
        ),
        render_chart_section(
            "Top 20 品种信号分布",
            img_symbols,
            note=(
                "按信号总数排序的前 20 个品种。条形越长表示该品种触发的信号越多。"
                "Buy/Sell 失衡的品种可能存在单边趋势，需结合基本面验证。"
            ),
        ),
        render_symbol_table(data["symbol_distribution"]),
        render_footer(data["评估口径"]),
    ]
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成 alpha-f1 因子回测 HTML 报告（self-contained，含 base64 内嵌图表）"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="强制离线模式（用 scripts/fixtures/*.parquet，无需凭证）",
    )
    parser.add_argument(
        "--json-path", type=Path,
        default=Path(__file__).parent.parent / "reports" / "backtest_result.json",
        help="中间 JSON 输出路径（默认 reports/backtest_result.json）",
    )
    parser.add_argument(
        "--html-path", type=Path,
        default=Path(__file__).parent.parent / "reports" / "report.html",
        help="最终 HTML 输出路径（默认 reports/report.html）",
    )
    parser.add_argument(
        "--dpi", type=int, default=100,
        help="图表 DPI（默认 100，增大体积随之线性增长）",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="生成后自动用默认浏览器打开 HTML 报告",
    )
    args = parser.parse_args()

    # 1. 跑回测
    offline_mode = args.offline or _is_offline(None)
    # validate._load_fixture_or_network 只看环境变量，不收参数；
    # 显式同步到这里，确保 --offline 命令行参数能正确触发离线 fixture 加载
    if offline_mode:
        os.environ["PANDA_DATA_OFFLINE"] = "1"
    print(f"[1/3] 运行回测 (offline={offline_mode}) ...")
    result = run_backtest_with_series(offline=args.offline)

    # 2. 落盘 JSON（HTML 渲染失败时 JSON 仍可用作排错）
    print(f"[2/3] 保存中间结果 → {args.json_path}")
    save_backtest_result(result, args.json_path)

    # 3. 渲染 HTML
    print(f"[3/3] 渲染 HTML 报告（dpi={args.dpi}）...")
    html = render_html(result, dpi=args.dpi)
    args.html_path.parent.mkdir(parents=True, exist_ok=True)
    args.html_path.write_text(html, encoding="utf-8")

    print()
    print("=" * 60)
    print(f"[OK] 报告已生成")
    print(f"     HTML: {args.html_path}")
    print(f"     JSON: {args.json_path}")
    print(f"     样本: {result['meta']['sample_start']} ~ {result['meta']['sample_end']}"
          f" ({result['meta']['trade_days']} 个交易日, {result['meta']['symbol_count']} 个品种)")
    print(f"     IC={result['IC']}, ICIR={result['ICIR']}, ARR={result['ARR(%)']:.4f}%, MDD={result['MDD(%)']:.4f}%")
    print("=" * 60)

    if args.open:
        import webbrowser
        webbrowser.open(args.html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
