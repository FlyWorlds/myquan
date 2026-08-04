# strategy — OpenBreak3 开盘±pct

## 结构

```
strategy/
├── open_break.py        # 规则、信号、945 逻辑
├── backtest.py          # OpenBreak3Strategy + 报告摘要
├── config.py            # BacktestConfig、标的预设
├── runner.py            # run_open_break 入口
├── gap945_analysis.py   # 945 规则专项分析
├── data.py              # 日线拉取
├── minute.py            # 1/5 分钟线
├── base.py              # akquant 回测骨架
└── registry.py          # 策略注册（仅 open_break3）

huice/
├── strategy1.py           # 凯盛科技
├── compare_kaicheng_*.py  # 对比脚本（仓位管理 / 软减半实验等）
├── hk1888.py              # 港股建滔积层板
└── gap945_*.py            # 945 专项统计
```

## 当前生效策略（因子1 · 唯一在用）

默认阈值 **±2.5%**。买卖均相对当日开盘（买入另有前日过滤）。

**买**

- 触发：`high ≥ ceil(open × 1.025)`，按触发价限价，仓位约 95%
- 过滤：前一日为阴线，或小阳（收盘涨幅严格 &lt; 2.5%）；且前面不能连续两根阳线
- T+1：买入当日不可卖（ETF 可设 `t0=True`）

**卖（优先级从高到低）**

1. 低开 09:45 未翻红 → **全清**（卖出价：09:45 分钟收盘价；无分钟可用 proxy）
2. 开盘 −2.5% 止损 → **全清**
3. 阴线收盘 → **全清**；阳线/十字持有

总开关：`ENABLE_SOFT_HALF_EXIT=False`（见下文「失败实验」）。回撤仓位管理默认关：`ENABLE_DD_SIZING=False`。

## 失败实验 · 不可用

### 软减半（945/阴线减半 · 止损全清）

曾在因子1上试过：

| 条件 | 原因子1 | 实验版 |
|------|---------|--------|
| 开盘 −2.5% 止损 | 全清 | 全清 |
| 低开 945 未翻红且未止损 | 全清 | 减半 |
| 收阴且未止损 | 全清 | 减半 |

凯盛科技（2020→2026-08）对比：**优化前全清 +503% / 夏普 1.05**；软减半 **+199% / 夏普 0.72**，回撤仅略好。结论：**失败，不可用**。

代码仍保留开关 `ENABLE_SOFT_HALF_EXIT` / `enable_soft_half_exit`，**必须保持 False**，日常回测与盯盘一律走原因子1全清。对比脚本：`huice/compare_kaicheng_soft_half.py`（仅复现实验，勿当生产配置）。

### 回撤仓位管理（20/15、优化 22/5）

权益回撤≥阈值半仓、回撤&lt;恢复阈值再全仓开仓。凯盛上相对无管理会明显少赚；**默认关闭** `ENABLE_DD_SIZING=False`。细节见 `huice/optimize_dd_sizing_RESULT.md`。

---

## 归档 · 因子2 / 因子3（已从代码删除，供后续开发参考）

> 以下规格仅文档存档。实现与开关（`ENABLE_FACTOR2` / `ENABLE_FACTOR3` 等）已从仓库移除；重新开发时按此设计即可。

### 因子2 · 高点回落减半仓

- **触发**：相对「开盘迄今最高价」回落 ≥ 2.5%（`mark ≤ floor(high_so_far × 0.975)`）
- **动作**：可卖仓位减半（整手）；一段持仓只减一次
- **优先级**：低于 945 / 止损，高于阴线全清；减半后当日仍可阴线清剩余
- **数据**：有 1 分钟线按分钟滚动最高价；否则日线近似（偏松）
- **历史开关名**：`ENABLE_FACTOR2`、`pullback_pct`、`enable_factor2`
- **凯盛结论（摘要）**：曾作为可选卖出因子；最终未纳入默认因子1

### 因子3 · 分时黄色均价线做 T

- **均线**：截至当前 K 的累计成交额 ÷ 累计成交量（分时黄线）；缺额量时退化为收盘价累计均值。盯盘用 1 分钟；回测可用 5 分钟近似（覆盖更长）
- **卖出**：现价相对当前分时均价涨幅 **&gt; 3%** → 可卖仓减半（整手）
- **回补**：某根 K 收盘落在该根分时均价 **±1%** 内 → 回补同等股数；未回补则尾盘最后可用价回补；若收阴且因子1要出则禁止回补
- **与因子1关系**：945 / 止损优先。因子1先触发则当日不做因子3；因子3先卖再触因子1 → 只卖剩余、禁止回补
- **历史开关名**：`ENABLE_FACTOR3`、`factor3_bar`（`1m`/`5m`）、`FACTOR3_SELL_ABOVE_MA_PCT=0.03`、`FACTOR3_REBUY_NEAR_MA_PCT=0.01`
- **凯盛结论（摘要）**：因子1+3(5m) 相对纯因子1有过阶段性超额（尤其近年），但默认策略已收敛为纯因子1；代码删除以免误开

---

## 用法

```python
from dataclasses import replace
from pathlib import Path
from strategy import BacktestConfig, run_open_break

cfg = BacktestConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    report_path=Path("凯盛科技_report.html"),
)
run_open_break(cfg, show_report=True)
```

```bash
cd huice && python strategy1.py --rules
```

注册表：

```python
from strategy.registry import get_strategy
get_strategy("open_break3").run(get_strategy("open_break3").default_config)
```
