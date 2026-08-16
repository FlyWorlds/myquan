---
name: skill-b11-auto-stop-loss-take-profit
description: 当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈、次日低开止损、持仓满2交易日强平、单票名义仓位上限控制。交易日历唯一来源 = panda_data.get_trade_cal（硬依赖）。
tags: [quant, skill, 止盈止损, 仓位管理, A股, 期货]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-b11-auto-stop-loss-take-profit
  repository_url: https://github.com/quantskills/skill-b11-auto-stop-loss-take-profit
  project_type: skill
  collection: quant
  license: GPL-3.0-only
---

## 维护者
- 上游组织：QuantSkills (https://github.com/quantskills)

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现，过去的表现不预示未来结果。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束。交易日历默认 A 股口径，港美股暂不支持。所有交易决策责任由使用者自行承担。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。


# B11 自动止盈止损+仓位管理

## 前置依赖 ⚠️（其它 AI / agent 首次运行必读）

本 skill **强依赖 [panda_data](https://pypi.org/project/panda-data/)** 提供交易日历。首次调用会自动读取环境变量登录，未安装或未配置时会抛 `RuntimeError` 含引导。

### 一次性配置（所有使用者必做）

**Step 1 — 安装 panda_data**

```bash
pip install panda_data
```

**Step 2 — 配置环境变量**（写入 shell 配置文件，然后重开终端或 `source`）

macOS / Linux（`~/.zshrc` 或 `~/.bashrc`）：

```bash
export PANDA_USERNAME=<your_username>
export PANDA_PASSWORD=<your_password>
```

Windows（PowerShell 用户配置）：

```powershell
setx PANDA_USERNAME "<your_username>"
setx PANDA_PASSWORD "<your_password>"
```

**Step 3（可选，强烈推荐）— 预热交易日历缓存**

```bash
python3 scripts/build_calendar.py
```

生成 `production/trade.parquet`（默认覆盖 今天-3 年 到 今天+1 年，~19KB），后续调用优先读该文件、跳过实时 panda_data 请求。文件过期或缺失时自动回退到实时拉取。

### 凭据获取
panda_data 账号需向 PandaAI 数据服务申请；未持有账号请联系上游数据服务方。

### 自检验证

```python
python3 -c "
import os
assert os.environ.get('PANDA_USERNAME'), '未配置 PANDA_USERNAME'
assert os.environ.get('PANDA_PASSWORD'), '未配置 PANDA_PASSWORD'
import panda_data
panda_data.init_token(username=os.environ['PANDA_USERNAME'], password=os.environ['PANDA_PASSWORD'])
print('OK')
"
```

若上述命令输出 `OK`，即可开始使用 B11。

### 错误消息含引导

| 场景 | 错误类型 | 引导内容 |
|---|---|---|
| 未装 panda_data | `RuntimeError` | 含 `pip install panda_data` + env 配置示例 |
| 未配置 PANDA_USERNAME/PANDA_PASSWORD | `RuntimeError` | 含 `export PANDA_USERNAME=...` 示例 |

---

## 工具定位
- 工具类型：交易执行辅助型（调用型 BUILD）
- 解决问题：按入场日期和开盘价自动判断止盈、止损、强平，以及单票名义仓位上限控制
- 使用对象：交易 agent / 人工辅助决策 / Alpha 信号

## 适用场景
- 每日开盘后检查持仓是否需要止盈/止损（基于交易日历的「次日」判定）
- 持仓满 2 个交易日自动平仓
- 单票名义仓位超总权益 10% 时自动减仓（A股按市值、期货按 名义价值=数量×价格×合约乘数）

## 支持品种（E3：先剥离 sh/sz 前缀，6位数字优先判 A股）

| 类别 | 识别规则 | 最小交易单位 | 合约乘数 |
|---|---|---|---|
| A_STOCK | 剥离 sh/sz/SH/SZ 前缀后为 6 位纯数字（含 600036 / sh600036 / SZ000001 / 688xxx / ETF） | 100 股 | 1 |
| FUTURE | 剥离前缀后仍含字母（如 IF2406 / rb2410 / cu2401） | 1 手 | 见内置乘数表，可由 `multiplier` 覆盖 |

## 决策规则（优先级从高到低）

| 优先级 | 条件 | 动作 |
|---|---|---|
| 0 | 守卫：today<entry（交易日） / 价格 NaN-inf / total_equity<=0 | hold（标注异常） |
| 1 | 次日（holding_trading_days==1）且 浮盈 ≥ +5% | 止盈全平 → target=0 |
| 2 | 次日 且 浮亏 ≤ -3% | 止损全平 → target=0 |
| 3 | 持仓满 2 个交易日（holding_trading_days ≥ 2） | 强制平仓 → target=0（不做手数下取整） |
| 4 | 单票名义仓位占总权益 > 10%（严格 >，==10% 不动） | 减仓至 ≤10% 最近整百股/整手；floor 后<1单位或 target≥current 则 hold（不清仓） |
| 5 | 其他 | hold |

### 交易日语义（E1）
- **入场当天 = 第 0 个交易日**；`holding_trading_days` 为持仓跨越的交易日数。
- **「次日」= holding_trading_days == 1**（entry 的下一个交易日），止盈/止损仅在该日有效。
- **「持仓 2 日强平」= holding_trading_days ≥ 2**（即 T+2 开盘）。
- 周五入场的「次日」是下周一（自然日差 3），由交易日历正确识别——原自然日实现的核心修复。
- 交易日历**唯一来源** = `panda_data.get_trade_cal`（无 fallback，无多入口）。

### 名义价值与仓位比（E2/E4）
- 仓位比 = 名义价值 / `total_equity`（调用方传入的总权益，不再用 available_cash）。
- 名义价值 = `current_qty × open_price × multiplier`（A股 multiplier=1）。
- `total_equity ≤ 0` 短路返回 hold（防除零）。

## 输入

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| code | str | 是 | 品种代码（A股/期货） |
| entry_price | numbers.Real | 是 | 入场价（>0，非 NaN/inf） |
| entry_date | str | 是 | 入场日期 YYYY-MM-DD |
| current_qty | numbers.Integral | 是 | 当前持仓数量（>=0，兼容 numpy 整数） |
| open_price | numbers.Real | 是 | 当日开盘价（>0，非 NaN/inf） |
| today | str | 是 | 当前交易日 YYYY-MM-DD（须 >= entry_date） |
| total_equity | numbers.Real | 是 | 总权益（仓位比分母），非 NaN/inf；<=0 时返回 hold |
| available_cash | numbers.Real | 否 | 可用现金（保留字段，不作分母） |
| multiplier | numbers.Real | 否 | 期货合约乘数；缺省时查内置表，未知品种未传则报错；A股忽略 |

> **入参已精简**：不再支持 `holding_trading_days` / `trade_days` / `config` 参数——交易日历统一由 `panda_data.get_trade_cal` 提供。

## 输出

标准 8 字段调仓指令：

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str | 品种代码 |
| pnl_pct | float | 浮盈亏（小数形式，0.05 = +5%） |
| current_qty | int | 当前总持仓 |
| time | str | 当前日期 |
| action | str | "sell" / "hold" / "buy"（本工具不产生 buy） |
| qty_change | int | 负=减仓，0=不动 |
| target_qty | int | 目标持仓 |
| reason | str | 触发原因，含 `[B11]` 前缀 |

## 调用方式

```python
from scripts.build import run

# 前置：已 pip install panda_data 且 export PANDA_USERNAME/PANDA_PASSWORD
# 首次调用自动 init_token 登录 panda_data 拉取交易日历

result = run({
    "code": "600036",
    "entry_price": 10.0,
    "entry_date": "2026-06-19",   # 周五
    "current_qty": 800,
    "open_price": 10.55,          # 次日高开 +5.5%
    "today": "2026-06-22",        # 周一（真实交易日次日）
    "total_equity": 1_000_000,
})
# → {"action": "sell", "target_qty": 0, "reason": "[B11]次日高开止盈 ..."}

# 批量
results = run([pos1, pos2, pos3])
```

## 可被 Alpha 调用
- 是
- 调用限制：需提供 total_equity；期货需可解析合约乘数（内置表或传 multiplier）；需已配置 panda_data 凭据
- 依赖数据：调用方传入标准结构化数据 + panda_data.get_trade_cal 交易日历

## 是否需要生产结果
- 是否生成 `数据库.parquet`：**是（混合型）**
- 输出产物：`production/trade.parquet` — A股交易日历缓存

### production/trade.parquet

**用途**：`build.py` 运行时优先读该文件构造 `TradingCalendar`，避免高频调用 `panda_data.get_trade_cal`。文件缺失或过期（最晚 `nature_date < today`）时自动回退到实时拉取，不影响功能。

**存放路径**：仓库根 `production/trade.parquet`（与 `scripts/` 同级）。

**默认覆盖范围**：今天-3 年 到 今天+1 年（约 971 个交易日，snappy 压缩 ~19 KB）。

#### 表结构（Schema）

parquet 文件的完整表结构如下，**列名与 `panda_data.get_trade_cal` 返回的 DataFrame 完全一致**（未做任何列裁剪或重命名，便于将来直接对齐上游变更）：

| # | 列名 | 数据类型 | 是否必需 | 语义说明 |
|---|---|---|---|---|
| 1 | `nature_date` | `int64` | ⭐ **build.py 唯一必需** | 交易日的自然日，格式 `YYYYMMDD`（如 `20260619`）。`build.py` 读盘时只读此列 |
| 2 | `next_trade_date` | `str` | 参考 | 该交易日的**下一个**交易日，格式 `YYYYMMDD`（周五 → 下周一） |
| 3 | `pretrade_date` | `str` | 参考 | 该交易日的**前一个**交易日，格式 `YYYYMMDD` |
| 4 | `exchange` | `str` | 参考 | 交易所代码。当前统一为 `"SH"`（A 股上交所口径，深交所交易日期一致） |
| 5 | `is_trade` | `int64` | 参考 | 是否交易日。文件内**全部为 `1`**（生成时用 `is_trading_day=1` 过滤，非交易日被排除） |

**行数据示例**：

```
   next_trade_date  pretrade_date  exchange  is_trade  nature_date
0         20260622       20260618        SH         1     20260619
1         20260623       20260619        SH         1     20260622
2         20260624       20260622        SH         1     20260623
```

**顺序保证**：按 `nature_date` 升序排列（`panda_data` 返回天然升序）；`build.py` 内部会再做一次 `sorted(set())` 归一化，即使乱序也不影响功能。

**日期格式关键约定**：
- 存储：`int64` 的 `YYYYMMDD`（**不是** `datetime` 或 `date` 类型）
- 转换回 `YYYY-MM-DD` 字符串：`f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:8]}"`
- `build.py:_load_trade_days_from_parquet` 已封装此转换

#### 生成方式

```bash
# 默认区间（推荐）：今天-3 年 到 今天+1 年
python3 scripts/build_calendar.py

# 自定义时间跨度
python3 scripts/build_calendar.py --years-back 5 --years-forward 2

# 自定义输出位置
python3 scripts/build_calendar.py --output /custom/path/trade.parquet

# 自定义交易所（目前 panda_data 支持 SH，其他交易所日历相同）
python3 scripts/build_calendar.py --exchange SH
```

生成过程会覆盖已有 `trade.parquet`（原子写入，无中间态）。

#### Agent 更新 SOP ⭐（**其它 AI/agent 使用本 skill 前必读**）

`build.py` 提供 **3 个公开 API**，覆盖 agent 侧「查询范围 → 判定过期 → 按需刷新」全链路：

```python
from scripts.build import check_date_coverage, inspect_calendar, refresh_calendar
```

##### 步骤 0 — check_date_coverage(date_or_start, end_date=None) ⭐ 首选入口

**agent 拿到某个 entry_date/today（或回测起止区间）后，先调它就能一键知道「范围够不够 + 该如何扩展」**。

返回 dict 关键字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `in_range` | bool | 查询区间是否**完全落在**当前 parquet 覆盖内 |
| `coverage` | dict | `{date_min, date_max, count}` — 当前日历实际范围 |
| `gap_before` | int | 查询起点早于 `date_min` 的自然日数（0 = 不缺） |
| `gap_after` | int | 查询终点晚于 `date_max` 的自然日数（0 = 不缺） |
| `suggested_years_back` | int | 建议给 `refresh_calendar` 的 `years_back`（含 1 年冗余） |
| `suggested_years_forward` | int | 建议给 `refresh_calendar` 的 `years_forward`（含 1 年冗余） |
| `suggested_action` | str | `ok` / `extend_back` / `extend_forward` / `extend_both` / `missing` |
| `refresh_command` | str\|None | 可**直接照抄执行**的 Python 调用字符串 |
| `reason` | str | 人类可读的判定说明 |

**典型 agent 流程**（3 行代码）：

```python
r = check_date_coverage("2020-01-15")     # agent 场景的实际日期
if not r["in_range"]:
    refresh_calendar(force=True,
                     years_back=r["suggested_years_back"],
                     years_forward=r["suggested_years_forward"])
# 之后可放心调 run() 走交易决策
```

**区间查询**：`check_date_coverage("2020-01-15", "2029-06-01")` 一次判定回测起止是否都覆盖。

##### 步骤 1 — inspect_calendar()  只读状态检查
`check_date_coverage` 内部已用它。**独立调用场景**：定时任务只想知道「日历健康度」（快过期没）。返回 dict 关键字段 `recommendation` 值：

| `recommendation` 值 | 含义 | agent 应做 |
|---|---|---|
| `"ok"` | 缓存正常，`date_max` 距 today ≥ 30 自然日 | 无需动作 |
| `"refresh_recommended"` | 缓存 <30 自然日过期 | 建议调 `refresh_calendar()` 静默刷新 |
| `"refresh_required"` | 已过期 / 空 / 读盘失败 | **必须**调 `refresh_calendar(force=True)` 或让实时 API 兜底 |
| `"missing"` | 文件不存在 | 首次运行 `python3 scripts/build_calendar.py` |

##### 步骤 2 — refresh_calendar(force=False, years_back=3, years_forward=1)

内置判定规则（`force=False` 时）：
- 缺失 或 `date_max < today` → 自动刷新
- `days_to_expiry < 30` → 自动刷新（预防长假前失效）
- 否则 → 跳过（`updated=False`）

**扩展历史/未来时必须传 `force=True` + 自定义 `years_back` / `years_forward`**（`check_date_coverage` 已算好建议值）。

返回示例：
```python
{
    "updated": True,
    "reason": "已刷新（refresh_required → ok）",
    "before": {...},   # 更新前的 inspect_calendar 结果
    "after":  {...},   # 更新后的 inspect_calendar 结果
    "file_size": 18917,
}
```

##### 步骤 3 — 触发条件与推荐节奏

| 触发场景 | agent 推荐动作 |
|---|---|
| **拿到未知日期（entry_date/回测区间）** | `check_date_coverage(date)` 一步到位 |
| **首次部署 skill** | `python3 scripts/build_calendar.py` 一次性生成 |
| **每日启动交易 agent 时** | `inspect_calendar()` 只读检查（微秒级） |
| **发现 `refresh_recommended`** | 调 `refresh_calendar()` 静默刷新 |
| **发现 `refresh_required`** | 调 `refresh_calendar(force=True)` |
| **回测跨越较早年份** | `check_date_coverage(backtest_start, backtest_end)` → 按 suggested_* 扩展 |
| **长假前（春节/国庆前 1-2 周）** | 主动 `refresh_calendar(force=True)` 拉最新日历 |
| **panda_data 变更 `nature_date` 类型** | 需同步修改 `_load_trade_days_from_parquet` 的转换逻辑 |
| **CI/定时任务** | 每季度 `refresh_calendar(force=True)` |

##### 步骤 4 — 失败降级

`refresh_calendar` 内部失败（如网络/凭据错误）时：
- 返回 `updated=False` + `reason` 含错误详情
- **不删除**已有 parquet（避免陷入更差状态）
- `build.py` 下次运行仍会读原 parquet；若原 parquet 已过期，自动回退到实时 `panda_data.get_trade_cal`
- 实时也失败 → `RuntimeError` 含引导（如 env 未配）

#### 读盘策略（`build.py` 内部逻辑）

```
TradingCalendar.from_panda_data(entry_date, today)
        │
        ├─ 命中 _CALENDAR_CACHE 单例 → 直接返回
        │
        ├─ _load_trade_days_from_parquet(trade.parquet, today)
        │     ├─ 文件存在 & max(nature_date) >= today → 读盘构造 ✅
        │     └─ 缺失/过期/损坏/schema 异常 → None，走下一步
        │
        └─ _ensure_panda_logged_in() → panda_data.get_trade_cal 实时拉取
```

## 依赖
- Python 标准库（math, numbers, re, datetime, bisect, os, pathlib）
- **硬依赖**：`panda_data`（PyPI）+ 环境变量 `PANDA_USERNAME` / `PANDA_PASSWORD`
- **软依赖**：`pyarrow`（读写 trade.parquet 缓存；`panda_data` 已依赖此包，通常无需单装）

## Known Limitations
1. 不区分涨停/跌停/停牌状态
2. 交易日历采用 A股口径（panda_data 的 SH 交易所）；港美股暂不支持
3. 仅支持多头持仓
4. 内置期货乘数表覆盖常见品种，未知品种须由调用方传 multiplier
5. 首次调用需网络与 panda_data 服务可达；后续调用会命中模块级登录标记，同一进程内不重复登录
