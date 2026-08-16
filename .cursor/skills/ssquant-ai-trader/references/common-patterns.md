# 常见交易模式模板

## 1. 双均线趋势跟踪

**用户描述示例**："用 5 日和 10 日均线，金叉做多，死叉平仓，每次 2 手"

```python
def initialize(api):
    api.register_indicator('ma5',
        lambda c,o,h,l,v: pd.Series(c).rolling(5).mean().to_numpy(), window=5)
    api.register_indicator('ma10',
        lambda c,o,h,l,v: pd.Series(c).rolling(10).mean().to_numpy(), window=10)

def strategy(api):
    ma5 = api.get_indicator_array('ma5', window=2)
    ma10 = api.get_indicator_array('ma10', window=2)
    if len(ma5) < 2 or len(ma10) < 2:
        return
    
    pos = api.get_pos()
    
    # 金叉开多
    if ma5[-2] <= ma10[-2] and ma5[-1] > ma10[-1] and pos == 0:
        api.buy(volume=2, order_type='next_bar_open')
        api.log(f"金叉开多 2 手 @ {api.get_close()}")
    
    # 死叉平多
    elif ma5[-2] >= ma10[-2] and ma5[-1] < ma10[-1] and pos > 0:
        api.sell(volume=2, order_type='next_bar_open')
        api.log(f"死叉平多 @ {api.get_close()}")
```

## 2. 价格突破（唐奇安通道）

**用户描述示例**："突破 20 日高点做多，跌破 10 日低点平仓"

```python
def initialize(api):
    api.register_indicator('high_20',
        lambda c,o,h,l,v: pd.Series(h).rolling(20).max().to_numpy(), window=20)
    api.register_indicator('low_10',
        lambda c,o,h,l,v: pd.Series(l).rolling(10).min().to_numpy(), window=10)

def strategy(api):
    high_20 = api.get_indicator('high_20')
    low_10 = api.get_indicator('low_10')
    close = api.get_close()
    high = api.get_high()
    low = api.get_low()
    pos = api.get_pos()
    
    # 突破 20 日高点开多
    if high[-1] >= high_20 and pos == 0:
        api.buy(volume=2, order_type='next_bar_open')
        api.log(f"突破20日高点开多 @ {close[-1]}")
    
    # 跌破 10 日低点平仓
    elif low[-1] <= low_10 and pos > 0:
        api.sell(volume=2, order_type='next_bar_open')
        api.log(f"跌破10日低点平仓 @ {close[-1]}")
```

## 3. RSI 均值回归

**用户描述示例**："RSI 低于 30 做多，高于 70 平仓"

```python
def _rsi(close, period=14):
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50).to_numpy()

def initialize(api):
    api.register_indicator('rsi_14', lambda c,o,h,l,v: _rsi(c, 14), window=14)

def strategy(api):
    rsi = api.get_indicator_array('rsi_14', window=2)
    if len(rsi) < 2:
        return
    
    pos = api.get_pos()
    
    # RSI 从超卖区回升
    if rsi[-2] < 30 and rsi[-1] >= 30 and pos == 0:
        api.buy(volume=2, order_type='next_bar_open')
        api.log(f"RSI 超卖回升开多 @ {api.get_close()}")
    
    # RSI 进入超买区平仓
    elif rsi[-1] > 70 and pos > 0:
        api.sell(volume=2, order_type='next_bar_open')
        api.log(f"RSI 超买平仓 @ {api.get_close()}")
```

## 4. MACD 趋势

**用户描述示例**："MACD 金叉做多，死叉平仓"

