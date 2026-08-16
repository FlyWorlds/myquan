# SIMNOW 账号配置指南

## 什么是 SIMNOW

SIMNOW 是上期技术提供的 CTP 模拟交易平台，提供仿真行情和模拟成交，用于策略验证。

## 注册 SIMNOW 账号

1. 访问 https://www.simnow.com.cn
2. 注册账号（需要手机号）
3. 登录后获取：
   - 投资者编号（Investor ID）
   - 交易密码
   - 经纪商代码（Broker ID，通常 9999）

## SSQuant 中配置 SIMNOW 账号

编辑 `ssquant/config/trading_config.py`，在 `ACCOUNTS` 字典中添加：

```python
ACCOUNTS = {
    'simnow_default': {
        'investor_id': '你的 SIMNOW 账号',
        'password': '你的密码',
        'broker_id': '9999',
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    },
}
```

## 服务器线路选择

| 线路 | 地址 | 特点 |
|---|---|---|
| 24hour（推荐） | tcp://180.168.146.187:10130 | 7×24 小时连续交易，适合全天候测试 |
| 电信1 | tcp://182.254.243.31:30001 | 正常交易时间，电信线路 |
| 电信2 | tcp://182.254.243.31:30002 | 正常交易时间，电信线路 |
| 移动 | tcp://218.202.237.33:10203 | 移动线路 |
| TEST | tcp://182.254.243.31:40001 | 测试环境 |
| N视界 | tcp://210.14.72.12:4600 | 另服务器 |

**AI 交易员默认使用 `24hour` 线路**，因为可以全天候运行。

## 验证连接

运行以下代码测试连接：

```python
from ssquant.backtest.unified_runner import RunMode, UnifiedStrategyRunner
from ssquant.config.trading_config import get_config

def initialize(api):
    api.log("SIMNOW 连接测试")

def strategy(api):
    if api.get_idx() == 0:
        api.log(f"行情数据: {api.get_close()}")
        api.log("连接成功！")

config = get_config(RUN_MODE,
    account='simnow_default',
    server_name='24hour',
    symbol='rb888',
    kline_period='1m',
    kline_source='data_server',
    preload_history=True,
    history_lookback_bars=10,
    lookback_bars=10,
)

runner = UnifiedStrategyRunner(mode=RunMode.SIMNOW)
runner.set_config(config)
runner.run(strategy=strategy, initialize=initialize)
```

## 常见问题

### 1. 连接失败

- 检查网络是否通畅
- 确认 `trading_config.py` 中的账号配置正确
- 尝试切换服务器线路

### 2. 行情数据不更新

- SIMNOW 只在交易时间有实时行情
- 24hour 环境有合成行情
- 检查 `kline_source` 设置（`data_server` 或 `local`）

### 3. 报单失败

- 检查品种代码是否正确（用 `rb888` 而非 `rb2610`）
- 检查资金是否充足
- 检查涨跌停限制

### 4. CTP 不可用

运行 `from ssquant import CTP_AVAILABLE` 检查：

- `True`：CTP 正常
- `False`：检查 Python 版本是否匹配（支持 py39-py314）

## 注意事项

- SIMNOW 是模拟环境，成交速度和滑点与实盘不同
- 24hour 环境行情是合成的，可能与真实行情有差异
- 策略在 SIMNOW 验证通过后，建议再用小资金在实盘试跑
