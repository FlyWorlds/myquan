# 因子34：地量转放量动量（研究）

基于2026-11-03当前池量价研究实现，可通过因子注册表取得。不自动下单，不绑定策略一或策略十六。
原研究：`reports/pool_volume_price_20261103/REPORT.md`。78次信号未证明稳定短线优势，故不选择最优持有天数，不宣称盈利。

## 规则

1. 含当日在内60个交易日成交量最低（相等也算）标为地量锚点。
2. 使用此前最近锚点，距信号日1至10个交易日。
3. 成交量至少是锚点日2倍，实体`close/open-1 >= 0.05`。
4. 每个锚点仅首次产生候选；新的地量日开始新的周期。

输出`candidate`及锚点日期、间隔、量倍数、实体收益、前20日均量倍数、RSI14、20日乖离、收盘区间位置。
收益/乖离使用小数（0.05代表5%）。RSI为0至100。不添加未经验证的RSI过滤或综合评分权重。

## 接口

```python
from strategy.factors.factor34 import compute, signal, tail_candidate

features = compute(completed_daily)  # date/open/high/low/close/volume
research = signal(completed_daily, as_of=decision_time)
tail = tail_candidate(previous_completed_daily, quote=observed_quote, now=decision_time,
                      consumed_anchors=persisted_anchor_dates)
```

`compute`是离线已完成日线特征计算；所有行只依赖此前及该行数据，无未来收益字段。
`signal`同日须15:15后才接受该日日线。没有行情就绪时刻的历史日线只能做收盘后研究，不能反推收盘前成交。

`tail_candidate`仅14:55至14:57前接收5秒内经确认的报价，报价字段为
`ts/open/high/low/last/volume/prev_close/source_verified`；`volume`必须是当时累计量，不能传最终日量。
`prev_close`为官方昨收参考价；近涨停（默认≥9.7%）排除。历史不能含当日或未来日。

调用者必须验证交易日历、上一完整交易日覆盖、历史无缺失、行情来源真实性；历史和现价须同一价格口径，成交量须同单位。
停牌日不能以零量占位；交易日间隔按输入有效交易日计算。拆股导致的成交量单位变化需上游处理。
尾盘调用者需持久化已处理锚点、保证幂等；纯函数不记订单状态、不判断现金/仓位/T+1。
历史收盘信号也会消耗对应锚点；尾盘首次信号与历史收盘首次信号并不保证完全一致，应保存真实尾盘观察日志。

所有接口的`hit_buy`均不输出可执行买单（候选接口固定False），只使用`candidate`研究。
通过下一笔可执行报价和独立执行层确认买点，不能按本函数给出的已知价格假设成交。
持仓期限、止损、T+1、涨跌停排队、手续费和滑点均属于策略执行层。

## 验证

`PYTHONPATH=. .venv/bin/python -m pytest -q strategy/test_factor34.py`

7项测试通过，涵盖因果前缀一致性、60日预热、十日期限、锚点去重、实体与跳空区别、收盘可用性、尾盘时效和研究注册。
另用冻结的25只股票历史数据核对，78次信号的日期和地量锚点与原研究完全一致。单位一致性仍由上游负责，无法从数值自动证明。
