"""Render the Q44 V9.4 multi-market evidence report."""

from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def _load(path: Path, market: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get(market, {})
    if not result or result.get("error"):
        raise ValueError(f"{path} does not contain a valid {market} result")
    return result


def _series(result: dict[str, Any], key: str) -> pd.Series:
    values = pd.Series(result[key], dtype=float)
    values.index = pd.to_datetime(values.index)
    return values.sort_index().dropna()


def _embedded_png(path: Path) -> str:
    """Keep the deliverable report usable when opened from an archive."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _metrics(nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    daily = nav.pct_change().dropna()
    return {
        "total_return": total,
        "cagr": float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1),
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "sharpe": float(daily.mean() / daily.std() * 252**0.5) if not daily.empty and daily.std() > 0 else 0.0,
    }


def _period(nav: pd.Series, start: str, end: str) -> dict[str, float]:
    return _metrics(nav.loc[pd.Timestamp(start):pd.Timestamp(end)])


def _save_chart(path: Path, title: str, lines: list[tuple[str, pd.Series, str, float]]) -> None:
    figure, axis = plt.subplots(figsize=(13, 6.6), dpi=150)
    figure.patch.set_facecolor("#f4f4f1")
    axis.set_facecolor("#ffffff")
    for label, series, color, width in lines:
        axis.plot(series.index, series, color=color, linewidth=width, label=label)
    axis.set_title(title, fontsize=17, loc="left", pad=14)
    axis.set_ylabel("净值（起点=1）")
    axis.grid(color="#d8d8d2", linewidth=0.7, alpha=0.8)
    axis.legend(frameon=False, ncol=min(3, len(lines)), loc="upper left")
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)


def _name_map(holdings_log: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in holdings_log:
        for field in ("entry_details", "removed_reasons"):
            for detail in row.get(field, []):
                symbol = str(detail.get("symbol") or "")
                name = str(detail.get("name") or "")
                if symbol and name:
                    names[symbol] = name
    return names


def _security_label(symbol: str, names: dict[str, str]) -> str:
    name = names.get(symbol)
    return f"{name}（{symbol}）" if name else symbol


def _security_list(symbols: list[str], names: dict[str, str]) -> str:
    return "、".join(html.escape(_security_label(symbol, names)) for symbol in symbols) if symbols else "无"


def _removal_explanation(row: dict[str, Any], names: dict[str, str]) -> str:
    reasons = {str(item.get("symbol")): item for item in row.get("removed_reasons", [])}
    trigger_labels = {
        "normalized_profit_nonpositive": "正常化利润转负",
        "quality_score_below_50": "质量状态显著恶化",
        "industry_manual_review": "行业风险需人工复核",
        "negative_audit_opinion": "审计意见触发",
        "quarterly_profit_nonpositive": "季度利润转负",
        "extreme_debt_deterioration": "债务极端恶化",
        "annual_profit_nonpositive": "年度净利润转负",
        "price_unavailable": "价格覆盖中断",
    }
    explanations = []
    for symbol in row.get("removed", []):
        detail = reasons.get(symbol, {})
        triggers = [trigger_labels.get(value, value) for value in detail.get("sell_triggers", [])]
        reason = "、".join(triggers) or str(detail.get("reason") or "未进入当期可持有集合")
        explanations.append(f"{html.escape(_security_label(symbol, names))}：{html.escape(reason)}")
    return "；".join(explanations) if explanations else "无卖出；原持仓继续满足长期持有条件"


def _rebalance_history(holdings_log: list[dict[str, Any]]) -> str:
    names = _name_map(holdings_log)
    blocks = []
    for row in holdings_log:
        blocks.append(
            "<details class='rebalance'>"
            f"<summary><span class='date'>{html.escape(str(row['date']))}</span>"
            f"<span>持仓 {len(row.get('picks', []))} 只</span>"
            f"<span class='buy'>新入 {len(row.get('new_entries', []))}</span>"
            f"<span class='sell'>卖出 {len(row.get('removed', []))}</span>"
            f"<span>换手 {float(row.get('turnover') or 0):.1%}</span></summary>"
            "<div class='rebalance-body'>"
            f"<p><strong>调仓摘要：</strong>{html.escape(str(row.get('reason_summary') or ''))}</p>"
            f"<p><strong>调仓后持仓：</strong>{_security_list(row.get('picks', []), names)}</p>"
            f"<p class='buy'><strong>新买入：</strong>{_security_list(row.get('new_entries', []), names)}</p>"
            f"<p class='sell'><strong>卖出：</strong>{_security_list(row.get('removed', []), names)}</p>"
            f"<p><strong>继续持有：</strong>{_security_list(row.get('kept', []), names)}</p>"
            f"<p><strong>卖出原因：</strong>{_removal_explanation(row, names)}</p>"
            f"<p class='muted'>该期换手率 {float(row.get('turnover') or 0):.1%}；"
            f"按 {float(row.get('transaction_cost_bps') or 0):.0f}bp 计入调仓成本。</p>"
            "</div></details>"
        )
    return "".join(blocks)


def _metric_rows(rows: list[dict[str, Any]]) -> str:
    return "".join(
        f"<tr><td>{html.escape(str(row['period']))}</td><td>{html.escape(str(row['strategy']))}</td>"
        f"<td>{row['total_return']:.2%}</td><td>{row['cagr']:.2%}</td>"
        f"<td>{row['max_drawdown']:.2%}</td><td>{row['sharpe']:.2f}</td></tr>"
        for row in rows
    )


def _latest_holdings(result: dict[str, Any], *, show_history: bool = False) -> str:
    latest = result["holdings_log"][-1]
    rows = []
    for detail in latest.get("entry_details", []):
        score = detail.get("soft_score")
        score_text = f"{float(score):.2f}" if score is not None else "名单固定"
        coverage = detail.get("score_coverage")
        coverage_text = f"{float(coverage):.0%}" if coverage is not None else "N/A"
        history = detail.get("history_coverage")
        history_text = f"{float(history):.0%}" if history is not None else "N/A"
        rows.append(
            f"<tr><td>{html.escape(str(detail.get('symbol', '')))}</td>"
            f"<td>{html.escape(str(detail.get('name', '')))}</td>"
            f"<td>{html.escape(str(detail.get('industry') or '未知'))}</td>"
            f"<td>{score_text}</td><td>{coverage_text}</td>"
            + (f"<td>{history_text}</td>" if show_history else "")
            + "</tr>"
        )
    history_header = "<th>历史年数覆盖</th>" if show_history else ""
    return (
        f"<p class='muted'>最后调仓日：{html.escape(str(latest['date']))}。这是历史模拟持仓，不是当前真实账户仓位。</p>"
        "<div class='table-wrap'><table><thead><tr><th>代码</th><th>名称</th><th>行业</th>"
        f"<th>软评分</th><th>指标覆盖</th>{history_header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def run(output_dir: Path) -> dict[str, Any]:
    soft = _load(output_dir / "backtest_a_share_strict.json", "a_share")
    hard = _load(ROOT / "output" / "hard_pit_2017_2026.json", "a_share")
    roster = _load(output_dir / "backtest_a_share_roster_2010.json", "a_share")
    us = _load(output_dir / "backtest_us_fixed_roster.json", "us")

    soft_nav, hard_nav = _series(soft, "nav"), _series(hard, "nav")
    strict_bench = _series(soft, "benchmark_nav")
    roster_nav, roster_bench = _series(roster, "nav"), _series(roster, "benchmark_nav")
    us_nav = _series(us, "nav")
    spy_nav = _series(us, "benchmark_nav") if us.get("benchmark_nav") else pd.Series(dtype=float)
    _save_chart(
        output_dir / "backtest_a_share_strict.png",
        "Q44 V9.4 点时沪深 300 回测",
        [("软评分长期组合（成本后）", soft_nav, "#0f6b5b", 2.2), ("旧 hard 对照（成本后）", hard_nav, "#9b3a32", 1.7), ("沪深 300", strict_bench, "#343a40", 1.5)],
    )
    _save_chart(
        output_dir / "backtest_a_share_roster_2010.png",
        "2010 起 A 股固定经典名单诊断",
        [("固定经典名单（成本后）", roster_nav, "#835d1e", 2.2), ("沪深 300", roster_bench, "#343a40", 1.5)],
    )
    us_lines = [("美股 Buffett 式研究组合（成本后）", us_nav, "#17698c", 2.2)]
    if not spy_nav.empty:
        us_lines.append(("SPY 价格收益", spy_nav, "#343a40", 1.5))
    _save_chart(output_dir / "backtest_us_fixed_roster.png", "2015 起美股固定研究池软评分回测", us_lines)

    strict_periods = {
        "完整严格期": ("2017-01-03", "2026-07-24"),
        "开发期": ("2017-01-03", "2021-12-31"),
        "回看诊断期": ("2022-01-01", "2026-07-24"),
    }
    strict_rows: list[dict[str, Any]] = []
    for period, (start, end) in strict_periods.items():
        for strategy, nav in (("A股软评分", soft_nav), ("旧 hard 对照", hard_nav), ("沪深300", strict_bench)):
            strict_rows.append({"period": period, "strategy": strategy, **_period(nav, start, end)})
    roster_rows = [
        {"period": "2010-2026 固定样本诊断", "strategy": "A股固定经典名单", **_metrics(roster_nav)},
        {"period": "2010-2026 固定样本诊断", "strategy": "沪深300", **_metrics(roster_bench)},
    ]
    us_rows = [{"period": "2015-2026 可验证期", "strategy": "美股固定研究池", **_metrics(us_nav)}]
    if not spy_nav.empty:
        us_rows.append({"period": "2015-2026 可验证期", "strategy": "SPY 价格收益", **_metrics(spy_nav)})
    summary = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "data_version": "9.4.0",
        "score_version": "soft-five-dimension-v1",
        "periods": strict_rows,
        "strategies": {
            "a_share_strict_pit": {"start": soft["start"], "end": soft["end"], "performance": soft["performance"]},
            "a_share_fixed_roster": {"start": roster["start"], "end": roster["end"], "performance": roster["performance"]},
            "us_fixed_research_roster": {"start": us["start"], "end": us["end"], "performance": us["performance"]},
        },
        "claim_boundary": "Three separate evidence tracks; fixed rosters are survivorship-prone and are not historical index universes.",
    }
    (output_dir / "backtest_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><link rel='icon' href='data:,'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Q44 V9.4 多市场回测报告</title>
<style>body{{margin:0;background:#f4f4f1;color:#202421;font-family:'Microsoft YaHei',Arial,sans-serif;letter-spacing:0}}header,section{{padding:28px max(20px,7vw)}}header{{background:#123d35;color:white}}h1{{font-size:30px;margin:0 0 8px}}h2{{font-size:21px;margin:0 0 16px}}h3{{font-size:16px;margin:0 0 10px}}p{{line-height:1.7}}img{{display:block;width:100%;height:auto;border:1px solid #d8d8d2}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:10px 12px;border-bottom:1px solid #deded8;text-align:left;font-size:14px;white-space:nowrap}}th{{background:#e7ece9}}.scope{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.scope>div{{background:white;border-top:3px solid #0f6b5b;padding:16px}}.scope p{{margin:0;color:#59605c;font-size:14px}}details.rebalance{{background:white;border-bottom:1px solid #deded8}}details.rebalance:first-of-type{{border-top:1px solid #deded8}}summary{{cursor:pointer;display:grid;grid-template-columns:120px repeat(4,minmax(90px,1fr));gap:12px;align-items:center;padding:14px 16px}}summary:hover{{background:#f0f4f1}}summary .date{{font-weight:700}}.rebalance-body{{padding:2px 16px 18px;border-top:1px solid #ecece7}}.rebalance-body p{{margin:10px 0}}.buy{{color:#0f6b5b}}.sell{{color:#9b3a32}}.muted{{color:#69706c;font-size:13px}}.note{{border-left:4px solid #9b3a32;padding:12px 16px;background:#fff}}.subhead{{margin-top:30px}}@media(max-width:800px){{.scope{{grid-template-columns:1fr}}summary{{grid-template-columns:1fr 1fr}}header,section{{padding:22px 16px}}h1{{font-size:25px}}}}@media(max-width:430px){{summary{{grid-template-columns:1fr}}th,td{{padding:9px 10px}}}}</style></head>
<body><header><h1>Q44 V9.4 巴菲特式多市场研究</h1><p>五维连续软评分 · 银行毛利率 N/A · 长期持有 · 15bp 调仓成本</p></header>
<section><h2>证据范围</h2><div class='scope'><div><h3>A 股严格沪深300</h3><p>2017-01-03 起，逐年使用 Panda 当时可见指数权重。2017 年以前不宣称完整点时沪深300。</p></div><div><h3>A 股 2010 固定名单</h3><p>2010-2026 仅为 18 只经典蓝筹固定样本诊断，存在幸存者偏差，不等于沪深300选股。</p></div><div><h3>美股固定研究池</h3><p>Panda 可用价格从 2015 起；12 只固定研究池不是历史标普500，也不是伯克希尔实际持仓复原。</p></div></div></section>
<section><h2>A 股严格点时沪深300：2017-2026</h2><img src='{_embedded_png(output_dir / "backtest_a_share_strict.png")}' alt='A股严格点时回测净值'><div class='table-wrap'><table><thead><tr><th>区间</th><th>策略</th><th>累计</th><th>年化</th><th>最大回撤</th><th>夏普</th></tr></thead><tbody>{_metric_rows(strict_rows)}</tbody></table></div><h3 class='subhead'>最新模拟持仓</h3>{_latest_holdings(soft)}<h3 class='subhead'>年度持仓与换仓记录</h3>{_rebalance_history(soft['holdings_log'])}</section>
<section><h2>A 股固定经典名单诊断：2010-2026</h2><p class='note'>该结果仅回答“这组今天已知的经典公司若从 2010 起持有会怎样”，不能回答“当时从完整沪深300能否选出它们”。</p><img src='{_embedded_png(output_dir / "backtest_a_share_roster_2010.png")}' alt='A股固定名单诊断净值'><div class='table-wrap'><table><thead><tr><th>区间</th><th>策略</th><th>累计</th><th>年化</th><th>最大回撤</th><th>夏普</th></tr></thead><tbody>{_metric_rows(roster_rows)}</tbody></table></div><h3 class='subhead'>最新模拟持仓</h3>{_latest_holdings(roster)}<h3 class='subhead'>年度持仓与换仓记录</h3>{_rebalance_history(roster['holdings_log'])}</section>
<section><h2>美股固定研究池：2015-2026</h2><p class='note'>收益口径为 Panda 未复权日线按明确公司行动校正后的价格收益，不含现金分红。get_us_daily 对 SPY/IVV/VOO/QQQ/DIA 均返回空，故本版不展示虚假的零收益美股基准；早期财务历史不足通过历史覆盖率降权。</p><img src='{_embedded_png(output_dir / "backtest_us_fixed_roster.png")}' alt='美股固定研究池回测净值'><div class='table-wrap'><table><thead><tr><th>区间</th><th>策略</th><th>累计</th><th>年化</th><th>最大回撤</th><th>夏普</th></tr></thead><tbody>{_metric_rows(us_rows)}</tbody></table></div><h3 class='subhead'>最新模拟持仓</h3>{_latest_holdings(us, show_history=True)}<h3 class='subhead'>年度持仓与换仓记录</h3>{_rebalance_history(us['holdings_log'])}</section>
<section><p class='note'>共同边界：所有结果均为历史量化诊断。固定名单结果受幸存者偏差影响，任何一条曲线都不构成投资建议或未来收益保证。</p></section></body></html>"""
    (output_dir / "backtest_report.html").write_text(report, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "生产产物"))
    args = parser.parse_args()
    run(Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
