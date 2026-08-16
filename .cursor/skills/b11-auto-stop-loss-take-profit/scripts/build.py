#!/usr/bin/env python3
# B11 自动止盈止损+仓位管理（增强版）
# 适用品种：A股 / 股指期货 / 商品期货
# 纯 Python 标准库实现；唯一定向例外：交易日历可选接入 panda_data.get_trade_cal（见 E1 决策）。
#
# 本文件按 CLAUDE.md §「架构约定」分四层：配置常量 / 判断层 / 决策层 / 批量层 / 输出层。
# 输出严格遵循 CLAUDE.md §「调仓指令数据结构」8 字段。
#
# 增强修复对照（验收报告 52/100 -> 修复 6 项）：
#   E1  交易日语义：用交易日历替代自然日差，拆分 is_next_day() 与 holding_trading_days()
#   E2  仓位分母：改为 total_equity（调用方传入），<=0 短路 hold
#   E3  代码分类：先剥离 sh/sz/SH/SZ 前缀，6 位纯数字优先判 A股
#   E4  期货乘数：名义价值 = qty*price*multiplier，内置乘数表 + 可传 multiplier 覆盖
#   E5  健壮性：减仓不退化清仓 / today>=entry 守卫 / NaN-inf 校验 / numbers 类型放宽
#   E6  测试补全：见 test.py

import math
import numbers
import re
from datetime import datetime

# ============================================================
# 配置常量（交易规则阈值）
# ============================================================

STOP_PROFIT_PCT   =  0.05    # [E1] 次日开盘 浮盈 >= +5% → 止盈全平
STOP_LOSS_PCT     = -0.03    # [E1] 次日开盘 浮亏 <= -3% → 止损全平
FORCE_CLOSE_TDAYS =  2       # [E1] 持仓满 2 个交易日（holding_trading_days >= 2）→ 强平
MAX_SINGLE_RATIO  =  0.10    # [E2/E4] 单票名义仓位上限占总权益 10%（严格 > 10% 才减仓）

DATE_FMT = "%Y-%m-%d"

# 最小交易单位
A_STOCK_LOT = 100            # A股 100 股
FUTURE_LOT  = 1              # 期货 1 手

# [E4] 内置合约乘数表（品种字母前缀 -> 每手合约乘数）。
# 调用方可通过输入字段 multiplier 覆盖；未知品种且未传 multiplier → 报错（不静默用 1）。
FUTURE_MULTIPLIER = {
    # 股指期货
    "IF": 300, "IC": 200, "IH": 300, "IM": 200,
    # 国债期货
    "T": 10000, "TF": 10000, "TS": 20000, "TL": 10000,
    # 常见商品期货（每手吨/单位 * 价格口径）
    "RB": 10, "HC": 10, "I": 100, "J": 100, "JM": 60, "ZC": 100,
    "CU": 5, "AL": 5, "ZN": 5, "PB": 5, "NI": 1, "SN": 1,
    "AU": 1000, "AG": 15,
    "RU": 10, "BU": 10, "FU": 10, "SC": 1000, "MA": 10, "TA": 5,
    "M": 10, "Y": 10, "P": 10, "C": 10, "CS": 10, "A": 10, "B": 10,
    "SR": 10, "CF": 5, "OI": 10, "RM": 10, "FG": 20, "SA": 20,
    "PP": 5, "L": 5, "V": 5, "EG": 10, "EB": 5, "PG": 20,
    "JD": 10, "AP": 10, "CJ": 5, "UR": 20, "SF": 5, "SM": 5,
}

# 标的类别
CLS_A_STOCK = "A_STOCK"
CLS_FUTURE  = "FUTURE"


# ============================================================
# 标的分类（E3：先归一化前缀，6 位纯数字优先判 A股）
# ============================================================

