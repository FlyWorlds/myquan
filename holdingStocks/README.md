# 持仓盯盘

本地持仓记录 + 盘中盯盘：对齐 `kskj600552` 的相对开盘买卖逻辑，生成 HTML 报告；支持止损/尾盘阴线自动结算与定时刷新。

## 盯盘标的

| 代码 | 名称 | 阈值 | 备注 |
|------|------|------|------|
| 000893 | 亚钾国际 | ±2.5% | |
| 600552 | 凯盛科技 | ±2.5% | |
| 002171 | 楚江新材 | ±2.5% | |
| 510580 | 易方达中证500ETF | ±1.2% | 价格 3 位小数；`t0=True` 当日可卖 |

改池子：编辑 `index.py` 里的 `WATCHLIST`。

## 策略规则（有仓）

优先级从上到下：

1. **买入当日（T+1）**：股票不判卖（ETF `t0` 除外）。
2. **低开 9:45 未翻红 → 全清**  
   - 低开：`open < 昨收`  
   - **翻红（触及即算）**：9:45 **前**（不含 9:45 那根 1 分钟 K）最高价 `>= 昨收` → **不卖**，继续按下列规则  
   - **未翻红**：到 09:45 仍 `9:45前最高 < 昨收` → **全部可卖仓位清仓**  
   - 成交价：`09:45` 那根 **1 分钟 K 收盘价**，或 **09:40~09:45 五分钟 K 收盘价**（由 `GAP945_EXIT_MODE` 配置，默认 1m）
3. **止损**：盘中最低价 ≤ 开盘×(1−阈值)（向下取整到 tick）→ **按止损价自动结算**并清仓。
4. **尾盘阴线**：未触上述规则，且现价 &lt; 开盘；  
   - 盘中：状态「阴线·待尾盘」（仅预警）；  
   - **≥14:55** 仍阴 → **按现价自动结算**（阴线收盘卖）。
5. **阳线 / 十字**：继续持有。

完整规则说明：`python -c "from strategy import STRATEGY_RULES; print(STRATEGY_RULES)"`  
或：`cd myquan/huice && python strategy1.py --rules`

空仓：最高冲到买点（开盘×(1+阈值) 向上取整）→ 「已触买 / 将买入」并建议限价。

已结算标的会继续刷新现价；止损单额外统计 **止损后最高 / 最低、回抽%、踏空金额**。

## 依赖

```bash
pip install akshare pandas
```

## 用法

在 `holdingStocks` 目录下：

```bash
# 跑一次：拉行情 + 写 HTML（默认会打开浏览器）
python index.py
python index.py status --no-open

# 只生成/打开报告
python index.py html

# 长驻盯盘：本地 HTTP + 每 60 秒更新；页头有倒计时并自动刷新
python index.py watch
python index.py watch --interval 30 --port 8765
# 浏览器打开：http://127.0.0.1:8765/holdings_report.html
# 停止：终端 Ctrl+C
```

### 持仓登记

```bash
python index.py buy 002171 9.05 1000
python index.py sell 002171 9.20 500
python index.py set-cost 600552 15.95 --qty 400
python index.py clear 002171
python index.py history
```

## 文件说明

| 文件 | 作用 |
|------|------|
| `index.py` | 主程序 |
| `holdings.json` | 持仓成本/数量、当日已实现盈亏 |
| `trades.jsonl` | 买卖流水（含自动止损/阴线卖） |
| `holdings_report.html` | 盯盘报告 |
| `holdings_watch.json` | `watch` 模式更新时间戳（供页面轮询刷新） |

## 注意

- **`python index.py` 只跑一次**，不会后台自动更新；要自动刷新请用 **`watch`**，并用本地服务地址打开页面（不要只开 `file://`）。
- 行情来源：新浪 1 分钟线拼当日 OHLC；大盘指数用新浪 spot。
- 自动结算是盯盘侧记账，**不会下真实委托**；实盘请按报告「建议挂单」自行下单。
- 尾盘阴线结算时刻：`YIN_EXIT_HOUR` / `YIN_EXIT_MINUTE`（默认 14:55）。
