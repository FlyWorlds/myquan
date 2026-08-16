# B11 自动止盈止损+仓位管理（增强版）

当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈（+5%）、次日低开止损（-3%）、持仓满 2 交易日强平、单票名义仓位上限（>10%）减仓，输出标准 8 字段调仓指令。

> 本版本为对 52/100 验收版的**增强修复**，全面落地 6 项缺陷改进（E1–E6），**v2 已升级为混合型 BUILD**——`production/trade.parquet` 提供本地交易日历缓存，agent 侧新增 `inspect_calendar()` / `refresh_calendar()` 自主决策 API。
> **v3 追加**：新增 `check_date_coverage(start_date, end_date=None)` 一键查询 API——agent 拿到任意日期或回测区间，一次调用即返回「是否在日历覆盖范围内 + 缺口 + 扩展建议 + 可直接执行的 refresh 命令」。

---

## ⚡ Agent 快速集成（3 分钟跑通）

其他 agent 拉取本 skill 后，按 3 步即可产出交易决策：

### Step 1 — 安装与配置（一次性）

```bash
# 装依赖
pip install panda_data pyarrow

# 配置 panda_data 凭据（写入 ~/.zshrc 或 ~/.bashrc 后 source）
export PANDA_USERNAME=<your_username>
export PANDA_PASSWORD=<your_password>
```

> `production/trade.parquet` 已随仓库发布（971 交易日 / ~18.5KB），开箱可用；若需扩展范围再运行 `python3 scripts/build_calendar.py`。

### Step 2 — 从 agent 代码里调用（最短 3 行）

```python
import sys
sys.path.insert(0, "/path/to/skill-b11-auto-stop-loss-take-profit/scripts")
from build import run

order = run({
    "code":         "600036",
    "entry_price":  10.0,
    "entry_date":   "2026-06-19",   # 周五入场
    "current_qty":  800,
    "open_price":   10.55,          # 次日 +5.5%
    "today":        "2026-06-22",   # 周一（交易日次日）
    "total_equity": 1_000_000,      # ⭐ 必传：总权益作为仓位比分母
})
# → {"code": "600036", "action": "sell", "target_qty": 0, "qty_change": -800,
#    "reason": "[B11]次日高开止盈 ...", ...}
```

批量调用只需传 list：`run([pos1, pos2, ...])` 返回同长度 list。

### Step 3 — 遇到「日历不覆盖你的日期」时（3 层 API）

```python
from build import check_date_coverage, refresh_calendar

# 拿到未知日期先问 —— 一次调用拿齐范围/覆盖/建议/命令
r = check_date_coverage("2020-01-15")   # 或区间 check_date_coverage("2020-01-15", "2029-06-01")

if not r["in_range"]:
    # r 已算好建议参数，agent 直接传给 refresh_calendar
    refresh_calendar(force=True,
                     years_back=r["suggested_years_back"],
                     years_forward=r["suggested_years_forward"])
# 之后再调 run(...) 即可
```

### Step 4 — 常见平台集成

| 平台 | 集成方式 |
|---|---|
| **Python agent（最通用）** | 上面 Step 2 三行代码，或 `python3 scripts/build.py` |
| **Claude Code** | `cp -R . ~/.claude/skills/skill-b11-auto-stop-loss-take-profit`；`/skill-b11-...` 触发 |
| **Cursor** | `.cursor/tools.json` 注册（`INSTALL.md § Cursor`） |
| **OpenAI Codex** | 函数工具 JSON schema（`INSTALL.md § Codex`） |
| **Hermes / OpenClaw** | YAML 配置（`INSTALL.md § Hermes` / `§ OpenClaw`） |

### 必传字段一览

| 字段 | 类型 | 必填 | 说明 |
|---|---|:---:|---|
| `code` | str | ✅ | A股（`600036`/`sh600036`）或期货（`IF2406`/`rb2410`） |
| `entry_price` | float | ✅ | 入场价 |
| `entry_date` | str | ✅ | 入场日 `YYYY-MM-DD` |
| `current_qty` | int | ✅ | 当前持仓（A股股数 / 期货手数） |
| `open_price` | float | ✅ | 今日开盘价 |
| `today` | str | ✅ | 当前日 `YYYY-MM-DD`（须 ≥ entry_date） |
| `total_equity` | float | ✅ | **总权益（仓位比分母）**，`≤0` 时返回 hold |
| `multiplier` | float | ⭕️ | 期货合约乘数；A股忽略；未知期货品种必传 |

### 输出契约（8 字段调仓指令）

```python
{
    "code":        "600036",
    "pnl_pct":     0.055,          # 浮盈亏（小数）
    "current_qty": 800,
    "time":        "2026-06-22",
    "action":      "sell",         # "sell" / "hold"（不产生 buy）
    "qty_change":  -800,           # 负=卖出，0=不动
    "target_qty":  0,
    "reason":      "[B11]次日高开止盈 ...",
}
```

### 遇到问题的最快诊断

