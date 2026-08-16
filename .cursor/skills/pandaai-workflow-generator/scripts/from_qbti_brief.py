#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 skill-qbti 产出的 strategy_brief.json 确定性翻译为 PandaAI complex_stock_selection
策略代码，并调用 generate_workflow.py 完成最终装配。

设计原则（与 skill-qbti 的 preference_mapping.yaml 一致）：翻译，不临场发挥。
因子家族 -> 打分公式、板块 -> 关键词的映射都是本文件顶部的固定表，不在生成时改写。
字段来源与取舍说明见 references/qbti_bridge.md。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_workflow as gw  # noqa: E402

SUPPORTED_BRIEF_SCHEMA = "1.0"

# ---------------------------------------------------------------
# 因子家族 -> 打分函数源码（固定表）。每个函数签名统一为
# (context, symbol, history) -> float | None，分数越高越优先买入。
# 除 quality_stable 外均只用逐 bar 累积的收盘价序列 history，不额外请求数据。
# ---------------------------------------------------------------
FAMILY_FUNCS = {
    "momentum": (
        "def _score_momentum(context, symbol, history):\n"
        '    """动量：近 20 日收益率，越高越好。"""\n'
        "    if len(history) < 21:\n"
        "        return None\n"
        "    past, latest = history[-21], history[-1]\n"
        "    if past <= 0:\n"
        "        return None\n"
        "    return latest / past - 1.0\n"
    ),
    "reversal": (
        "def _score_reversal(context, symbol, history):\n"
        '    """短期反转：近 5 日收益率取负，跌得越多分越高。"""\n'
        "    if len(history) < 6:\n"
        "        return None\n"
        "    past, latest = history[-6], history[-1]\n"
        "    if past <= 0:\n"
        "        return None\n"
        "    return -(latest / past - 1.0)\n"
    ),
    "mean_reversion": (
        "def _score_mean_reversion(context, symbol, history):\n"
        '    """均值回归：相对20日均线的偏离度取负，越低于均线分越高。"""\n'
        "    if len(history) < 20:\n"
        "        return None\n"
        "    window = history[-20:]\n"
        "    ma = sum(window) / len(window)\n"
        "    if ma <= 0:\n"
        "        return None\n"
        "    return -(history[-1] / ma - 1.0)\n"
    ),
    "low_volatility": (
        "def _score_low_volatility(context, symbol, history):\n"
        '    """低波动：近20日日收益率标准差取负，波动越低分越高。"""\n'
        "    if len(history) < 21:\n"
        "        return None\n"
        "    window = history[-21:]\n"
        "    rets = []\n"
        "    for i in range(1, len(window)):\n"
        "        if window[i - 1] > 0:\n"
        "            rets.append(window[i] / window[i - 1] - 1.0)\n"
        "    if len(rets) < 2:\n"
        "        return None\n"
        "    mean_r = sum(rets) / len(rets)\n"
        "    var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)\n"
        "    return -(var_r ** 0.5)\n"
    ),
    "quality_stable": (
        "def _score_quality_stable(context, symbol, history):\n"
        '    """质量稳定：营收/净利润增速的负标准差，越稳越高（来自 initialize 预取的 get_factor 数据）。"""\n'
        "    return context.quality_scores.get(symbol)\n"
    ),
}

# ---------------------------------------------------------------
# QBTI sector_enum -> 名称关键词（近似匹配，非严谨行业分类，见 qbti_bridge.md）
# ---------------------------------------------------------------
SECTOR_NAME_KEYWORDS = {
    "consumer_staples": ["食品", "饮料", "家电"],
    "consumer_discretionary": ["汽车", "零售", "社会服务", "商贸"],
    "healthcare": ["医药", "医疗", "生物"],
    "technology": ["电子", "计算机", "通信", "软件"],
    "financials": ["银行", "证券", "保险", "金融"],
    "industrials": ["机械", "电力设备", "军工", "国防"],
    "materials": ["化工", "有色", "钢铁", "建材"],
    "energy": ["煤炭", "石油", "石化"],
    "utilities": ["公用事业", "环保", "燃气", "水务"],
    "real_estate": ["地产", "置业", "房地产"],
    "agriculture": ["农业", "林业", "牧业", "渔业"],
    "media_entertainment": ["传媒", "文化", "影视", "游戏"],
}

