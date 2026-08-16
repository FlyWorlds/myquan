#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PandaAI 工作流自动装配与生成脚本 (纯标准库实现)

节点定位符 (target) 语法:
  "CodeControl"      匹配所有该类型的节点
  "CodeControl#11"   匹配 litegraph_id 为 11 的该类型节点
  "#11"              匹配 litegraph_id 为 11 的任意节点
"""

import os
import sys
import json
import argparse
import uuid

# 默认模板映射关系
TEMPLATE_MAP = {
    "simple_backtest": "simple_backtest.json",
    "complex_stock_selection": "complex_stock_selection.json",
    "multi_factor_analysis": "multi_factor_analysis.json",
    "multi_agent_trading": "multi_agent_trading.json"
}


def load_json_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_template_path(template_arg):
    # 1. 检查是否是内置简称
    if template_arg in TEMPLATE_MAP:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base_dir, "references", "templates", TEMPLATE_MAP[template_arg])
        if os.path.exists(path):
            return path

    # 2. 作为直接路径检查
    if os.path.exists(template_arg):
        return template_arg

    raise FileNotFoundError(f"未找到指定的模板文件: {template_arg}")


def parse_target(target_key):
    """
    解析节点定位符，返回 (node_type, litegraph_id)，两者均可为 None。
    """
    if "#" in target_key:
        type_part, _, id_part = target_key.partition("#")
        try:
            lg_id = int(id_part)
        except ValueError:
            raise ValueError(f"节点定位符 '{target_key}' 中 '#' 之后必须是 litegraph 节点 id 数字")
        return (type_part or None), lg_id
    return target_key, None


def find_nodes(workflow_data, node_type, lg_id):
    matched = []
    for node in workflow_data.get("nodes", []):
        if node_type and not (node.get("name") == node_type or node.get("type") == node_type):
            continue
        if lg_id is not None and node.get("litegraph_id") != lg_id:
            continue
        matched.append(node)
    return matched


def describe_nodes(workflow_data, node_type=None):
    """列出模板中的节点，用于报错提示。"""
    lines = []
    for node in workflow_data.get("nodes", []):
        name = node.get("name") or node.get("type")
        if node_type and name != node_type:
            continue
        lines.append(f"  {name}#{node.get('litegraph_id')}")
    return "\n".join(lines)


def find_litegraph_node(workflow_data, lg_id):
    for lg_node in workflow_data.get("litegraph", {}).get("nodes", []):
        if lg_node.get("id") == lg_id:
            return lg_node
    return None


def set_node_fields(workflow_data, node, fields):
    """
    将字段值同时写入后端 static_input_data 和前端 litegraph 的 properties。
    litegraph 属性键为中文显示名，通过 inputs[].fieldName -> name 映射获得。
    """
    static_input = node.setdefault("static_input_data", {})
    for field, value in fields.items():
        static_input[field] = value

    lg_node = find_litegraph_node(workflow_data, node.get("litegraph_id"))
    if lg_node is None:
        print(f"警告: 节点 litegraph_id={node.get('litegraph_id')} 在 litegraph 中不存在，"
              f"仅更新了后端 static_input_data。", file=sys.stderr)
        return

    props = lg_node.setdefault("properties", {})
    field_to_display = {}
    for inp in lg_node.get("inputs", []) or []:
        field_name = inp.get("fieldName")
        if field_name:
            field_to_display[field_name] = inp.get("name")

    for field, value in fields.items():
        display_name = field_to_display.get(field)
        if display_name:
            props[display_name] = value
        else:
            # 没有找到对应的中文显示名时，用英文 field 兜底写入，前端可能不识别
            print(f"警告: 节点 {node.get('name')}#{node.get('litegraph_id')} 的字段 '{field}' "
                  f"没有对应的 litegraph 输入映射，已按英文键写入 properties。", file=sys.stderr)
            props[field] = value


def parse_code_file_arg(arg):
    """
    解析 --code-file 参数，返回 (target_or_None, file_path)。
    支持 'path'、'CodeControl#11=path'、'#11=path' 三种写法。
    """
    if "=" in arg:
        target_part, _, path_part = arg.partition("=")
        try:
            node_type, lg_id = parse_target(target_part.strip())
        except ValueError:
            return None, arg
        if lg_id is not None or (node_type and node_type.endswith("Control")):
            return target_part.strip(), path_part.strip()
    return None, arg


def apply_code_overrides(workflow_data, code_specs):
    """
    将 Python 代码注入指定的 CodeControl 节点。
    code_specs: [(target_or_None, code_content)]
    """
    for target, code_content in code_specs:
        if target is None:
            nodes = find_nodes(workflow_data, "CodeControl", None)
            if not nodes:
                raise ValueError("模板中不存在 CodeControl 节点，无法注入代码。")
            if len(nodes) > 1:
                raise ValueError(
                    "模板中存在多个 CodeControl 节点，未指定目标时无法注入（会互相覆盖）。\n"
                    "请使用 --code-file 'CodeControl#<litegraph_id>=<path>' 分别指定：\n"
                    + describe_nodes(workflow_data, "CodeControl"))
        else:
            node_type, lg_id = parse_target(target)
            nodes = find_nodes(workflow_data, node_type or "CodeControl", lg_id)
            if len(nodes) != 1:
                raise ValueError(
                    f"代码注入目标 '{target}' 匹配到 {len(nodes)} 个节点（应为 1 个）。模板中的节点：\n"
                    + describe_nodes(workflow_data))

        for node in nodes:
            set_node_fields(workflow_data, node, {"code": code_content})
            print(f"已将代码注入节点 {node.get('name')}#{node.get('litegraph_id')}。", file=sys.stderr)


def apply_parameter_overrides(workflow_data, overrides):
    """
    根据节点定位符覆盖参数并同步到 LiteGraph 属性。
    overrides 格式: { "<target>": { "fieldName": value } }
    """
    if not overrides:
        return

    for target, params in overrides.items():
        node_type, lg_id = parse_target(target)
        nodes = find_nodes(workflow_data, node_type, lg_id)
        if not nodes:
            raise ValueError(
                f"参数覆盖目标 '{target}' 未匹配到任何节点，请检查拼写。模板中的节点：\n"
                + describe_nodes(workflow_data))

        for node in nodes:
            set_node_fields(workflow_data, node, params)

        print(f"参数覆盖: '{target}' 匹配到 {len(nodes)} 个节点，已同步更新后端与前端属性。", file=sys.stderr)


def regenerate_workflow_id(workflow_data):
    """
    重新生成顶层工作流 ID，防止重复导入时在 MongoDB 中发生 ID 冲突。
    """
    new_id = uuid.uuid4().hex[:24]
    workflow_data["id"] = new_id
    if "_id" in workflow_data:
        workflow_data["_id"] = new_id
    print(f"已重置工作流 ID 为: {new_id}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="PandaAI 工作流文件自动装配器 (Generator)")
    parser.add_argument("--template", required=True,
                        help="内置模板简称 (simple_backtest, complex_stock_selection, "
                             "multi_factor_analysis, multi_agent_trading) 或模板 JSON 路径")
    parser.add_argument("--code-file", action="append", default=[],
                        help="要嵌入 CodeControl 的 Python 代码文件。可重复传入。"
                             "模板中有多个 CodeControl 时必须写成 'CodeControl#<litegraph_id>=<path>'")
    parser.add_argument("--param-json",
                        help="要覆盖的节点参数，JSON 字符串或 JSON 文件路径。"
                             "格式 {\"<节点定位符>\": {\"字段\": 值}}，定位符支持 'Type'、'Type#<id>'、'#<id>'")
    parser.add_argument("--out", required=True, help="生成的 JSON 文件输出路径")

    args = parser.parse_args()

    try:
        # 1. 解析模板文件路径
        template_path = resolve_template_path(args.template)
        print(f"正在加载模板: {template_path}", file=sys.stderr)
        workflow_data = load_json_file(template_path)

        # 2. 读取代码文件内容
        code_specs = []
        for code_arg in args.code_file:
            target, code_path = parse_code_file_arg(code_arg)
            if not os.path.exists(code_path):
                raise FileNotFoundError(f"未找到代码文件: {code_path}")
            with open(code_path, 'r', encoding='utf-8') as f:
                code_specs.append((target, f.read()))

        # 3. 解析参数覆盖
        overrides = {}
        if args.param_json:
            try:
                overrides = json.loads(args.param_json)
            except json.JSONDecodeError:
                if os.path.exists(args.param_json):
                    overrides = load_json_file(args.param_json)
                else:
                    raise ValueError(f"param-json 无法解析为有效 JSON，"
                                     f"且未找到对应的配置文件路径: {args.param_json}")

        # 4. 执行代码注入与参数改写
        apply_code_overrides(workflow_data, code_specs)
        apply_parameter_overrides(workflow_data, overrides)

        # 5. 重置工作流 ID (规避 MongoDB 重复 ID 无法入库的报错)
        regenerate_workflow_id(workflow_data)

        # 6. 保存新工作流文件
        save_json_file(workflow_data, args.out)
        print(f"成功生成 PandaAI 工作流文件: {args.out}", file=sys.stderr)

    except Exception as e:
        print(f"装配工作流发生错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
