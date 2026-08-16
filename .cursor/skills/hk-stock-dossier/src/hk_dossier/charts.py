"""Chart generation — 价格走势图与成交量图."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Use non-interactive Agg backend for headless environments
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Chinese font fallback — try common CJK fonts
_CHINESE_FONTS = [
    "Microsoft YaHei",
    "SimHei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK SC",
    "PingFang SC",
    "STHeiti",
    "AR PL UMing CN",
]
for _f in _CHINESE_FONTS:
    try:
        matplotlib.font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f] + plt.rcParams["font.sans-serif"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


def generate_charts(
    daily_data: Any,
    output_dir: str,
    prefix: str = "chart",
) -> dict[str, str]:
    """Generate price trend and volume charts from daily price data.

    Args:
        daily_data: DataFrame with columns [date, close, volume, ...]
        output_dir: Directory to save chart images.
        prefix: File name prefix for the chart images.

    Returns:
        Dict mapping chart name to file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    result: dict[str, str] = {}

    if daily_data is None or daily_data.empty:
        logger.warning("No daily data available for chart generation")
        return result

    try:
        df = daily_data.copy()
        df = df.sort_values("date").reset_index(drop=True)
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)
        df["date_dt"] = df["date"].apply(_parse_date)

        # ── 1. Price trend chart ──
        price_path = os.path.join(output_dir, f"{prefix}_price.png")
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(df["date_dt"], df["close"], color="#E23636", linewidth=1.5, label="收盘价")
        ax.fill_between(df["date_dt"], df["close"], alpha=0.1, color="#E23636")
        ax.set_title("股价走势", fontsize=14, fontweight="bold")
        ax.set_ylabel("收盘价 (HKD)", fontsize=11)
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate(rotation=45)
        fig.tight_layout()
        fig.savefig(price_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        result["price_chart"] = price_path
        logger.info("Price chart saved to %s", price_path)

        # ── 2. Volume chart ──
        vol_path = os.path.join(output_dir, f"{prefix}_volume.png")
        fig, ax = plt.subplots(figsize=(12, 3.5))
        colors = ["#E23636" if c < o else "#3CB371" for c, o in zip(df["close"], df["open"])]
        ax.bar(df["date_dt"], df["volume"], color=colors, alpha=0.7, width=0.8)
        ax.set_title("成交量", fontsize=14, fontweight="bold")
        ax.set_ylabel("成交量 (股)", fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate(rotation=45)
        fig.tight_layout()
        fig.savefig(vol_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        result["volume_chart"] = vol_path
        logger.info("Volume chart saved to %s", vol_path)

    except Exception as e:
        logger.warning("Failed to generate charts: %s", e)

    return result


def _parse_date(date_val: Any) -> Any:
    """Parse various date formats to datetime."""
    from datetime import datetime
    s = str(date_val).replace("-", "")
    if len(s) >= 8:
        try:
            return datetime.strptime(s[:8], "%Y%m%d")
        except ValueError:
            pass
    return date_val
