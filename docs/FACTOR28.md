# 因子28 · 紫阳真君（席位龙虎榜近 3 个月池）

> 研究用途，不构成投资建议。  
> 注册表见 [`strategy/README.md`](../strategy/README.md)；挂载 **策略十七·紫阳真君**。

**最后更新**：2026-09-16

---

## 定义

- **席位**：国泰海通证券股份有限公司武汉紫阳东路证券营业部（历史亦称**国泰君安**武汉紫阳东路；东财营业部代码 `10026937`）
- **口径**：该营业部在龙虎榜明细中近 **90 日**出现过买或卖的股票并集
- **排序**：上榜日数 ↓、买入额 ↓、净买额 ↓
- **标签**：b7 席位库民间映射「消闲派」（**非官方认定**）
- **产物**：`backtest/strategy17_ziyang/picks_3m.json`（明细 CSV：`seat_trades_3m.csv`）
- **数据源**：东方财富营业部交易明细（与 akshare `stock_lhb_yyb_detail_em` 同口径）；应急/研究可用，正式若接 panda_data 可再对齐 `get_lhb_detail`

## 与策略十七的关系

| 步骤 | 说明 |
|------|------|
| 选股 | 因子28 近3个月席位成交池（本因子） |
| 自选池 | `SELF_WATCHLIST_PICKS` 公共自选（Tab 展示并入；**不入**默认四槽交易） |
| 买/卖规则 | 同策略十六内核：因子26 + 因子2；因子22 默认关 |
| 默认交易 | **否**（默认仍为策略十六）；本策略为盯盘叠加池 |

## 真源

- `strategy/ziyang_universe.py`
- `strategy/factors/factor28.py`
- 挖池：`python backtest/strategy17_ziyang/mine_ziyang_lhb.py` 或 `python strategy/run_ziyang_pool.py`
