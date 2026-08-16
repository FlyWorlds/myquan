# 回测沙箱数据诊断方法论 (Sandbox Diagnostics)

## 已知限制：ETF/基金数据不支持（先看这条）

**结论（2026-07-08，全市场扫描后确定性证据，见下方事实表）：`StockBacktestControl`（股票回测）沙箱的数据仓库对 ETF/场内基金完全没有覆盖，不区分发行方、不区分代码段。** 证据链：①6 种独立查询路径对 ETF 代码 510300.SH 全部返回 0 行/空值，同一次运行里对照股 300750.SZ 全部查询成功；②全市场标的池 5203 个符号（≈全市场 A 股总数）按 20 个 ETF 常见代码前缀段（510/511/512/513/515/516/517/518/560-569/159/588）扫描命中 0 个；③按名称关键词（"ETF"/"指数"/"300"）扫描同样命中 0 个——这条排除了"代码段猜漏了、但产品其实存在于池子里"的可能，因为关键词匹配不依赖代码格式。三条证据互相独立、结论一致：这不是某一只 ETF 缺失，是整个基金/ETF 品类都不在这个账号的数据覆盖范围内。

**行动准则：只要用户提出 ETF/基金相关的策略需求（轮动、配置、追踪等），在写任何代码之前先告知这个限制**，不要生成一版策略让用户自己跑失败了才发现。直接建议替代方案：用对应风格/行业的代表性个股替换 ETF，复用已验证的股票查询链路（`get_stock_daily`、`data[symbol]`）。不再需要额外扫描确认——上面三条证据已经关闭了这个疑问。

## 为什么需要这份文档

