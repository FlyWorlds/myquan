---
name: skill-b12-intraday-position-manager
description: 当需要对日内多品种持仓做动态仓位管理时，使用此 skill。支持 A股/A股ETF/股指期货/商品期货/港股+ETF；区分 T+1/T+0、昨仓/今仓、保证金/现金，输出标准 8 字段调仓指令。
tags: [quant, skill, position-management, 仓位管理, 多品种]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-b12-intraday-position-manager
  repository_url: https://github.com/quantskills/skill-b12-intraday-position-manager
  project_type: skill
  collection: position-management
  license: GPL-3.0-only
---

# B12 v3 多品种日内仓位动态管理

## ⚠️ v3 变更公告（Breaking Changes）

如果你从 v2 升级，请重点关注以下**破坏性变更**：

1. **强平/全平「平到 0」，不再手数下取整**
   - A股/ETF：`qty_change = -sellable_qty`（允许零股清仓），`target_qty = locked_qty`（保留 T+1 锁仓）
   - 港股/期货：`qty_change = -sellable_qty`，`target_qty = 0`
   - 砍半仓/加仓仍走 round_lot 手数下取整（不变）
2. **校验加固**：`pnl_pct` / `price` / `available_cash` 拒绝 `NaN` / `inf` / `bool`；`sellable_qty` / `locked_qty` / `max_qty` 拒绝 `bool`；`time` 必须在合法交易时段内（可通过 `session_check=False` 关闭）
3. **`time` 时段白名单**：默认按 market 区分（A股 09:30-11:30 / 13:00-14:57 等），午休及盘外时间拒绝
4. **新增可选入参 `max_qty`**：目标仓位上限；加仓时先按 max_qty 截断再校验现金；封顶时返回 `hold` 且 `flags` 含 `"capped_by_max_qty"`
5. **输出新增 5 个顶层字段**：`market` / `sellable` / `cash_req` / `flags` / `capped_by_max_qty`（8 基础字段保持不变，向后兼容）
6. **`reason` 恢复为纯人类可读文本**；结构化数据改由顶层字段承载。`[MARKET][sellable=N][cash_req=X]` 前缀由模块级开关 `INCLUDE_REASON_PREFIX`（默认 `True`）控制，标记为 **deprecated**，下一版将默认关闭

## 工具定位
- 工具类型：交易执行辅助型
- 解决问题：根据浮盈亏阈值和时间窗口，按品种规则（T+1/T+0、保证金、合约乘数、可卖部分）自动生成标准化调仓指令
- 使用对象：交易 agent / 人工辅助决策 / Alpha 信号

