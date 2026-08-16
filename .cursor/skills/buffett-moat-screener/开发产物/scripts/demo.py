"""Generate an offline visual demonstration from the packaged production snapshot.

The default path never calls Panda Data or any trading interface. It turns the
versioned Parquet snapshot into a reusable JSON research result and a matching
standalone HTML report for demonstrations.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.build import _buffett_guidance, run
    from scripts.core import DATA_VERSION
else:
    from .build import _buffett_guidance, run
    from .core import DATA_VERSION


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTION = ROOT / "生产产物" / "数据库.parquet"
DEFAULT_STRICT_BACKTEST = ROOT / "生产产物" / "backtest_a_share_strict.json"
DEFAULT_ROSTER_BACKTEST = ROOT / "生产产物" / "backtest_a_share_roster_2010.json"
DEFAULT_JSON = ROOT / "output" / "demo_result.json"
DEFAULT_HTML = ROOT / "output" / "demo_report.html"
REQUIRED_COLUMNS = {"trade_date", "target_id", "result_type", "result_json", "data_version"}


def _parse_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _guidance_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the production schema, including pre-9.4 decision labels."""
    payload = _parse_payload(row.get("result_json"))
    payload.setdefault("target_id", str(row["target_id"]))
    payload.setdefault("coverage_ratio", payload.get("score_coverage"))
    decision = str(payload.get("decision") or "")
    if decision.endswith("research_candidate"):
        payload["decision"] = "research_candidate"
    elif decision.endswith("watchlist"):
        payload["decision"] = "watchlist"
    elif decision in {"reject", "insufficient_data"}:
        payload["decision"] = decision
    else:
        payload["decision"] = "insufficient_data"
    return payload


def _latest_payload(frame: pd.DataFrame, result_type: str) -> tuple[dict[str, Any], str | None]:
    selected = frame.loc[frame["result_type"].eq(result_type)].copy()
    if selected.empty:
        return {}, None
    selected = selected.sort_values(["trade_date", "update_time"], na_position="last")
    row = selected.iloc[-1]
    return _parse_payload(row["result_json"]), str(row["trade_date"])


