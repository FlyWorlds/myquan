# B12 v3 数据接口说明

## ⚠️ v3 Breaking Changes（对调用方影响）

1. **拒绝 NaN / inf / bool**：`pnl_pct`、`price`、`available_cash` 遇到 NaN/inf → `ValueError`；bool → `TypeError`。`sellable_qty` / `locked_qty` / `max_qty` 拒绝 `bool`
2. **time 交易时段校验（默认开启）**：`time` 必须在品种交易时段内，否则 `ValueError`。回测/离线场景可传 `session_check=False` 关闭
3. **强平/全平「平到 0」**：不再走 round_lot；A股 `target_qty = locked_qty`（保留 T+1 锁仓），T+0 品种 `target_qty = 0`
4. **新增可选入参 `max_qty`**：目标仓位上限；加仓时先按 `max_qty - total` 截断，再校验现金
5. **输出新增 5 顶层字段**：`market` / `sellable` / `cash_req` / `flags` / `capped_by_max_qty`。8 基础字段保持不变
6. **`reason` 前缀 `[MARKET][sellable=N][cash_req=X]` deprecated**：保留一版（`common.INCLUDE_REASON_PREFIX = True` 控制），下版删除。**请立即改用顶层字段解析结构化数据**

## 数据来源

本 BUILD 为**调用型**，不依赖外部数据拉取，由调用方传入标准结构化数据。

## 输入格式

```python
# 单条（dict）
{
    "code":           str,          # 品种代码（A股/ETF/期货/港股）
    "pnl_pct":        float,        # 浮盈亏，小数形式（0.01=+1%）；拒绝 NaN/inf/bool
    "sellable_qty":   int,          # 可卖数量（>=0）；拒绝 bool
    "locked_qty":     int,          # 锁仓数量（>=0），A股/ETF=今日 T+1 锁定；T+0 品种填 0
    "price":          float,        # 现价（>0）；拒绝 NaN/inf/bool
    "available_cash": float,        # 可用现金/保证金（>=0）；拒绝 NaN/inf/bool
    "time":           str,          # 当前时间 "HH:MM"（HH 0-23, MM 0-59，且需在交易时段内）
    "max_qty":        int | None,   # v3 新增，可选；目标仓位上限（sellable_qty 同单位）
}

# 批量（list of dict）
[
    {"code": "IF2406", "pnl_pct":  0.015, "sellable_qty": 2, "locked_qty": 0,
     "price": 4000.0,  "available_cash": 200000, "time": "10:00"},
    ...
]
```

## `run()` 函数签名

```python
run(input_data, config=None, session_check: bool = True) -> list[dict]
```

| 参数 | 说明 |
|---|---|
| `input_data` | dict 或 list of dict |
| `config` | 保留参数，暂未使用 |
| `session_check` | 是否校验 `time` 在品种交易时段内（默认 True） |

## 交易时段白名单

| market | 交易时段 |
|---|---|
| A_STOCK / A_ETF | 09:30-11:30, 13:00-14:57 |
| INDEX_FUTURE | 09:30-11:30, 13:00-15:00 |
| COMMODITY_FUTURE | 09:00-10:15, 10:30-11:30, 13:30-15:00（不含夜盘） |
| HK_STOCK | 09:30-12:00, 13:00-16:00 |
| UNKNOWN | 不校验 |

## 输出格式

**基础 8 字段（v1/v2 兼容，字段名/语义不变）**

```python
{
    "code":        str,    # 品种代码
    "pnl_pct":     float,  # 浮盈亏（原样返回）
    "current_qty": int,    # 总持仓 = sellable_qty + locked_qty
    "time":        str,    # 时间（原样返回）
    "action":      str,    # "buy" / "sell" / "hold"
    "qty_change":  int,    # 正=加仓，负=减仓，0=不动
    "target_qty":  int,    # 目标持仓
                           #  - A股/ETF 强平/全平: target_qty = locked_qty（保留 T+1 锁仓）
                           #  - T+0 品种强平/全平: target_qty = 0
                           #  - 加仓/砍半:         current_qty ± qty_change
    "reason":      str,    # 触发原因（人类可读文本；v3 默认仍带 [MARKET][sellable=N][cash_req=X] 前缀，deprecated）
}
```

**v3 新增 5 顶层字段（结构化元数据，替代 reason 前缀）**

```python
{
    "market":            str,        # A_STOCK / A_ETF / INDEX_FUTURE / COMMODITY_FUTURE / HK_STOCK / UNKNOWN
    "sellable":          int,        # 决策实际用的可卖数量（T+1 品种=sellable_qty，T+0 品种=sellable_qty+locked_qty）
    "cash_req":          float,      # 加仓所需现金/保证金；未触发或非加仓分支为 0.0
    "flags":             list[str],  # 结构化标签（见下）
    "capped_by_max_qty": bool,       # 是否触发 max_qty 封顶
}
```