| 现象 | 排查 |
|---|---|
| `RuntimeError: 需要 panda_data` | `pip install panda_data pyarrow` |
| `RuntimeError: 需要 PANDA_USERNAME / PANDA_PASSWORD` | 配置 env 后 `source ~/.zshrc` |
| `ValueError: 未知期货品种` | 传 `multiplier` 参数覆盖 |
| `ValueError: 缺少字段: total_equity` | v2 必传总权益 |
| 全部返回 hold，reason 含"总权益非正" | 传入的 `total_equity ≤ 0` |
| 回测日期不在日历范围内 | `check_date_coverage()` → 按建议 `refresh_calendar(force=True, ...)` |

---

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现，过去的表现不预示未来结果。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束。交易日历默认 A 股口径（`panda_data` 的 SH 交易所），港美股暂不支持；仅支持多头持仓。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。

## 目录结构

```
├── SKILL.md                                ← 技能设计书（含 metadata / 决策规则 / Agent 更新 SOP）
├── README.md                               ← 本文件
├── README.en.md                            ← English version
├── LICENSE                                 ← GPL-3.0-only
├── INSTALL.md                              ← 多平台安装指南（5 平台）
├── requirements.txt                        ← 依赖声明（panda_data 硬依赖 + pyarrow）
├── scripts/
│   ├── build.py                            ← 主入口（run / validate_input / check_date_coverage / inspect_calendar / refresh_calendar）
│   ├── test.py                             ← 自测脚本（68 用例）
│   ├── build_calendar.py                   ← 独立初始化：拉取交易日历 → 写 production/trade.parquet
│   └── _verify_prod.py                     ← 生产路径验证（panda_data 实测）
├── references/
│   └── api_guide.md                        ← 接口调用文档（含增强变更清单 + Agent 更新 SOP）
└── production/
    └── trade.parquet                       ← 交易日历缓存（今天-3年 → 今天+1年，snappy 压缩，~18.5KB）
```

## 快速开始

```bash
# 一：初始化交易日历缓存（首次使用必做，需 PANDA_USERNAME/PANDA_PASSWORD）
python3 scripts/build_calendar.py

# 二：单元测试（零外部数据依赖，68 用例）
python3 scripts/test.py

# 三：build 主入口示例
python3 scripts/build.py

# 四（可选）：生产路径实测（需 panda_data + env 凭据）
python3 scripts/_verify_prod.py
```

## Agent 使用示例（详细）

上面「⚡ Agent 快速集成」是最短路径；下面是 `check_date_coverage` 三层 SOP 的完整调用形态。

```python
from scripts.build import check_date_coverage, refresh_calendar, run

# 1. 一键查询：agent 拿到未知日期先问日历
r = check_date_coverage("2020-01-15")   # 或 ("2020-01-15", "2029-06-01") 查区间
# {
#   "in_range": False,
#   "coverage": {"date_min": "2023-07-06", "date_max": "2027-07-05", "count": 971},
#   "gap_before": 1268, "gap_after": 0,
#   "suggested_years_back": 7, "suggested_years_forward": 1,
#   "suggested_action": "extend_back",
#   "refresh_command": "refresh_calendar(force=True, years_back=7, years_forward=1)",
#   "reason": "start=2020-01-15 早于 date_min=2023-07-06（缺 1268 天）..."
# }

# 2. 按建议扩容（agent 只需照抄 refresh_command 的参数）
if not r["in_range"]:
    refresh_calendar(force=True,
                     years_back=r["suggested_years_back"],
                     years_forward=r["suggested_years_forward"])

# 3. 正常调用主入口（单条 dict 或批量 list[dict]）
order = run({
    "code": "600519", "entry_price": 1_800.0, "entry_date": "2025-01-02",
    "current_qty": 100, "open_price": 1_890.0, "today": "2025-01-03",
    "total_equity": 5_000_000,
})
```

底层仍提供 `inspect_calendar()`（只读健康检查）/ `refresh_calendar(force, years_back, years_forward)`（按需刷新）——完整三层 SOP 与 7 种触发场景决策表见 `SKILL.md` § Agent 更新 SOP。

## v3 更新记录

相对 v2（commit `abf1227`）的 4 项主要变更：

1. **新增 `check_date_coverage(start_date, end_date=None)` 公开 API**：agent 侧首选入口，一次调用即可拿到「日历范围 + 是否覆盖 + 缺口自然日数 + 扩展建议 + 可直接执行的 refresh 命令」，字段包含 `in_range` / `coverage` / `gap_before` / `gap_after` / `suggested_years_back` / `suggested_years_forward` / `suggested_action` / `refresh_command` / `reason`。
2. **三层 agent SOP 完善**：`check_date_coverage`（查询 + 建议）→ `inspect_calendar`（健康检查）→ `refresh_calendar`（按需刷新）。`SKILL.md` 详细写明每层使用场景。
3. **测试 62 → 68 例**：新增 6 例 `check_date_coverage` 用例（范围内 / 早于 `date_min` / 晚于 `date_max` / 两端超出 / parquet 缺失回退 / 反向区间自动交换）。
4. **保留 `production/trade.parquet` 数据源与全部 v2 行为**，agent 开箱即用。