[skill-pandadata-api](https://github.com/quantskills/skill-pandadata-api) 文档的是**公开研究环境**下的 `panda_data` SDK（218 个方法）。PandaAI 官网"股票回测"（`StockBacktestControl`）节点内运行的 `panda_data`，实测确认（2026-07-08）**不是同一个方法集合**——例如 `get_fund_daily`/`get_fund_daily_post` 在公开 SDK 文档中存在，但在回测沙箱里 `hasattr(panda_data, "get_fund_daily")` 为 `False`。

因此：**任何要在回测沙箱里访问的数据域，一旦超出四个内置模板已验证过的调用（`data[symbol]`、`panda_data.get_factor(type='stock'/'future')`、`panda_data.get_market_data(type='future')`、`panda_data.get_stock_detail`），都必须先用只读诊断跑一次，再动手写完整策略。** 不要把探测代码和交易逻辑混在同一份策略里——历史教训见下方"反面案例"。

## 反面案例：为什么混着写会浪费轮次

写 ETF 轮动策略时，探测逻辑被裹进了一版又一版全功能策略（含 `initialize`/`handle_data`/下单逻辑）里，导致：

1. 某一版探测代码写在 `initialize` 里，取不到行情时直接 `raise`——工作流在拿到诊断结果前就整体失败退出，只看到最后一次探测的报错，前面探测过的结果没打印出来看到。
2. 某一版为了列出 `panda_data` 全部方法用了 `dir(panda_data)`——触发了平台的静态安全校验（见 [sandbox_restrictions.md](sandbox_restrictions.md)），代码在**导入阶段**就被拒绝，连 `initialize` 都没跑起来，之前设计好的探测逻辑完全没有机会执行。
3. 每次探测都要走"改代码 → 装配 → 用户手动导入官网 → 跑一次回测 → 截图报错发回来"的完整循环，一次浪费的探测等于一次浪费的人工回测。

## 正确做法：先跑一个独立的只读诊断工作流

不要在实盘策略里"顺便"探测。单独生成一份**探测专用**的最小工作流，特点：

- **只读，不下单**：不调用任何 `order_*` API，出错面降到最低。
- **绝不 raise**：所有探测调用都套 `try/except`，异常打印出来但不让工作流失败退出，确保这一轮能拿到全部诊断结果，而不是卡在第一个失败点。
- **只用 `hasattr()` 探测方法存在性，不用 `dir()`**：`dir()` 在平台黑名单里，见 [sandbox_restrictions.md](sandbox_restrictions.md)。
- **设对照组**：用一个已知能正常出行情的标的（如模板样本里的 `300750.SZ`）和待验证的目标标的并排探测，用来区分"这个方法本身不可用"与"这个方法可用但这个标的没数据"两种情况——否则报错信息会含糊不清。
- **回测区间设短**（如 1-2 个月）：诊断不需要跑满全周期，缩短区间能让日志更短（避免出现十几页日志才能翻到关键行）、回测跑得更快。

### 可复用的探测代码骨架

```python
import panda_data

CONTROL_SYMBOL = "300750.SZ"   # 已知能正常出行情/成交的标的，作对照组
TEST_SYMBOL = "<待诊断的标的代码>"

CANDIDATE_METHODS = [
    # 按需从 skill-pandadata-api 的 method-index.md 里挑候选方法名
    "get_stock_daily", "get_index_daily", "get_fund_daily",
    "get_factor", "get_market_data", "get_stock_detail",
]


def _safe_call(label, fn):
    """任何异常都吞掉并打印，绝不向上抛出，保证工作流能跑完。"""
    try:
        df = fn()
        n = 0 if df is None else len(df)
        print(f"  {label}: 成功，返回 {n} 行")
    except Exception as e:
        print(f"  {label}: 异常 {type(e).__name__}: {e}")


def initialize(context):
    context.probed = False
    available = [m for m in CANDIDATE_METHODS if hasattr(panda_data, m)]
    missing = [m for m in CANDIDATE_METHODS if not hasattr(panda_data, m)]
    print(f"可用方法: {available}")
    print(f"不可用方法: {missing}")
    # 对每个可用方法，分别用 CONTROL_SYMBOL 和 TEST_SYMBOL 调用一次并打印行数
    # ...（按候选方法逐个 _safe_call，见 scripts/ 或此前生成的探针示例）


def handle_data(context, data):
    if context.probed:
        return
    context.probed = True
    for label, symbol in (("对照", CONTROL_SYMBOL), ("目标", TEST_SYMBOL)):
        try:
            bar = data[symbol]
            print(f"{label} data['{symbol}'].close = {bar.close if bar else None}")
        except Exception as e:
            print(f"{label} data['{symbol}'] 异常: {e}")


def before_trading(context):
    pass


def after_trading(context):
    pass
```

拿到诊断日志后再写正式策略——这时候用的每一个 API 调用都已经在这个具体沙箱里验证过存在且有数据，不再是从公开文档或其他模板猜测移植过来的。

## 已确认的沙箱事实（持续更新，标注日期）

| 事实 | 状态 | 验证日期 |
|---|---|---|
| `panda_data.get_fund_daily` / `get_fund_daily_post` 在回测沙箱中不存在（`hasattr` 为 `False`） | 已确认 | 2026-07-08 |
| `dir()` 触发平台静态安全校验，代码在导入阶段即被拒绝，不会执行到 `initialize` | 已确认 | 2026-07-08 |
| 场内 ETF（510300.SH 等）在 `data[symbol]` 逐 bar 行情中每 bar 均为空 | 已确认 | 2026-07-08 |
| `get_market_data(type='future')` 对期货标的可用（`multi_agent_trading` 模板内嵌代码示例） | 已确认（来自模板样本，非独立复测） | 模板编写时 |
| `get_market_data` 对 `type='stock'/'etf'/'fund'/'index'` 各值查询 ETF 代码返回空 | 已确认 | 2026-07-08 |
| `get_factor`（type=stock/fund/etf/index 四种）、`get_stock_daily`、`get_index_daily` 查询 ETF 代码（510300.SH）均返回 0 行 | 已确认（用只读诊断探针跑通，同一次运行里 `get_stock_daily` 对照股 300750.SZ 返回 36 行，`data['300750.SZ'].close` 有效值，排除了"方法本身不可用"的可能） | 2026-07-08 |
| **该 PandaAI 账号的 `get_stock_detail` 全市场标的池（5203 个符号）不含任何 510300 前缀标的** | 已确认——5203 的量级基本等于全市场 A 股数，强烈提示该账号数据仓库为纯股票覆盖，ETF/基金代码未被收录 | 2026-07-08 |
| 该账号是否对**任何**场内基金/ETF代码（20 个常见前缀段 + 名称关键词双重扫描）有覆盖 | **已确认为否**——全市场标的池 5203 个符号，代码前缀扫描命中 0 个，名称关键词（ETF/指数/300）扫描同样命中 0 个，两种独立方法互相印证 | 2026-07-08 |

**结论（2026-07-08，最终）**：该账号的股票回测环境为纯 A 股股票覆盖，**不含任何 ETF/基金数据**，证据完整、无遗留疑问。设计策略时应使用股票标的（四个内置模板已验证的路径）；用户如需"轮动/配置一篮子资产"类的策略创意，用代表性个股替代 ETF 是唯一可行路径。

如果你在使用本 skill 时又发现了新的沙箱行为差异，请在此表格追加一行，并注明验证方式与日期。不要覆盖旧行，方便追溯什么时候、用什么方法验证过。