## flags 语义

| flag | 触发场景 |
|---|---|
| `force_close` | 到达品种强平时间触发强平 |
| `stop_loss_full` | 浮亏 >= 1% 触发全平止损 |
| `stop_loss_half` | 浮亏 >= 0.5% 触发砍半止损 |
| `add_position` | 浮盈 > 1% 触发加仓 |
| `t1_blocked` | A股/ETF 因 T+1 锁仓部分被阻断 |
| `cash_insufficient` | 加仓因现金/保证金不足降级为 hold |
| `capped_by_max_qty` | 加仓被 max_qty 封顶（截断或完全阻断） |
| `unknown_market` | 未识别品种，直接 hold |
| `lot_short` | 砍半/加仓计算数量不足一手 |

**flags 优先顺序**：当 max_qty 与现金同时不足时，**先命中 max_qty 截断**，`flags` 只含 `["add_position", "capped_by_max_qty"]`，不含 `cash_insufficient`。

## reason 前缀（deprecated，保留一版）

v2 曾把 market / sellable / cash_req 编码进 reason 前缀：

```
[<MARKET>][sellable=<N>][cash_req=<X>] <动作描述>
```

v3 保留此前缀（模块级开关 `common.INCLUDE_REASON_PREFIX = True`），但**已不推荐解析**，请改用顶层字段。下一版将默认关闭。关闭方式：

```python
import common
common.INCLUDE_REASON_PREFIX = False
```

## 品种识别规则

| 输入示例 | 识别为 | 备注 |
|---|---|---|
| 600036 / 000001 / 300750 / 688981 | A_STOCK | 6 位数字按号段判 |
| 510300 / 159919 / 588000 | A_ETF | 6 位数字按 ETF 号段判 |
| sh600036 / sz000001 | A_STOCK | 剥离前缀后按 6 位判 |
| IF2406 / IC2406 / IH2406 / IM2406 | INDEX_FUTURE | 必须 4 位 |
| rb2410 / cu2406 / au2412 | COMMODITY_FUTURE | 小写字母 + 数字，需命中规格表白名单 |
| 00700 / 02800 / 09988 | HK_STOCK | 5 位数字 |
| HK00700 | HK_STOCK | 带 HK 前缀 |
| ABCD / 123 / FOO | UNKNOWN | 一律 hold（flags 含 `unknown_market`） |

## 调用示例

```python
from scripts.build import run

# 多品种批量
positions = [
    {"code": "600036", "pnl_pct":  0.015, "sellable_qty":  800, "locked_qty":   0,
     "price": 10.0,    "available_cash": 100000, "time": "10:00", "max_qty": 1200},  # A股加仓+封顶
    {"code": "300750", "pnl_pct": -0.012, "sellable_qty":  600, "locked_qty": 400,
     "price": 100.0,   "available_cash":      0, "time": "13:00"},  # A股全平 T+1 阻断
    {"code": "IF2406", "pnl_pct":  0.015, "sellable_qty":    2, "locked_qty":   0,
     "price": 4000.0,  "available_cash": 200000, "time": "10:00"},  # IF 加仓
    {"code":  "00700", "pnl_pct": -0.007, "sellable_qty":  200, "locked_qty":   0,
     "price": 400.0,   "available_cash":      0, "time": "10:00"},  # 港股砍半 T+0
]
for order in run(positions):
    if order["market"] == "UNKNOWN" or "unknown_market" in order["flags"]:
        continue
    print(order["code"], order["action"], order["qty_change"], order["flags"])
```

## 约束说明

- `pnl_pct` 使用小数形式，不是百分比整数（1% 传 `0.01`）
- `time` 必须是 `HH:MM` 格式（v2 起不再接受 `HH:MM:SS`；v3 起默认校验交易时段）
- 持仓数据由调用方提供 `sellable_qty + locked_qty`（可卖 + 锁仓），BUILD 不维护持仓状态
- 资金占用近似计算（A股/港股=现金+手续费，期货=保证金+手续费）；不计印花税、过户费等细项
- v3 仅支持多头持仓；空头/双向未在 roadmap

## 异常

| 异常 | 触发条件 |
|---|---|
| `TypeError` | `input_data` 非 dict/list；item 非 dict；`code` 非字符串；`pnl_pct` 非数值；`pnl_pct` / `price` / `available_cash` / `sellable_qty` / `locked_qty` / `max_qty` 为 `bool` |
| `KeyError`  | item 缺 7 个必填字段中的任一 |
| `ValueError` | 空列表；qty 为负；price <= 0；available_cash < 0；code 为空；`time` 格式错、越界（HH>23 或 MM>59）、非交易时段（`session_check=True` 时）；`pnl_pct` / `price` / `available_cash` 为 NaN/inf；`max_qty` 为负 |
