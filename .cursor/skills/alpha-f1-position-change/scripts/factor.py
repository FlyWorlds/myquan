from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import panda_data


FACTOR_ID = "F1"
FACTOR_NAME = "期货前20席位持仓突变"
CHANGE_THRESHOLD = 0.02  # 2% 变化阈值
BATCH_SIZE = 4  # 单次 API 调用最多 8 个品种，避免服务器超限
REQUIRED_COLUMNS = {"underlying_symbol", "date", "broker_name", "net_position", "position_type"}


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"请先设置环境变量 {name}")
    return value


def _chunked(items: list, size: int = BATCH_SIZE):
    """把列表切成固定大小的批次（生成器）

    用于 API 分批调用：单次请求品种过多会触发服务器限额，按 BATCH_SIZE 切片循环调用即可。
    """
    for i in range(0, len(items), size):
        yield items[i:i + size]


def load_position_data(
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """从 panda_data 获取期货持仓数据

    默认获取当日往前三个月的数据。
    也可通过 start_date 和 end_date 指定日期范围（格式：YYYY-MM-DD）。
    支持环境变量 PANDA_DATA_START_DATE 和 PANDA_DATA_END_DATE。
    """
    username = _get_env("PANDA_DATA_USERNAME")
    password = _get_env("PANDA_DATA_PASSWORD")
    panda_data.init_token(username=username, password=password)

    # 计算日期范围
    end_date = end_date or os.getenv("PANDA_DATA_END_DATE", datetime.now().strftime("%Y-%m-%d"))
    if start_date is None:
        start_date = os.getenv("PANDA_DATA_START_DATE")
        if not start_date:
            # 往前三个月
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=180)
            start_date = start_dt.strftime("%Y-%m-%d")

    # 转换为 YYYYMMDD 格式给 panda_data
    start_date_8 = start_date.replace("-", "")
    end_date_8 = end_date.replace("-", "")

    print(f"获取数据范围: {start_date} ~ {end_date}")

    # 默认 symbols：覆盖 SHFE / INE / DCE / CZCE / GFEX / CFFEX 全市场（62 个品种）
    symbols = (symbols or [
        # SHFE 上海期货交易所（16 个）
        'AU', 'AG', 'CU', 'AL', 'ZN', 'PB', 'NI', 'SN',
        'HC', 'RB', 'FU', 'BU', 'RU', 'SS', 'AO', 'BR',
        # INE 上海国际能源交易中心（3 个；删除 BC 国际铜、NR 20号胶 — 低流动性）
        'SC', 'LU', 'EC',
        # DCE 大连商品交易所（18 个；删除 FB 纤维板、BB 胶合板 — 公认僵尸品种）
        'C', 'CS', 'A', 'B', 'M', 'Y', 'P', 'JD', 'LH',
        'L', 'V', 'PP', 'EB', 'EG', 'PG', 'J', 'JM', 'I',
        # CZCE 郑州商品交易所（13 个；删除 CY 棉纱、PF 短纤 — 低流动性）
        'SR', 'CF', 'TA', 'OI', 'RM',
        'FG', 'AP', 'CJ', 'PK', 'MA', 'SA', 'UR', 'SH',
        # GFEX 广州期货交易所（3 个，后缀 GFE 待运行时验证）
        'SI', 'LC', 'PS',
        # CFFEX 中国金融期货交易所（8 个：4 股指 + 4 国债）
        'IF', 'IH', 'IC', 'IM',
        'T', 'TF', 'TS', 'TL',
        ])

    # 分批拉取多头数据（单次 API 调用 ≤ BATCH_SIZE 个品种，避免服务器超限）
    debug_mode = os.getenv("PANDA_DATA_DEBUG", "0") == "1"  # PANDA_DATA_DEBUG=1 触发 schema 探针
    debug_printed = False
    total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"获取多头数据（按 {BATCH_SIZE} 个/批，共 {total_batches} 批）...")
    long_parts = []
    for batch_idx, batch_syms in enumerate(_chunked(symbols), start=1):
        print(f"  批次 {batch_idx}/{total_batches}: {batch_syms}", flush=True)
        df = panda_data.get_future_netposi_rank(
            start_date=start_date_8,
            end_date=end_date_8,
            underlying_symbol=batch_syms,
            max_rank=20,
            type="long",
        )
        if df is not None and not df.empty:
            # DEBUG 探针：首次成功调用后打印 schema，便于调试接口字段名不匹配问题
            if debug_mode and not debug_printed:
                print(f"[DEBUG] get_future_netposi_rank 返回字段: {df.columns.tolist()}")
                print(f"[DEBUG] 前 3 行示例:\n{df.head(3)}")
                debug_printed = True
            long_parts.append(df)
    long_df = pd.concat(long_parts, ignore_index=True) if long_parts else pd.DataFrame()

    # 分批拉取空头数据
    print(f"获取空头数据（按 {BATCH_SIZE} 个/批，共 {total_batches} 批）...")
    short_parts = []
    for batch_idx, batch_syms in enumerate(_chunked(symbols), start=1):
        print(f"  批次 {batch_idx}/{total_batches}: {batch_syms}", flush=True)
        df = panda_data.get_future_netposi_rank(
            start_date=start_date_8,
            end_date=end_date_8,
            underlying_symbol=batch_syms,
            max_rank=20,
            type="short",
        )
        if df is not None and not df.empty:
            short_parts.append(df)
    short_df = pd.concat(short_parts, ignore_index=True) if short_parts else pd.DataFrame()

    # 合并数据
    if long_df is not None and not long_df.empty:
        long_df = long_df.copy()
        long_df['position_type'] = 'long'
    if short_df is not None and not short_df.empty:
        short_df = short_df.copy()
        short_df['position_type'] = 'short'

    if long_df is not None and not long_df.empty and short_df is not None and not short_df.empty:
        combined_df = pd.concat([long_df, short_df], ignore_index=True)
    elif long_df is not None and not long_df.empty:
        combined_df = long_df
    elif short_df is not None and not short_df.empty:
        combined_df = short_df
    else:
        combined_df = pd.DataFrame()

    if combined_df.empty:
        raise ValueError(f"未获取到期货持仓数据 (日期范围: {start_date} ~ {end_date})")

    print(f"[OK] 共 {len(combined_df)} 行")
    return combined_df.sort_values(["underlying_symbol", "date", "broker_name", "position_type"])


