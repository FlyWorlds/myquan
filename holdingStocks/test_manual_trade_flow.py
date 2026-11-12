# -*- coding: utf-8 -*-
"""手动交易（买入入池建仓 / 卖出平仓锁定收益）核心流与接口单测。"""

import pytest
from unittest.mock import patch, MagicMock

import holdingStocks.watch_config as watch_config
from holdingStocks.index import (
    _CONDITION_BUY_ACTIVE,
    manual_api_buy,
    manual_api_sell,
)


def test_auto_buy_disabled():
    """验证后台自动买入入池已被彻底关闭。"""
    assert watch_config.AUTO_BUY_ENABLED is False
    assert _CONDITION_BUY_ACTIVE is False


def test_manual_api_buy_validation():
    """验证手动买入参数校验。"""
    # 纯英文字符拦截
    with pytest.raises(ValueError, match="请输入有效的6位股票代码"):
        manual_api_buy("invalid", price=10.0, qty=100)

    # 长度不足6位或全0拦截
    with pytest.raises(ValueError, match="请输入有效的6位股票代码"):
        manual_api_buy("000000", price=10.0, qty=100)

    with pytest.raises(ValueError, match="请输入有效的6位股票代码"):
        manual_api_buy("123", price=10.0, qty=100)

    # 买入价格必须大于0
    with pytest.raises(ValueError, match="买入价格与数量必须大于 0"):
        manual_api_buy("600519", price=0.0, qty=100)

    # 买入股数必须为100的倍数
    with pytest.raises(ValueError, match="买入数量必须为 100 的整数倍"):
        manual_api_buy("600519", price=10.0, qty=50)


def test_manual_api_buy_success_and_watchlist():
    """验证手动买入建仓入池的调用闭环。"""
    with patch("holdingStocks.index.cmd_buy") as mock_cmd_buy, \
         patch("holdingStocks.index._find_meta", return_value={"code": "600519", "name": "贵州茅台", "market": "上证"}):

        res = manual_api_buy(code="600519", price=1500.0, qty=200, note="波段建仓")
        assert res["success"] is True
        assert res["code"] == "600519"
        assert res["name"] == "贵州茅台"
        assert res["price"] == 1500.0
        assert res["qty"] == 200

        # 验证底层交易执行参数
        mock_cmd_buy.assert_called_once()
        args = mock_cmd_buy.call_args[0][0]
        assert args.code == "600519"
        assert args.price == 1500.0
        assert args.qty == 200
        assert args.note == "波段建仓"


def test_manual_api_sell_validation_and_pnl_calc():
    """验证手动卖出平仓参数校验及已实现收益计算。"""
    mock_pos = {
        "qty": 500,
        "cost": 20.0,
        "name": "测试股票",
    }
    fake_holdings = {
        "positions": {"000001": mock_pos}
    }

    with patch("holdingStocks.index.load_holdings", return_value=fake_holdings), \
         patch("holdingStocks.index.cmd_sell") as mock_cmd_sell, \
         patch("holdingStocks.index._find_meta", return_value={"code": "000001", "name": "平安银行", "market": "深证"}):

        # 1. 验证卖出数量超额拦截
        with pytest.raises(ValueError, match="超过当前持仓数量 500"):
            manual_api_sell(code="000001", price=22.0, qty=600)

        # 2. 验证卖出价格必须大于0
        with pytest.raises(ValueError, match="卖出价格与数量必须大于 0"):
            manual_api_sell(code="000001", price=0.0, qty=200)

        # 3. 验证无持仓时卖出拦截
        with pytest.raises(ValueError, match="当前无持仓，无法卖出"):
            manual_api_sell(code="600519", price=1500.0, qty=100)

        # 4. 正常盈利平仓测试：成本20元，卖出价22元，卖出300股，实现盈利 ¥600 (+10.00%)
        sell_res = manual_api_sell(code="000001", price=22.0, qty=300, note="波段高抛")
        assert sell_res["success"] is True
        assert sell_res["code"] == "000001"
        assert sell_res["pnl"] == 600.0
        assert sell_res["pnl_pct"] == 10.0
        mock_cmd_sell.assert_called_once()
        sell_args = mock_cmd_sell.call_args[0][0]
        assert sell_args.code == "000001"
        assert sell_args.price == 22.0
        assert sell_args.qty == 300

        # 5. 亏损平仓测试：成本20元，卖出价18元，卖出200股，实现亏损 -¥400 (-10.00%)
        mock_cmd_sell.reset_mock()
        sell_loss_res = manual_api_sell(code="000001", price=18.0, qty=200, note="波段止损")
        assert sell_loss_res["success"] is True
        assert sell_loss_res["pnl"] == -400.0
        assert sell_loss_res["pnl_pct"] == -10.0
        mock_cmd_sell.assert_called_once()


def test_holding_pnl_formula():
    """验证买入后盯盘界面的浮动收益计算公式与当日盈亏一致性。"""
    cost = 100.0
    qty = 300
    current_price = 115.5
    prev_close = 110.0

    # 1. 买入后累计浮动盈亏（金额与百分比）
    total_market_val = current_price * qty
    total_cost_val = cost * qty
    cycle_pnl_amt = (current_price - cost) * qty
    cycle_pnl_pct = (current_price - cost) / cost * 100

    assert round(total_market_val, 2) == 34650.0
    assert round(total_cost_val, 2) == 30000.0
    assert round(cycle_pnl_amt, 2) == 4650.0
    assert round(cycle_pnl_pct, 2) == 15.50

    # 2. 当日盈亏（基于昨收价）
    day_pnl_amt = (current_price - prev_close) * qty
    day_pnl_pct = (current_price - prev_close) / prev_close * 100

    assert round(day_pnl_amt, 2) == 1650.0
    assert round(day_pnl_pct, 2) == 5.00


def test_1m_rules_disabled():
    """验证全局买卖规则已彻底禁用 1 分钟拉取与 1m 路径回放。"""
    assert watch_config.ENABLE_1M_RULES is False
    from holdingStocks.index import _resolve_hit_stop_path_dependent

    # 模拟持仓与报价，断言在计算止盈止损触达时，绝不会触发 _today_1m_bars
    fake_quote = {
        "last": 19.5,
        "high": 20.5,
        "low": 19.0,
        "open": 20.0,
        "session": "2026-11-11",
    }
    with patch("holdingStocks.index._today_1m_bars", side_effect=AssertionError("严禁拉取1分钟K线")):
        res = _resolve_hit_stop_path_dependent(
            sina="sz000001",
            session="2026-11-11",
            quote=fake_quote,
            pullback_pct=0.03,
            tick=0.01,
            need_accurate=True,
            stop_px=20.0,
        )
        assert res["hit_stop"] is True
        assert res["source"] == "last_vs_stop"
        assert res["bars"].empty

