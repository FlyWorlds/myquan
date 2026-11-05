"""Notification severity; never changes trading decisions or alert admission."""

def signal_priority(*values):
    text = ' '.join(str(v or '') for v in values).lower()
    if any(k in text for k in ('hard_from_cost', 'hard_stop', 'risk_exit', 'force_exit', 'forced_exit', 'open_protect', '硬止损', '硬保护', '强制退出', '强制平仓', '风控退出', '风险退出', '隔夜开盘保护')):
        return 'P0 紧急'
    if any(k in text for k in ('half_gain', 'peak_pullback', 'peak_trail', 'vol_giveback', 'trend_break', 'trend_broken', '峰值回撤', '峰值回落', '峰值回吐', '波动回吐', '趋势破位', '趋势跌破', '回落止盈', '回吐一半', '中赚回落')) :
        return 'P1 重要'
    return 'P2 普通'
