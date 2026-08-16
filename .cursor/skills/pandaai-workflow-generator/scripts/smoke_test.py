#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_workflow.py 与 from_qbti_brief.py 冒烟测试 (纯标准库)。

覆盖场景:
  1. simple_backtest: 代码注入 + 参数覆盖，双写(后端 static_input_data / 前端 litegraph properties)均生效
  2. multi_factor_analysis: 按 litegraph_id 分别覆盖三个 FactorWeightAdjustControl 权重与一个 FormulaControl 公式
  3. multi_agent_trading: 未指定目标注入代码 -> 必须报错; 指定 #11 注入 -> 只改动目标节点
  4. complex_stock_selection: 纯装配，输出合法 JSON 且顶层 ID 已重置
  5. 拼错节点类型的参数覆盖 -> 必须报错
  6. from_qbti_brief.py: 单因子/三因子组合正确生成打分函数与板块过滤；未知因子家族与空
     factor_family_tags -> 必须报错

用法: python scripts/smoke_test.py
"""

import json
import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATOR = os.path.join(SCRIPT_DIR, "generate_workflow.py")
QBTI_BRIDGE = os.path.join(SCRIPT_DIR, "from_qbti_brief.py")
TEMPLATE_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "references", "templates")

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILURES.append(label)


def run_generator(*cli_args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, GENERATOR, *cli_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def run_qbti_bridge(*cli_args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, QBTI_BRIDGE, *cli_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def backend_node(data, lg_id):
    for node in data.get("nodes", []):
        if node.get("litegraph_id") == lg_id:
            return node
    return None


def litegraph_node(data, lg_id):
    for node in data.get("litegraph", {}).get("nodes", []):
        if node.get("id") == lg_id:
            return node
    return None


def main():
    workdir = tempfile.mkdtemp(prefix="pandaai_smoke_")
    code_path = os.path.join(workdir, "dummy_strategy.py")
    marker = "# SMOKE_TEST_MARKER\nprint('hello')\n"
    with open(code_path, "w", encoding="utf-8") as f:
        f.write(marker)

    # --- 场景 1: simple_backtest 代码注入 + 参数覆盖双写 ---
    print("[1] simple_backtest: 代码注入 + 参数覆盖")
    out1 = os.path.join(workdir, "out_simple.json")
    r = run_generator(
        "--template", "simple_backtest",
        "--code-file", code_path,
        "--param-json", json.dumps(
            {"StockBacktestControl": {"start_date": "20240101", "end_date": "20241231"}}),
        "--out", out1)
    check("装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = load(out1)
        template = load(os.path.join(TEMPLATE_DIR, "simple_backtest.json"))
        cc = backend_node(data, 3)
        bt = backend_node(data, 1)
        check("后端 CodeControl.code 已注入", cc["static_input_data"]["code"] == marker)
        check("前端 CodeControl 属性 '策略代码' 已同步",
              litegraph_node(data, 3)["properties"].get("策略代码") == marker)
        check("后端 start_date 已覆盖", bt["static_input_data"]["start_date"] == "20240101")
        check("前端属性 '回测开始时间' 已同步",
              litegraph_node(data, 1)["properties"].get("回测开始时间") == "20240101")
        check("顶层 ID 已重置", data.get("id") and data["id"] != template.get("id"))

    # --- 场景 2: multi_factor_analysis 按 litegraph_id 分别覆盖 ---
    print("[2] multi_factor_analysis: 按 #litegraph_id 分别覆盖权重与公式")
    out2 = os.path.join(workdir, "out_mfa.json")
    formula = "RANK((HIGH / DELAY(LOW, 5)) - 1)"
    r = run_generator(
        "--template", "multi_factor_analysis",
        "--param-json", json.dumps({
            "FactorWeightAdjustControl#9": {"weight": 5},
            "FactorWeightAdjustControl#14": {"weight": 3},
            "FactorWeightAdjustControl#15": {"weight": 1},
            "FormulaControl#1": {"formulas": formula},
        }),
        "--out", out2)
    check("装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = load(out2)
        weights = {lg: backend_node(data, lg)["static_input_data"]["weight"] for lg in (9, 14, 15)}
        check("三个权重节点分别生效", weights == {9: 5, 14: 3, 15: 1}, str(weights))
        check("后端 FormulaControl#1 公式已覆盖",
              backend_node(data, 1)["static_input_data"]["formulas"] == formula)
        check("前端属性 '公式' 已同步",
              litegraph_node(data, 1)["properties"].get("公式") == formula)
        check("FormulaControl#10 未被误改",
              backend_node(data, 10)["static_input_data"]["formulas"]
              == "RANK((OPEN / DELAY(CLOSE, 20)) - 1)")

    # --- 场景 3: multi_agent_trading 多 CodeControl ---
    print("[3] multi_agent_trading: 未指定目标必须报错; 指定 #11 只改目标节点")
    out3 = os.path.join(workdir, "out_mat.json")
    r = run_generator("--template", "multi_agent_trading",
                      "--code-file", code_path, "--out", out3)
    check("未指定目标时报错退出", r.returncode != 0)
    check("报错信息包含定位指引", "CodeControl#" in r.stderr, r.stderr)

    template = load(os.path.join(TEMPLATE_DIR, "multi_agent_trading.json"))
    original_19 = backend_node(template, 19)["static_input_data"]["code"]
    r = run_generator("--template", "multi_agent_trading",
                      "--code-file", f"CodeControl#11={code_path}", "--out", out3)
    check("指定目标装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = load(out3)
        check("目标节点 #11 代码已注入",
              backend_node(data, 11)["static_input_data"]["code"] == marker)
        check("非目标节点 #19 未被改动",
              backend_node(data, 19)["static_input_data"]["code"] == original_19)

    # --- 场景 4: complex_stock_selection 纯装配 ---
    print("[4] complex_stock_selection: 纯装配输出合法 JSON")
    out4 = os.path.join(workdir, "out_css.json")
    r = run_generator("--template", "complex_stock_selection", "--out", out4)
    check("装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        template = load(os.path.join(TEMPLATE_DIR, "complex_stock_selection.json"))
        data = load(out4)
        check("顶层 ID 已重置", data.get("id") and data["id"] != template.get("id"))

    # --- 场景 5: 拼错节点类型 ---
    print("[5] 拼错节点类型的参数覆盖必须报错")
    r = run_generator("--template", "simple_backtest",
                      "--param-json", json.dumps({"StockBackTestControl": {"start_date": "20240101"}}),
                      "--out", os.path.join(workdir, "out_typo.json"))
    check("0 匹配时报错退出", r.returncode != 0)

    # --- 场景 6: from_qbti_brief.py ---
    print("[6] from_qbti_brief.py: 单因子/三因子组合 + 未知家族与空家族报错")

    def write_brief(path, **overrides):
        brief = {
            "schema_version": "1.0",
            "factor_family_tags": ["momentum"],
            "universe_filters": {"preferred_sectors": [], "excluded_sectors": [],
                                 "exclude_st_and_risk_flags": True},
            "position_constraints": {"max_position_pct": 10, "stop_loss_discipline": "soft_review"},
            "rebalance_frequency": "monthly",
        }
        brief.update(overrides)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False)

    brief1 = os.path.join(workdir, "brief_single.json")
    write_brief(brief1, factor_family_tags=["low_volatility"],
               position_constraints={"max_position_pct": 8, "stop_loss_discipline": "hard_stop_wide"},
               universe_filters={"preferred_sectors": [], "excluded_sectors": ["real_estate"],
                                 "exclude_st_and_risk_flags": True})
    out_q1 = os.path.join(workdir, "out_qbti_single.json")
    r = run_qbti_bridge("--brief", brief1, "--out", out_q1)
    check("单因子(low_volatility)装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = load(out_q1)
        cc = backend_node(data, next(
            n["litegraph_id"] for n in data["nodes"] if n["name"] == "CodeControl"))
        code = cc["static_input_data"]["code"]
        check("只含选中家族的打分函数", "_score_low_volatility" in code and "_score_momentum" not in code)
        check("板块排除关键词已注入", "地产" in code)
        check("止损阈值按 hard_stop_wide 映射为 0.15", "STOP_LOSS_PCT = 0.15" in code)

    brief3 = os.path.join(workdir, "brief_triple.json")
    write_brief(brief3, factor_family_tags=["momentum", "reversal", "quality_stable"])
    out_q3 = os.path.join(workdir, "out_qbti_triple.json")
    r = run_qbti_bridge("--brief", brief3, "--out", out_q3)
    check("三因子组合装配成功", r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = load(out_q3)
        cc = backend_node(data, next(
            n["litegraph_id"] for n in data["nodes"] if n["name"] == "CodeControl"))
        code = cc["static_input_data"]["code"]
        check("三个打分函数均已注入",
              all(f in code for f in ("_score_momentum", "_score_reversal", "_score_quality_stable")))
        check("quality_stable 触发了 get_factor 预取块", "context.quality_scores" in code
              and "get_factor" in code)

    brief_unknown = os.path.join(workdir, "brief_unknown.json")
    write_brief(brief_unknown, factor_family_tags=["nonexistent_family"])
    r = run_qbti_bridge("--brief", brief_unknown, "--out", os.path.join(workdir, "out_unknown.json"))
    check("未知因子家族报错退出", r.returncode != 0)

    brief_empty = os.path.join(workdir, "brief_empty.json")
    write_brief(brief_empty, factor_family_tags=[])
    r = run_qbti_bridge("--brief", brief_empty, "--out", os.path.join(workdir, "out_empty.json"))
    check("空 factor_family_tags 报错退出", r.returncode != 0)

    print()
    if FAILURES:
        print(f"冒烟测试失败: {len(FAILURES)} 项未通过")
        sys.exit(1)
    print("冒烟测试全部通过。")


if __name__ == "__main__":
    main()
