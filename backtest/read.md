# 回测与合格标的池

> **现行盯盘池以 `holdingStocks/README.md` / `holdingStocks/watch_config.py` 为准**（中证500+1000，夏普≥1 且策略超额，约 11 只）。  
> 下文旧「50 只 HS300+ZZ500」口径已废弃，勿再用于盯盘配置。

## 策略锁定（与策略一一致）

- **策略**：策略一 · 因子1（+ 可选因子2 权益叠加）
- **买**：`high ≥ ceil(open×(1+pct))`；前日阴线或小阳；禁双阳跨日≥5%；T+1
- **卖**：仅止损 `low ≤ floor(open×(1−pct))` 全清；无止盈
- **个股阈值**：默认 ±2.5%；天通 ±3.0% / 凯盛 ±2.5%（`holdingStocks/watch_config._WATCH_PCT`）
- **筛选（现行）**：中证500 + 中证1000（剔科创/创业/北交）；夏普 ≥ 1.0 且策略收益 > 买入持有
- **脚本**：`universe_zz500_1000.py`（全池统一阈值）；盯盘拟合度：`fit_strategy1_watch.py`
- **盯盘列表真源**：`holdingStocks/watch_config.py` 的 `_FIT_WATCH` / `_WATCH_PCT`

## 常用入口

```bash
cd backtest
python run.py --list
python run.py kaicheng
python strategy1.py --rules
```

历史实验 CSV / `universe_abc/` 仅为研究残留，不代表当前生产池。
