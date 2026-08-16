# B12 日内仓位动态管理

当需要对日内多品种持仓做动态仓位管理时，使用此 skill。支持 A股/A股ETF/股指期货/商品期货/港股+ETF；区分 T+1/T+0、昨仓/今仓、保证金/现金，输出标准 8 字段调仓指令。

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束，生成的调仓指令可能因市场条件变化而无法成交或造成亏损。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证。

## 目录结构

```
├── SKILL.md                                ← 技能设计书（v2.1）
├── README.md                               ← 本文件
├── README.en.md                            ← English version
├── LICENSE                                 ← GPL-3.0
├── INSTALL.md                              ← 多平台安装指南
├── requirements.txt                        ← 依赖声明
├── scripts/
│   ├── build.py                            ← 主入口（run / validate_input）
│   ├── test.py                             ← 自测脚本
│   ├── classify.py                         ← 品种识别
│   ├── common.py                           ← 共享常量与工具
│   ├── specs.py                            ← 合约规格加载器
│   └── markets/
│       ├── __init__.py
│       ├── a_stock.py                      ← A股 + A股ETF（T+1）
│       ├── index_future.py                 ← 股指期货（IF/IC/IH/IM）
│       ├── commodity_future.py             ← 商品期货（rb/cu/m/au/ag/i）
│       └── hk_stock.py                     ← 港股+ETF（T+0）
└── references/
    ├── api_guide.md                        ← 接口调用文档
    └── contract_specs.json                 ← 合约规格中央表
```

## 快速开始

```bash
cd scripts
python3 build.py
python3 test.py
```

## 核心设计要点

1. **五级优先级决策**：强平（时间触发）→ 全平止损（浮亏 ≥ 1%）→ 砍半仓（浮亏 ≥ 0.5%）→ 加仓 50%（浮盈 > 1%）→ 持有。数量操作向下取整到品种最小交易单位（A股 100 股、期货 1 手）。

2. **T+1/T+0 仓位拆分**：输入 `sellable_qty + locked_qty` 替代单一 `current_qty`。T+1 品种（A股/ETF）当日新建仓位被锁定不可卖，强平和止损仅操作可卖部分；T+0 品种（期货/港股）全部仓位可操作。

3. **资金校验阻断**：加仓时按品种计算所需现金（A股/港股）或保证金（期货），不足时直接 `hold`，不降级到部分加仓，避免半仓指令导致执行不确定性。

4. **模块化规则引擎**：`classify.py` 识别品种 → `specs.py` 加载合约规格 → 各 `markets/*.py` 独立实现品种专属仓位逻辑。新增品种只需添加一个市场模块并补充 `contract_specs.json`。

5. **纯 Python 零依赖**：仅使用标准库（json/os/re/sys），无 pandas/numpy 等三方库依赖。

## 支持的运行时平台

| 平台 | 安装指南 |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## 验收状态

- build.py 独立可运行 ✅
- validate_input 输入校验 ✅
- test.py 自测覆盖：正常输入、边界值、多品种批量、资金不足、强平触发 ✅

## 局限与后续优化方向

| 局限 | 说明 | 后续 |
|---|---|---|
| 仅多头 | 不处理空头/双向/套利/跨期组合 | v3 扩展 |
| 不感知涨跌停/停牌/流动性 | 执行失败由调用方回报 | 接入行情状态标志 |
| 手续费固定 fee_rate | 不计印花税、过户费、规费档位 | 细化费率模型 |
| 港股 lot_size 仅 6 支 | 未命中按 100 兜底 | 扩展覆盖表 |
| 不处理多币种 | 港股/A股汇率由调用方自行换算 | 接入汇率 |
| 商品期货品种有限 | 仅 rb/cu/m/au/ag/i | 补充 contract_specs.json |
| 不区分集合竞价/盘前盘后 | 时间阈值一刀切 | 接入交易时段日历 |