# rebalance_frequency -> 约等价交易日数（行业惯例近似值，非平台特定实测值）
REBALANCE_DAYS = {"weekly": 5, "biweekly": 10, "monthly": 20, "quarterly": 60}

# stop_loss_discipline -> 单票机械止损阈值（generator 自定的合理默认值，非 QBTI 映射表给出）
STOP_LOSS_PCT = {
    "hard_stop_tight": 0.08,
    "hard_stop_wide": 0.15,
    "soft_review": None,
    "none_ride_through": None,
}


def load_brief(path):
    with open(path, "r", encoding="utf-8") as f:
        brief = json.load(f)
    if brief.get("schema_version") != SUPPORTED_BRIEF_SCHEMA:
        print(
            f"警告：strategy_brief.json 的 schema_version 为 "
            f"{brief.get('schema_version')!r}，本脚本按 {SUPPORTED_BRIEF_SCHEMA!r} 编写，"
            f"字段含义可能已变化，请核对后再用。",
            file=sys.stderr,
        )
    return brief


def keyword_list(sectors):
    keywords = []
    for sector in sectors or []:
        keywords.extend(SECTOR_NAME_KEYWORDS.get(sector, []))
    return sorted(set(keywords))


def build_strategy_code(brief):
    families = brief.get("factor_family_tags") or []
    unknown = [f for f in families if f not in FAMILY_FUNCS]
    if unknown:
        raise ValueError(
            f"strategy_brief.json 中的 factor_family_tags 含未知家族 {unknown}，"
            f"本脚本只认识 {sorted(FAMILY_FUNCS)}，请更新 FAMILY_FUNCS 固定表后再运行。"
        )
    if not families:
        raise ValueError("strategy_brief.json 的 factor_family_tags 为空，无法生成打分逻辑。")

    universe_filters = brief.get("universe_filters") or {}
    position_constraints = brief.get("position_constraints") or {}
    rebalance_frequency = brief.get("rebalance_frequency", "monthly")
    max_position_pct = position_constraints.get("max_position_pct", 10)
    stop_loss_discipline = position_constraints.get("stop_loss_discipline", "soft_review")
    exclude_st = bool(universe_filters.get("exclude_st_and_risk_flags", True))

    preferred_keywords = keyword_list(universe_filters.get("preferred_sectors"))
    excluded_keywords = keyword_list(universe_filters.get("excluded_sectors"))
    rebalance_days = REBALANCE_DAYS.get(rebalance_frequency, 20)
    stop_loss_pct = STOP_LOSS_PCT.get(stop_loss_discipline)
    top_n = max(3, min(15, round(100 / max_position_pct))) if max_position_pct else 10

    score_funcs_src = "\n".join(FAMILY_FUNCS[f] for f in families)
    score_func_refs = ", ".join(f"_score_{f}" for f in families)
    needs_quality = "quality_stable" in families

    quality_init_block = ""
    if needs_quality:
        quality_init_block = '''
    # quality_stable 打分需要的营收/净利润增长稳定性，一次性预取（做法沿用
    # complex_stock_selection 模板已验证的 5 年区间回溯写法，避开日期范围报错）。
    today = datetime.datetime.now().strftime('%Y%m%d')
    try:
        base_date = str(context.now)
    except Exception:
        base_date = today
    base_dt = datetime.datetime.strptime(base_date, '%Y%m%d')
    start_dt = base_dt - datetime.timedelta(days=365)
    end_dt = base_dt + datetime.timedelta(days=4 * 365)
    q_start, q_end = start_dt.strftime('%Y%m%d'), end_dt.strftime('%Y%m%d')

    context.quality_scores = {}
    if hasattr(panda_data, "get_factor"):
        try:
            df_factor = panda_data.get_factor(
                start_date=q_start, end_date=q_end, symbol=universe,
                factors=["revenue", "net_profit"], type="stock")
        except Exception as e:
            df_factor = None
            print(f"quality_stable 因子获取异常：{e}")
        if df_factor is not None and len(df_factor) > 0:
            for symbol, group in df_factor.groupby("symbol"):
                group = group.sort_values("date")
                vals = []
                for col in ("revenue", "net_profit"):
                    if col not in group.columns:
                        continue
                    series = group[col].astype(float).ffill().pct_change().dropna()
                    vals.extend(series.tolist())
                if len(vals) >= 2:
                    mean_v = sum(vals) / len(vals)
                    var_v = sum((v - mean_v) ** 2 for v in vals) / len(vals)
                    context.quality_scores[symbol] = -(var_v ** 0.5)
    print(f"quality_stable 打分覆盖 {len(context.quality_scores)} 个标的")
'''
    else:
        quality_init_block = "    context.quality_scores = {}\n"

    imports_block = "from panda_backtest.api.api import *\nimport panda_data\n"
    if needs_quality:
        imports_block += "import datetime\n"

    code = f'''"""QBTI 驱动的多因子选股策略（由 skill-qbti 的 strategy_brief.json 确定性生成）。

因子家族：{families}
调仓周期：{rebalance_frequency}（约 {rebalance_days} 个交易日）
单票仓位上限：{max_position_pct}%，等权持有前 {top_n} 只打分最高的标的
止损纪律：{stop_loss_discipline}（{"机械止损 " + format(stop_loss_pct, ".0%") if stop_loss_pct else "无机械止损，靠调仓周期自然轮换"}）
偏好板块关键词：{preferred_keywords or "（无限制）"}
剔除板块关键词：{excluded_keywords or "（无）"}
是否剔除 ST：{exclude_st}

本文件由 scripts/from_qbti_brief.py 从 strategy_brief.json 确定性翻译生成，
翻译规则见 skill-pandaai-workflow-generator/references/qbti_bridge.md。
本策略仅供研究与教育参考，不构成投资建议，历史表现不代表未来收益。
"""

{imports_block}
TOP_N = {top_n}
REBALANCE_DAYS = {rebalance_days}
MAX_POSITION_PCT = {max_position_pct}
STOP_LOSS_PCT = {stop_loss_pct!r}
PREFERRED_NAME_KEYWORDS = {preferred_keywords!r}
EXCLUDED_NAME_KEYWORDS = {excluded_keywords!r}
EXCLUDE_ST = {exclude_st!r}


# ---- 因子家族打分函数（固定表生成，见 from_qbti_brief.py 的 FAMILY_FUNCS） ----
{score_funcs_src}

SCORE_FUNCS = [{score_func_refs}]


def initialize(context):
    context.account = '15032863'
    context.bar_count = 0
    context.entry_price = {{}}

    stock_list_df = panda_data.get_stock_detail(symbol="", fields=["symbol", "name"], market="cn", status=1)
    if stock_list_df is None or stock_list_df.empty:
        raise ValueError("获取全市场股票列表失败，请检查数据服务")

    universe = []
    for _, row in stock_list_df.iterrows():
        try:
            sym = str(row["symbol"])
            name = str(row["name"]) if row.get("name") is not None else ""
        except Exception:
            continue
        if EXCLUDE_ST and "ST" in name.upper():
            continue
        if PREFERRED_NAME_KEYWORDS and not any(kw in name for kw in PREFERRED_NAME_KEYWORDS):
            continue
        if EXCLUDED_NAME_KEYWORDS and any(kw in name for kw in EXCLUDED_NAME_KEYWORDS):
            continue
        universe.append(sym)

    if not universe:
        raise ValueError("板块过滤后标的池为空，请放宽 preferred_sectors/excluded_sectors")

    context.universe = universe
    context.price_history = {{s: [] for s in universe}}
    print(f"QBTI 策略初始化完成，过滤后标的池共 {{len(universe)}} 个")
{quality_init_block}

def handle_data(context, data):
    context.bar_count += 1

    for symbol in context.universe:
        close = None
        try:
            bar = data[symbol]
            if bar is not None and bar.close is not None and bar.close > 0:
                close = float(bar.close)
        except Exception:
            close = None
        history = context.price_history[symbol]
        if close is not None:
            history.append(close)
        elif history:
            history.append(history[-1])
        if len(history) > 30:
            del history[: len(history) - 30]

    account = context.stock_account_dict.get(context.account)
    if account is None:
        return

    # 止损检查：每个 bar 都做，不等到调仓日才发现亏损过深
    if STOP_LOSS_PCT is not None:
        for symbol, pos in list(account.positions.items()):
            entry = context.entry_price.get(symbol)
            history = context.price_history.get(symbol)
            if not entry or not history or pos.sellable <= 0:
                continue
            latest = history[-1]
            if latest / entry - 1.0 <= -STOP_LOSS_PCT:
                try:
                    order_shares(context.account, symbol, -int(pos.sellable), style=MarketOrderStyle)
                    print(f"[{{context.now}}] 止损卖出 {{symbol}}，跌幅 {{latest / entry - 1.0:.2%}}")
                    context.entry_price.pop(symbol, None)
                except Exception as e:
                    print(f"[{{context.now}}] 止损卖出 {{symbol}} 失败：{{e}}")

    if context.bar_count % REBALANCE_DAYS != 1:
        return

    scored = []
    for symbol in context.universe:
        history = context.price_history[symbol]
        parts = [f(context, symbol, history) for f in SCORE_FUNCS]
        parts = [p for p in parts if p is not None]
        if not parts:
            continue
        scored.append((symbol, sum(parts) / len(parts)))

    if not scored:
        print(f"[{{context.now}}] 打分数据不足，跳过调仓")
        return

    scored.sort(key=lambda kv: kv[1], reverse=True)
    target = [s for s, _ in scored[:TOP_N]]
    print(f"[{{context.now}}] 目标持仓（共 {{len(scored)}} 只有效打分）: {{target}}")

    for symbol in list(account.positions.keys()):
        if symbol in target:
            continue
        pos = account.positions.get(symbol)
        if pos is None or pos.sellable <= 0:
            continue
        try:
            order_shares(context.account, symbol, -int(pos.sellable), style=MarketOrderStyle)
            context.entry_price.pop(symbol, None)
        except Exception as e:
            print(f"[{{context.now}}] 卖出 {{symbol}} 失败：{{e}}")

    total_value = account.total_value
    if total_value <= 0:
        return
    cash_per_stock = total_value * (MAX_POSITION_PCT / 100.0)

    for symbol in target:
        pos = account.positions.get(symbol)
        if pos is not None and pos.quantity > 0:
            continue
        history = context.price_history[symbol]
        price = history[-1] if history else None
        if not price or price <= 0:
            continue
        buy_num = int(cash_per_stock / price / 100) * 100
        if buy_num <= 0:
            continue
        try:
            order_shares(context.account, symbol, buy_num, style=MarketOrderStyle)
            context.entry_price[symbol] = price
            print(f"[{{context.now}}] 买入 {{symbol}} {{buy_num}} 股 @ {{price:.2f}}")
        except Exception as e:
            print(f"[{{context.now}}] 买入 {{symbol}} 失败：{{e}}")


def before_trading(context):
    pass


def after_trading(context):
    account = context.stock_account_dict.get(context.account)
    if account:
        print(f"[{{context.now}}] 总资产: {{account.total_value:.2f}} 持仓数: {{len(account.positions)}}")
'''
    return code


