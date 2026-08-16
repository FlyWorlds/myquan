#!/usr/bin/env python3
"""Static review for PandaAI workflow JSON exports.

The reviewer intentionally separates static fragility signals from empirical
overfitting evidence. A workflow file without returns or trial history cannot
prove that a strategy is, or is not, overfit.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
BACKTEST_NODE_RE = re.compile(r"BacktestControl$", re.IGNORECASE)
FACTOR_NODE_RE = re.compile(r"Factor(?:Build|Clean|Analysis|Evaluate|Decay|Blend)", re.IGNORECASE)
ORDER_CALL_NAMES = {
    "order",
    "order_value",
    "order_values",
    "order_target",
    "order_target_value",
    "target_stock_group_order",
    "buy_open",
    "sell_open",
    "buy_close",
    "sell_close",
}
PLACEHOLDER_OUTPUTS = {None, "", "error", "none", "null", "pending"}
BAR_PRICE_ATTRS = {"close", "open", "high", "low", "vwap"}
FUTURE_PRODUCT_RE = re.compile(r"[A-Z]{1,2}\d{0,4}")
# 前端导出的 litegraph properties 使用中文键；规范化 code 缺失时按此映射兜底。
CODE_PROPERTY_KEYS = {"code": ("code", "策略代码", "代码"), "custom_code": ("custom_code",)}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    category: str
    title: str
    evidence: str
    impact: str
    recommendation: str
    node: str | None = None


@dataclass
class AuditContext:
    raw: dict[str, Any]
    nodes: list[dict[str, Any]]
    links: list[dict[str, Any]]
    litegraph: dict[str, Any]
    source_path: str


class PythonSignals(ast.NodeVisitor):
    """Collect conservative strategy-code signals without executing code."""

    def __init__(self) -> None:
        self.function_stack: list[str] = []
        self.negative_shifts: list[int] = []
        self.order_calls: list[tuple[str, int, str | None]] = []
        self.rolling_lines: list[int] = []
        self.rank_lines: list[int] = []
        self.random_calls: list[int] = []
        self.seed_calls: list[int] = []
        self.broad_excepts: list[int] = []
        self.context_parameters: list[tuple[str, Any, int]] = []
        self.module_parameters: list[tuple[str, Any, int]] = []
        self.symbol_literals: set[str] = set()
        self.future_symbol_literals: set[str] = set()
        self.bar_price_reads: list[int] = []
        self.data_calls_in_initialize: list[tuple[str, int]] = []
        self.has_lag_operation = False

    @property
    def current_function(self) -> str | None:
        return self.function_stack[-1] if self.function_stack else None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        if node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        ):
            self.broad_excepts.append(node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        value = literal_value(node.value)
        for target in node.targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                if target.value.id == "context" and value is not _MISSING:
                    self.context_parameters.append((target.attr, value, node.lineno))
            elif (
                not self.function_stack
                and isinstance(target, ast.Name)
                and value is not _MISSING
                and target.id.isupper()
            ):
                self.module_parameters.append((target.id, value, node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        name = dotted_name(node.func)
        leaf = name.rsplit(".", 1)[-1] if name else ""
        if leaf == "shift" and node.args:
            shift = literal_value(node.args[0])
            if isinstance(shift, (int, float)):
                if shift < 0:
                    self.negative_shifts.append(node.lineno)
                elif shift > 0:
                    self.has_lag_operation = True
        if leaf in {"rolling", "ewm", "expanding", "pct_change", "diff"}:
            self.rolling_lines.append(node.lineno)
        if leaf in {"rank", "qcut", "cut", "nlargest", "nsmallest"}:
            self.rank_lines.append(node.lineno)
        if leaf in ORDER_CALL_NAMES:
            self.order_calls.append((leaf, node.lineno, self.current_function))
        if name.startswith(("random.", "np.random.", "numpy.random.")):
            if leaf == "seed":
                self.seed_calls.append(node.lineno)
            else:
                self.random_calls.append(node.lineno)
        if self.current_function == "initialize" and re.search(
            r"(?:get|load|query|fetch|read)_", leaf, re.IGNORECASE
        ):
            self.data_calls_in_initialize.append((name, node.lineno))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, str) and re.fullmatch(
            r"\d{6}\.(?:SH|SZ|BJ|HK)|\d{4,5}\.HK", node.value, re.IGNORECASE
        ):
            self.symbol_literals.add(node.value.upper())

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        # 当期 bar 价格读取；initialize / before_trading / after_trading 之外才视为交易时信号来源。
        if node.attr in BAR_PRICE_ATTRS and self.current_function not in {
            None,
            "initialize",
            "before_trading",
            "after_trading",
        }:
            self.bar_price_reads.append(node.lineno)
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> Any:
        self._collect_future_universe(node.elts)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        self._collect_future_universe(node.elts)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> Any:
        self._collect_future_universe(node.elts)
        self.generic_visit(node)

    def _collect_future_universe(self, elts: list[ast.expr]) -> None:
        values = [
            el.value for el in elts if isinstance(el, ast.Constant) and isinstance(el.value, str)
        ]
        if (
            len(values) >= 3
            and len(values) == len(elts)
            and all(FUTURE_PRODUCT_RE.fullmatch(value) for value in values)
        ):
            self.future_symbol_literals.update(values)


class _Missing:
    pass


_MISSING = _Missing()


def literal_value(node: ast.AST) -> Any:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return _MISSING
    if isinstance(value, (str, int, float, bool, type(None), list, tuple, dict, set)):
        return value
    return _MISSING


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def unwrap_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("workflow JSON root must be an object")
    data = raw.get("data")
    if isinstance(data, dict) and any(k in data for k in ("nodes", "links", "litegraph")):
        return data
    return raw


def load_workflow(path: Path) -> AuditContext:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    payload = unwrap_payload(raw)
    litegraph = payload.get("litegraph") if isinstance(payload.get("litegraph"), dict) else {}
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    links = payload.get("links") if isinstance(payload.get("links"), list) else []
    if not nodes and isinstance(litegraph.get("nodes"), list):
        nodes = derive_nodes_from_litegraph(litegraph.get("nodes", []))
    nodes = [n for n in nodes if isinstance(n, dict)]
    links = [link for link in links if isinstance(link, dict)]
    merge_litegraph_properties(nodes, litegraph)
    return AuditContext(payload, nodes, links, litegraph, str(path.resolve()))


def derive_nodes_from_litegraph(nodes: list[Any]) -> list[dict[str, Any]]:
    derived: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        flags = node.get("flags") if isinstance(node.get("flags"), dict) else {}
        derived.append(
            {
                "uuid": flags.get("uuid") or f"litegraph:{node.get('id')}",
                "litegraph_id": node.get("id"),
                "name": node.get("type") or "",
                "type": node.get("type") or "",
                "title": node.get("title") or node.get("type") or "",
                "static_input_data": dict(node.get("properties") or {}),
                "_derived_from_litegraph": True,
            }
        )
    return derived


def merge_litegraph_properties(nodes: list[dict[str, Any]], litegraph: dict[str, Any]) -> None:
    by_id = {
        item.get("id"): item
        for item in litegraph.get("nodes", [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    for node in nodes:
        static = node.get("static_input_data")
        if not isinstance(static, dict):
            static = {}
            node["static_input_data"] = static
        lg_node = by_id.get(node.get("litegraph_id"))
        if not isinstance(lg_node, dict):
            continue
        properties = lg_node.get("properties")
        if not isinstance(properties, dict):
            continue
        node["_litegraph_properties"] = properties
        for target, sources in CODE_PROPERTY_KEYS.items():
            if static.get(target):
                continue
            for source in sources:
                value = properties.get(source)
                if isinstance(value, str) and value.strip():
                    static[target] = value
                    break


def node_name(node: dict[str, Any]) -> str:
    return str(node.get("name") or node.get("type") or "UnknownNode")


def node_label(node: dict[str, Any]) -> str:
    title = str(node.get("title") or "").strip()
    name = node_name(node)
    return f"{title} ({name})" if title and title != name else name


def add_finding(findings: list[Finding], **kwargs: Any) -> None:
    findings.append(Finding(**kwargs))


def audit_structure(ctx: AuditContext, findings: list[Finding]) -> None:
    for key in ("format_version", "name", "litegraph"):
        if key not in ctx.raw:
            add_finding(
                findings,
                rule_id=f"WF-STRUCT-{key.upper()}",
                severity="medium",
                category="workflow-integrity",
                title=f"缺少顶层字段 {key}",
                evidence=f"工作流根对象中未发现 `{key}`。",
                impact="审计器无法确认格式版本或完整还原 PandaAI 画布语义。",
                recommendation=f"从 PandaAI 的导出功能重新导出，并保留 `{key}` 字段。",
            )
    if not ctx.nodes:
        add_finding(
            findings,
            rule_id="WF-STRUCT-NODES",
            severity="critical",
            category="workflow-integrity",
            title="工作流没有可审计节点",
            evidence="`nodes` 与 `litegraph.nodes` 均为空或不可解析。",
            impact="无法确定策略、因子、回测配置或执行关系。",
            recommendation="重新导出包含完整节点数据的工作流文件。",
        )
        return

    uuids = [n.get("uuid") for n in ctx.nodes if n.get("uuid")]
    duplicate_uuids = sorted(k for k, count in Counter(uuids).items() if count > 1)
    if duplicate_uuids:
        add_finding(
            findings,
            rule_id="WF-STRUCT-DUPLICATE-UUID",
            severity="critical",
            category="workflow-integrity",
            title="节点 UUID 不唯一",
            evidence=f"重复 UUID：{', '.join(map(str, duplicate_uuids[:5]))}",
            impact="连线可能指向错误节点，执行图与审计图都不可信。",
            recommendation="在 PandaAI 中重新保存或重建重复节点，再导出工作流。",
        )
    ids = [n.get("litegraph_id") for n in ctx.nodes if n.get("litegraph_id") is not None]
    duplicate_ids = sorted(k for k, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        add_finding(
            findings,
            rule_id="WF-STRUCT-DUPLICATE-LITEGRAPH-ID",
            severity="high",
            category="workflow-integrity",
            title="LiteGraph 节点 ID 不唯一",
            evidence=f"重复 litegraph_id：{', '.join(map(str, duplicate_ids[:5]))}",
            impact="前端画布与规范化节点可能产生错配。",
            recommendation="重新保存工作流，确保每个节点的 litegraph_id 唯一。",
        )

    known_uuids = set(uuids)
    dangling: list[str] = []
    for link in ctx.links:
        prev = link.get("previous_node_uuid")
        nxt = link.get("next_node_uuid")
        if prev not in known_uuids or nxt not in known_uuids:
            dangling.append(str(link.get("uuid") or link.get("litegraph_id") or "unknown"))
    if dangling:
        add_finding(
            findings,
            rule_id="WF-STRUCT-DANGLING-LINK",
            severity="critical",
            category="workflow-integrity",
            title="存在悬空连线",
            evidence=f"{len(dangling)} 条连线引用不存在的节点：{', '.join(dangling[:5])}",
            impact="工作流可能无法按画布显示的方式执行。",
            recommendation="删除失效连线或恢复被引用节点后重新导出。",
        )

    if graph_has_cycle(ctx.nodes, ctx.links):
        add_finding(
            findings,
            rule_id="WF-STRUCT-CYCLE",
            severity="high",
            category="workflow-integrity",
            title="执行图包含环",
            evidence="规范化 `nodes + links` 无法完成拓扑排序。",
            impact="除非这些节点明确实现循环协议，否则可能无法稳定执行或重复消费未来数据。",
            recommendation="确认循环是否由专用循环节点管理；普通节点之间应改成无环数据流。",
        )

    if isinstance(ctx.litegraph.get("nodes"), list) and len(ctx.litegraph["nodes"]) != len(ctx.nodes):
        add_finding(
            findings,
            rule_id="WF-STRUCT-NODE-MISMATCH",
            severity="medium",
            category="workflow-integrity",
            title="规范化节点与 LiteGraph 节点数量不一致",
            evidence=f"nodes={len(ctx.nodes)}，litegraph.nodes={len(ctx.litegraph['nodes'])}。",
            impact="审计所见的执行配置可能与用户画布不完全一致。",
            recommendation="重新保存并导出；修复前同时人工核对 `nodes` 和 `litegraph.nodes`。",
        )


def graph_has_cycle(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> bool:
    ids = {n.get("uuid") for n in nodes if n.get("uuid")}
    indegree = {node_id: 0 for node_id in ids}
    adjacency: dict[Any, list[Any]] = defaultdict(list)
    for link in links:
        prev, nxt = link.get("previous_node_uuid"), link.get("next_node_uuid")
        if prev in ids and nxt in ids:
            adjacency[prev].append(nxt)
            indegree[nxt] += 1
    queue = deque(k for k, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return bool(ids) and visited != len(ids)


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def audit_backtest_nodes(ctx: AuditContext, findings: list[Finding]) -> None:
    backtests = [node for node in ctx.nodes if BACKTEST_NODE_RE.search(node_name(node))]
    if not backtests:
        add_finding(
            findings,
            rule_id="WF-EVIDENCE-NO-BACKTEST",
            severity="info",
            category="evidence",
            title="未发现回测节点",
            evidence="节点名称中没有 `*BacktestControl`。",
            impact="若这是因子工作流，应依赖因子分析证据；若这是策略工作流，则缺少经验验证入口。",
            recommendation="根据工作流目的连接相应的回测或因子分析节点。",
        )
        return

    for node in backtests:
        static = node.get("static_input_data", {})
        label = node_label(node)
        code = static.get("code")
        if not isinstance(code, str) or not code.strip():
            linked_code = any(
                link.get("next_node_uuid") == node.get("uuid")
                and link.get("input_field_name") in {"code", "strategy_code"}
                for link in ctx.links
            )
            if not linked_code:
                add_finding(
                    findings,
                    rule_id="WF-BACKTEST-NO-CODE",
                    severity="critical",
                    category="workflow-integrity",
                    title="回测节点没有策略代码输入",
                    evidence=f"{label} 的静态 code 为空，且没有 code 输入连线。",
                    impact="该节点无法执行可复核的策略。",
                    recommendation="连接 CodeControl 或在回测节点中提供完整策略代码。",
                    node=label,
                )

        start, end = parse_date(static.get("start_date")), parse_date(static.get("end_date"))
        if start and end and end > start:
            days = (end - start).days
            if days < 366:
                severity = "high"
                title = "回测区间不足一年"
            elif days < 730:
                severity = "medium"
                title = "回测区间不足两年"
            else:
                severity = "info"
                title = "工作流只声明了一个回测区间"
            add_finding(
                findings,
                rule_id="WF-BACKTEST-SINGLE-WINDOW",
                severity=severity,
                category="validation-design",
                title=title,
                evidence=f"{label}: {static.get('start_date')} 至 {static.get('end_date')}，约 {days} 天。",
                impact="单一区间无法证明策略跨市场阶段稳定，也无法区分调参样本与最终检验样本。",
                recommendation="至少增加时间顺序样本外区间；更进一步使用 walk-forward，并封存最终测试集。",
                node=label,
            )
        elif static.get("start_date") or static.get("end_date"):
            add_finding(
                findings,
                rule_id="WF-BACKTEST-BAD-DATE",
                severity="high",
                category="workflow-integrity",
                title="回测日期无法解析",
                evidence=f"{label}: start_date={static.get('start_date')!r}, end_date={static.get('end_date')!r}。",
                impact="无法确认样本长度和时间顺序。",
                recommendation="使用 YYYYMMDD 格式且保证结束日期晚于开始日期。",
                node=label,
            )

        if numeric_value(static.get("slippage")) == 0:
            add_finding(
                findings,
                rule_id="WF-EXECUTION-ZERO-SLIPPAGE",
                severity="medium",
                category="execution-realism",
                title="滑点假设为零",
                evidence=f"{label}: slippage=0。",
                impact="交易频繁、流动性较弱或多标的同时调仓时，回测表现可能被系统性高估。",
                recommendation="使用可解释的非零基准，并对至少三档滑点做敏感性测试。",
                node=label,
            )
        if numeric_value(static.get("commission_rate")) == 0:
            add_finding(
                findings,
                rule_id="WF-EXECUTION-ZERO-COMMISSION",
                severity="high",
                category="execution-realism",
                title="佣金倍率为零",
                evidence=f"{label}: commission_rate=0。",
                impact="净收益和最优调仓频率可能被显著高估。",
                recommendation="恢复市场适用的基础佣金，并进行成本压力测试。",
                node=label,
            )


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iter_code_nodes(ctx: AuditContext) -> Iterable[tuple[dict[str, Any], str, str]]:
    seen: set[tuple[str, str]] = set()
    for node in ctx.nodes:
        static = node.get("static_input_data") if isinstance(node.get("static_input_data"), dict) else {}
        for field in ("code", "custom_code"):
            code = static.get(field) or node.get(field)
            if isinstance(code, str) and code.strip():
                key = (str(node.get("uuid") or node.get("litegraph_id")), code)
                if key not in seen:
                    seen.add(key)
                    yield node, field, code


def audit_python_code(ctx: AuditContext, findings: list[Finding]) -> None:
    code_count = 0
    for node, field, code in iter_code_nodes(ctx):
        code_count += 1
        label = node_label(node)
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            add_finding(
                findings,
                rule_id="WF-CODE-SYNTAX",
                severity="critical",
                category="code-correctness",
                title="Python 代码无法解析",
                evidence=f"{label}.{field} 第 {exc.lineno} 行：{exc.msg}。",
                impact="策略或因子节点无法可靠运行，其他静态检查也不完整。",
                recommendation="先修复语法错误，再重新运行审计。",
                node=label,
            )
            continue
        signals = PythonSignals()
        signals.visit(tree)
        if signals.negative_shifts:
            add_finding(
                findings,
                rule_id="WF-CODE-NEGATIVE-SHIFT",
                severity="critical",
                category="data-leakage",
                title="发现负向 shift，疑似直接使用未来数据",
                evidence=f"{label}.{field} 行 {format_lines(signals.negative_shifts)}。",
                impact="负向 shift 会把未来观测移动到当前行，通常导致前视偏差。",
                recommendation="改成只使用当前时点可获得的数据；通常应使用正向 lag，并明确标签与特征时间。",
                node=label,
            )
        handle_orders = [line for _, line, fn in signals.order_calls if fn == "handle_data"]
        signal_lines = signals.rolling_lines + signals.rank_lines + signals.bar_price_reads
        if handle_orders and signal_lines and not signals.has_lag_operation:
            evidence_lines = sorted(set(handle_orders + signal_lines))
            add_finding(
                findings,
                rule_id="WF-CODE-SAME-BAR-RISK",
                severity="high",
                category="data-leakage",
                title="当期信号与当期下单存在时序泄漏风险",
                evidence=f"{label}.{field} 同时包含当期信号计算（滚动/排序/当期 bar 价格读取）与 handle_data 下单，相关行 {format_lines(evidence_lines)}，未发现显式正向 lag。",
                impact="若当日收盘数据用于当日可成交价格，回测会使用现实中下单时尚不可知的信息。",
                recommendation="明确引擎撮合时点；将信号至少滞后一根 bar，或使用下一交易时点成交并写入测试。",
                node=label,
            )
        tunables = [
            item
            for item in signals.context_parameters + signals.module_parameters
            if is_research_tunable(item[0], item[1])
        ]
        if len(tunables) >= 8:
            examples = ", ".join(f"{name}={short_value(value)}" for name, value, _ in tunables[:8])
            add_finding(
                findings,
                rule_id="WF-CODE-MANY-TUNABLES",
                severity="high" if len(tunables) >= 15 else "medium",
                category="research-flexibility",
                title="策略包含较多可调研究决策",
                evidence=f"{label}.{field} 识别到至少 {len(tunables)} 个常量或 context 参数，例如 {examples}。",
                impact="参数、阈值和权重越多，在同一历史区间反复修改时越容易拟合噪声。",
                recommendation="登记所有试验版本；做参数邻域稳定性与组件消融；保留未查看的最终样本外区间。",
                node=label,
            )
        universe_symbols = signals.symbol_literals | signals.future_symbol_literals
        if len(universe_symbols) >= 5:
            symbols = ", ".join(sorted(universe_symbols)[:8])
            add_finding(
                findings,
                rule_id="WF-CODE-HARDCODED-UNIVERSE",
                severity="high",
                category="selection-bias",
                title="代码硬编码了标的池",
                evidence=f"{label}.{field} 包含 {len(universe_symbols)} 个证券或期货品种代码，例如 {symbols}。",
                impact="如果标的是看到完整历史表现后挑选，简单买入持有也会产生严重选择偏差。",
                recommendation="记录股票池形成日期、可复现选择规则和退市样本；用形成日之后的数据验证。",
                node=label,
            )
        if signals.data_calls_in_initialize:
            calls = ", ".join(f"{name}@{line}" for name, line in signals.data_calls_in_initialize[:5])
            add_finding(
                findings,
                rule_id="WF-CODE-IMPLICIT-DATA",
                severity="medium",
                category="reproducibility",
                title="策略初始化时隐式加载外部数据",
                evidence=f"{label}.{field}: {calls}。",
                impact="工作流文件没有固定数据快照时，同一文件未来重跑可能得到不同输入，也难以证明 point-in-time 可得性。",
                recommendation="记录数据源、查询区间、复权方式、获取时间与快照哈希；优先通过显式上游节点传入数据。",
                node=label,
            )
        if signals.random_calls and not signals.seed_calls:
            add_finding(
                findings,
                rule_id="WF-CODE-UNSEEDED-RANDOM",
                severity="medium",
                category="reproducibility",
                title="使用随机过程但未固定随机种子",
                evidence=f"{label}.{field} 随机调用行 {format_lines(signals.random_calls)}。",
                impact="重复回测结果不可复现，差异可能被误解为策略变化。",
                recommendation="在研究入口固定种子，并在报告中记录种子与软件版本。",
                node=label,
            )
        if signals.broad_excepts:
            add_finding(
                findings,
                rule_id="WF-CODE-BROAD-EXCEPT",
                severity="low",
                category="auditability",
                title="代码捕获了过宽的异常",
                evidence=f"{label}.{field} 行 {format_lines(signals.broad_excepts)}。",
                impact="数据缺失或下单失败可能被降级成日志后继续运行，使回测结果看似完整。",
                recommendation="只捕获可恢复异常；不可恢复的数据或交易错误应让回测失败并进入审计报告。",
                node=label,
            )
    if code_count == 0:
        add_finding(
            findings,
            rule_id="WF-CODE-NOT-AVAILABLE",
            severity="high",
            category="evidence",
            title="工作流中没有可审计的策略或因子代码",
            evidence="未在 `static_input_data.code`、`custom_code` 或 LiteGraph properties 中发现非空代码。",
            impact="无法检查未来函数、选股规则、参数自由度和下单时序。",
            recommendation="使用包含代码的完整导出文件，或通过 API 获取带 custom_code 的工作流。",
        )


def is_research_tunable(name: str, value: Any) -> bool:
    ignored = {"account", "account_id", "warned", "day_count", "last_rebalance_day"}
    if any(token in name.lower() for token in ignored):
        return False
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return False


def short_value(value: Any, limit: int = 28) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_lines(lines: Iterable[int]) -> str:
    unique = sorted(set(lines))
    shown = ", ".join(str(line) for line in unique[:12])
    return shown + ("…" if len(unique) > 12 else "")


def audit_factor_nodes(ctx: AuditContext, findings: list[Finding]) -> None:
    factor_nodes = [node for node in ctx.nodes if FACTOR_NODE_RE.search(node_name(node))]
    for node in factor_nodes:
        name = node_name(node)
        static = node.get("static_input_data") if isinstance(node.get("static_input_data"), dict) else {}
        label = node_label(node)
        if "Analysis" in name:
            settings = {
                key: static.get(key)
                for key in ("adjustment_cycle", "group_number", "factor_direction", "stock_pool")
                if key in static
            }
            add_finding(
                findings,
                rule_id="WF-FACTOR-SINGLE-CONFIG",
                severity="medium",
                category="validation-design",
                title="因子分析只记录了单组配置",
                evidence=f"{label}: {json.dumps(settings, ensure_ascii=False, default=str)}。",
                impact="单一调仓周期、分组数和股票池无法说明因子在邻近设定下是否稳定。",
                recommendation="至少比较多个持有期、股票池和分组数，并检查 IC 稳定性、单调性、换手与衰减。",
                node=label,
            )


def audit_evidence(ctx: AuditContext, findings: list[Finding]) -> None:
    valid_output = False
    for node in ctx.nodes:
        static = node.get("static_input_data") if isinstance(node.get("static_input_data"), dict) else {}
        candidates = [node.get("output_db_id"), static.get("task_id"), static.get("backtest_id")]
        if any(normalize_placeholder(value) not in PLACEHOLDER_OUTPUTS for value in candidates):
            valid_output = True
            break
    if not valid_output:
        add_finding(
            findings,
            rule_id="WF-EVIDENCE-NO-RUN-OUTPUT",
            severity="high",
            category="evidence",
            title="导出文件不包含可用运行结果",
            evidence="所有 output_db_id、task_id 和 backtest_id 均为空或占位值。",
            impact="无法计算收益稳定性、样本外退化、DSR、PBO 或多重检验修正。",
            recommendation="补充工作流运行输出；在线模式可读取 run snapshot 与 output，离线模式可附带收益和交易明细。",
        )
    add_finding(
        findings,
        rule_id="WF-EVIDENCE-UNKNOWN-TRIALS",
        severity="info",
        category="evidence",
        title="工作流没有记录完整试验次数",
        evidence="PandaAI 导出格式描述当前配置，但不包含所有已尝试参数、因子变体和人工修改次数。",
        impact="即使最终回测很好，也无法修正多重检验和人工数据窥探造成的选择偏差。",
        recommendation="维护 append-only 研究日志，记录每次配置、代码哈希、样本区间和结果；将历史版本数仅视为试验次数下界。",
    )


def normalize_placeholder(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def workflow_kind(ctx: AuditContext) -> str:
    names = [node_name(n) for n in ctx.nodes]
    has_backtest = any(BACKTEST_NODE_RE.search(name) for name in names)
    has_factor = any(FACTOR_NODE_RE.search(name) for name in names)
    if has_backtest and has_factor:
        return "mixed"
    if has_backtest:
        return "strategy"
    if has_factor:
        return "factor"
    return "unknown"


def summarize(ctx: AuditContext, findings: list[Finding]) -> dict[str, Any]:
    findings.sort(key=lambda item: (SEVERITY_ORDER[item.severity], item.rule_id, item.node or ""))
    counts = Counter(item.severity for item in findings)
    valid_output = not any(item.rule_id == "WF-EVIDENCE-NO-RUN-OUTPUT" for item in findings)
    evidence_level = "single-run-reference" if valid_output else "static-only"
    # static_risk 只度量文件内可核实的缺陷；证据缺失由 verdict 和 evidence_level 表达，
    # evidence 类 finding 不参与计分，否则任何纯静态导出都会被推到 high。
    scored = Counter(item.severity for item in findings if item.category != "evidence")
    high_risk = scored["critical"] > 0 or scored["high"] >= 2
    static_risk = "high" if high_risk else "medium" if scored["high"] or scored["medium"] >= 3 else "low"
    verdict = "insufficient-evidence" if not valid_output else (
        "highly-fragile" if scored["critical"] else "fragile" if scored["high"] >= 2 else "mixed"
    )
    return {
        "schema_version": "1.0",
        "tool": "pandaai-workflow-audit",
        "source": ctx.source_path,
        "workflow": {
            "name": ctx.raw.get("name") or "",
            "format_version": ctx.raw.get("format_version") or "",
            "kind": workflow_kind(ctx),
            "node_count": len(ctx.nodes),
            "link_count": len(ctx.links),
        },
        "assessment": {
            "verdict": verdict,
            "static_risk": static_risk,
            "overfit_risk": "unassessable" if not valid_output else "not-computed",
            "evidence_level": evidence_level,
            "finding_counts": {key: counts.get(key, 0) for key in SEVERITY_ORDER},
        },
        "findings": [asdict(item) for item in findings],
        "limitations": [
            "Static review does not prove future performance.",
            "A workflow export does not reveal every experiment the researcher tried.",
            "Statistical overfitting tests require returns and, ideally, a trial matrix.",
        ],
    }


def audit(path: Path) -> dict[str, Any]:
    ctx = load_workflow(path)
    findings: list[Finding] = []
    audit_structure(ctx, findings)
    audit_backtest_nodes(ctx, findings)
    audit_python_code(ctx, findings)
    audit_factor_nodes(ctx, findings)
    audit_evidence(ctx, findings)
    return summarize(ctx, findings)


def render_markdown(report: dict[str, Any]) -> str:
    workflow = report["workflow"]
    assessment = report["assessment"]
    lines = [
        f"# PandaAI 工作流文件审计：{workflow['name'] or '未命名工作流'}",
        "",
        "## 结论",
        "",
        f"- 审计结论：`{assessment['verdict']}`",
        f"- 静态脆弱性：`{assessment['static_risk']}`",
        f"- 统计过拟合风险：`{assessment['overfit_risk']}`",
        f"- 证据等级：`{assessment['evidence_level']}`",
        f"- 类型：`{workflow['kind']}`；节点 {workflow['node_count']} 个，连线 {workflow['link_count']} 条",
        "",
        "> 这里的结论是研究审计，不是未来收益预测。没有收益序列和完整试验历史时，不能证明策略未过拟合。",
        "",
        "## Findings",
        "",
    ]
    findings = report["findings"]
    if not findings:
        lines.append("没有发现静态问题；这不等于已经证明研究可信。")
    for index, item in enumerate(findings, 1):
        location = f" — {item['node']}" if item.get("node") else ""
        lines.extend(
            [
                f"### {index}. [{item['severity'].upper()}] {item['title']}{location}",
                "",
                f"- 规则：`{item['rule_id']}`",
                f"- 证据：{item['evidence']}",
                f"- 影响：{item['impact']}",
                f"- 优化：{item['recommendation']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 已知限制",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review a PandaAI workflow JSON like code review, without executing it."
    )
    parser.add_argument("workflow", type=Path, help="PandaAI exported workflow JSON")
    parser.add_argument("--json-out", type=Path, help="write machine-readable audit JSON")
    parser.add_argument("--markdown-out", type=Path, help="write human-readable Markdown report")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="stdout format (default: markdown)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit(args.workflow)
    except (OSError, ValueError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2

    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown = render_markdown(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    print(json_text if args.format == "json" else markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
