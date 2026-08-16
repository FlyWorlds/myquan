# PandaData 接入

## 接入结论

- 模式：**直接接入**
- 可用方法：`get_future_detail`、`get_future_dominant`、`get_future_daily`、`get_future_daily_post`
- 覆盖范围：PandaData 可提供期货合约元数据、逐日主力映射、原始日线和后复权日线，能够直接构造换月账本。
- 必须补充：主力映射只是供应商口径；若用户策略按成交量、持仓量或固定日换月，仍需提供自身 roll rule 并与主力映射分开报告。

## 调用原则

1. 用户已经提供符合输入契约的 CSV 时，直接审计该文件，不为重复取数调用 PandaData。
2. 用户未提供市场数据、且任务落在上述覆盖范围时，使用兄弟 Skill `pandadata-api`。
3. 先读取 `pandadata-api/references/method-index.md`，再加载目标方法在 `api-docs.md` 中的完整参数与响应字段；不要凭记忆编造参数。
4. 先做单标的、短窗口 smoke test，检查 `shape`、列名、数据日期、单位和空结果原因，再扩大查询。
5. 将 API 结果写入新的规范化 CSV，再运行本 Skill 的分析脚本；不要在原始 DataFrame 上就地覆盖。
6. 在最终报告记录方法名、参数、查询时间、最新数据日期、原始行数、标准化行数和字段映射。

## 方法与规范字段映射

| 数据需要 | PandaData 方法/来源 | 规范化规则 |
|---|---|---|
| 合约有效期与元数据 | `get_future_detail` | `symbol`,`listed_date`,`de_listed_date`,`maturity_date` → 合约约束 |
| 逐日选择合约 | `get_future_dominant` | `date`,`underlying_symbol`,`symbol` → selected |
| 前后合约原始价格 | `get_future_daily` | 同日拉取候选合约 close → front_price/back_price |
| 供应商连续序列对照 | `get_future_daily_post` | 可选交叉检查，可能受账号权限限制；不能替代原始合约价格，也不是运行本 Skill 的前置条件 |

## 失败与降级

- SDK、凭证或服务未配置时，明确返回 `insufficient-evidence`，列出缺少的配置；不要回退到伪造数据。
- `get_future_daily_post` 无访问权限时，记录权限限制并跳过连续序列交叉检查；只要 `get_future_dominant` 与 `get_future_daily` 可用，仍可基于真实合约价格完成核心换月审计。
- 空结果时先检查交易日、日期格式、标的代码、接口窗口和必要筛选条件。
- PandaData 只覆盖部分字段时，保留已取到的市场证据，并向用户索取缺失的私有字段。
- 代理变量必须写入 `assumptions` 和 `limitations`，不得把代理指标描述为真实盘口、真实成交或完整事件历史。