# 期货品种 → 交易所后缀映射（用于 get_future_daily 主力合约查询）
# 主力合约代码格式：{品种}_DOMINANT.{交易所后缀}
SYMBOL_EXCHANGE_MAP = {
    # 上海期货交易所 SHFE
    "AU": "SHF", "AG": "SHF", "CU": "SHF", "AL": "SHF", "ZN": "SHF",
    "PB": "SHF", "NI": "SHF", "SN": "SHF", "HC": "SHF", "RB": "SHF",
    "BU": "SHF", "RU": "SHF", "FU": "SHF", "SS": "SHF",
    "AO": "SHF", "BR": "SHF",  # 氧化铝、丁二烯橡胶（2023 年上市）
    # 上海国际能源交易中心 INE（共用 SHF 后缀）
    "SC": "SHF", "LU": "SHF", "EC": "SHF",
    # 已删除：BC（国际铜）、NR（20号胶）— 低流动性
    # 大连商品交易所 DCE
    "I": "DCE", "M": "DCE", "Y": "DCE", "P": "DCE", "C": "DCE",
    "CS": "DCE", "JD": "DCE", "L": "DCE", "V": "DCE", "PP": "DCE",
    "EB": "DCE",  # 苯乙烯
    "EG": "DCE", "J": "DCE", "JM": "DCE", "A": "DCE", "B": "DCE",
    "RR": "DCE", "LH": "DCE", "PG": "DCE",
    # 已删除：FB（纤维板）、BB（胶合板）— 公认僵尸品种
    # 郑州商品交易所 CZCE
    "TA": "CZC", "AP": "CZC", "CF": "CZC", "CJ": "CZC",
    "OI": "CZC", "SA": "CZC", "SR": "CZC", "UR": "CZC", "MA": "CZC",
    "FG": "CZC", "RM": "CZC", "PK": "CZC",
    "SH": "CZC",  # 烧碱（2023-9-15 上市）
    # 已删除：CY（棉纱）、PF（短纤）、ZC（动力煤）、RI（早籼稻）、WH（强麦）、PM（普麦）、JR（粳稻）— 低流动性
    # 广州期货交易所 GFEX（后缀 GFE 待运行时验证，如失败可改为 GFEX）
    "SI": "GFE",  # 工业硅
    "LC": "GFE",  # 碳酸锂
    "PS": "GFE",  # 多晶硅（2024-12-13 上市）
    # 中国金融期货交易所 CFFEX
    "IF": "CFF", "IH": "CFF", "IC": "CFF", "IM": "CFF",
    "T": "CFF", "TF": "CFF", "TS": "CFF", "TL": "CFF",  # 国债
}


