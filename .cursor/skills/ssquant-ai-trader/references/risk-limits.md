# 风控规则库

## 单笔交易风控

### 止损设置

| 规则 | 计算公式 | 适用场景 |
|---|---|---|
| 固定点数止损 | `开仓价 ± N 点` | 波动稳定的品种（如螺纹、铁矿） |
| 百分比止损 | `开仓价 × (1 ± N%)` | 波动差异大的品种 |
| ATR 倍数止损 | `开仓价 ± N × ATR` | 自适应波动率 |
| 技术位止损 | `前低/前高/均线位置` | 有明确技术支撑压力的品种 |

### 默认止损规则

如果用户未指定止损，AI 自动计算：

```python
# 默认止损 = 2 × ATR(14)
atr_val = api.get_indicator('atr_14')
stop_loss_price = entry_price - 2 * atr_val  # 多单
stop_loss_price = entry_price + 2 * atr_val  # 空单
```

### 仓位计算

```python
# 基于单笔最大亏损（账户 2%）计算手数
max_loss_per_trade = equity * 0.02
stop_distance = abs(entry_price - stop_loss_price)
contract_multiplier = {品种乘数}
volume = int(max_loss_per_trade / (stop_distance * contract_multiplier))
volume = max(1, min(volume, max_allowed_volume))
```

## 账户级风控

### 日亏损限制

| 级别 | 阈值 | 动作 |
|---|---|---|
| 警告 | 日亏损 3% | 发送通知，继续交易 |
| 熔断 | 日亏损 5% | 暂停交易，通知用户 |
| 强平 | 日亏损 8% | 平掉所有持仓，通知用户 |

### 连续亏损限制

| 连续亏损笔数 | 动作 |
|---|---|
| 2 笔 | 发送提醒，关注策略表现 |
| 3 笔 | 暂停交易，通知用户检查 |
| 5 笔 | 强制暂停，要求用户确认后才恢复 |

### 最大回撤限制

| 回撤幅度 | 动作 |
|---|---|
| 5% | 警告 |
| 10% | 暂停交易 |
| 15% | 平仓 + 停止策略 |

## 持仓风控

### 保证金占用率

| 占用率 | 动作 |
|---|---|
| < 50% | 正常 |
| 50-70% | 警告，控制新开仓 |
| > 70% | 拒绝新开仓 |
| > 85% | 减仓警告 |

### 持仓时间

| 持仓时间 | 动作 |
|---|---|
| < 5 天 | 正常 |
| 5-15 天 | 关注 |
| > 20 天 | 提醒用户考虑平仓 |
| > 30 天 | 强制提醒 |

### 同向敞口监控

```python
# 检查多品种同向持仓
long_positions = [pos for pos in positions if pos['direction'] == 'long']
short_positions = [pos for pos in positions if pos['direction'] == 'short']

# 如果所有持仓同向，发出警告
if len(long_positions) > 3 and len(short_positions) == 0:
    log("⚠️ 全部多头持仓，无对冲")
if len(short_positions) > 3 and len(long_positions) == 0:
    log("⚠️ 全部空头持仓，无对冲")
```

## 市场异常风控

### 涨跌停检测

```python
# 检测涨跌停（价格长时间不动或成交量为 0）
if volume[-1] == 0 and close[-1] == close[-2]:
    log("⚠️ 疑似涨跌停，暂停交易")
    return
```

### 流动性检测

```python
# 成交量低于阈值
avg_volume = volume[-20:].mean()
if volume[-1] < avg_volume * 0.2:
    log("⚠️ 流动性不足，暂停交易")
    return
```

### 数据断点检测

```python
# 检查 K 线时间是否连续
current_time = api.get_datetime()
last_time = api.get_datetime(-1)
gap = current_time - last_time
if gap > expected_interval * 2:
    log("⚠️ K 线数据断点，暂停交易")
    return
```

## 风控代码模板

在策略 `strategy()` 函数中完整集成：

```python
def strategy(api: StrategyAPI):
    """带风控的策略主循环"""
    
    # ===== 风控层（最先执行） =====
    
    account = api.get_account_info()
    if account:
        equity = account.get('equity', 500000)
        initial_capital = account.get('initial_capital', 500000)
        daily_pnl = account.get('daily_pnl', 0)
        margin = account.get('margin', 0)
        
        # 日亏损熔断
        if daily_pnl < -initial_capital * 0.05:
            api.log("🚨 日亏损超 5%，暂停交易")
            return
        
        # 保证金限制
        if equity > 0 and margin / equity > 0.7:
            api.log("⚠️ 保证金占用率 > 70%，拒绝新开仓")
            # 仅允许平仓
            pos = api.get_pos()
            if pos == 0:
                return
        # ===== 以下仅允许平仓逻辑 =====
    
    # ===== 策略层 =====
    # ... 原有策略逻辑
```
