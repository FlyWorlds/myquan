# 策略1交互选股

策略1页上方提供指数范围多选、重新选股、保存并启用。勾选的成分取并集；剔除非主板/ST，候选最新日线收盘价须低于100元。目标30只，质量带不足允许放宽补足；最低数据与交易次数不足30只则报错，不覆盖旧池。

重新选股只产生持久化草稿及新增/移出预览。保存使用服务端草稿ID，不接受浏览器提交股票名单。保存前检查当前池指纹，避免覆盖其他操作；名单与逐股阈值在一个JSON内原子替换，旧池备份存于 `holdingStocks/.strategy1_selection/`。保存过的新池不再固定追加海量数据，公共自选和现有持仓继续沿用原管理机制。运行时策略池函数及条件单准备循环读取新名单。

时间口径沿用现有研究：2025年因子13A初筛，2026年初至执行日进行因子16排序及阈值拟合。数据实际截止日逐股展示。这不是独立样本外验证，也没有在本次改动中启用月度自动调度。

旧初筛面板不包含所有指数，缺失股票会补算2025初筛并缓存。后台独立子进程执行，每个任务使用独立目录；默认网络请求超时，整个任务60分钟超时退出。失败保留原池。四个选项按照现有 `backtest/universe_wide/results.csv` 的index列筛选：其中“中证1500”标签包含2000只，尚未核实其标准指数身份，界面明确提示，不声称已核实。

接口：GET `/api/strategy1/selection`；POST `/run` 参数 `indices`；POST `/save` 参数 `draft_id`（后两者均在上述路径下）。

验证：`python -m pytest holdingStocks/test_strategy1_selection.py holdingStocks/test_strategy1_backtest_api.py -q`；前端 `npm --prefix holdingStocks/watch-ui run build`。
