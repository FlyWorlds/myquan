# 美股联动 → 策略11 → 策略1 联合选股

研究回测，不构成投资建议。

## 流水线
1. **美股隔夜**：前一美股交易日主题 ETF 涨跌（yfinance），取 Top2 主题
   且主题涨幅 ≥ 0.5%
2. **策略11**：2020-01-01～2024-12-31 笔盈亏比 ≥ 1.5，闭环 ≥ 3
3. **策略1**：周频 `px_composite` Top5，entry_pct=0.03

最近美股快照（2026-08-27）：
  - software (IGV): +7.74%
  - tech (XLK): +3.16%
  - semiconductor (SMH): +3.10%
  - innovation (ARKK): +1.87%
  - nasdaq (QQQ): +1.37%

## 样本内最优
| 参数 | 值 |
|------|-----|
| us_top_n | 2 |
| us_min_ret | 0.005 |
| pl_ratio_min | 1.5 |
| entry_pct | 0.03 |
| top_k | 5 |
| value_col | px_composite |
| 联动后池子 | 10 |

样本内：累计 719.2%，夏普 1.96，回撤 31.3%

## 2025 至今验证（OOS）
- 累计 **111.8%**
- 夏普 **1.92**
- 最大回撤 **22.0%**
- 合格标的 **10** 只

## 当前合格池（美股主题 ∩ 笔盈亏比）
```
  symbol name                      themes  pl_ratio_is  n_trades_is
sz301550 斯菱智驱 [semiconductor, industrial]        2.832           56
sh600206 有研新材     [semiconductor, mining]        2.592           93
sz002747  埃斯顿    [industrial, innovation]        2.306          150
sz301205 联特科技       [semiconductor, comm]        2.194           96
sz002335 科华数据            [software, tech]        2.181          162
sh600552 凯盛科技       [semiconductor, tech]        2.152          133
sz001339 智微智能            [software, tech]        2.116           73
sz002979 雷赛智能          [tech, industrial]        1.975          131
sh603083 剑桥科技       [comm, semiconductor]        1.736          157
sh601208 东材科技 [industrial, semiconductor]        1.504          144
```

## 分年
```
 year   ret_pct   sharpe   mdd_pct   ann_pct  n_days
 2020 63.264887 2.752616 17.498699 63.539958     243
 2021 22.714683 0.878820 19.084787 23.010758     243
 2022 33.499168 1.430940 22.145727 34.062852     242
 2023 78.657443 3.040099  8.886885 80.175784     242
 2024 62.863935 1.928324 22.111493 63.136953     242
 2025 50.886894 1.832451 22.033239 51.272109     243
 2026 36.979442 1.918619 18.309659 63.419943     158
```

## 与纯 A 股 s1+s11 对比
纯 A 股流水线（无美股门控）见 `s1_s11_select/report.md`；本报告在同样策略1/11 前增加**美股主题过滤**。

免责声明：映射为静态主题标签 + ETF 代理，不构成投资建议。
