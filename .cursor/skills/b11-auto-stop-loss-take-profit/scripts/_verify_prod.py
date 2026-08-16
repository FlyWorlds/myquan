"""临时验证脚本：确认 panda_data.get_trade_cal 响应结构 + 跑通 B11 生产路径。
运行方式：cd /Users/sina/workspace/panda-trading && .venv/bin/python src/build/build-b11-auto-stop-loss-take-profit/开发产物/scripts/_verify_prod.py

需要环境变量 PANDA_USERNAME / PANDA_PASSWORD（已在 zshrc 配置）。
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("Step 1: import panda_data + init_token")
import panda_data
print("  path:", panda_data.__file__)
print("  has get_trade_cal:", hasattr(panda_data, "get_trade_cal"))

# 从环境变量登录（PANDA_USERNAME / PANDA_PASSWORD）
username = os.environ.get("PANDA_USERNAME")
password = os.environ.get("PANDA_PASSWORD")
if not username or not password:
    raise RuntimeError("请设置 PANDA_USERNAME / PANDA_PASSWORD 环境变量")
panda_data.init_token(username=username, password=password)
print("  init_token OK")

print("\nStep 2: get_trade_cal(20260615..20260625, SH, is_trading_day=1)")
result = panda_data.get_trade_cal(
    start_date="20260615", end_date="20260625",
    exchange="SH", is_trading_day=1, fields=[],
)
print("  type:", type(result).__module__ + "." + type(result).__name__)
if hasattr(result, "shape"):
    print("  shape:", result.shape)
if hasattr(result, "columns"):
    print("  columns:", list(result.columns))
if hasattr(result, "dtypes"):
    print("  dtypes:\n", result.dtypes)
if hasattr(result, "head"):
    print("  head(15):\n", result.head(15))

print("\nStep 3: TradingCalendar.from_panda_data")
from build import TradingCalendar
cal = TradingCalendar.from_panda_data("2026-06-15", "2026-06-25")
print("  trade_days:", cal._days)
print("  is_next_day(06-19, 06-22):", cal.is_next_day("2026-06-19", "2026-06-22"))
print("  holding_trading_days(06-19, 06-23):", cal.holding_trading_days("2026-06-19", "2026-06-23"))

print("\nStep 4: end-to-end B11 production path (no config, panda_data fallback)")
from build import run, print_order
examples = [
    {"code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
     "current_qty": 800, "open_price": 10.55, "total_equity": 100000, "today": "2026-06-22"},
    {"code": "sh600036", "entry_price": 10.0, "entry_date": "2026-06-19",
     "current_qty": 800, "open_price": 9.65, "total_equity": 100000, "today": "2026-06-22"},
    {"code": "SZ000001", "entry_price": 15.0, "entry_date": "2026-06-19",
     "current_qty": 500, "open_price": 15.1, "total_equity": 100000, "today": "2026-06-23"},
    {"code": "IF2406", "entry_price": 4000.0, "entry_date": "2026-06-19",
     "current_qty": 10, "open_price": 4050.0, "multiplier": 300,
     "total_equity": 100_000_000, "today": "2026-06-19"},
]
for pos in examples:
    order = run(pos)
    print_order(order)
print("\ndone")