def main():
    parser = argparse.ArgumentParser(
        description="将 skill-qbti 的 strategy_brief.json 翻译为 PandaAI complex_stock_selection 工作流")
    parser.add_argument("--brief", required=True, help="skill-qbti 产出的 strategy_brief.json 路径")
    parser.add_argument("--out", required=True, help="生成的 JSON 工作流输出路径")
    parser.add_argument("--start-date", default="20250101", help="回测开始日期 YYYYMMDD")
    parser.add_argument("--end-date", default="20260630", help="回测结束日期 YYYYMMDD")
    parser.add_argument("--start-capital", type=int, default=1000000, help="初始资金")
    parser.add_argument("--standard-symbol", default="沪深300", help="基准指数")
    parser.add_argument("--keep-code", help="可选：把生成的策略代码另存一份到该路径，便于人工审查")
    args = parser.parse_args()

    try:
        brief = load_brief(args.brief)
        code = build_strategy_code(brief)

        if args.keep_code:
            with open(args.keep_code, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"策略代码已另存: {args.keep_code}", file=sys.stderr)

        template_path = gw.resolve_template_path("complex_stock_selection")
        workflow_data = gw.load_json_file(template_path)

        gw.apply_code_overrides(workflow_data, [(None, code)])
        gw.apply_parameter_overrides(workflow_data, {
            "StockBacktestControl": {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "start_capital": args.start_capital,
                "standard_symbol": args.standard_symbol,
            }
        })
        gw.regenerate_workflow_id(workflow_data)
        gw.save_json_file(workflow_data, args.out)
        print(f"成功生成 PandaAI 工作流文件: {args.out}", file=sys.stderr)

    except Exception as e:
        print(f"从 strategy_brief.json 生成工作流失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