## 维护者
- duanyong <hiduan@qq.com>
- 上游组织：QuantSkills (https://github.com/quantskills)

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现，过去的表现不预示未来结果。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束，生成的调仓指令可能因市场条件变化而无法成交或造成亏损。所有交易决策责任由使用者自行承担。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。

## 适用场景
- 日内多品种持仓监控，需对每只品种实时判断是否加仓、减仓或持有
- 收盘前按品种各自规则触发强平
- 资金不足时阻断加仓，避免越界报单

## 支持品种

| 类别 | 识别规则 | 结算 | 强平时间 | 单位 |
|---|---|---|---|---|
| A_STOCK | 6 位数字（沪/深主板/科创板/创业板）或 sh/sz 前缀 | T+1 | 14:45 | 100 股 |
| A_ETF | 510xxx / 159xxx / 588xxx 等 | T+1 | 14:45 | 100 股 |
| INDEX_FUTURE | IF/IC/IH/IM + 4 位 | T+0 | 14:45 | 1 手 |
| COMMODITY_FUTURE | rb / cu / m / au / ag / i 等小写前缀 + 数字 | T+0 | 14:45 | 1 手 |
| HK_STOCK | 5 位数字 / HK 前缀 | T+0 | 15:45 | 按表（默认 100） |
| UNKNOWN | 其他 | — | — | 一律 hold |

## 交易窗口参考

B12 在 `run()` 调用时会按 `market` 校验 `time` 是否在**连续竞价时段**内；不在则抛 `ValueError`。可通过 `session_check=False` 关闭。

### 当前允许调用的窗口（连续竞价）

| 市场 | 允许调用窗口 | 强平触发 (`force_close_time`) | 备注 |
|---|---|---|---|
| A_STOCK / A_ETF | `09:30-11:30` / `13:00-14:57` | `14:45` | 14:57-15:00 收盘集合竞价**不在窗口内**（见下方注意事项） |
| INDEX_FUTURE | `09:30-11:30` / `13:00-15:00` | `14:45` | 09:25-09:30 开盘集合竞价**不在窗口内** |
| COMMODITY_FUTURE | `09:00-10:15` / `10:30-11:30` / `13:30-15:00` | `14:45` | 08:55-09:00 开盘集合竞价、夜盘时段**不在窗口内** |
| HK_STOCK | `09:30-12:00` / `13:00-16:00` | `15:45` | 09:00-09:30 开盘竞价、16:00-16:10 收盘竞价**不在窗口内** |
| UNKNOWN | 无校验 | — | 未识别品种直接返回 hold |

### 关于集合竞价的行为

**B12 v3 目前不接受集合竞价时段的调用**，原因：
1. 集合竞价期间的价格是**参考价 / 匹配价**，与连续竞价的可成交价语义不同
2. 集合竞价挂单规则（可否撤单、订单类型）与连续竞价不同，B12 生成的调仓指令语义不匹配
3. 收盘集合竞价（14:57-15:00）**理论上强平应能挂单**，当前 v3 未支持——若需要，请设置 `session_check=False` 并自行判断

**调用方推荐做法**：
- **开盘竞价**：不要调用 B12，等首笔连续竞价成交后再喂
- **收盘竞价**：如果需要在 14:57-15:00 期间挂集合竞价单清仓，`session_check=False` 调用 B12 拿到目标数量，但订单类型需自行标记为集合竞价单
- **午休期间**：不要调用 B12（`sellable_qty` 无实际意义）

### 政策变更时如何修改交易窗口

各市场交易窗口是**中央配置**，集中在 `scripts/build.py` 顶部的 `_TRADING_SESSIONS` 常量中。当交易所修改交易时段（如延长午间交易、调整收盘时间）时，**修改这一处即可**，不需要改动任何决策逻辑代码。

**修改位置**：`scripts/build.py`

```python
_TRADING_SESSIONS = {
    "A_STOCK":          [("09:30", "11:30"), ("13:00", "14:57")],
    "A_ETF":            [("09:30", "11:30"), ("13:00", "14:57")],
    "INDEX_FUTURE":     [("09:30", "11:30"), ("13:00", "15:00")],
    "COMMODITY_FUTURE": [("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00")],
    "HK_STOCK":         [("09:30", "12:00"), ("13:00", "16:00")],
}
```

**规则**：
1. Value 是 `list[tuple[str, str]]`，每个 tuple 是一个 `(start_hhmm, end_hhmm)` 闭区间
2. 时间格式必须严格为 `"HH:MM"`（两位小时 + 冒号 + 两位分钟，24 小时制）
3. 一个市场可以有**多段**窗口（如 A 股上下午两段、商品期货三段）
4. `_check_trading_session` 采用**字符串按字典序比较**（等价于时间数值比较，因为格式固定），命中任一段即通过
5. 未在此表中列出的 market key（如 `UNKNOWN`）**跳过校验**（不抛异常）

**修改示例**：

假设未来 A 股延长交易到 15:30，且新增 21:00-23:00 夜盘：

```python
"A_STOCK": [
    ("09:30", "11:30"),
    ("13:00", "15:30"),   # 原 14:57 → 15:30
    ("21:00", "23:00"),   # 新增夜盘段
],
```

同时如果强平时间也顺延（比如 15:15），需要修改 `references/contract_specs.json`：

```json
"A_STOCK": {
  ...
  "force_close_time": "15:15"
}
```

**注意**：`force_close_time` 必须落在 `_TRADING_SESSIONS` 的窗口内，否则强平决策永远无法触发（因为时段校验先被拒）。

### 已知未覆盖的窗口

以下窗口 v3 **有意不覆盖**，如有需要可按上文规则扩表：

| 场景 | 当前行为 | 扩展方式 |
|---|---|---|
| A 股/港股收盘集合竞价 | 拒绝 | 上文示例已给出 |
| 商品期货夜盘 | 拒绝 | 加 `("21:00", "23:00")` 等段 |
| 商品期货各交易所差异（DCE / CZC / SHF / INE） | 统一按主流窗口 | 拆分为 `COMMODITY_FUTURE_DCE` / `COMMODITY_FUTURE_SHF` 等 market key，并同步扩展 `classify.py` |
| 港股半日市（12:00 收盘） | 未识别 | 需在调用侧自行判断日期，动态传入不同 market key 或用 `session_check=False` |

## 决策规则（优先级从高到低，对所有品种语义一致）

| 优先级 | 条件 | 动作 | 手数取整 |
|---|---|---|---|
| 1 | 时间 >= 品种强平时间 | 强平（平到 0） | 否（v3 变更） |
| 2 | 浮亏 >= 1% | 全平止损（平到 0） | 否（v3 变更） |
| 3 | 浮亏 >= 0.5% | 砍半仓（sellable × 0.5） | 是（round_lot） |
| 4 | 浮盈 > 1% | 加仓 50%（先 max_qty 截断再校验现金） | 是（round_lot） |
| 5 | 其他 | hold | — |

`sellable_qty` 计算：
- T+1 品种（A股/A股ETF）：`sellable = sellable_qty`，`locked_qty` 视为今日新建被 T+1 锁定，当日不可卖
- T+0 品种（股指/商品期货/港股）：`sellable = sellable_qty + locked_qty`，BUILD 容错处理（调用方一般传 `locked_qty=0`）

字段语义说明：
- `sellable_qty` — 可卖数量，可能是任何此前交易日建的仓位（不仅限于昨日）
- `locked_qty`   — 锁仓数量，A股/ETF 表示今日 T+1 锁定的部分；T+0 品种应填 0

资金校验：加仓时计算 `_required_cash`（A股/港股用现金+手续费，期货用保证金+手续费），不足时直接 `hold`，**不降级**到部分加仓。

## 输入

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str | 品种代码 |
| pnl_pct | float | 浮盈亏，小数形式（0.01=+1%，-0.005=-0.5%）。**拒绝 NaN/inf/bool** |
| sellable_qty | int | 可卖数量（>=0），任何此前交易日建的仓位。**拒绝 bool** |
| locked_qty | int | 锁仓数量（>=0），A股/ETF 表示今日 T+1 锁定；T+0 品种填 0。**拒绝 bool** |
| price | float | 现价（>0）。**拒绝 NaN/inf/bool** |
| available_cash | float | 可用现金/保证金（>=0）。**拒绝 NaN/inf/bool** |
| time | str | 当前时间，格式 HH:MM。**必须在品种交易时段内**（可通过 `session_check=False` 关闭） |
| max_qty | int / None | **v3 新增，可选**。目标仓位上限（sellable_qty 同单位）。加仓时先按 `max_qty - total` 截断，再校验现金 |

调用 `run()` 时的关键字参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| session_check | bool | True | 是否校验 `time` 在交易时段内 |

## 输出

`8 基础字段（向后兼容）+ 5 v3 顶层字段`：

**基础 8 字段（不变，向后兼容）**

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str | 品种代码 |
| pnl_pct | float | 浮盈亏（原样返回） |
| current_qty | int | 总持仓 = sellable_qty + locked_qty |
| time | str | 时间 |
| action | str | "buy" / "sell" / "hold" |
| qty_change | int | 正=加仓，负=减仓，0=不动 |
| target_qty | int | 目标持仓（A股强平/全平时为 `locked_qty`，其他品种为 0） |
| reason | str | 触发原因，人类可读文本；默认仍带 `[MARKET][sellable=N][cash_req=X]` 前缀（deprecated，一版后关闭） |

**v3 新增 5 字段（顶层）**

| 字段 | 类型 | 说明 |
|---|---|---|
| market | str | `A_STOCK` / `A_ETF` / `INDEX_FUTURE` / `COMMODITY_FUTURE` / `HK_STOCK` / `UNKNOWN` |
| sellable | int | 实际用于决策的可卖数量（T+1 品种=sellable_qty，T+0 品种=sellable_qty+locked_qty） |
| cash_req | float | 加仓所需现金/保证金，未触发或非加仓分支为 0.0 |
| flags | list[str] | 结构化标签，见下 |
| capped_by_max_qty | bool | 是否触发 max_qty 封顶 |

**flags 语义**

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

## 调用方式

```python
from scripts.build import run

# 单条
result = run({
    "code": "600036", "pnl_pct": 0.015,
    "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000,
    "time": "10:00",
    "max_qty": 1200,      # v3 可选
})

# 批量 + 关闭时段校验（回测/离线场景）
results = run([
    {"code": "IF2406", "pnl_pct":  0.015, "sellable_qty":   2, "locked_qty":   0,
     "price": 4000.0, "available_cash": 200000, "time": "10:00"},
    {"code": "00700",  "pnl_pct": -0.007, "sellable_qty": 200, "locked_qty":   0,
     "price":  400.0, "available_cash":      0, "time": "10:00"},
], session_check=False)
```

## 模块结构

```
├── SKILL.md
├── scripts/
│   ├── build.py                # 标准入口 run() / validate_input() / 派发
│   ├── specs.py                # 加载 contract_specs.json
│   ├── classify.py             # 品种识别
│   ├── common.py               # 共享常量、工具、调仓指令构造器
│   ├── markets/
│   │   ├── __init__.py
│   │   ├── a_stock.py          # A股 + A股ETF（T+1）
│   │   ├── index_future.py     # 股指期货（IF/IC/IH/IM）
│   │   ├── commodity_future.py # 商品期货（rb/cu/m/au/ag/i）
│   │   └── hk_stock.py         # 港股+ETF（T+0，覆盖手数）
│   └── test.py
└── references/
    ├── contract_specs.json     # 合约规格中央表
    └── api_guide.md            # 调用协议、reason 解析协议
```

## 可被 Alpha 调用
- 是
- 调用限制：Alpha 负责提供 pnl_pct / yesterday_qty / today_qty / price / available_cash，本 BUILD 只做决策不拉数据
- 依赖数据：调用方传入标准结构化数据

## 是否需要生产结果
- 是否生成 `数据库.parquet`：否（调用型，实时返回）

## 依赖
- 调用方传入标准结构化数据
- Python 标准库（json, os, re, sys）
- 无三方依赖（无 pandas / numpy）

## 数据来源
本 BUILD 为**调用型**，不主动拉取数据。所有输入数据（品种代码、浮盈亏、可卖数量、锁仓数量、现价、可用现金/保证金、当前时间）均由调用方（Alpha / Agent / 人工）传入标准结构化数据。

## 假设条件
- 调用方传入的 `pnl_pct` 已按品种口径正确计算（小数形式，0.01 = +1%）
- `sellable_qty` 与 `locked_qty` 由调用方按 T+1/T+0 规则正确拆分，BUILD 不做持仓状态维护
- 现价 `price` 为市场实时价或最近成交价，不考虑涨跌停/停牌对可交易性的影响
- 可用现金/保证金 `available_cash` 为调用方传入的实时可用资金，BUILD 不做账户余额校验
- 时间 `time` 为交易所当地时间，BUILD 不处理时区转换
- 手续费按固定费率近似计算，不计印花税、过户费、规费等细项差异

## Changelog

### v3（BREAKING）
- **强平/全平「平到 0」**：不再走 round_lot 手数下取整；A股 target_qty=locked（保留 T+1 锁仓），T+0 品种 target_qty=0
- **校验加固**：拒绝 NaN/inf/bool；time HH:MM 校验 0-23 时 0-59 分；默认按品种校验交易时段（可 `session_check=False` 关闭）
- **新增 `max_qty`**：目标仓位上限，加仓时先按 `max_qty - total` 截断再校验现金；触发时 flags 含 `capped_by_max_qty`
- **输出新增 5 顶层字段**：`market` / `sellable` / `cash_req` / `flags` / `capped_by_max_qty`；8 基础字段保持不变
- **reason 恢复为纯人类可读文本**；`[MARKET][sellable=N][cash_req=X]` 前缀由 `INCLUDE_REASON_PREFIX`（默认 True）控制，deprecated 下版关闭

### v2.1
- **合规**：仓库重命名为 `skill-` 前缀；SKILL.md 提升至仓库根目录；添加 metadata 元数据块；添加免责声明与风险边界
- **文档**：新增 README.en.md；README.md 更新目录结构
- **多平台**：安装指南覆盖 Codex / Claude Code / Cursor / Hermes / OpenClaw

### v2（BREAKING）
- **input schema 变更**：`current_qty` 拆分为 `sellable_qty + locked_qty`（语义=可卖+锁仓，非"昨仓+今仓"），新增 `price` 与 `available_cash`，`time` 由 HH:MM:SS 改为 HH:MM
- **多品种支持**：A股 / A股ETF / 股指期货 / 商品期货 / 港股+ETF
- **T+1/T+0 区分**：A股 14:45 强平时锁仓阻断，仅卖可卖部分
- **资金校验**：加仓时计算所需现金/保证金，不足 → hold（reason 标 `[v2:cash_insufficient]`）
- **调仓基数 = sellable_qty**（T+0 品种为 sellable_qty + locked_qty）
- **强平时间按品种表**：港股 15:45，其他 14:45
- **模块拆分**：build.py 单文件 → 按市场分拆为 markets/*.py

### v1
- 单一 A股、单一 14:45 强平、不区分可卖/锁仓、不校验资金

## Known Limitations（v3 待解决）

1. **仅多头**：不处理空头 / 双向 / 套利 / 跨期组合
2. **不感知涨跌停 / 停牌 / 流动性**：执行失败由调用方回报
3. **集合竞价 / 盘前盘后不在时段白名单内**：详见「交易窗口参考」章节；如需支持请扩表或使用 `session_check=False`
4. **手续费固定 fee_rate**：不计 A股印花税、过户费、规费档位
5. **港股 lot_size 覆盖表仅 6 支**：未命中按 100 兜底，可能与真实手数不符
6. **不处理多币种**：港股价格按港币、A股按人民币，调用方自行换算
7. **商品期货品种表有限**：仅 rb/cu/m/au/ag/i，扩展需要在 contract_specs.json 中补充