def _normalize_code(code):
    """
    剥离交易所前缀/后缀，返回归一化后的代码主体（大小写不敏感）：
      - 前缀写法：sh600036 / SZ000001 → 600036 / 000001
      - [M2] 后缀写法（Wind/万得）：600036.SH / 000001.SZ / 600036.SS → 600036 / 000001 / 600036
      - 其它写法原样返回
    """
    if not isinstance(code, str):
        raise TypeError(f"code 必须是 str，实际 {type(code).__name__}")
    c = code.strip()
    # 前缀 sh/sz
    m = re.match(r'^(?:sh|sz)(.+)$', c, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # 后缀 .SH/.SZ/.SS（Yahoo/Wind 惯例）
    m = re.match(r'^(.+)\.(sh|sz|ss)$', c, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return c


def _is_a_stock(code):
    """归一化后为 6 位纯数字 → A股（覆盖 600036 / sh600036 / 688xxx / ETF 等）。"""
    core = _normalize_code(code)
    return len(core) == 6 and core.isdigit()


def _is_future(code):
    """非 A股 且 剥离前缀后仍含字母 → 期货（如 IF2406 / rb2410 / cu2401）。"""
    if _is_a_stock(code):
        return False
    core = _normalize_code(code)
    # 期货代码形如 字母前缀 + 数字月份，剥离前缀后仍含字母
    return bool(re.match(r'^[A-Za-z]{1,3}\d{2,4}$', core))


def classify(code):
    """返回标的类别：A_STOCK / FUTURE。无法识别时抛出 ValueError。"""
    if _is_a_stock(code):
        return CLS_A_STOCK
    if _is_future(code):
        return CLS_FUTURE
    raise ValueError(f"无法识别的标的代码: {code!r}（既非6位A股代码，也非期货合约代码）")


def _get_lot_size(code):
    return A_STOCK_LOT if classify(code) == CLS_A_STOCK else FUTURE_LOT


def _resolve_multiplier(code, multiplier=None):
    """
    [E4] 解析合约乘数：
      - A股 multiplier = 1（恒定）
      - 期货：调用方传入 multiplier 优先；否则查内置表；都没有 → 报错。
    """
    if classify(code) == CLS_A_STOCK:
        return 1
    if multiplier is not None:
        if not isinstance(multiplier, numbers.Real) or isinstance(multiplier, bool):
            raise ValueError(f"multiplier 类型错误: {type(multiplier)}")
        if multiplier <= 0 or math.isnan(multiplier) or math.isinf(multiplier):
            raise ValueError(f"multiplier 必须为正有限数，实际 {multiplier}")
        return multiplier
    # 提取期货品种字母前缀（大写）查内置表，如 IF2406 → IF, rb2410 → RB
    m = re.match(r'^([A-Za-z]{1,3})\d', _normalize_code(code))
    prefix = m.group(1).upper() if m else ""
    if prefix in FUTURE_MULTIPLIER:
        return FUTURE_MULTIPLIER[prefix]
    raise ValueError(
        f"未知期货品种 {code!r}（前缀 {prefix!r} 不在内置乘数表），"
        f"请通过 multiplier 字段显式传入合约乘数"
    )


# ============================================================
# 交易日历（唯一来源：panda_data；优先读本地 parquet 缓存）
# ============================================================
#
# 依赖：需先安装 panda_data 包，并在环境变量中配置 PANDA_USERNAME / PANDA_PASSWORD。
#
#   pip install panda_data
#   export PANDA_USERNAME=your_username
#   export PANDA_PASSWORD=your_password
#
# 加速与离线：可先运行 `python3 scripts/build_calendar.py` 生成
# `production/trade.parquet`（默认覆盖 今天-3年..今天+1年），运行时优先读该文件；
# 未找到或过期（最晚交易日 < today）时自动回退到实时 panda_data.get_trade_cal。
#
# 缓存策略：TradingCalendar 单例进程内复用（_CALENDAR_CACHE），避免 batch_manage 重复 IO。

import os as _os
from pathlib import Path as _Path

# 交易日历缓存文件位置：与本 scripts/ 目录并列的 production/trade.parquet
# 本文件:  <skill_root>/scripts/build.py
# 目标:    <skill_root>/production/trade.parquet
_TRADE_PARQUET_PATH = _Path(__file__).resolve().parent.parent / "production" / "trade.parquet"

_PANDA_LOGIN_DONE = False   # 模块级登录状态标记，避免重复 init_token
_CALENDAR_CACHE = None      # 模块级 TradingCalendar 单例（parquet 或实时拉取，缓存首个成功结果）


def _ensure_panda_logged_in():
    """
    首次调用交易日历前的懒登录：
      1. 检查 panda_data 是否已安装；未装 → RuntimeError 含 pip install 引导
      2. 检查 PANDA_USERNAME / PANDA_PASSWORD 环境变量；缺失 → RuntimeError 含 export 引导
      3. 调 panda_data.init_token(username, password)；成功后设置模块级标记
      4. 重复调用直接返回（幂等）
    """
    global _PANDA_LOGIN_DONE
    if _PANDA_LOGIN_DONE:
        return
    try:
        import panda_data
    except ImportError as e:
        raise RuntimeError(
            "B11 需要 panda_data 提供交易日历。请先安装：\n"
            "    pip install panda_data\n"
            "再在环境变量中配置：\n"
            "    export PANDA_USERNAME=<your_username>\n"
            "    export PANDA_PASSWORD=<your_password>"
        ) from e
    username = _os.environ.get("PANDA_USERNAME")
    password = _os.environ.get("PANDA_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "B11 需要 PANDA_USERNAME / PANDA_PASSWORD 环境变量以登录 panda_data。\n"
            "请在 shell 配置文件（如 ~/.zshrc / ~/.bashrc）中添加：\n"
            "    export PANDA_USERNAME=<your_username>\n"
            "    export PANDA_PASSWORD=<your_password>\n"
            "然后重新打开终端或 source 该文件。"
        )
    panda_data.init_token(username=username, password=password)
    _PANDA_LOGIN_DONE = True


def _load_trade_days_from_parquet(parquet_path, today):
    """
    读 trade.parquet 并返回 YYYY-MM-DD 交易日列表。
    - 文件不存在 → None
    - 覆盖不到 today（最晚交易日 < today）→ None，触发回退
    读盘失败、schema 异常、类型不兼容（如 panda_data 未来把 nature_date
    改成 str/datetime）、nature_date 全为 None 等一切异常一律返回 None，
    由上层回退到实时 panda_data.get_trade_cal，保证 SKILL.md 承诺的降级路径生效。
    """
    p = _Path(parquet_path)
    if not p.is_file():
        return None
    # [H2/M4] 整个类型转换 + max/min 计算全部包在 try 内：
    # 1) panda_data 未来若把 nature_date 改成 str "2026-06-19" / datetime.date，
    #    int(x) 会抛 ValueError/TypeError，此处兜底为 None 回退
    # 2) nature_date 全为 None 时，vals 为空列表，max() 会抛 ValueError，同兜底
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(p, columns=["nature_date"])
        nature_dates = table.column("nature_date").to_pylist()
        if not nature_dates:
            return None
        # nature_date 是 int64 的 YYYYMMDD；转 YYYY-MM-DD 字符串
        today_int = int(today.replace("-", ""))
        vals = [int(x) for x in nature_dates if x is not None]
        if not vals:
            return None
        max_date = max(vals)
        if max_date < today_int:
            # 缓存过期，让上层拉实时（避免用旧日历漏判未来的交易日）
            return None
        return [
            f"{str(v)[:4]}-{str(v)[4:6]}-{str(v)[6:8]}"
            for v in vals
        ]
    except Exception:
        return None


# ============================================================
# 公开 API：agent 侧交易日历检查与更新
# ============================================================

def inspect_calendar(parquet_path=None):
    """
    只读探查 trade.parquet 状态，供 agent 决定是否需要 refresh_calendar。

    Args:
        parquet_path: 自定义 parquet 位置；None 用默认 production/trade.parquet

    Returns: dict
        {
            "exists":       bool,             # 文件是否存在
            "path":         str,              # 检查的路径
            "count":        int,              # 交易日数量（不存在=0）
            "date_min":     "YYYY-MM-DD"|None,# 最早交易日
            "date_max":     "YYYY-MM-DD"|None,# 最晚交易日
            "today":        "YYYY-MM-DD",     # 系统当前日期
            "covers_today": bool,             # date_max >= today
            "days_to_expiry": int|None,       # date_max - today 的自然日数（负=已过期）
            "recommendation": str,            # "ok" | "refresh_recommended" | "refresh_required" | "missing"
            "reason":       str,              # 判定原因
        }
    """
    from datetime import date as _date
    path = _Path(parquet_path or _TRADE_PARQUET_PATH)
    today_str = _date.today().isoformat()
    today_int = int(today_str.replace("-", ""))

    if not path.is_file():
        return {
            "exists": False, "path": str(path), "count": 0,
            "date_min": None, "date_max": None, "today": today_str,
            "covers_today": False, "days_to_expiry": None,
            "recommendation": "missing",
            "reason": "trade.parquet 不存在。运行 `python3 scripts/build_calendar.py` 首次生成。",
        }
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(path, columns=["nature_date"])
        nature_dates = [int(x) for x in table.column("nature_date").to_pylist() if x is not None]
    except Exception as e:
        return {
            "exists": True, "path": str(path), "count": 0,
            "date_min": None, "date_max": None, "today": today_str,
            "covers_today": False, "days_to_expiry": None,
            "recommendation": "refresh_required",
            "reason": f"读盘失败: {type(e).__name__}: {e}",
        }
    if not nature_dates:
        return {
            "exists": True, "path": str(path), "count": 0,
            "date_min": None, "date_max": None, "today": today_str,
            "covers_today": False, "days_to_expiry": None,
            "recommendation": "refresh_required",
            "reason": "parquet 为空，需重新生成。",
        }

    date_min_int = min(nature_dates)
    date_max_int = max(nature_dates)
    date_max_str = f"{str(date_max_int)[:4]}-{str(date_max_int)[4:6]}-{str(date_max_int)[6:8]}"
    date_min_str = f"{str(date_min_int)[:4]}-{str(date_min_int)[4:6]}-{str(date_min_int)[6:8]}"

    # 自然日差（近似）：只算 today 与 date_max 的自然日距离，用于给 agent 提醒阈值
    from datetime import datetime as _dt
    days_to_expiry = (_dt.strptime(date_max_str, "%Y-%m-%d") - _dt.strptime(today_str, "%Y-%m-%d")).days

    covers_today = date_max_int >= today_int
    if not covers_today:
        recommendation = "refresh_required"
        reason = f"缓存已过期（date_max={date_max_str} < today={today_str}）。运行 refresh_calendar(force=True)。"
    elif days_to_expiry < 30:
        recommendation = "refresh_recommended"
        reason = f"缓存即将过期（余 {days_to_expiry} 自然日）。建议运行 refresh_calendar()。"
    else:
        recommendation = "ok"
        reason = f"缓存正常（date_max={date_max_str}，余 {days_to_expiry} 自然日）。"

    return {
        "exists": True, "path": str(path), "count": len(nature_dates),
        "date_min": date_min_str, "date_max": date_max_str, "today": today_str,
        "covers_today": covers_today, "days_to_expiry": days_to_expiry,
        "recommendation": recommendation, "reason": reason,
    }


def refresh_calendar(force=False, years_back=3, years_forward=1,
                     exchange="SH", parquet_path=None):
    """
    检查并按需刷新 trade.parquet；供 agent 定期/按需调用。

    判定规则（force=False 时）：
      - 缺失 或 覆盖不到 today          → 强制刷新
      - date_max 距 today < 30 自然日   → 刷新（预防长假前失效）
      - 否则                             → 跳过

    Args:
        force: True 无视缓存直接重跑
        years_back / years_forward / exchange: 透传给 build_calendar.build_calendar
        parquet_path: 自定义输出路径

    Returns: dict
        {
            "updated":    bool,       # 是否实际重跑
            "reason":     str,        # 判定原因
            "before":     dict,       # 更新前 inspect_calendar 结果
            "after":      dict|None,  # 更新后 inspect_calendar 结果（未更新为 None）
            "file_size":  int|None,   # 新文件字节数（未更新为 None）
        }
    """
    before = inspect_calendar(parquet_path)
    should_refresh = force or before["recommendation"] in ("missing", "refresh_required", "refresh_recommended")
    if not should_refresh:
        return {
            "updated": False,
            "reason": f"跳过：{before['reason']}",
            "before": before, "after": None, "file_size": None,
        }

    # 触发生成：优先复用 build_calendar 模块的实现，避免逻辑重复
    import sys as _sys
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    try:
        import build_calendar
        build_calendar.build_calendar(
            years_back=years_back, years_forward=years_forward,
            exchange=exchange, output_path=parquet_path,
        )
    except Exception as e:
        return {
            "updated": False,
            "reason": f"刷新失败：{type(e).__name__}: {e}",
            "before": before, "after": None, "file_size": None,
        }

    # 清缓存单例，让下次决策读到新日历
    global _CALENDAR_CACHE
    _CALENDAR_CACHE = None

    after = inspect_calendar(parquet_path)
    file_size = _Path(after["path"]).stat().st_size if after["exists"] else None
    return {
        "updated": True,
        "reason": f"已刷新（{before['recommendation']} → {after['recommendation']}）",
        "before": before, "after": after, "file_size": file_size,
    }


def check_date_coverage(start_date, end_date=None, parquet_path=None):
    """
    检查一个日期或日期区间是否落在当前 trade.parquet 交易日历范围内；不在范围时给出
    agent 可直接执行的扩展建议。这是 agent 侧最常用的入口 —— 单次调用即可获取
    「查询 + 判定 + 建议命令」。

    Args:
        start_date: 日期字符串 YYYY-MM-DD（单点查询）；或区间起点
        end_date:   区间终点 YYYY-MM-DD；None 时视为单点查询（等价 end_date=start_date）
        parquet_path: 自定义 parquet 位置；None 用默认 production/trade.parquet

    Returns: dict
        {
            "query":         {"start_date", "end_date"},      # 用户查询的区间（归一化）
            "coverage":      {"date_min", "date_max", "count"},  # 当前日历覆盖
            "in_range":      bool,                            # 查询区间是否完全落在覆盖内
            "gap_before":    int,                             # 需向前扩展的自然日数（0 = 无需）
            "gap_after":     int,                             # 需向后扩展的自然日数（0 = 无需）
            "suggested_years_back":    int,                   # 建议 refresh_calendar 传的 years_back
            "suggested_years_forward": int,                   # 建议 refresh_calendar 传的 years_forward
            "suggested_action": str,                          # "ok" | "extend_back" | "extend_forward" |
                                                              # "extend_both" | "missing"
            "refresh_command":  str,                          # agent 可直接执行的 Python 调用
            "reason":         str,                            # 判定说明（人类可读）
        }

    典型用法：
        r = check_date_coverage("2020-01-05")
        if not r["in_range"]:
            refresh_calendar(force=True,
                             years_back=r["suggested_years_back"],
                             years_forward=r["suggested_years_forward"])
    """
    from datetime import date as _date, datetime as _dt

    if end_date is None:
        end_date = start_date
    if start_date > end_date:
        # 兼容用户传反，交换而不是报错
        start_date, end_date = end_date, start_date

    query = {"start_date": start_date, "end_date": end_date}

    info = inspect_calendar(parquet_path)
    if not info["exists"] or info["count"] == 0:
        # parquet 不存在：所有日期都不在范围内
        s_dt = _dt.strptime(start_date, "%Y-%m-%d").date()
        e_dt = _dt.strptime(end_date, "%Y-%m-%d").date()
        today = _date.today()
        years_back = max(1, (today - s_dt).days // 365 + 1) if s_dt < today else 3
        years_forward = max(1, (e_dt - today).days // 365 + 1) if e_dt > today else 1
        return {
            "query": query,
            "coverage": {"date_min": None, "date_max": None, "count": 0},
            "in_range": False,
            "gap_before": None, "gap_after": None,
            "suggested_years_back": years_back,
            "suggested_years_forward": years_forward,
            "suggested_action": "missing",
            "refresh_command": (
                f"refresh_calendar(force=True, "
                f"years_back={years_back}, years_forward={years_forward})"
            ),
            "reason": (
                "trade.parquet 不存在。运行 refresh_calendar(force=True, ...) 或 "
                "`python3 scripts/build_calendar.py --years-back N --years-forward M` 生成。"
            ),
        }

    date_min = info["date_min"]
    date_max = info["date_max"]
    coverage = {"date_min": date_min, "date_max": date_max, "count": info["count"]}

    s_dt = _dt.strptime(start_date, "%Y-%m-%d").date()
    e_dt = _dt.strptime(end_date, "%Y-%m-%d").date()
    min_dt = _dt.strptime(date_min, "%Y-%m-%d").date()
    max_dt = _dt.strptime(date_max, "%Y-%m-%d").date()

    gap_before = max(0, (min_dt - s_dt).days)   # start 早于 min 的自然日数
    gap_after = max(0, (e_dt - max_dt).days)    # end 晚于 max 的自然日数

    if gap_before == 0 and gap_after == 0:
        return {
            "query": query,
            "coverage": coverage,
            "in_range": True,
            "gap_before": 0, "gap_after": 0,
            "suggested_years_back": None,
            "suggested_years_forward": None,
            "suggested_action": "ok",
            "refresh_command": None,
            "reason": f"查询区间 {start_date} .. {end_date} 已在覆盖 {date_min} .. {date_max} 内。",
        }

    # 计算需要扩展的年数（向上取整 + 冗余 1 年，避免频繁扩展）
    today = _date.today()
    current_years_back = max(1, (today - min_dt).days // 365)
    current_years_forward = max(1, (max_dt - today).days // 365)

    if gap_before > 0:
        # 需要更多历史：从 today 到 start_date 的年数 + 1 年冗余
        need_years_back = (today - s_dt).days // 365 + 1
        suggested_years_back = max(current_years_back, need_years_back)
    else:
        suggested_years_back = current_years_back

    if gap_after > 0:
        need_years_forward = (e_dt - today).days // 365 + 1
        suggested_years_forward = max(current_years_forward, need_years_forward)
    else:
        suggested_years_forward = current_years_forward

    if gap_before > 0 and gap_after > 0:
        action = "extend_both"
    elif gap_before > 0:
        action = "extend_back"
    else:
        action = "extend_forward"

    refresh_command = (
        f"refresh_calendar(force=True, "
        f"years_back={suggested_years_back}, years_forward={suggested_years_forward})"
    )

    parts = []
    if gap_before > 0:
        parts.append(f"start={start_date} 早于 date_min={date_min}（缺 {gap_before} 天）")
    if gap_after > 0:
        parts.append(f"end={end_date} 晚于 date_max={date_max}（缺 {gap_after} 天）")
    reason = "；".join(parts) + f"。建议：{refresh_command}"

    return {
        "query": query,
        "coverage": coverage,
        "in_range": False,
        "gap_before": gap_before,
        "gap_after": gap_after,
        "suggested_years_back": suggested_years_back,
        "suggested_years_forward": suggested_years_forward,
        "suggested_action": action,
        "refresh_command": refresh_command,
        "reason": reason,
    }


class TradingCalendar:
    """
    交易日历。唯一来源：panda_data.get_trade_cal（或其 parquet 缓存）。

    提供两个能力：
      - holding_trading_days(entry_date, today): 持仓跨越的交易日数（entry 当天 = 第 0 个交易日）
      - is_next_day(entry_date, today): today 是否为 entry 的下一个交易日（== 1 时为真）

    构造方式：`TradingCalendar.from_panda_data(entry_date, today)`
    （手动传 trade_days 的构造仅供 test 内部 monkey-patch 使用）
    """

    def __init__(self, trade_days):
        # trade_days: 可迭代的 YYYY-MM-DD 字符串；内部归一化为有序去重列表 + 索引
        days = sorted(set(trade_days))
        self._days = days
        self._index = {d: i for i, d in enumerate(days)}

    def _ordinal(self, date_str):
        """返回该日期在交易日序列中的序号；非交易日返回 None。"""
        return self._index.get(date_str)

    def trading_days_between(self, entry_date, today):
        """
        entry 当天记为第 0 个交易日。返回 today 相对 entry 跨越的交易日数。
        - entry/today 均为交易日时：直接取序号差 ti - ei（精确）。
        - 任一为非交易日（数据异常）时回退到"夹逼"语义：
          (<= today 的交易日数) - (<= entry 的交易日数)，保证单调，不崩溃。
        - today < entry 时返回负数（交由守卫层处理）。
        """
        ei = self._ordinal(entry_date)
        ti = self._ordinal(today)
        if ei is not None and ti is not None:
            return ti - ei
        import bisect
        ei2 = bisect.bisect_right(self._days, entry_date)
        ti2 = bisect.bisect_right(self._days, today)
        return ti2 - ei2

    def holding_trading_days(self, entry_date, today):
        """持仓交易日数（entry 当天=0）。今天=entry 返回 0，次日返回 1，T+2 返回 2。"""
        return self.trading_days_between(entry_date, today)

    def is_next_day(self, entry_date, today):
        """today 是否为 entry 的下一个交易日。"""
        return self.holding_trading_days(entry_date, today) == 1

    @classmethod
    def from_panda_data(cls, start_date, end_date, exchange="SH"):
        """
        构造交易日历。策略（优先级由高到低）：
          1. production/trade.parquet 存在且覆盖 end_date → 读盘
          2. 否则从 panda_data.get_trade_cal 实时拉取 start_date..end_date

        进程内单例（_CALENDAR_CACHE）复用：同一进程内第一次成功构造后，后续所有
        调用直接返回该单例；跨进程需重启或手动清空 _CALENDAR_CACHE。

        入参 start_date/end_date 为 YYYY-MM-DD；内部转 YYYYMMDD 调用。
        """
        global _CALENDAR_CACHE
        if _CALENDAR_CACHE is not None:
            return _CALENDAR_CACHE

        # 1) 优先读 parquet 缓存
        trade_days = _load_trade_days_from_parquet(_TRADE_PARQUET_PATH, end_date)
        if trade_days:
            _CALENDAR_CACHE = cls(trade_days)
            return _CALENDAR_CACHE

        # 2) 回退实时拉取
        _ensure_panda_logged_in()
        import panda_data
        s = start_date.replace("-", "")
        e = end_date.replace("-", "")
        result = panda_data.get_trade_cal(
            start_date=s, end_date=e, exchange=exchange, is_trading_day=1, fields=[]
        )
        trade_days = []
        records = result.to_dict("records") if hasattr(result, "to_dict") else result
        for row in records:
            is_trade = row.get("is_trade", 1)
            nd = row.get("nature_date")
            if is_trade == 1 and nd is not None:
                s = str(nd)
                trade_days.append(f"{s[0:4]}-{s[4:6]}-{s[6:8]}")
        _CALENDAR_CACHE = cls(trade_days)
        return _CALENDAR_CACHE



# ============================================================
# 校验层（E2/E5：分母守卫 / NaN-inf / numbers 类型放宽）
# ============================================================

def _is_real(x):
    """数值（含 numpy 浮点/整数），排除 bool。"""
    return isinstance(x, numbers.Real) and not isinstance(x, bool)


def _finite(x):
    """有限实数（非 NaN/inf）。"""
    return _is_real(x) and not math.isnan(float(x)) and not math.isinf(float(x))


def validate_input(pos):
    """
    校验单条输入，返回 (ok, error_msg)。
    [E5] 数量用 numbers.Integral、价格/权益用 numbers.Real（兼容 numpy）；NaN/inf 一律拒绝。
    [E2] total_equity 校验下界与运行时守卫一致：允许 <=0 通过校验（运行时短路 hold），
         但 NaN/inf 必须拒绝（无法做除零守卫）。
    """
    if not isinstance(pos, dict):
        return False, "输入必须为 dict"

    # 必填 + 类型
    if not isinstance(pos.get("code"), str) or not pos.get("code").strip():
        return False, "缺少或非法字段: code"
    for f in ("entry_date", "today"):
        if not isinstance(pos.get(f), str):
            return False, f"缺少或非法字段: {f}（需 str）"
    for f in ("entry_price", "open_price"):
        if f not in pos:
            return False, f"缺少字段: {f}"
        if not _is_real(pos[f]):
            return False, f"字段 {f} 类型错误，需 numbers.Real，实际 {type(pos[f])}"
        if not _finite(pos[f]):
            return False, f"字段 {f} 为 NaN/inf，非法"
        if pos[f] <= 0:
            return False, f"{f} 必须 > 0"
    if "current_qty" not in pos:
        return False, "缺少字段: current_qty"
    if not isinstance(pos["current_qty"], numbers.Integral) or isinstance(pos["current_qty"], bool):
        return False, f"字段 current_qty 类型错误，需 numbers.Integral，实际 {type(pos['current_qty'])}"
    if pos["current_qty"] < 0:
        return False, "current_qty 必须 >= 0"

    # total_equity：方案A 必填（仓位分母）
    if "total_equity" not in pos:
        return False, "缺少字段: total_equity（仓位比例分母，方案A 由调用方传入）"
    if not _is_real(pos["total_equity"]):
        return False, f"字段 total_equity 类型错误，需 numbers.Real，实际 {type(pos['total_equity'])}"
    if math.isnan(float(pos["total_equity"])) or math.isinf(float(pos["total_equity"])):
        return False, "total_equity 为 NaN/inf，非法"
    # 注意：total_equity <= 0 允许通过校验，运行时短路返回 hold（E2 守卫）

    # available_cash：可选，若提供需为有限实数（不作分母）
    if "available_cash" in pos and pos["available_cash"] is not None:
        if not _finite(pos["available_cash"]):
            return False, "available_cash 若提供须为有限实数"

    # multiplier：可选
    if "multiplier" in pos and pos["multiplier"] is not None:
        if not _is_real(pos["multiplier"]) or not _finite(pos["multiplier"]) or pos["multiplier"] <= 0:
            return False, "multiplier 若提供须为正有限数"

    # 代码可分类
    try:
        classify(pos["code"])
    except ValueError as e:
        return False, str(e)

    # 日期格式
    # [M3] 前置严格正则：Python strptime 允许 "2026-6-19" 无前导零，会破坏输出契约
    # （order["time"] 直接回写原字符串，下游依赖 YYYY-MM-DD 严格格式）。
    _date_re = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(_date_re, pos["entry_date"]):
        return False, f"entry_date 必须严格为 YYYY-MM-DD（含前导零），实际 {pos['entry_date']!r}"
    if not re.match(_date_re, pos["today"]):
        return False, f"today 必须严格为 YYYY-MM-DD（含前导零），实际 {pos['today']!r}"
    try:
        entry = datetime.strptime(pos["entry_date"], DATE_FMT)
        today = datetime.strptime(pos["today"], DATE_FMT)
    except (ValueError, TypeError):
        return False, "日期格式错误，需为 YYYY-MM-DD"

    # [E5] today >= entry_date 守卫（自然日层面先粗筛；交易日层面在决策层再守）
    if today < entry:
        return False, f"today({pos['today']}) 早于 entry_date({pos['entry_date']})"

    return True, ""


# ============================================================
# 决策层（返回标准 8 字段调仓指令 dict）
# ============================================================

def manage_position(code, entry_price, entry_date, current_qty, open_price, today,
                    total_equity, multiplier=None,
                    **_ignored):
    """
    核心决策函数。决策优先级：TP > SL > 强平 > 减仓 > hold，全程仅用当日可得数据。

    Args:
        total_equity (E2): 仓位比例分母（持仓市值+现金，调用方传入）。<=0 短路 hold。
        multiplier   (E4): 期货合约乘数；A股恒为 1；未知期货且未传 → 报错。
        **_ignored: 吞掉调用方 pos dict 中的可选透传字段（如 available_cash），不参与决策。

    交易日历唯一来源 = panda_data.get_trade_cal，需先配置 PANDA_USERNAME/PANDA_PASSWORD
    环境变量并 `pip install panda_data`；缺失时抛 RuntimeError 含引导。

    Returns: dict，8 字段（code/pnl_pct/current_qty/time/action/qty_change/target_qty/reason）。
    """
    # pnl_pct 惰性计算：守卫通过后再算，避免 entry_price=0/NaN/inf 触发 ZeroDivisionError / nan 污染。
    # 守卫失败时 _mk_order 用 pnl_pct=0.0 兜底（reason 里会明确写"价格异常"）。
    pnl_pct = 0.0

    def _mk_order(action, target_qty, reason):
        return {
            "code": code,
            "pnl_pct": round(pnl_pct, 6),
            "current_qty": int(current_qty),
            "time": today,
            "action": action,
            "qty_change": int(target_qty) - int(current_qty),
            "target_qty": int(target_qty),
            "reason": reason,
        }

    # ---- 守卫层（E2/E5）：异常输入一律返回 hold，不进入数值计算 ----
    # [H1] 价格守卫必须在 pnl_pct 计算之前：entry_price=0/NaN/inf 一律 hold，避免除零/nan 污染
    if not _finite(entry_price) or not _finite(open_price):
        return _mk_order("hold", current_qty, "[B11]hold 价格为 NaN/inf，跳过")
    if entry_price <= 0:
        return _mk_order("hold", current_qty, f"[B11]hold entry_price 非正({entry_price})，跳过")
    # [H4] today < entry_date 字符串守卫：YYYY-MM-DD 字典序等价时序，防止两者都落在日历外时
    # bisect 返回 0 误判为"入场当天"。放在交易日历查询之前，避免读盘。
    if isinstance(today, str) and isinstance(entry_date, str) and today < entry_date:
        return _mk_order("hold", current_qty,
                         f"[B11]hold today({today}) 早于 entry_date({entry_date})，异常跳过")
    # [M1] 空仓短路：current_qty==0 时无操作对象，避免命中 TP/SL/强平后产出
    # action=sell,target=0,qty_change=0 的无效指令污染下游订单系统
    if int(current_qty) == 0:
        return _mk_order("hold", 0, "[B11]hold 空仓，无操作对象")
    # E2：总权益分母 <= 0（含 0 与负权益）短路，防除零
    if not _is_real(total_equity) or math.isnan(float(total_equity)) or math.isinf(float(total_equity)) \
            or total_equity <= 0:
        return _mk_order("hold", current_qty, f"[B11]hold 总权益非正({total_equity})，跳过仓位校验")

    # 守卫通过后再算 pnl（此时 entry_price 保证 >0 且有限）
    pnl_pct = (open_price - entry_price) / entry_price

    # ---- 交易日语义（E1）：唯一来源 panda_data.get_trade_cal ----
    cal = TradingCalendar.from_panda_data(entry_date, today)
    hold_tdays = cal.holding_trading_days(entry_date, today)
    is_next = cal.is_next_day(entry_date, today)

    # E5：today < entry（交易日维度持仓为负）守卫（保留作为交易日层面的双保险）
    if hold_tdays < 0:
        return _mk_order("hold", current_qty, f"[B11]hold today 早于 entry_date(交易日数={hold_tdays})，异常跳过")

    # ---- 优先级 1：次日止盈（E1：is_next 基于交易日历） ----
    if is_next and pnl_pct >= STOP_PROFIT_PCT:
        return _mk_order("sell", 0,
                         f"[B11]次日高开止盈 open={open_price:.4f} entry={entry_price:.4f} pnl={pnl_pct:+.4f}")

    # ---- 优先级 2：次日止损（与止盈条件互斥，用 elif） ----
    elif is_next and pnl_pct <= STOP_LOSS_PCT:
        return _mk_order("sell", 0,
                         f"[B11]次日低开止损 open={open_price:.4f} entry={entry_price:.4f} pnl={pnl_pct:+.4f}")

    # ---- 优先级 3：持仓满 2 交易日强平（E1：holding_trading_days >= 2，平到 0 不下取整） ----
    if hold_tdays >= FORCE_CLOSE_TDAYS:
        return _mk_order("sell", 0,
                         f"[B11]持仓{hold_tdays}个交易日≥{FORCE_CLOSE_TDAYS}强制平仓 entry_date={entry_date}")

    # ---- 优先级 4：单票名义仓位 > 10% 减仓（E2 分母 total_equity / E4 分子乘乘数） ----
    mult = _resolve_multiplier(code, multiplier)
    lot = _get_lot_size(code)
    notional = current_qty * open_price * mult          # E4：名义价值 = qty*price*multiplier
    ratio = notional / total_equity                     # E2：分子分母同口径（名义价值）
    if ratio > MAX_SINGLE_RATIO:                        # 严格 > 10% 才动（==10% 不动）
        # 目标名义价值 = total_equity * 10%；换算目标数量后向下取整到最小单位
        raw_target_qty = (total_equity * MAX_SINGLE_RATIO) / (open_price * mult)
        target_qty = max(0, int(math.floor(raw_target_qty / lot)) * lot)
        # E5：floor 后若 >0 保留（A股>=100 / 期货>=1手）；且 target<current 才 sell，不退化清仓
        if 0 < target_qty < current_qty:
            return _mk_order("sell", target_qty,
                             f"[B11]单票仓位{ratio:.2%}>{MAX_SINGLE_RATIO:.0%} 减仓至{target_qty}(占比≤10%)")
        # floor 到 0 或 target>=current：不操作（严禁清仓退化）
        return _mk_order("hold", current_qty,
                         f"[B11]hold 仓位{ratio:.2%}超限但减仓后不足1单位/无需减，保持原仓")

    # ---- 优先级 5：hold ----
    return _mk_order("hold", current_qty,
                     f"[B11]hold 持仓{hold_tdays}交易日 pnl={pnl_pct:+.4f} 仓位{ratio:.2%}")


# ============================================================
# 批量层
# ============================================================

def batch_manage(positions):
    """批量处理持仓列表。"""
    return [manage_position(**pos) for pos in positions]


# ============================================================
# 输出层
# ============================================================

def print_order(order):
    """格式化打印单条调仓指令。"""
    print(f"code={order['code']:<10s} pnl={order['pnl_pct']:>+.4f} "
          f"qty={order['current_qty']:>6d} -> {order['action']:<4s} "
          f"target={order['target_qty']:>6d} change={order['qty_change']:>+7d} "
          f"| {order['reason']}")


# ============================================================
# 标准入口
# ============================================================

def run(input_data):
    """
    标准入口函数。
    Args:
        input_data: dict（单条）或 list[dict]（批量）
    Returns:
        dict（单条）或 list[dict]（批量）

    交易日历唯一来源 = panda_data.get_trade_cal。首次调用会自动读取环境变量
    PANDA_USERNAME / PANDA_PASSWORD 完成 init_token 登录；未装 panda_data 或
    env 缺失时抛 RuntimeError 含引导信息。
    """
    if isinstance(input_data, list):
        if len(input_data) == 0:
            return []
        for i, pos in enumerate(input_data):
            ok, err = validate_input(pos)
            if not ok:
                raise ValueError(f"输入[{i}]校验失败: {err}")
        return batch_manage(input_data)
    elif isinstance(input_data, dict):
        ok, err = validate_input(input_data)
        if not ok:
            raise ValueError(f"输入校验失败: {err}")
        return manage_position(**input_data)
    else:
        raise TypeError("run() 入参必须为 dict 或 list[dict]")


# ============================================================
# 示例（__main__）
# ============================================================
#
# 前置条件（否则抛 RuntimeError）：
#   pip install panda_data
#   export PANDA_USERNAME=<your_username>
#   export PANDA_PASSWORD=<your_password>
#
# 首次调用交易日历时自动 init_token 登录 panda_data，从 get_trade_cal 拉取
# entry_date..today 区间的交易日序列。

if __name__ == "__main__":
    examples = [
        {   # A股次日止盈：周五(06-19)入场，周一(06-22, 真实交易日次日)高开 +5.5%
            "code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
            "current_qty": 800, "open_price": 10.55,
            "total_equity": 100000, "today": "2026-06-22",
        },
        {   # A股带 sh 前缀次日止损：归一化后判 A股，-3.5%
            "code": "sh600036", "entry_price": 10.0, "entry_date": "2026-06-19",
            "current_qty": 800, "open_price": 9.65,
            "total_equity": 100000, "today": "2026-06-22",
        },
        {   # 持仓满 2 交易日强平（周五入场，周二=T+2）
            "code": "SZ000001", "entry_price": 15.0, "entry_date": "2026-06-19",
            "current_qty": 500, "open_price": 15.1,
            "total_equity": 100000, "today": "2026-06-23",
        },
        {   # 期货 IF 名义价值 = 10*4050*300 = 12,150,000，占总权益 12.15% > 10% → 减仓至 8 手
            "code": "IF2406", "entry_price": 4000.0, "entry_date": "2026-06-19",
            "current_qty": 10, "open_price": 4050.0, "multiplier": 300,
            "total_equity": 100_000_000, "today": "2026-06-19",
        },
        {   # 入场当天，hold（0 个交易日，既非次日也未满 2 日）
            "code": "000001", "entry_price": 15.0, "entry_date": "2026-06-22",
            "current_qty": 500, "open_price": 14.9,
            "total_equity": 100000, "today": "2026-06-22",
        },
    ]

    print("=== B11 自动止盈止损+仓位管理 ===\n")
    for pos in examples:
        order = run(pos)
        print_order(order)

    print("\n=== 批量调用 ===")
    for r in run(examples):
        print(f"{r['code']:<10s}: {r['action']:<4s} qty_change={r['qty_change']:+d}")