def load_price_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """从 panda_data 获取期货主力合约日线 OHLC 数据

    用于回测中计算 forward_return（真实价格收益），是修复"持仓自相关 IC"问题的核心数据源。

    Args:
        symbols: 期货品种代码列表（如 ["AP", "CF"]）
        start_date: 起始日期，YYYY-MM-DD 格式
        end_date: 结束日期，YYYY-MM-DD 格式

    Returns:
        DataFrame，包含字段：
        - date: 交易日期（YYYYMMDD 字符串）
        - symbol: 品种代码（如 "AP"，已从 dominant code 中提取）
        - open / high / low / close: OHLC 价格
        - volume: 成交量
    """
    username = _get_env("PANDA_DATA_USERNAME")
    password = _get_env("PANDA_DATA_PASSWORD")
    panda_data.init_token(username=username, password=password)

    # 日期格式转换
    start_date_8 = start_date.replace("-", "")
    end_date_8 = end_date.replace("-", "")

    # 构造主力合约代码列表，跳过未识别品种
    dominant_symbols = []
    skipped = []
    for sym in symbols:
        exchange = SYMBOL_EXCHANGE_MAP.get(sym)
        if exchange is None:
            skipped.append(sym)
            continue
        dominant_symbols.append(f"{sym}_DOMINANT.{exchange}")

    if skipped:
        print(f"[WARN] 跳过未识别品种（无交易所映射）: {skipped}")

    if not dominant_symbols:
        raise ValueError(f"没有有效的品种代码可查询（输入: {symbols}）")

    # 分批拉取价格数据（单次 API 调用 ≤ BATCH_SIZE 个品种，避免服务器超限）
    total_batches = (len(dominant_symbols) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"获取价格数据（按 {BATCH_SIZE} 个/批，共 {total_batches} 批）: {len(dominant_symbols)} 个品种, {start_date} ~ {end_date}")
    price_parts = []
    for batch_idx, batch in enumerate(_chunked(dominant_symbols), start=1):
        print(f"  批次 {batch_idx}/{total_batches}: {len(batch)} 个品种", flush=True)
        df = panda_data.get_future_daily(
            symbol=batch,
            start_date=start_date_8,
            end_date=end_date_8,
            fields=[],  # 返回所有默认字段
        )
        if df is not None and not df.empty:
            price_parts.append(df)

    if not price_parts:
        raise ValueError(f"未获取到价格数据 (品种数: {len(dominant_symbols)}, 日期: {start_date} ~ {end_date})")

    price_df = pd.concat(price_parts, ignore_index=True)
    price_df = price_df.copy()

    # 主力合约代码 "AP_DOMINANT.CZC" → 品种代码 "AP"
    if "symbol" not in price_df.columns:
        raise ValueError("价格数据缺少 'symbol' 字段，无法提取品种代码")
    price_df["symbol"] = price_df["symbol"].astype(str).str.extract(r"^([A-Z]+)_DOMINANT\.")[0]

    # 字段标准化与必要字段检查
    required = {"date", "symbol", "open", "high", "low", "close"}
    missing = required - set(price_df.columns)
    if missing:
        raise ValueError(f"价格数据缺少必要字段: {sorted(missing)}")

    # 删除未提取出品种代码的行
    price_df = price_df.dropna(subset=["symbol"])

    # 数值类型转换
    for col in ["open", "high", "low", "close"]:
        price_df[col] = pd.to_numeric(price_df[col], errors="coerce")
    price_df = price_df.dropna(subset=["open", "close"])

    keep_cols = [c for c in ["date", "symbol", "open", "high", "low", "close", "volume"] if c in price_df.columns]
    print(f"[OK] 价格数据共 {len(price_df)} 行")
    return price_df[keep_cols].sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_input(input_data: Any) -> pd.DataFrame:
    """验证输入数据

    加字段别名映射防御层：panda_data 接口字段名可能变化（如返回 `symbol` 而非 `underlying_symbol`），
    本函数自动把 `symbol` / `code` / `instrument_id` 重命名为 `underlying_symbol`，
    避免接口契约不对称导致的"不回显即崩"。
    """
    df = pd.DataFrame(input_data)
    if df.empty:
        raise ValueError("持仓数据不能为空")

    # 字段别名映射（防御接口字段名变更，按优先级顺序处理）
    # 优先级：underlying_symbol > symbol > code > instrument_id
    aliases = {
        "symbol": "underlying_symbol",
        "code": "underlying_symbol",
        "instrument_id": "underlying_symbol",
    }
    for actual, expected in aliases.items():
        if actual in df.columns and expected not in df.columns:
            print(f"[INFO] 接口字段 {actual!r} 自动映射为 {expected!r}")
            df = df.rename(columns={actual: expected})

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        # 错误信息含接口实际返回字段，便于调试契约不匹配
        actual_cols = sorted(df.columns.tolist())
        raise ValueError(
            f"持仓数据缺少必要字段: {sorted(missing)}。"
            f"接口实际返回字段: {actual_cols}"
        )

    df = df.copy()
    df["underlying_symbol"] = df["underlying_symbol"].astype(str)
    df["date"] = df["date"].astype(str)
    df["broker_name"] = df["broker_name"].astype(str)
    df["net_position"] = pd.to_numeric(df["net_position"], errors="coerce")
    df["position_type"] = df["position_type"].astype(str)

    return df