```python
def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = pd.Series(close).ewm(span=fast, adjust=False).mean()
    ema_slow = pd.Series(close).ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif.to_numpy(), dea.to_numpy()

def initialize(api):
    api.register_indicator('macd_dif', lambda c,o,h,l,v: _macd(c)[0], window=26)
    api.register_indicator('macd_dea', lambda c,o,h,l,v: _macd(c)[1], window=26)

def strategy(api):
    dif = api.get_indicator_array('macd_dif', window=2)
    dea = api.get_indicator_array('macd_dea', window=2)
    if len(dif) < 2 or len(dea) < 2:
        return
    
    pos = api.get_pos()
    
    # MACD 金叉
    if dif[-2] <= dea[-2] and dif[-1] > dea[-1] and pos == 0:
        api.buy(volume=2, order_type='next_bar_open')
        api.log(f"MACD 金叉开多 @ {api.get_close()}")
    
    # MACD 死叉
    elif dif[-2] >= dea[-2] and dif[-1] < dea[-1] and pos > 0:
        api.sell(volume=2, order_type='next_bar_open')
        api.log(f"MACD 死叉平仓 @ {api.get_close()}")
```

## 5. 布林带突破

**用户描述示例**："价格突破布林上轨做空（回归），回到中轨平仓"

```python
def _bollinger(close, period=20, std_mult=2):
    sma = pd.Series(close).rolling(period).mean()
    std = pd.Series(close).rolling(period).std()
    return (sma + std_mult * std).to_numpy(), sma.to_numpy(), (sma - std_mult * std).to_numpy()

def initialize(api):
    api.register_indicator('bb_upper', lambda c,o,h,l,v: _bollinger(c)[0], window=20)
    api.register_indicator('bb_mid', lambda c,o,h,l,v: _bollinger(c)[1], window=20)
    api.register_indicator('bb_lower', lambda c,o,h,l,v: _bollinger(c)[2], window=20)

def strategy(api):
    upper = api.get_indicator('bb_upper')
    mid = api.get_indicator('bb_mid')
    lower = api.get_indicator('bb_lower')
    close = api.get_close()
    pos = api.get_pos()
    
    # 突破上轨做空（均值回归）
    if close[-1] > upper and pos == 0:
        api.sellshort(volume=2, order_type='next_bar_open')
        api.log(f"突破上轨做空 @ {close[-1]}")
    
    # 回到中轨平空
    elif close[-1] <= mid and pos < 0:
        api.buycover(volume=2, order_type='next_bar_open')
        api.log(f"回到中轨平空 @ {close[-1]}")
    
    # 突破下轨做多
    elif close[-1] < lower and pos == 0:
        api.buy(volume=2, order_type='next_bar_open')
        api.log(f"突破下轨做多 @ {close[-1]}")
    
    # 回到中轨平多
    elif close[-1] >= mid and pos > 0:
        api.sell(volume=2, order_type='next_bar_open')
        api.log(f"回到中轨平多 @ {close[-1]}")
```

## 6. 固定点数止损 + 跟踪止盈

**用户描述示例**："做多，固定 30 点止损，盈利超过 20 点后用跟踪止盈（回撤 15 点平仓）"

```python
# 需要在 initialize 中记录开仓价和最高价
# 用全局变量或 api 对象属性存储

def initialize(api):
    api._entry_price = None
    api._highest_price = None
    api.register_indicator('ma20',
        lambda c,o,h,l,v: pd.Series(c).rolling(20).mean().to_numpy(), window=20)

def strategy(api):
    close = api.get_close()
    high = api.get_high()
    pos = api.get_pos()
    
    # 记录开仓价和最高价
    if pos > 0 and api._entry_price is None:
        api._entry_price = close[-1]
        api._highest_price = close[-1]
    
    if pos > 0 and api._entry_price is not None:
        api._highest_price = max(api._highest_price, high[-1])
        
        # 固定止损
        if close[-1] <= api._entry_price - 30:
            api.sell(volume=api.get_pos(), order_type='next_bar_open')
            api.log(f"固定止损平仓 @ {close[-1]}")
            api._entry_price = None
            api._highest_price = None
            return
        
        # 跟踪止盈（盈利 > 20 点后，回撤 15 点平仓）
        profit = api._highest_price - api._entry_price
        if profit >= 20 and close[-1] <= api._highest_price - 15:
            api.sell(volume=api.get_pos(), order_type='next_bar_open')
            api.log(f"跟踪止盈平仓 @ {close[-1]}")
            api._entry_price = None
            api._highest_price = None
            return
    
    # 重置
    if pos == 0:
        api._entry_price = None
        api._highest_price = None
    
    # 原有开仓逻辑
    # ...
```
