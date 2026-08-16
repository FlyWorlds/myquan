# 交易规则 → 代码映射表

## 均线类

| 用户描述 | 注册代码 | 判断逻辑 |
|---|---|---|
| "N 日均线" | `api.register_indicator('ma_N', lambda c,o,h,l,v: pd.Series(c).rolling(N).mean().to_numpy(), window=N)` | `ma_N[-1] > ma_N[-2]` |
| "EMA 指数均线" | 自定义 EMA 函数 | 同上 |
| "金叉" | 注册两条均线 | `fast[-2] <= slow[-2] and fast[-1] > slow[-1]` |
| "死叉" | 注册两条均线 | `fast[-2] >= slow[-2] and fast[-1] < slow[-1]` |
| "价格在均线上方" | 注册均线 | `close[-1] > ma_N[-1]` |
| "均线多头排列" | 注册多条均线 | `ma5 > ma10 > ma20` |

## MACD

```python
def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = pd.Series(close).ewm(span=fast, adjust=False).mean()
    ema_slow = pd.Series(close).ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = 2 * (dif - dea)
    return dif.to_numpy(), dea.to_numpy(), macd.to_numpy()

api.register_indicator('macd_dif', lambda c,o,h,l,v: _macd(c)[0], window=26)
api.register_indicator('macd_dea', lambda c,o,h,l,v: _macd(c)[1], window=26)
api.register_indicator('macd_hist', lambda c,o,h,l,v: _macd(c)[2], window=26)
```

| 用户描述 | 判断逻辑 |
|---|---|
| "MACD 金叉" | `dif[-2] <= dea[-2] and dif[-1] > dea[-1]` |
| "MACD 死叉" | `dif[-2] >= dea[-2] and dif[-1] < dea[-1]` |
| "MACD 红柱变长" | `hist[-1] > hist[-2] > 0` |
| "MACD 底背离" | 价格新低但 DIF 未新低（需比较历史极值） |

## RSI

```python
def _rsi(close, period=14):
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50).to_numpy()

api.register_indicator('rsi_14', lambda c,o,h,l,v: _rsi(c, 14), window=14)
```

| 用户描述 | 判断逻辑 |
|---|---|
| "RSI 超买" | `rsi[-1] > 70` |
| "RSI 超卖" | `rsi[-1] < 30` |
| "RSI 从超卖区回升" | `rsi[-2] < 30 and rsi[-1] >= 30` |

## 布林带

```python
def _bollinger(close, period=20, std_mult=2):
    sma = pd.Series(close).rolling(period).mean()
    std = pd.Series(close).rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    return upper.to_numpy(), sma.to_numpy(), lower.to_numpy()

api.register_indicator('bb_upper', lambda c,o,h,l,v: _bollinger(c)[0], window=20)
api.register_indicator('bb_mid', lambda c,o,h,l,v: _bollinger(c)[1], window=20)
api.register_indicator('bb_lower', lambda c,o,h,l,v: _bollinger(c)[2], window=20)
```

| 用户描述 | 判断逻辑 |
|---|---|
| "突破布林上轨" | `close[-1] > bb_upper[-1] and close[-2] <= bb_upper[-2]` |
| "跌破布林下轨" | `close[-1] < bb_lower[-1] and close[-2] >= bb_lower[-2]` |
| "回踩中轨支撑" | `close[-1] > bb_mid[-1] and close[-2] <= bb_mid[-2]` |

## 价格突破

| 用户描述 | 判断逻辑 |
|---|---|
| "突破前 N 日高点" | `close[-1] > max(high[-N-1:-1])` |
| "跌破前 N 日低点" | `close[-1] < min(low[-N-1:-1])` |
| "创 N 日新高" | `high[-1] == max(high[-N:])` |
| "创 N 日新低" | `low[-1] == min(low[-N:])` |

## ATR（波动率）

```python
def _atr(high, low, close, period=14):
    tr1 = pd.Series(high) - pd.Series(low)
    tr2 = (pd.Series(high) - pd.Series(close).shift()).abs()
    tr3 = (pd.Series(low) - pd.Series(close).shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    return atr.to_numpy()

api.register_indicator('atr_14', lambda c,o,h,l,v: _atr(h, l, c, 14), window=14)
```

| 用户描述 | 判断逻辑 |
|---|---|
| "波动率放大" | `atr[-1] > atr[-1] 的 20 日均线` |
| "固定点数止损" | `开仓价 - N * price_tick` |
| "ATR 倍数止损" | `开仓价 - N * atr[-1]` |

## 成交量

| 用户描述 | 判断逻辑 |
|---|---|
| "放量" | `volume[-1] > volume[-N:].mean() * 1.5` |
| "缩量" | `volume[-1] < volume[-N:].mean() * 0.5` |
| "天量" | `volume[-1] == max(volume[-N:])` |
| "地量" | `volume[-1] == min(volume[-N:])` |

## 止损止盈

| 用户描述 | 实现方式 |
|---|---|
| "固定点数止损" | `开仓价 - N 点`（多）/ `开仓价 + N 点`（空） |
| "百分比止损" | `开仓价 * (1 - N%)`（多）/ `开仓价 * (1 + N%)`（空） |
| "跟踪止盈" | 记录最高价，回撤 N 点或 N% 平仓 |
| "时间止损" | 持仓超过 N 根 K 线未盈利则平仓 |
| "保本止损" | 浮盈超过 N 点后，止损上移至开仓价 |
