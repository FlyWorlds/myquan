# A 股与美股 Panda Data 点时契约

## 接口路由

| 用途 | 接口 | 点时规则 |
|---|---|---|
| 全 A 股票池 | `get_stock_detail(status=None)` | `listed_date <= event_date < de_listed_date`，仅 SH/SZ |
| 原子年报 | `get_fina_reports` | `is_latest=False`，只选 `date <= signal_date` 的最新完整 Q4 行 |
| 原始日线 | `get_stock_daily` | 当前收盘价、成交参考及原始 `limit_up/limit_down` |
| 股票收益 | `get_stock_daily_post` | 后复权开收盘收益 |
| 历史行业 | `get_industry_constituents` | `in_date <= signal_date < out_date` |
| 行业名称 | `get_industry_detail` | 映射申万一级代码 |
| 审计历史 | `get_audit_opinion` | 对潜在候选取最近三财年并过滤披露日 |
| 事件与交易日 | `get_trade_cal` | 年报/季报/审计/公告/价格事件，下一开市日参考执行 |
| ETF | `get_fund_daily_post` | `510300.SH` 辅助基准，`511880.SH` 主现金腿 |
| 指数 | `get_index_daily` | `000985.SH` 全 A 主基准，`000300.SH` 仅历史对照 |

不得调用只支持港股的 operating、mktfin 或 industry-median 成品接口处理 A 股。

## 原子修订

按 `symbol + quarter` 分组，选择信号日前发布日期最晚的一整行。禁止逐字段跨修订补值。相同发布日期存在冲突时记录修订冲突和研究缺口。最新年度字段缺失时不得回退旧年度冒充当前值。

## 字段与代理

| 项目 | 字段或公式 |
|---|---|
| 归母净利润 | `is_n_income_attr_p` |
| 权益/资产 | `bs_total_hldr_eqy_exc_min_int` / `bs_total_assets` |
| 毛利与收入 | `is_gross_profit` / `is_revenue` |
| 营业利润、利润总额、所得税 | `is_operate_profit` / `is_total_profit` / `is_income_tax` |
| 经营现金流 | 优先 `cfs_net_cash_operating`，兼容 `cfs_net_cashflow_operate` |
| 资本开支代理 | `abs(cfs_cash_paid_asset)` |
| 现金等价物 | `cfs_end_cash_equiv` |
| 有息长期债务 | 长期借款、应付债券、租赁负债、一年内到期长期债务之和 |
| ROE/ROA | 当年归母净利润 / 平均权益或平均资产 |
| ROIC 代理 | NOPAT / 平均投入资本；投入资本为权益 + 有息债务 - 非负现金等价物 |
| 正常化 EPS | `min(最新基本EPS, 最近三年基本EPS中位数)` |
| 现金收益率代理 | 正常化 EPS × 截断至 0–1.2 的五年现金转换率 / 原始收盘价 |
| 新入场反稀释门槛 | 五年隐含股份稀释不超过 5%；仅限制新入场和加仓，不因单次门槛变化强制卖出健康持仓 |

全部债务字段缺失时保持缺失，禁止使用全部非流动负债替代。银行不使用普通企业现金收益代理。

## 美股接口路由

| 用途 | 接口 | 点时规则 |
|---|---|---|
| 美股日线 | `get_us_daily` | 单次区间不超过 5 年；字段使用 `symbol/date/close/pre_close` |
| 美股季度财报 | `get_fina_ex` | 单次季度区间不超过 5 年；`is_latest=False` 后按 `date <= signal_date` 过滤 |
| 美股基本信息 | `get_us_detail` | 只用于名称、行业和上市状态辅助，不替代历史成分股 |

`get_fina_ex` 返回的美股财务代码通常带 `.NB`，与 `get_us_daily` 的裸代码不一致，必须规范化后连接。年度指标只取 `fy_period` 以 `Q4` 结尾的记录；同一财年存在多次披露时保留信号日前发布日期最新的一行。

美股五维字段使用 `is_net_income`、`bs_common_equity_total`、`is_gross_profit`、`is_revenue_goods_services`、`cfs_capex_total`、`is_eps_basic_inc_exord` 和 `is_op_profit_before_non_recurring`。`get_stock_operating_metric` 是公司专属经营 KPI，不得冒充通用 ROE 或利润率来源。

当前探测结果：`get_us_daily` 对 2010-2014 返回空，对 SPY/IVV/VOO/QQQ/DIA 也返回空。2015 起固定研究池可以验证，但不得声称为 2010 起美股回测或历史标普 500。该接口没有复权收盘价或总收益字段；只对明确公司行动且价格断点吻合的拆股做校正，现金分红不计入收益。

## 状态与生产

组合状态只读取 `data_version=9.4.0` 且 `trade_date < event_date` 的状态行。首次 V9.4 由现金初始化并重放事件；随后按 `trade_date + build_id + target_id + result_type` 原子 upsert。旧版本产物只读归档，失败不得覆盖正式文件。

## 沪深 300 点时回测

对每个年度信号日调用 `get_index_weights(index_symbol="000300.SH")`，只使用 `date <= signal_date` 的最后完整 300 只截面。`--top-symbols 300` 表示每期完整成分，不表示先用最新权重选 300 只再倒推历史。当前可验证覆盖从 2017-01-03 开始；更早接口返回空时必须停止或披露缺口。

凭证只从当前子进程环境读取，立即从 `os.environ` 删除并阻止 SDK 持久化；日志、HTML、demo 和 Parquet 不得包含凭证或令牌。