def calculate_total_position(df: pd.DataFrame) -> pd.DataFrame:
    """计算每日每个品种的前20名持仓总和

    按日期、品种和持仓类型分组，计算前20名持仓的总和。
    """
    # 按日期、品种和持仓类型分组，求和净持仓
    daily_total = df.groupby(["underlying_symbol", "date", "position_type"])["net_position"].sum().reset_index()

    # 透视为宽表：每行一个日期+品种，包含多头和空头总和
    pivot_df = daily_total.pivot(index=["underlying_symbol", "date"], columns="position_type", values="net_position").reset_index()

    # 防御层：确保 long 和 short 列都存在（修复纯多头/纯空头品种的 KeyError）
    # pandas.pivot 只把 position_type 实际出现的值作为输出列，单边数据会缺一整列
    for col in ["long", "short"]:
        if col not in pivot_df.columns:
            print(f"[INFO] 数据缺少 {col!r} 列（可能是纯多头/纯空头品种），自动填充 0")
            pivot_df[col] = 0
    pivot_df = pivot_df.rename(columns={"long": "long_total", "short": "short_total"})

    # 填充缺失值（fillna 只能处理单元格级 NaN，整列缺失已由上方防御层补齐）
    pivot_df["long_total"] = pivot_df["long_total"].fillna(0)
    pivot_df["short_total"] = pivot_df["short_total"].fillna(0)

    # 统计参与计算的期货公司数量
    broker_count = df.groupby(["underlying_symbol", "date", "position_type"])["broker_name"].nunique().reset_index()
    broker_count = broker_count.pivot(index=["underlying_symbol", "date"], columns="position_type", values="broker_name").reset_index()

    # 同样的防御层（broker_count 也用 pivot）
    for col in ["long", "short"]:
        if col not in broker_count.columns:
            broker_count[col] = 0
    broker_count = broker_count.rename(columns={"long": "long_broker_count", "short": "short_broker_count"})

    result = pivot_df.merge(broker_count, on=["underlying_symbol", "date"], how="left")
    result["long_broker_count"] = result["long_broker_count"].fillna(0).astype(int)
    result["short_broker_count"] = result["short_broker_count"].fillna(0).astype(int)

    return result.sort_values(["underlying_symbol", "date"])


