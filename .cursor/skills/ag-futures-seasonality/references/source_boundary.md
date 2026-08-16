# Source Boundary

本 skill 只对公开历史行情做季节性统计，不预测、不喊单。

Allowed sources（允许）:

- 公开期货行情：主力连续/合约日线（经 `skill-pandadata-api` 等数据类 skill 合规获取）
- 用户自备的行情导出（csv：date, close）
- 公开农业常识：作物种植/收割日历、南北半球错季等（见 `crop-calendar.md`）

Not allowed unless the user has rights and explicitly provides them（除非用户拥有权利并明确提供，否则不允许）:

- 付费墙内 / 会员专享数据
- 非公开的产量、库存、天气预报等商业数据源

## 输出边界

- 只输出"历史季节性统计规律 + 作物日历解释 + 当前所处周期位置"
- 不输出点位预测、目标价、买卖指令
- 每个季节性结论须标注：品种、数据窗口、样本年数、统计显著性、是事实还是推断
- 必须声明"季节性是历史概率，当年基本面可覆盖季节性"