## v2 更新记录

相对 v1（commit `ea1585e`）的 7 项主要变更：

1. **交易日历硬依赖 panda_data**：删除 `config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]` 四个入口，唯一来源 = `panda_data.get_trade_cal`（消除口径分歧风险）。
2. **自动 env 登录**：`build.py` 首次调用交易日历时自动读 `PANDA_USERNAME` / `PANDA_PASSWORD` 并调 `init_token`；凭据缺失抛 `RuntimeError` 含引导链接。
3. **新增 `production/trade.parquet` 缓存产物**：本 BUILD 从纯调用型升级为**混合型**——本地 parquet 缓存作为交易日历的持久层，避免每次调用都走网络。
4. **新增独立初始化脚本 `scripts/build_calendar.py`**：拉取今天−3年至今天+1年的交易日历，`snappy` 压缩写入 parquet 缓存（~18.5KB / 971 交易日）。
5. **新增 agent 侧公开 API**：`inspect_calendar()`（只读探查）+ `refresh_calendar(force=False)`（按需刷新），供 agent 自主决策日历生命周期。
6. **完整 schema 文档 + Agent 更新 SOP**：`SKILL.md` 详细列出 parquet 5 列 schema、日期格式约定、agent 更新四步流程、7 种触发场景决策表。
7. **测试从 49 → 62 例**：新增 parquet cache / inspect_calendar / refresh_calendar 全套用例，`pyarrow` 缺失时智能 skip。

## 核心设计要点

1. **五级决策优先级**：`守卫(异常返回 hold) → 次日止盈(+5%) → 次日止损(-3%) → 持仓 ≥2 交易日强平 → 单票名义仓位 >10% 减仓 → hold`。
2. **交易日语义（E1）**：入场当天 = 第 0 个交易日；`holding_trading_days` 为跨越的交易日数。次日 = `holding_trading_days == 1`，强平 = `holding_trading_days >= 2`。周五入场的「次日」是下周一（自然日差 3），由交易日历正确识别。
3. **仓位分母（E2）**：仓位比 = 名义价值 / `total_equity`（方案 A：调用方传入的**总权益**，不再用 available_cash）。名义价值 = `current_qty × open_price × multiplier`（A 股 multiplier=1）。
4. **代码分类（E3）**：先剥离 `sh/sz/SH/SZ` 前缀再判定，6 位纯数字为 A 股，含字母为期货。
5. **期货合约乘数（E4）**：内置乘数表覆盖 IF/IC/IH/IM/rb/cu 等常见品种，未知品种可通过 `multiplier` 显式覆盖。
6. **健壮性（E5）**：入场价/开盘价 NaN/inf、`total_equity ≤ 0`、`today < entry` 等异常统一返回 hold。
7. **交易日历唯一来源（v2）**：`panda_data.get_trade_cal` 硬依赖，本地 `production/trade.parquet` 提供持久缓存。删除 v1 的 4 个降级入口（`config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]`）以消除口径分歧。
8. **纯 Python 标准库（业务层）**：`math / numbers / re / datetime / bisect`，无 pandas/numpy。仅数据缓存层依赖 `panda_data` + `pyarrow`。

## 支持的运行时平台

| 平台 | 安装指南 |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## 验收状态

- **测试**：`scripts/test.py` — **68 / 68 用例通过**（正常流、边界值、异常输入、增强项 E1–E6、v2 parquet cache / inspect / refresh 全覆盖，v3 新增 6 例 check_date_coverage 覆盖）。
- **增强改进落地**：
  - E1 交易日语义（`panda_data.get_trade_cal` 唯一来源） ✅
  - E2 仓位分母改为 `total_equity` ✅
  - E3 代码分类先剥离 sh/sz 前缀 ✅
  - E4 期货合约乘数（内置表 + `multiplier` 覆盖） ✅
  - E5 健壮性（NaN/inf、非法权益、时间倒流守卫） ✅
  - E6 测试补全（62 用例，覆盖 v2 新增字段与边界） ✅
- **v2 混合型产物**：`production/trade.parquet`（971 交易日 / snappy 压缩 / ~18.5KB）已随仓库发布。
- **生产路径验证**：`scripts/_verify_prod.py` — `panda_data.get_trade_cal` **实测通过**（PANDA_USERNAME/PANDA_PASSWORD 环境变量自动读取）。
- `build.py` 独立可运行、`validate_input` / `inspect_calendar` / `refresh_calendar` API 完备。

## Known Limitations

1. **交易日历默认 A 股口径**（`panda_data` SH 交易所），港美股暂不支持。
2. **不区分涨停/跌停/停牌**——触发日若无法交易，指令不可执行。
3. **仅支持多头持仓**——不处理空头、双向、套利、跨期组合。
4. **未知期货品种需传 multiplier**——内置表未覆盖时调用方必须显式提供合约乘数。
5. 不感知市场流动性、滑点、冲击成本——大单执行可能偏离预期价格。

## 维护者

- 上游组织：QuantSkills (<https://github.com/quantskills>)
- License：GPL-3.0-only（详见 `LICENSE`）