def _annual_holding_items(path: Path, *, scope: str, scope_note: str) -> list[dict[str, Any]]:
    """Read annual holding evidence from an already materialized A-share backtest."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        backtest = payload["a_share"]
        holding_log = backtest["holdings_log"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    items: list[dict[str, Any]] = []
    for event in holding_log:
        if not isinstance(event, Mapping) or not event.get("date"):
            continue
        details = {
            str(item.get("symbol")): item
            for item in event.get("entry_details", [])
            if isinstance(item, Mapping) and item.get("symbol")
        }
        holdings = []
        for symbol in event.get("picks", []):
            detail = details.get(str(symbol), {})
            holdings.append(
                {
                    "symbol": str(symbol),
                    "name": detail.get("name"),
                    "industry": detail.get("industry"),
                    "reason": detail.get("reason"),
                }
            )
        items.append(
            {
                "year": str(event["date"])[:4],
                "signal_date": str(event["date"]),
                "research_scope": scope,
                "scope_note": scope_note,
                "source_file": path.name,
                "holding_count": len(holdings),
                "holdings": holdings,
                "recommendation": event.get("reason_summary") or "按年度信号复核持仓。",
                "new_entries": list(event.get("new_entries", [])),
                "kept": list(event.get("kept", [])),
                "removed": list(event.get("removed", [])),
                "turnover": event.get("turnover"),
                "transaction_cost_bps": event.get("transaction_cost_bps"),
            }
        )
    return items


def _annual_holdings() -> dict[str, Any]:
    """Build one annual timeline without overstating the 2010-2016 sample."""
    roster = _annual_holding_items(
        DEFAULT_ROSTER_BACKTEST,
        scope="固定经典名单诊断",
        scope_note="固定 18 只经典公司，存在幸存者偏差，不是历史点时沪深 300 选股。",
    )
    strict = _annual_holding_items(
        DEFAULT_STRICT_BACKTEST,
        scope="严格点时沪深 300",
        scope_note="使用信号日可见的沪深 300 成分，财务指标采用软锚点评分。",
    )
    by_year = {item["year"]: item for item in roster}
    by_year.update({item["year"]: item for item in strict})
    return {
        "items": [by_year[year] for year in sorted(by_year)],
        "boundary": "2010-2016 为固定名单诊断；2017 起才有可验证的严格点时沪深 300 年度持仓建议。年度记录用于回测复盘，不构成当前买卖指令或未来收益承诺。",
    }


def _snapshot_result(production_path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(production_path)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"生产快照缺少必需字段: {', '.join(missing)}")
    frame = frame.loc[frame["data_version"].astype(str).eq(DATA_VERSION)].copy()
    if frame.empty:
        raise ValueError(f"生产快照中没有 data_version={DATA_VERSION} 的结果")

    candidate_rows = frame.loc[frame["result_type"].eq("buffett_research_candidate")].copy()
    if candidate_rows.empty:
        raise ValueError("生产快照中没有巴菲特研究候选记录")
    candidate_date = str(candidate_rows["trade_date"].max())
    records = [_guidance_record(row) for _, row in candidate_rows.loc[candidate_rows["trade_date"].eq(candidate_date)].iterrows()]
    portfolio, portfolio_date = _latest_payload(frame, "portfolio_summary")
    if not portfolio:
        portfolio = {"holdings": [], "cash_weight": 1.0, "state": "research_only"}
    transition_rows = frame.loc[frame["result_type"].eq("portfolio_state_transition")]
    portfolio["transitions"] = [item for _, row in transition_rows.iterrows() if (item := _parse_payload(row["result_json"]))]

    try:
        source_path = str(production_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        source_path = str(production_path)
    return {
        "demo_version": "1.0.0",
        "mode": "production_snapshot",
        "data_version": DATA_VERSION,
        "as_of_date": str(frame["trade_date"].max()),
        "candidate_as_of_date": candidate_date,
        "portfolio_as_of_date": portfolio_date,
        "buffett_guidance": _buffett_guidance(records, portfolio),
        "portfolio_state": {
            "state": portfolio.get("state", "research_only"),
            "reason": portfolio.get("reason"),
            "holdings": portfolio.get("holdings", []),
            "transitions": portfolio.get("transitions", []),
        },
        "annual_holdings": _annual_holdings(),
        "source": {
            "path": source_path,
            "network_called": False,
            "orders_created": False,
        },
    }


def _live_result(as_of_date: str) -> dict[str, Any]:
    """Run the normal production entry point only when the caller opts in."""
    result = run({"as_of_date": as_of_date, "universe": "all_a"}, {"selection_mode": "soft", "materialize": False})
    portfolio = dict(result.get("portfolio") or {})
    return {
        "demo_version": "1.0.0",
        "mode": "live_panda_data",
        "data_version": result["data_version"],
        "as_of_date": result["as_of_date"],
        "candidate_as_of_date": result["as_of_date"],
        "portfolio_as_of_date": result["as_of_date"],
        "buffett_guidance": result["buffett_guidance"],
        "portfolio_state": {
            "state": portfolio.get("state", "research_only"),
            "reason": portfolio.get("reason"),
            "holdings": portfolio.get("holdings", []),
            "transitions": portfolio.get("transitions", []),
        },
        "annual_holdings": {
            "items": [],
            "boundary": "实时筛选不重跑历史回测；运行默认离线演示可查看已交付的年度持仓建议与标的。",
        },
        "source": {"provider": "panda_data", "network_called": True, "orders_created": False},
    }


def _html_report(result: Mapping[str, Any]) -> str:
    """Render the exact JSON result into an offline, self-contained report."""
    data = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>巴菲特式研究建议演示</title>
<style>
:root{--ink:#1e2b34;--muted:#5f6b72;--line:#d9e0e2;--paper:#f6f8f7;--white:#fff;--green:#176b57;--blue:#176b8a;--amber:#9a6413;--red:#9b3f33}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 "Microsoft YaHei",Arial,sans-serif}.wrap{max-width:1180px;margin:auto;padding:32px 24px 56px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;border-bottom:3px solid var(--ink);padding-bottom:20px}h1{font-size:28px;line-height:1.2;margin:0 0 8px;letter-spacing:0}h2{font-size:19px;margin:0 0 14px;letter-spacing:0}.sub,.meta{color:var(--muted);margin:0}.meta{text-align:right;font-size:13px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.metric,.panel{background:var(--white);border:1px solid var(--line);border-radius:6px}.metric{padding:16px}.metric b{display:block;font-size:28px;line-height:1.15;margin-top:5px}.label{color:var(--muted);font-size:13px}.panel{padding:20px;margin-top:14px}.principles{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:0;margin:0;list-style:none}.principles li{border-left:3px solid var(--green);padding:6px 10px;background:#f3f8f6}.cash{border-left:4px solid var(--amber);padding:12px 14px;background:#fffaf0;margin-top:16px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:760px}#annual table{min-width:1060px}th,td{border-bottom:1px solid var(--line);padding:10px 8px;text-align:left;vertical-align:top}th{font-size:13px;color:var(--muted);font-weight:600}.stance{font-weight:700}.stance.hold{color:var(--green)}.stance.research{color:var(--blue)}.stance.watch{color:var(--amber)}.stance.pause{color:var(--red)}.holdings{margin:0;padding-left:20px}.boundary{border:1px solid #d8ad6b;background:#fff8ed;padding:14px 16px;font-weight:600}.small{font-size:13px;color:var(--muted)}.annual-holdings{min-width:300px}@media(max-width:700px){.wrap{padding:22px 14px}header{display:block}.meta{text-align:left;margin-top:12px}.grid,.principles{grid-template-columns:1fr}h1{font-size:24px}}
</style></head><body><main class="wrap"><header><div><h1>巴菲特式研究建议</h1><p class="sub">可解释的长期研究队列与持仓复核演示</p></div><p id="meta" class="meta"></p></header><section id="metrics" class="grid"></section><section class="panel"><h2>投资原则</h2><p id="overall"></p><ul id="principles" class="principles"></ul><div id="cash" class="cash"></div></section><section class="panel"><h2>候选与持仓复核</h2><div class="table-wrap"><table><thead><tr><th>标的</th><th>研究立场</th><th>质量分</th><th>估值分</th><th>行业</th><th>复核建议</th><th>风险关注</th></tr></thead><tbody id="actions"></tbody></table></div></section><section class="panel"><h2>持仓与换仓说明</h2><div id="portfolio"></div></section><section id="annual" class="panel"><h2>年度持仓建议与标的</h2><p id="annual-boundary" class="small"></p><div class="table-wrap"><table><thead><tr><th>年度</th><th>信号日</th><th>研究口径</th><th>年度持仓建议</th><th>持仓标的</th><th>调仓复核</th></tr></thead><tbody id="annual-rows"></tbody></table></div></section><section class="panel"><h2>研究边界</h2><div id="boundary" class="boundary"></div></section></main><script>
const data = __DATA__;
const g = data.buffett_guidance, p = data.portfolio_state;
const esc = value => String(value ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
document.querySelector('#meta').innerHTML = `模式：${esc(data.mode)}<br>候选信号日：${esc(data.candidate_as_of_date)}<br>组合状态日：${esc(data.portfolio_as_of_date || '无')}`;
document.querySelector('#metrics').innerHTML = [['持仓数量',g.portfolio.holding_count],['现金权重',pct(g.portfolio.cash_weight)],['研究候选',g.research_actions.length]].map(([label,value]) => `<article class="metric"><span class="label">${label}</span><b>${esc(value)}</b></article>`).join('');
document.querySelector('#overall').textContent = g.overall;
document.querySelector('#principles').innerHTML = g.principles.map(value => `<li>${esc(value)}</li>`).join('');
document.querySelector('#cash').textContent = g.portfolio.cash_guidance;
const cls = stance => stance.includes('持有') ? 'hold' : stance.includes('优先') ? 'research' : stance.includes('观察') ? 'watch' : 'pause';
document.querySelector('#actions').innerHTML = g.research_actions.map(item => `<tr><td>${esc(item.target_id)}</td><td class="stance ${cls(item.stance)}">${esc(item.stance)}</td><td>${item.quality_score == null ? 'N/A' : Number(item.quality_score).toFixed(1)}</td><td>${item.valuation_score == null ? 'N/A' : Number(item.valuation_score).toFixed(1)}</td><td>${esc(item.industry || '未知')}</td><td>${esc(item.recommendation)}</td><td>${esc((item.concerns || []).join('；') || '无新增量化风险标记')}</td></tr>`).join('');
const holdings = p.holdings || [], transitions = p.transitions || [];
let portfolioHtml = `<p><b>当前组合状态：</b>${esc(p.state || 'research_only')}。${esc(p.reason || '')}</p>`;
portfolioHtml += holdings.length ? `<ul class="holdings">${holdings.map(item => `<li>${esc(item.target_id)}：目标权重 ${pct(item.actual_weight ?? item.policy_weight ?? item.target_weight)}</li>`).join('')}</ul>` : '<p class="small">当前快照没有可执行股票持仓；保留现金意味着在证据或组合约束不足时不为满仓降低质量标准。</p>';
const transitionText = item => item.review_action === 'no_transition' ? '本次无换仓，维持研究仅模式' : (item.review_action || item.action || '复核');
portfolioHtml += transitions.length ? `<p><b>本次持仓状态变更：</b></p><ul class="holdings">${transitions.map(item => `<li>${esc(item.target_id || '组合')}：${esc(transitionText(item))}</li>`).join('')}</ul>` : '<p class="small">没有记录新的换仓动作。健康的既有持仓不会仅因年度排名回落或估值上升而自动退出；退出须有基本面、审计、利润或债务恶化等证据。</p>';
document.querySelector('#portfolio').innerHTML = portfolioHtml;
const annual = data.annual_holdings || {items: [], boundary: '没有可用的年度回测产物。'};
document.querySelector('#annual-boundary').textContent = annual.boundary;
document.querySelector('#annual-rows').innerHTML = annual.items.length ? annual.items.map(item => {
  const holdingsText = item.holdings.map(holding => `${esc(holding.name || holding.symbol)}（${esc(holding.symbol)}）${holding.industry ? '，' + esc(holding.industry) : ''}`).join('<br>');
  const adjustment = `新入 ${item.new_entries.length}，保留 ${item.kept.length}，剔除 ${item.removed.length}；换手率 ${pct(item.turnover)}`;
  return `<tr><td>${esc(item.year)}</td><td>${esc(item.signal_date)}</td><td><b>${esc(item.research_scope)}</b><br><span class="small">${esc(item.scope_note)}</span></td><td>${esc(item.recommendation)}</td><td class="annual-holdings">${holdingsText}</td><td>${esc(adjustment)}</td></tr>`;
}).join('') : '<tr><td colspan="6" class="small">实时模式不重跑历史回测；请使用默认离线演示。</td></tr>';
document.querySelector('#boundary').textContent = g.boundary;
</script></body></html>""".replace("__DATA__", data)


def run_demo(production_path: Path | str = DEFAULT_PRODUCTION, *, live: bool = False, as_of_date: str | None = None) -> dict[str, Any]:
    """Return a reusable demo result without creating orders."""
    if live:
        if not as_of_date:
            raise ValueError("--live 必须同时提供 --as-of-date YYYYMMDD")
        return _live_result(as_of_date)
    return _snapshot_result(Path(production_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="输出巴菲特式研究建议的 JSON 与可视化 HTML 演示。")
    parser.add_argument("--production", type=Path, default=DEFAULT_PRODUCTION, help="离线生产 Parquet 路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON, help="JSON 输出路径")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML, help="HTML 输出路径")
    parser.add_argument("--open", action="store_true", help="生成后在默认浏览器打开 HTML")
    parser.add_argument("--live", action="store_true", help="显式调用 Panda Data 生成当日研究结果")
    parser.add_argument("--as-of-date", help="live 模式的信号日，格式 YYYYMMDD")
    args = parser.parse_args()

    result = run_demo(args.production, live=args.live, as_of_date=args.as_of_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.html.write_text(_html_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"JSON: {args.output}")
    print(f"HTML: {args.html}")
    if args.open:
        webbrowser.open(args.html.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
