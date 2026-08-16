"""
B12 v2 — 品种识别

输入 code 字符串，输出 5 类市场标签之一：
    A_STOCK / A_ETF / INDEX_FUTURE / COMMODITY_FUTURE / HK_STOCK / UNKNOWN

支持的代码格式：
    A 股         600036 / sh600036 / sz000001 / 600036.SH / 000001.SZ
    A 股 ETF     510300 / sh510300 / 510300.SH / 159919.SZ
    港股         00700 / HK00700 / 00700.HK
    股指期货     IF2506 / IC2506 / IH2506 / IM2506
    商品期货     rb2410 / cu2506 / au2506（需在 contract_specs.json 白名单）
"""
import re

from specs import CATEGORIES

_RE_INDEX_FUT     = re.compile(r"^(IF|IC|IH|IM)\d{4}$")
_RE_COMMODITY_FUT = re.compile(r"^([a-z]{1,3})\d{3,4}$")
_RE_A_DIGIT6      = re.compile(r"^\d{6}$")
_RE_HK_DIGIT5     = re.compile(r"^\d{5}$")
_RE_HK_PREFIX     = re.compile(r"^HK\d+$", re.IGNORECASE)
_RE_A_PREFIX      = re.compile(r"^(sh|sz)\d{6}$", re.IGNORECASE)

# 主流数据源（panda-data / Wind / 天软 / 聚宽）标准后缀
_RE_SUFFIX        = re.compile(r"^(.+)\.(SH|SZ|HK)$", re.IGNORECASE)

# A股 ETF 号段
_A_ETF_RANGES = [(510000, 518999), (159000, 159999), (588000, 588999)]
# A股股票号段（沪市主板/科创板/深市主板/中小板/创业板）
_A_STOCK_RANGES = [
    (600000, 605999),  # 沪市主板
    (601000, 601999),
    (603000, 603999),
    (688000, 688999),  # 科创板
    (1,      3999),    # 深市主板（000001-003999）
    (300000, 301999),  # 创业板
]


def _classify_a_digit6(c: str) -> str:
    """6 位数字代码 → A_STOCK / A_ETF / UNKNOWN"""
    n = int(c)
    for lo, hi in _A_ETF_RANGES:
        if lo <= n <= hi:
            return "A_ETF"
    for lo, hi in _A_STOCK_RANGES:
        if lo <= n <= hi:
            return "A_STOCK"
    return "UNKNOWN"


def _strip_suffix(c: str) -> tuple[str, str | None]:
    """剥离 .SH / .SZ / .HK 后缀。返回 (纯代码, 后缀 or None)。"""
    m = _RE_SUFFIX.match(c)
    if m:
        return m.group(1), m.group(2).upper()
    return c, None


def classify(code: str) -> str:
    """品种识别入口。返回 5 类市场标签或 UNKNOWN。"""
    if not isinstance(code, str) or not code:
        return "UNKNOWN"
    c = code.strip()

    # 先剥后缀（主流数据源格式）：000001.SZ / 600036.SH / 00700.HK
    body, suffix = _strip_suffix(c)

    # .HK 后缀强制走港股（不管 body 位数）
    if suffix == "HK":
        # body 通常是 4~5 位数字，允许其它长度容错
        if body.isdigit():
            return "HK_STOCK"
        return "UNKNOWN"

    # .SH / .SZ 后缀：body 必须是 6 位数字
    if suffix in ("SH", "SZ"):
        if _RE_A_DIGIT6.match(body):
            return _classify_a_digit6(body)
        return "UNKNOWN"

    # 无后缀：走原有识别路径
    # 股指期货：IF/IC/IH/IM + 4 位数字
    if _RE_INDEX_FUT.match(c):
        return "INDEX_FUTURE"

    # 商品期货：小写字母 + 3~4 位数字（如 rb2410），需命中规格表白名单
    m = _RE_COMMODITY_FUT.match(c)
    if m and c[0].islower():
        prefix = m.group(1)
        if prefix in CATEGORIES["COMMODITY_FUTURE"]["contracts"]:
            return "COMMODITY_FUTURE"
        return "UNKNOWN"

    # 带前缀
    if _RE_A_PREFIX.match(c):
        return _classify_a_digit6(c[2:])
    if _RE_HK_PREFIX.match(c):
        return "HK_STOCK"

    # 5 位数字 → 港股
    if _RE_HK_DIGIT5.match(c):
        return "HK_STOCK"

    # 6 位数字 → A股 / A股ETF
    if _RE_A_DIGIT6.match(c):
        return _classify_a_digit6(c)

    return "UNKNOWN"
