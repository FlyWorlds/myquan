# Strategy Contract — 策略契约模板

一份可回测的策略必须先把"契约"写清楚：谁在什么信号下、以多大仓位、按什么规则进出、受什么风控约束。
下面每个字段都要能被 `scripts/validate_report.py` 和人工逐条核对。产物 `strategy_spec.md` 按此模板填。

## 1. Universe（标的池）

- 明确列出海外标的及其数据代码，例如：
  - 原油连续期货 `CL=F`、黄金 `GC=F`、标普 500 期货 `ES=F`、10 年美债期货 `ZN=F`
  - 外汇 `EURUSD=X`、`USDJPY=X`；指数 `^GSPC`
- 采样频率：默认**日线**（本 skill 只做日线研究，不做日内）。
- 数据来源：Yahoo Finance / stooq 下载的 CSV，至少含 `date, close`，可选 `open`（用于 t+1 开盘成交）。
- 标的数量提醒：单标的或 2–3 个标的的回测**统计意义有限**，结论只能当案例，不能外推为普适策略。

## 2. Signal（信号定义）

信号是一列与日期对齐的数值 `signal(t)`，来源三选一：

| 来源 | 说明 | 取数方式 |
| --- | --- | --- |
| 姊妹海外技能 | 商品期限结构 / 宏观利率汇率 / 因子矿工产出 | 消费其输出的 `date,value` 序列 |
| 用户自带 | 用户提供 `date,value` 的信号 CSV | 直接读入 |
| 内置示例 | 收盘价均线交叉（`SMA_fast - SMA_slow`）符号 | `scripts/backtest.py --signal builtin_ma` 生成，仅用于跑通 demo |

- **方向约定**：`signal>0` → 看多目标暴露为正，`signal<0` → 看空（或空仓，若只做多）。
- **标准化（可选）**：趋势策略常用滚动 z-score：`z(t) = (signal(t) - mean_N) / std_N`，便于设阈值带。
- **Pandadata 信号**：若信号取自 Pandadata 海外接口，**不要臆造方法签名**——把取数委托给 `pandadata-api`
  skill，本 skill 只接收其返回的 `date,value`。

## 3. Entry / Exit（进出场规则）

- **趋势跟随（默认）**：
  - 纯符号：`position_target = sign(signal)`（或 `sign(z)`）。
  - 阈值带（滞回，推荐）：`|z| > enter` 才进场，`|z| < exit` 才平仓，`enter > exit`（如 1.0 / 0.3），
    减少在零轴附近反复打脸的换手。
- **只做多 vs 多空**：写清是 long-only（`position ∈ {0, +w}`）还是 long/short（`{-w, 0, +w}`）。
- **再平衡频率**：每日或每周对齐一次目标仓位；频率越高换手越大、成本越重（见 backtest-notes）。

## 4. Position Sizing（仓位管理，二选一）

- **波动率目标 vol-target**：
  - `realized_vol(t) = std(returns, N) * sqrt(annualization)`（N 如 20，年化 252）。
  - `weight(t) = clip(target_vol / realized_vol(t), 0, max_leverage) * direction`。
  - 好处：低波动期加仓、高波动期减仓，组合波动更稳。
- **固定比例 fixed-fraction**：
  - 每个方向固定暴露 `f`（如 1.0 满仓、0.5 半仓），`weight(t) = f * direction`。
  - 好处：简单、可解释；缺点：不随波动自适应。
- 两者都要声明 `max_leverage`（默认 1.0，不加杠杆）。

## 5. Risk Limits（风控上限，至少三道）

| 闸门 | 参数 | 行为 |
| --- | --- | --- |
| 单标的最大权重 | `max_weight` | 目标权重超限则截断到 `max_weight` |
| 止损 | `stop_pct` | 持仓价格较入场价回撤超 `stop_pct` 时平仓，冷却到下次信号 |
| 回撤守门 | `dd_guard` | 组合 NAV 从峰值回撤超 `dd_guard` 时降杠杆或空仓，回到阈值内再恢复 |

- 风控是"研究阶段的纪律假设"，不等于真实成交能拿到的价格；止损在跳空时可能滑点更大。

## 6. Execution & Costs（执行与成本，规避前视）

- **执行滞后**：`signal(t)` 在收盘后才知道，**只能在 `t+1` 成交**（开盘或收盘，二选一并写明）。
  脚本默认 `t+1` 收盘成交；有 `open` 列时可切到 `t+1` 开盘。
- **成本**：双边手续费 + 滑点，用 bps 表示（如手续费 2bps + 滑点 1bps）。成本按**换手**计提。
- **换手定义**：`turnover(t) = sum |weight(t) - weight(t-1)|`，成本 = `turnover * cost_bps/1e4`。

## 契约自检清单

- [ ] universe、频率、数据来源都写明？
- [ ] 信号来源与方向约定清楚？（三选一）
- [ ] 进出场是纯符号还是阈值带？再平衡频率？
- [ ] 仓位是 vol-target 还是 fixed-fraction？参数齐全？
- [ ] 三道风控（max_weight / stop / dd_guard）都有值？
- [ ] 明确 `signal(t) → trade(t+1)`，成本与滑点 bps 写清？
- [ ] 声明"仅研究、不下单、不构成任何投资建议"？
