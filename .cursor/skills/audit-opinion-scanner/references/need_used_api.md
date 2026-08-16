# panda_data — Audit Opinion Scanner Skill 使用的 API

以下 4 个 API 是本 skill 所依赖的全部数据接口。字段名与参数格式与 `panda_data_api_doc.md` 原文一致。

> **全局约定**
> - 日期格式统一 `YYYYMMDD` 字符串
> - 季度格式统一 `YYYYqN`（如 `2024q4`）
> - 股票代码带交易所后缀：`.SH` / `.SZ`
> - `panda_data` 为私有包，需 `init_token(username, password)` 后使用
> - 未特别说明的响应表已省略与本 skill 无关的字段

---

**1. get_audit_opinion - 获取财务报告审计意见**

**1.1. 方法名：get_audit_opinion**

**1.2. 入参**

| 字段 | 类型 | 描述 | 是否必填 |
|:---|:---|:---|:---|
| symbol | Optional[string] | 股票代码。不传 = 全市场 | 非必填 |
| start_quarter | string | 开始季度，格式 `"YYYYqN"` | 非必填 |
| end_quarter | string | 结束季度，格式 `"YYYYqN"` | 非必填 |
| fields | Optional[string/list] | 返回字段列表，`[]` 返回全部 | 非必填 |
| market | string | 市场，默认 `"cn"` | 非必填 |

**1.3. 响应参数**

| 字段 | 类型 | 描述 |
|:---|:---|:---|
| symbol | string | 股票代码 |
| quarter | string | 报告季度，如 `"2024q4"` |
| date | string | 公告发布日，格式 `YYYYMMDD` |
| agency | string | 会计师事务所名称 |
| audit_type | string | 审计报告类型（`financial_statements` / `internal_control`） |
| opinion | string | 审计意见（`unqualified_opinion` / `no_audit_performed` / ...） |

**1.4. 使用示例**

```python
import panda_data
result = panda_data.get_audit_opinion(
    symbol="000001.SZ",
    start_quarter="2024q1",
    end_quarter="2025q3",
    market="cn",
)
print(result.head())
```

**响应示例**

```text
symbol  quarter  date  agency  audit_type  opinion
0  000001.SZ  2024q1  20240420  None  financial_statements  no_audit_performed
1  000001.SZ  2024q2  20240816  None  financial_statements  no_audit_performed
2  000001.SZ  2024q3  20241019  None  financial_statements  no_audit_performed
3  000001.SZ  2024q4  20250315  安永华明会计师事务所(特殊普通合伙)  internal_control  unqualified_opinion
4  000001.SZ  2024q4  20250315  安永华明会计师事务所(特殊普通合伙)  financial_statements  unqualified_opinion
5  000001.SZ  2025q1  20250419  None  financial_statements  no_audit_performed
```

**说明**：
- 季度报告（q1-q3）通常 `opinion = no_audit_performed`，`agency = None`
- 年报（q4）才会出现正式审计意见和会计师事务所
- `audit_type` 区分 `financial_statements`（财报审计）和 `internal_control`（内控审计）
- 默认扫描仅纳入 `financial_statements`

---

**2. get_index_weights - 获取指数权重信息数据**

**2.1. 方法名：get_index_weights**

**2.2. 入参**

| 字段 | 类型 | 描述 | 是否必填 |
|:---|:---|:---|:---|
| index_symbol | Optional[string/list] | 指数代码，如 `"000300.SH"` | 非必填 |
| stock_symbol | Optional[string/list] | 成分股代码 | 非必填 |
| start_date | string | 开始日期 | 必填 |
| end_date | string | 结束日期 | 必填 |
| fields | Optional[string/list] | 返回字段列表 | 非必填 |

**2.3. 响应参数**

| 字段 | 类型 | 描述 |
|:---|:---|:---|
| index_symbol | string | 指数代码 |
| date | string | 日期 |
| stock_symbol | string | 成分股代码 |
| weight | float | 权重 |

**2.4. 使用示例**

```python
import panda_data
result = panda_data.get_index_weights(
    index_symbol="000300.SH",
    start_date="20260729",
    end_date="20260729",
)
print(result.head())
```

---

**3. get_stock_detail - 获取股票基本信息**

**3.1. 方法名：get_stock_detail**

**3.2. 入参**

| 字段 | 类型 | 描述 | 是否必填 |
|:---|:---|:---|:---|
| symbol | string/list | 股票代码 | 非必填 |

**3.3. 响应参数（与本 skill 相关字段）**

| 字段 | 类型 | 描述 |
|:---|:---|:---|
| symbol | string | 股票代码 |
| name | string | 股票名称 |

**3.4. 使用示例**

```python
import panda_data
result = panda_data.get_stock_detail(symbol="000001.SZ")
print(result[["symbol", "name"]].head())
```

**说明**：`get_audit_opinion` 不返回股票名称，需通过此接口补充。

---

**4. get_last_trade_date - 获取最新交易日**

**4.1. 方法名：get_last_trade_date**

**4.2. 入参**

| 字段 | 类型 | 描述 | 是否必填 |
|:---|:---|:---|:---|
| exchange | Optional[string] | 交易所代码，默认 `"SH"` | 非必填 |

**4.3. 响应参数**

| 字段 | 类型 | 描述 |
|:---|:---|:---|
| date | string | 最新交易日，格式 `YYYYMMDD` |

**4.4. 使用示例**

```python
import panda_data
result = panda_data.get_last_trade_date(exchange="SH")
print(result["date"].iloc[0])
```

**说明**：用于确定指数权重查询的参考日期。