def calculate_position_change(df: pd.DataFrame) -> pd.DataFrame:
    """计算多空持仓变化率

    计算多头和空头持仓的日变化率（按品种分组）。
    """
    df = df.sort_values(["underlying_symbol", "date"])

    # 按品种分组，计算前一日持仓
    df["prev_long_total"] = df.groupby("underlying_symbol")["long_total"].shift(1)
    df["prev_short_total"] = df.groupby("underlying_symbol")["short_total"].shift(1)

    # 计算多头变化率
    df["long_change_amount"] = df["long_total"] - df["prev_long_total"]
    df["long_change_rate"] = np.where(
        df["prev_long_total"].abs() > 0,
        df["long_change_amount"] / df["prev_long_total"].abs(),
        0
    )

    # 计算空头变化率
    df["short_change_amount"] = df["short_total"] - df["prev_short_total"]
    df["short_change_rate"] = np.where(
        df["prev_short_total"].abs() > 0,
        df["short_change_amount"] / df["prev_short_total"].abs(),
        0
    )

    # 因子值：多头变化率 - 空头变化率（正值表示多头优势增强）
    df["factor_value"] = df["long_change_rate"] - df["short_change_rate"]

    return df


def calculate_factor(
    input_data: Any | None = None,
    window: int | None = None,
    update_time: str | None = None,
) -> pd.DataFrame:
    """完整流程：加载数据 -> 计算总持仓 -> 计算变化率 -> 生成信号

    算法逻辑：
    1. 将某日的前20名持仓按品种加总，多头加在一起，空头加在一起
    2. 计算多空持仓变化率（每个品种独立计算）
    3. 如果多头增加2%以上或空头减少2%以上，判定为多头优势（buy）
    4. 如果多头减少2%以上或空头增加2%以上，判定为空头优势（sell）
    5. 其他情况为 hold

    Args:
        input_data: 可选，直接传入持仓数据 DataFrame。若为 None 则自动从 panda_data 加载。
        window: 本因子不使用窗口参数，保留以兼容标准接口。
        update_time: 结果生成时间，默认当前时间。

    Returns:
        包含以下标准字段的 DataFrame，每个品种每天一条记录：
        - trade_date: 交易日期
        - asset_type: 资产类型
        - symbol: 标的代码
        - factor_id: 因子编号
        - factor_name: 因子名称
        - factor_value: 因子原始值（多头变化率 - 空头变化率）
        - score: 标准化评分
        - rank: 横截面排名
        - signal: 交易信号
        - confidence: 置信度
        - data_version: 数据版本
        - update_time: 结果生成时间
        - long_total: 当前多头总持仓
        - short_total: 当前空头总持仓
        - prev_long_total: 前一日多头总持仓
        - prev_short_total: 前一日空头总持仓
        - long_change_rate: 多头变化率
        - short_change_rate: 空头变化率
        - long_broker_count: 参与多头计算的期货公司数
        - short_broker_count: 参与空头计算的期货公司数
    """
    update_time = update_time or datetime.now().isoformat(timespec="seconds")

    # 加载数据
    if input_data is None:
        raw_data = load_position_data()
    else:
        raw_data = input_data

    validated = validate_input(raw_data)
    total_position = calculate_total_position(validated)
    with_change = calculate_position_change(total_position)

    # 过滤掉第一天（无前一日数据）
    df = with_change.dropna(subset=["prev_long_total", "prev_short_total"]).copy()

    if df.empty:
        raise ValueError("历史数据长度不足，无法计算持仓变化率")

    # 生成信号
    # 多头增加2%以上或空头减少2%以上 → 多头优势
    # 多头减少2%以上或空头增加2%以上 → 空头优势
    conditions = [
        (df["long_change_rate"] >= CHANGE_THRESHOLD) | (df["short_change_rate"] <= -CHANGE_THRESHOLD),
        (df["long_change_rate"] <= -CHANGE_THRESHOLD) | (df["short_change_rate"] >= CHANGE_THRESHOLD),
    ]
    choices = ["buy", "sell"]
    df["signal"] = np.select(conditions, choices, default="hold")

    # 按日期计算横截面排名（保留 rank 字段供下游定位）
    df["rank"] = df.groupby("date")["factor_value"].rank(ascending=False, method="first").astype(int)

    # score: z-score 经 logistic squash 到 (0, 100) 开区间
    #   公式: score = 100 / (1 + exp(-z))，其中 z = (x - mean) / std
    #   优势：真正达到 (0, 100)；保留连续分布信息（相邻 rank 的 score 差距反映 sigma 倍数）
    # confidence: |z|，表示当日品种因子值偏离横截面均值的标准差倍数（统计意义明确）
    g = df.groupby("date")["factor_value"]
    z = g.transform(lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-9))
    df["score"] = (100 / (1 + np.exp(-z))).round(2)
    df["confidence"] = z.abs().round(4)

    # 小样本降级：当日参与品种数 N_t < 5 时 std 估计噪声大，z-score 不可靠
    n_per_day = df.groupby("date")["factor_value"].transform("count")
    small_n_mask = n_per_day < 5
    if small_n_mask.any():
        degraded_dates = sorted(df.loc[small_n_mask, "date"].unique().tolist())
        print(f"[WARN] 以下日期品种数 < 5，score/confidence 降级为 NaN，signal 强制 hold: {degraded_dates}")
        df.loc[small_n_mask, "score"] = np.nan
        df.loc[small_n_mask, "confidence"] = np.nan
        df.loc[small_n_mask, "signal"] = "hold"

    # 添加元数据
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    df["asset_type"] = "future"
    df["symbol"] = df["underlying_symbol"]  # 使用原始品种代码
    df["factor_id"] = FACTOR_ID
    df["factor_name"] = FACTOR_NAME
    df["data_version"] = "real-v1"
    df["update_time"] = update_time

    columns = [
        "trade_date",
        "asset_type",
        "symbol",
        "factor_id",
        "factor_name",
        "factor_value",
        "score",
        "rank",
        "signal",
        "confidence",
        "long_total",
        "short_total",
        "prev_long_total",
        "prev_short_total",
        "long_change_rate",
        "short_change_rate",
        "long_broker_count",
        "short_broker_count",
        "data_version",
        "update_time",
    ]

    return df[columns].sort_values(["trade_date", "rank"]).reset_index(drop=True)


def get_significant_signals(df: pd.DataFrame, threshold: float = 0.02) -> pd.DataFrame:
    """获取显著信号"""
    buy_signals = df[df["signal"] == "buy"]
    sell_signals = df[df["signal"] == "sell"]
    return pd.concat([buy_signals, sell_signals]).sort_values("trade_date", ascending=False)


if __name__ == "__main__":
    result = calculate_factor(update_time=datetime.now().isoformat(timespec="seconds"))

    print(f"计算完成，共 {len(result)} 条记录")
    print(f"有效信号数量: {len(result[result['signal'] != 'hold'])}")
    print(f"涉及品种: {result['symbol'].unique().tolist()}")

    # 显示最新信号（按品种分组）
    print("\n各品种最新信号:")
    latest_by_symbol = result.groupby("symbol").last().reset_index()
    print(latest_by_symbol[["symbol", "trade_date", "signal", "factor_value", "long_change_rate", "short_change_rate"]].to_string(index=False))
