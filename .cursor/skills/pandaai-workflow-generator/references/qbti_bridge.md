# QBTI 桥接 (QBTI Bridge)

## 解决什么问题

`skill-pandaai-workflow-generator` 的 Core workflow 第 1 步假设"用户的策略或因子设计"已经存在——它是一个**装配工具**，不是一个**引导工具**。如果用户根本不知道自己想要什么策略（"我不懂量化但想试试"），这个 skill 单独用不上。

[skill-qbti](https://github.com/quantskills/skill-qbti) 正是为这个场景设计的：五组趣味问答摸清风险承受力、参与度、因子口味、行业偏好、持有周期，产出结构化的 `strategy_brief.json`。但 QBTI 自己的下游是通用回测流水线（`skill-factor-evaluate` / `skill-backtest` / `skill-backtest-overfit`），并不认识 PandaAI 的 LiteGraph 工作流格式——两个 skill 之间原本没有桥梁，`strategy_brief.json` 里的抽象字段（因子标签、持仓约束、调仓频率）需要人工翻译成具体的模板选择和 Python 代码，才能变成一份可导入 PandaAI 官网的工作流。

`scripts/from_qbti_brief.py` 就是这座桥：读入 `strategy_brief.json`，确定性翻译成一份 `complex_stock_selection` 工作流 JSON，一条命令完成。

```bash
python scripts/from_qbti_brief.py --brief <path/to/strategy_brief.json> --out <output.json>
```

可选参数：`--start-date`/`--end-date`/`--start-capital`/`--standard-symbol`（覆盖默认回测区间与基准）、`--keep-code <path>`（把生成的策略代码另存一份供人工审查）。

## 为什么统一路由到 complex_stock_selection

QBTI 的 `factor_affinity`（对应 `strategy_brief.json` 的 `factor_family_tags`）长度是 1–3 不固定，而 `multi_factor_analysis` 模板的节点拓扑是死的（固定 3 个 `FactorBuildProControl`、2 个 `FormulaControl`、3 个 `FactorWeightAdjustControl`）。把 1–3 个可变数量的因子家族硬套进一个固定节点数的图里，要么要在没测试过的情况下瞎猜怎么"占位"多余的槽位，要么要在运行时对节点数做判断——两者都比直接把因子家族翻译成 Python 打分逻辑、注入 `complex_stock_selection` 的单个 `CodeControl` 节点脆弱得多。`complex_stock_selection` 本身就是"整个市场取因子快照、按条件筛选/排序"的结构，天然能装下任意数量的打分因子，是更稳的落点。

## 因子家族 → 打分公式（固定表，翻译不临场发挥）

和 QBTI 的 `preference_mapping.yaml` 同一个精神：下面这张表是唯一真源，写在 `from_qbti_brief.py` 的 `FAMILY_FUNCS` 里，不在生成时现改。每个因子返回一个分数，越高越优先买入；多个家族的分数取算术平均。

| factor_family_tags 值 | 打分逻辑 | 数据来源 |
|---|---|---|
| `momentum` | 近 20 日收益率 | `data[symbol]` 逐 bar 累积的收盘价（已验证对股票标的可靠） |
| `reversal` | 近 5 日收益率取负（跌得越多分越高） | 同上 |
| `mean_reversion` | 相对 20 日均线的偏离度取负 | 同上 |
| `low_volatility` | 近 20 日日收益率标准差取负 | 同上 |
| `quality_stable` | 营收/净利润增速的标准差取负（越稳越高） | `initialize` 里一次性预取 `panda_data.get_factor(type='stock', factors=['revenue','net_profit'])`，日期区间回溯写法沿用 `complex_stock_selection` 模板已验证过的"前1年后4年"技巧，规避 5 年区间限制报错 |

这五个都是价格/基本面驱动的朴素信号，不是经过 IC 检验的真实 Alpha 因子——QBTI 自己的正式流水线（`skill-quant-factor-*-alpha` 因子库 + `skill-factor-evaluate`）才是有检验依据的因子来源。这份小公式表的定位是"让 PandaAI 里能有一版可以立刻导入回测、看得懂持仓变化的起始策略"，不是替代那条正式流水线。

## 其它字段映射

| `strategy_brief.json` 字段 | 映射到 | 备注 |
|---|---|---|
| `position_constraints.max_position_pct` | 单票资金分配比例 + 持仓只数 `TOP_N = max(3, min(15, round(100/max_position_pct)))` | 仓位上限直接决定组合能装下多少只标的 |
| `position_constraints.stop_loss_discipline` | 机械止损阈值：`hard_stop_tight`→8%、`hard_stop_wide`→15%、`soft_review`/`none_ride_through`→不设机械止损 | **这组百分比是 generator 自己定的合理默认值，不是 QBTI 映射表给出的**——QBTI 的表只到定性纪律级别，没有具体数字 |
| `rebalance_frequency` | 调仓间隔交易日数：`weekly`→5、`biweekly`→10、`monthly`→20、`quarterly`→60 | 行业惯例近似值，非平台特定实测值 |
| `universe_filters.preferred_sectors` / `excluded_sectors` | 标的名称关键词过滤（见下表） | **近似匹配，不是严谨的行业分类**——用 `get_stock_detail` 返回的股票名称做关键词包含判断，不是行业代码join |
| `universe_filters.exclude_st_and_risk_flags` | 剔除名称含 "ST" 的标的 | 同样是名称层面的近似判断 |

### 板块关键词表（`sector_enum` → 名称关键词，近似匹配）

| sector_enum | 关键词 |
|---|---|
| `consumer_staples` | 食品、饮料、家电 |
| `consumer_discretionary` | 汽车、零售、社会服务、商贸 |
| `healthcare` | 医药、医疗、生物 |
| `technology` | 电子、计算机、通信、软件 |
| `financials` | 银行、证券、保险、金融 |
| `industrials` | 机械、电力设备、军工、国防 |
| `materials` | 化工、有色、钢铁、建材 |
| `energy` | 煤炭、石油、石化 |
| `utilities` | 公用事业、环保、燃气、水务 |
| `real_estate` | 地产、置业、房地产 |
| `agriculture` | 农业、林业、牧业、渔业 |
| `media_entertainment` | 传媒、文化、影视、游戏 |

这张表是名称关键词的近似匹配，不是申万行业分类的严谨 join——如果某只股票名称里恰好带了关键词但实际不属于该行业（或反之），会被误判。对精度要求高的场景应该用真正的行业分类接口重做这一步（本 skill 尚未验证 `get_industry_constituents`/`get_stock_industry` 在回测沙箱里的可用性，按 `references/sandbox_diagnostics.md` 的方法论，用前应先探测）。

## 版本与边界

- 脚本只认 `strategy_brief.json` 的 `schema_version: "1.0"`；版本不符会打印警告但仍尝试运行，因为字段含义可能已经变化，产出前请人工核对。
- `factor_family_tags` 出现脚本不认识的值会直接报错并列出已知家族，不会静默忽略或瞎猜映射。
- 沿用 QBTI 的措辞纪律：这是**翻译**，不是**推荐**。生成的策略只是"把问卷答案变成一份能跑的起始工作流"，不构成投资建议，也不代表这些朴素信号经过了因子有效性检验。
- 写任何代码前，仍然适用 `references/sandbox_restrictions.md`（平台代码沙箱安全限制）——`from_qbti_brief.py` 生成的代码已经过冒烟测试确认不触发黑名单，但如果你修改 `FAMILY_FUNCS`，改完要重新过一遍 `python scripts/smoke_test.py` 的第 6 组用例。
