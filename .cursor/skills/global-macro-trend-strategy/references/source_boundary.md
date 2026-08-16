# Source Boundary — 数据读取边界

本 skill 只做**离线研究回测**，不联网、不下单、不使用实时行情。数据由使用者自行准备。

Allowed sources（允许）:

- 公开海外日线价格：Yahoo Finance / stooq 的连续期货、外汇、指数（导出为 CSV，含 `date, close`）。
- 用户自备的信号序列（`date, value` CSV）。
- 姊妹海外技能（商品期限结构 / 宏观利率汇率 / 因子矿工）产出的信号序列。
- 脚本内置的示例信号（均线交叉），仅用于跑通 demo。
- 若信号来自 Pandadata 海外接口：把取数委托给 `pandadata-api` skill，本 skill 只消费其 `date,value` 返回。

Not allowed unless the user has rights and explicitly provides them（未经授权不得使用）:

- 付费 / 会员 / 私有数据源、内幕或非公开数据。
- 实时行情、券商账户、下单接口（本 skill 不接触实盘执行）。
- 任何 API key / token / 私有凭据——不得写入任何文件。

Reminder: 数据合法性与许可由使用者负责；回测结果仅为历史统计，不构成任何投资建议。
