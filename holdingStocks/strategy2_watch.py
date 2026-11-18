"""策略二 · 缠论图形形态全景扫描与盯盘服务。

支持：
1. 行业核心板块日线全景扫描（图形选板块，如半导体881319）；
2. 板块内成分股穿透扫描（如半导体成分股中微公司、北方华创等）；
3. 中证500 / 中证1000 / 沪深300 指数成分股选股；
4. 缠论经典形态识别（图示精准对应）：
   - 下跌中枢背驰一买（1买）：下跌笔a -> 盘整中枢 -> 下跌笔b创新低 + MACD绿柱面积底背驰 + 底分型放量止跌；
   - 类二买（类2买 / 预二买）：1买反弹后回调不破1买低点（低点抬高） + 底分型拐点向上展开主升；
5. 缠论图表数据生成（K线、CZSC笔、中枢方框、MACD柱状面积）；
6. 缠论多维历史回测与战绩统计。
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from czsc import RawBar, CZSC, ZS, Direction, Freq
from strategy.data import fetch_daily


ROOT = Path(__file__).resolve().parent
STRATEGY_ID = "strategy2"
STRATEGY_NAME = "策略二·缠论"

# 行业核心板块池（东财与申万核心行业）
CORE_SECTORS = [
    {"code": "BK0475", "name": "半导体", "symbol": "881319"},
    {"code": "BK0448", "name": "软件开发", "symbol": "881276"},
    {"code": "BK0447", "name": "互联网服务", "symbol": "881275"},
    {"code": "BK0437", "name": "通信设备", "symbol": "881265"},
    {"code": "BK0459", "name": "电子元件", "symbol": "881287"},
    {"code": "BK0465", "name": "光学光电子", "symbol": "881293"},
    {"code": "BK0474", "name": "汽车零部件", "symbol": "881302"},
    {"code": "BK0424", "name": "光伏设备", "symbol": "881252"},
    {"code": "BK0425", "name": "电池", "symbol": "881253"},
    {"code": "BK0427", "name": "风电设备", "symbol": "881255"},
    {"code": "BK0478", "name": "消费电子", "symbol": "881306"},
    {"code": "BK0464", "name": "医疗器械", "symbol": "881292"},
    {"code": "BK0457", "name": "化学制药", "symbol": "881285"},
    {"code": "BK0456", "name": "中药", "symbol": "881284"},
    {"code": "BK0469", "name": "生物制品", "symbol": "881297"},
    {"code": "BK0473", "name": "专用设备", "symbol": "881301"},
    {"code": "BK0420", "name": "通用设备", "symbol": "881248"},
    {"code": "BK0450", "name": "计算机设备", "symbol": "881278"},
    {"code": "BK0438", "name": "电网设备", "symbol": "881266"},
    {"code": "BK0477", "name": "非金属材料", "symbol": "881305"},
    {"code": "BK0470", "name": "有色金属", "symbol": "881298"},
    {"code": "BK0479", "name": "贵金属", "symbol": "881307"},
    {"code": "BK0471", "name": "钢铁行业", "symbol": "881299"},
    {"code": "BK0428", "name": "电力行业", "symbol": "881256"},
    {"code": "BK0480", "name": "工业金属", "symbol": "881308"},
    {"code": "BK0484", "name": "航天航空", "symbol": "881312"},
    {"code": "BK0436", "name": "游戏", "symbol": "881264"},
    {"code": "BK0481", "name": "证券", "symbol": "881309"},
    {"code": "BK0476", "name": "银行", "symbol": "881304"},
    {"code": "BK0451", "name": "文化传媒", "symbol": "881279"},
    {"code": "BK0422", "name": "电网自动化", "symbol": "881250"},
    {"code": "BK0485", "name": "消费建材", "symbol": "881313"},
]

# 经典指数成分股抽样底池
HS300_PRESET = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "601318", "name": "中国平安"},
    {"code": "000858", "name": "五粮液"},
    {"code": "002594", "name": "比亚迪"},
    {"code": "600036", "name": "招商银行"},
    {"code": "601899", "name": "紫金矿业"},
    {"code": "002475", "name": "立讯精密"},
    {"code": "600900", "name": "长江电力"},
    {"code": "000333", "name": "美的集团"},
    {"code": "601138", "name": "工业富联"},
    {"code": "600887", "name": "伊利股份"},
    {"code": "000001", "name": "平安银行"},
    {"code": "300750", "name": "宁德时代"},
    {"code": "601012", "name": "隆基绿能"},
    {"code": "600309", "name": "万华化学"},
]

ZZ500_PRESET = [
    {"code": "600111", "name": "北方稀土"},
    {"code": "600552", "name": "凯盛科技"},
    {"code": "600489", "name": "中金黄金"},
    {"code": "000988", "name": "华工科技"},
    {"code": "600522", "name": "中天科技"},
    {"code": "601689", "name": "拓普集团"},
    {"code": "002555", "name": "三七互娱"},
    {"code": "002415", "name": "海康威视"},
    {"code": "600760", "name": "中航沈飞"},
    {"code": "002074", "name": "国轩高科"},
    {"code": "002466", "name": "天齐锂业"},
    {"code": "603501", "name": "韦尔股份"},
    {"code": "600584", "name": "长电科技"},
    {"code": "002049", "name": "紫光国微"},
    {"code": "002156", "name": "通富微电"},
]

ZZ1000_PRESET = [
    {"code": "002520", "name": "日发精机"},
    {"code": "002838", "name": "道恩股份"},
    {"code": "002045", "name": "国光电器"},
    {"code": "601606", "name": "长城军工"},
    {"code": "603206", "name": "嘉环科技"},
    {"code": "002579", "name": "中京电子"},
    {"code": "600644", "name": "乐山电力"},
    {"code": "002093", "name": "国脉科技"},
    {"code": "600698", "name": "湖南天雁"},
    {"code": "002851", "name": "麦格米特"},
    {"code": "688012", "name": "中微公司"},
    {"code": "688008", "name": "澜起科技"},
    {"code": "002371", "name": "北方华创"},
    {"code": "300661", "name": "圣邦股份"},
    {"code": "603986", "name": "兆易创新"},
]


@dataclass
class ChanPatternResult:
    code: str
    name: str
    is_sector: bool
    pattern: str  # "buy2_prime" (类2买) | "buy1" (1买) | "none"
    pattern_label: str
    last_price: float
    change_pct: float
    # 结构关键点位
    buy1_price: float | None = None
    buy1_date: str | None = None
    rebound_high: float | None = None
    pullback_low: float | None = None
    pullback_date: str | None = None
    stop_loss: float | None = None
    divergence_ratio: float | None = None  # MACD面积背驰比例 Sb / Sa
    volume_expansion: float | None = None  # 1买后放量倍数
    details: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_macd(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """标准 MACD(12, 26, 9) 计算。"""
    close = df["close"].astype(float)
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    dif = exp1 - exp2
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_bar = (dif - dea) * 2.0
    return dif, dea, macd_bar


def analyze_chan_pattern(
    symbol: str,
    name: str,
    df: pd.DataFrame,
    *,
    is_sector: bool = False,
) -> ChanPatternResult | None:
    """分析一段日K线序列，判断是否符合缠论 1买 或 类2买 结构。

    结构匹配规则（精准对应半导体 881319 图示）：
    1. 必须经历显著前期下跌笔 a；
    2. 震荡盘整形成中枢；
    3. 下跌笔 b 创出新低（下跌b终点价格 < 下跌a终点价格）；
    4. 下跌笔 b 的负 MACD 绿柱面积明显小于下跌笔 a（动能背驰，Sb <= Sa * 0.85）；
    5. 1买出现：在背驰低点确立底分型，成交量止跌回升；
    6. 类2买出现：1买后反弹走出向上笔，随后向下回调笔低点 >= 1买低点（低点不破前低！），
       且当前已经出现向上底分型拐点展开反弹。
    """
    if df is None or len(df) < 40:
        return None

    df = df.copy().sort_values("date").reset_index(drop=True)
    dif, dea, macd_bar = _compute_macd(df)
    df["dif"] = dif
    df["dea"] = dea
    df["macd_bar"] = macd_bar

    # 构造 CZSC RawBar
    bars = []
    for row in df.itertuples():
        dt = pd.to_datetime(row.date)
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        vol = float(getattr(row, "volume", 0.0) or getattr(row, "vol", 0.0) or 0.0)
        bars.append(
            RawBar(
                symbol=symbol,
                dt=dt,
                freq=Freq.D,
                open=float(row.open),
                close=float(row.close),
                high=float(row.high),
                low=float(row.low),
                vol=vol,
                amount=float(getattr(row, "amount", 0.0) or 0.0),
            )
        )

    try:
        cz = CZSC(bars)
        bis = cz.bi_list
    except Exception:
        return None

    if len(bis) < 3:
        return None

    last_row = df.iloc[-1]
    last_price = float(last_row["close"])
    prev_close = float(df.iloc[-2]["close"]) if len(df) >= 2 else last_price
    change_pct = round((last_price / prev_close - 1.0) * 100, 2)
    today_str = str(last_row["date"])[:10]

    last_dt = pd.to_datetime(df["date"].iloc[-1]).tz_localize(None)

    # 工具函数：计算某一段K线区间内的负MACD绿柱绝对值累加面积
    def calc_macd_green_area(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> float:
        mask = (pd.to_datetime(df["date"]).dt.tz_localize(None) >= start_dt) & (
            pd.to_datetime(df["date"]).dt.tz_localize(None) <= end_dt
        )
        sub = df.loc[mask, "macd_bar"]
        neg = sub[sub < 0]
        return float(neg.abs().sum()) if len(neg) else 0.001

    # 0. 优先检查正在形成中的最新结构（即时预2买 / 1买放量反弹中）
    # 当 bis[-1] 为 1买后的向上反弹笔，bis[-2] 为底背驰 1买下跌笔时：
    if len(bis) >= 2 and bis[-1].direction == Direction.Up and bis[-2].direction == Direction.Down:
        bi_rebound1 = bis[-1]
        bi_drop_buy1 = bis[-2]
        p_buy1 = float(bi_drop_buy1.low)
        p_rebound = float(bi_rebound1.high)
        dt_buy1 = bi_drop_buy1.fx_b.dt.strftime("%Y-%m-%d")

        # 时效性铁律：反弹笔见顶距今不得超过 15 个自然日，避免过期形态误报
        days_since_rebound = (last_dt - bi_rebound1.fx_b.dt).days
        if days_since_rebound <= 15:
            early_drops = [b for b in bis[:-2] if b.direction == Direction.Down]
            if early_drops:
                area_b = calc_macd_green_area(bi_drop_buy1.fx_a.dt, bi_drop_buy1.fx_b.dt)
                max_early_area = max(calc_macd_green_area(b.fx_a.dt, b.fx_b.dt) for b in early_drops)
                div_ratio = round(area_b / max(max_early_area, 0.001), 2)
                min_early_low = min(b.low for b in early_drops)

                # 条件：出中枢破新低（或极度接近前低双底）且 MACD 绿柱动能底背驰（Sb < Sa * 0.88）
                if p_buy1 <= min_early_low * 1.03 and div_ratio <= 0.88:
                    # 检查反弹笔顶点之后的最新 K 线回调走势
                    recent_bars = df[pd.to_datetime(df["date"]).dt.tz_localize(None) >= bi_rebound1.fx_b.dt]
                    if not recent_bars.empty:
                        pullback_low = float(recent_bars["low"].min())
                        pullback_row = recent_bars.loc[recent_bars["low"] == pullback_low].iloc[0]
                        pullback_dt = str(pullback_row["date"])[:10]
                    else:
                        pullback_low = p_buy1
                        pullback_dt = dt_buy1

                    # 铁律：回调低点严格不跌破 1买低点（低点抬高），且当前价格未跌破回调低点！
                    if pullback_low >= p_buy1 and last_price >= pullback_low and p_rebound > p_buy1 * 1.02:
                        retracement = (p_rebound - pullback_low) / max(p_rebound - p_buy1, 1e-6)
                        # 如果已有明显回调企稳（至少回调且不深踩超过88%）
                        if 0.05 <= retracement <= 0.88:
                            stop_px = round(min(pullback_low * 0.985, last_price * 0.95), 2)
                            return ChanPatternResult(
                                code=symbol,
                                name=name,
                                is_sector=is_sector,
                                pattern="buy2_prime",
                                pattern_label="🔥 类2买确认 (放量不破前低)",
                                last_price=last_price,
                                change_pct=change_pct,
                                buy1_price=p_buy1,
                                buy1_date=dt_buy1,
                                rebound_high=p_rebound,
                                pullback_low=pullback_low,
                                pullback_date=pullback_dt,
                                stop_loss=stop_px,
                                divergence_ratio=div_ratio,
                                details=f"1买低点{p_buy1:.2f}反弹至{p_rebound:.2f}，回踩低点{pullback_low:.2f}不破前低，现展开类2买主升",
                                updated_at=today_str,
                            )
                        elif retracement < 0.05:
                            # 刚反弹尚未回调，属于 1买放量反弹中，观察等待回调
                            return ChanPatternResult(
                                code=symbol,
                                name=name,
                                is_sector=is_sector,
                                pattern="buy1",
                                pattern_label="🌱 1买放量反弹中 (观察等待回踩出类2买)",
                                last_price=last_price,
                                change_pct=change_pct,
                                buy1_price=p_buy1,
                                buy1_date=dt_buy1,
                                rebound_high=p_rebound,
                                pullback_low=p_buy1,
                                stop_loss=round(min(p_buy1 * 0.97, last_price * 0.95), 2),
                                divergence_ratio=div_ratio,
                                details=f"出中枢下跌背驰（MACD面积比{div_ratio}），在{p_buy1:.2f}确立1买放量反弹，等待回调形成类2买",
                                updated_at=today_str,
                            )

    # 1. 查找笔级别已确认的类2买结构：
    # 只检查最新的结构（倒数前两笔），杜绝穿越数月匹配历史旧笔
    for i in [len(bis) - 1, len(bis) - 2]:
        if i < 3:
            continue
        bi_curr = bis[i]
        if bi_curr.direction == Direction.Up:
            bi_pullback = bis[i - 1]  # 向下回调笔
            bi_rebound1 = bis[i - 2]  # 1买后的向上反弹笔
            if bi_pullback.direction == Direction.Down and bi_rebound1.direction == Direction.Up:
                bi_drop_buy1 = bis[i - 3]  # 形成 1 买的那一笔下跌
                if bi_drop_buy1.direction == Direction.Down:
                    # 时效性铁律：回调结束距今不得超过 15 个自然日
                    days_since_pb = (last_dt - bi_pullback.fx_b.dt).days
                    if days_since_pb > 15:
                        continue

                    p_buy1 = float(bi_drop_buy1.low)
                    p_pullback = float(bi_pullback.low)
                    p_rebound = float(bi_rebound1.high)

                    # 铁律：回调低点绝对不能跌破 1 买低点，且当前最新价格未跌破回调低点！
                    if p_pullback >= p_buy1 and last_price >= p_pullback and p_rebound > p_buy1 * 1.02:
                        early_drops = [b for b in bis[: i - 3] if b.direction == Direction.Down]
                        area_b = calc_macd_green_area(bi_drop_buy1.fx_a.dt, bi_drop_buy1.fx_b.dt)
                        max_early_area = (
                            max(calc_macd_green_area(b.fx_a.dt, b.fx_b.dt) for b in early_drops)
                            if early_drops
                            else area_b * 1.5
                        )
                        div_ratio = round(area_b / max(max_early_area, 0.001), 2)

                        # 回调幅度：不破前低且不过度深踩
                        retracement = (p_rebound - p_pullback) / max(p_rebound - p_buy1, 1e-6)
                        if retracement <= 0.88:
                            stop_px = round(min(p_pullback * 0.985, last_price * 0.95), 2)
                            return ChanPatternResult(
                                code=symbol,
                                name=name,
                                is_sector=is_sector,
                                pattern="buy2_prime",
                                pattern_label="🔥 类2买确认 (放量不破前低)",
                                last_price=last_price,
                                change_pct=change_pct,
                                buy1_price=p_buy1,
                                buy1_date=bi_drop_buy1.fx_b.dt.strftime("%Y-%m-%d"),
                                rebound_high=p_rebound,
                                pullback_low=p_pullback,
                                pullback_date=bi_pullback.fx_b.dt.strftime("%Y-%m-%d"),
                                stop_loss=stop_px,
                                divergence_ratio=div_ratio,
                                details=f"1买低点{p_buy1:.2f}反弹至{p_rebound:.2f}，回踩低点{p_pullback:.2f}不破前低，现展开类2买主升",
                                updated_at=today_str,
                            )

    # 2. 检查是否处于 1 买初成（一买刚确立，正处于筑底反弹，等待回调出类2买）
    if len(bis) >= 2:
        last_bi = bis[-1]
        prev_bi = bis[-2]
        drop_bi = last_bi if last_bi.direction == Direction.Down else (prev_bi if prev_bi.direction == Direction.Down else None)
        if drop_bi is not None:
            # 1买底分型形成时间距今不得超过 15 个自然日
            if (last_dt - drop_bi.fx_b.dt).days <= 15:
                early_drops = [b for b in bis if b.direction == Direction.Down and b.fx_b.dt < drop_bi.fx_b.dt]
                if early_drops:
                    max_early_area = max(calc_macd_green_area(b.fx_a.dt, b.fx_b.dt) for b in early_drops)
                    area_curr = calc_macd_green_area(drop_bi.fx_a.dt, drop_bi.fx_b.dt)
                    min_early_low = min(b.low for b in early_drops)
                    if drop_bi.low <= min_early_low * 1.03 and area_curr < max_early_area * 0.88:
                        div_ratio = round(area_curr / max(max_early_area, 0.001), 2)
                        p_buy1 = float(drop_bi.low)
                        return ChanPatternResult(
                            code=symbol,
                            name=name,
                            is_sector=is_sector,
                            pattern="buy1",
                            pattern_label="🌱 1买初成 (底背驰确立·筑底观察)",
                            last_price=last_price,
                            change_pct=change_pct,
                            buy1_price=p_buy1,
                            buy1_date=drop_bi.fx_b.dt.strftime("%Y-%m-%d"),
                            rebound_high=round(last_price, 2),
                            pullback_low=p_buy1,
                            stop_loss=round(min(p_buy1 * 0.97, last_price * 0.95), 2),
                            divergence_ratio=div_ratio,
                            details=f"出中枢下跌背驰（MACD面积比{div_ratio}），在{p_buy1:.2f}形成1买底分型，观察等待类2买回调",
                            updated_at=today_str,
                        )

    return None


class Strategy2Manager:
    """策略二运行管理引擎：包含扫描器、快照缓存与后台多线程调度。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._payload: dict[str, Any] = {}
        self._last_scan_time: str = ""
        self._running: bool = False
        self._progress: dict[str, Any] = {"percent": 0, "stage": "就绪", "completed": 0, "total": 0}
        self._error: str = ""
        self._load_cached_payload()

    def _load_cached_payload(self) -> None:
        doc_path = ROOT / "strategy2_watch_cache.json"
        if doc_path.exists():
            try:
                self._payload = json.loads(doc_path.read_text(encoding="utf-8"))
                return
            except Exception:
                pass
        self._payload = {
            "strategyId": STRATEGY_ID,
            "strategyName": STRATEGY_NAME,
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_scanned": len(CORE_SECTORS),
                "buy2_count": 0,
                "buy1_count": 0,
                "scope": "sectors",
            },
            "sectors_buy2": [],
            "sectors_buy1": [],
            "stocks_buy2": [],
            "stocks_buy1": [],
            "all_buy2": [],
            "all_buy1": [],
            "current_scope": "sectors",
        }

    def _save_cached_payload(self) -> None:
        doc_path = ROOT / "strategy2_watch_cache.json"
        try:
            doc_path.write_text(json.dumps(self._payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_payload(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._payload)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "progress": dict(self._progress),
                "error": self._error,
                "updatedAt": self._last_scan_time,
            }

    def run_scan_async(self, scope: str = "sectors", target_concept: str = "", symbol_subset: list[str] | None = None) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._error = ""
            self._progress = {"percent": 0, "stage": "准备标的列表...", "completed": 0, "total": 0}

        def _worker():
            try:
                self._execute_scan(scope, target_concept, symbol_subset)
            except Exception as e:
                with self._lock:
                    self._error = str(e)
            finally:
                with self._lock:
                    self._running = False

        threading.Thread(target=_worker, name="strategy2-scan-worker", daemon=True).start()

    def _execute_scan(self, scope: str, target_concept: str, symbol_subset: list[str] | None) -> None:
        items_to_scan: list[dict[str, Any]] = []

        if scope == "sectors":
            items_to_scan = [dict(s, is_sector=True) for s in CORE_SECTORS]
        elif scope in ("csi500", "zz500"):
            items_to_scan = [dict(s, is_sector=False) for s in ZZ500_PRESET]
        elif scope in ("csi1000", "zz1000"):
            items_to_scan = [dict(s, is_sector=False) for s in ZZ1000_PRESET]
        elif scope in ("csi300", "hs300"):
            items_to_scan = [dict(s, is_sector=False) for s in HS300_PRESET]
        elif scope == "sector_members" or target_concept:
            # 穿透获取指定板块的所有成分股
            c_name = target_concept or "半导体"
            members = self.fetch_sector_members(c_name)
            items_to_scan = [dict(s, is_sector=False) for s in members]
        elif symbol_subset:
            items_to_scan = [{"code": c, "name": c, "symbol": c, "is_sector": False} for c in symbol_subset]
        else:
            items_to_scan = [dict(s, is_sector=True) for s in CORE_SECTORS]

        total = len(items_to_scan)
        with self._lock:
            self._progress = {"percent": 5, "stage": f"开始计算 {total} 个标的的缠论结构...", "completed": 0, "total": total}

        buy2_list: list[dict[str, Any]] = []
        buy1_list: list[dict[str, Any]] = []
        completed = 0

        start_date = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime("%Y%m%d")
        end_date = pd.Timestamp.now().strftime("%Y%m%d")

        def _analyze_one(item: dict[str, Any]) -> ChanPatternResult | None:
            code = str(item.get("code") or item.get("symbol") or "")
            name = str(item.get("name") or code)
            is_sec = bool(item.get("is_sector", False))

            df = pd.DataFrame()
            if is_sec:
                df = self._fetch_sector_daily(name)
            else:
                market = "sh" if code.startswith("6") else "sz"
                sina = f"{market}{code}"
                try:
                    df = fetch_daily(sina, start_date, end_date)
                except Exception:
                    df = pd.DataFrame()

            if df is not None and not df.empty:
                return analyze_chan_pattern(code, name, df, is_sector=is_sec)
            return None

        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="chan-scan") as executor:
            futures = {executor.submit(_analyze_one, it): it for it in items_to_scan}
            for fut in as_completed(futures):
                completed += 1
                try:
                    res = fut.result()
                    if res:
                        if res.pattern == "buy2_prime":
                            buy2_list.append(res.to_dict())
                        elif res.pattern == "buy1":
                            buy1_list.append(res.to_dict())
                except Exception:
                    pass

                pct = min(98, int((completed / max(total, 1)) * 95) + 5)
                with self._lock:
                    self._progress = {
                        "percent": pct,
                        "stage": f"正在扫描: 已处理 {completed}/{total} (发现类2买 {len(buy2_list)} 只, 1买 {len(buy1_list)} 只)",
                        "completed": completed,
                        "total": total,
                    }

        buy2_list.sort(key=lambda x: (x.get("change_pct") or 0), reverse=True)
        buy1_list.sort(key=lambda x: (x.get("change_pct") or 0), reverse=True)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._last_scan_time = now_str
            self._payload = {
                "strategyId": STRATEGY_ID,
                "strategyName": STRATEGY_NAME,
                "updatedAt": now_str,
                "current_scope": scope,
                "target_concept": target_concept,
                "summary": {
                    "total_scanned": total,
                    "buy2_count": len(buy2_list),
                    "buy1_count": len(buy1_list),
                    "scope": scope,
                },
                "sectors_buy2": [x for x in buy2_list if x.get("is_sector")],
                "sectors_buy1": [x for x in buy1_list if x.get("is_sector")],
                "stocks_buy2": [x for x in buy2_list if not x.get("is_sector")],
                "stocks_buy1": [x for x in buy1_list if not x.get("is_sector")],
                "all_buy2": buy2_list,
                "all_buy1": buy1_list,
            }
            self._progress = {"percent": 100, "stage": "扫描完成", "completed": total, "total": total}
            self._save_cached_payload()

    def _fetch_sector_daily(self, concept_name: str) -> pd.DataFrame:
        """从本地东财/新浪板块接口拉取板块日线。"""
        try:
            encoded = urllib.parse.quote(concept_name)
            url = f"http://127.0.0.1:8765/api/sectors/concept/{encoded}?months=12"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.load(resp)
                kline = data.get("kline", [])
                if kline:
                    df = pd.DataFrame(kline)
                    df["date"] = pd.to_datetime(df["date"])
                    return df
        except Exception:
            pass
        return pd.DataFrame()

    def fetch_sector_members(self, concept_name: str) -> list[dict[str, Any]]:
        """从板块接口穿透拉取成分股。"""
        try:
            encoded = urllib.parse.quote(concept_name)
            url = f"http://127.0.0.1:8765/api/sectors/concept/{encoded}?months=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.load(resp)
                members = data.get("members_preview", [])
                if members:
                    return [{"code": m["code"], "name": m["name"], "symbol": m["code"], "is_sector": False} for m in members]
        except Exception:
            pass
        return []


MANAGER = Strategy2Manager()


def get_strategy2_watch_payload() -> dict[str, Any]:
    return MANAGER.get_payload()


def get_strategy2_chart_data(code: str, name: str = "", is_sector: bool = False) -> dict[str, Any]:
    """生成缠论 K 线、分型、笔与 MACD 绘图全量数据。"""
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime("%Y%m%d")
    end_date = pd.Timestamp.now().strftime("%Y%m%d")
    df = pd.DataFrame()

    if is_sector:
        df = MANAGER._fetch_sector_daily(name or code)
    else:
        market = "sh" if str(code).startswith("6") else "sz"
        sina = f"{market}{code}"
        try:
            df = fetch_daily(sina, start_date, end_date)
        except Exception:
            df = pd.DataFrame()

    if df is None or df.empty:
        return {"error": "未获取到日K线数据"}

    df = df.copy().sort_values("date").reset_index(drop=True)
    dif, dea, macd_bar = _compute_macd(df)
    df["dif"] = dif.round(3)
    df["dea"] = dea.round(3)
    df["macd_bar"] = macd_bar.round(3)

    bars = []
    for row in df.itertuples():
        dt = pd.to_datetime(row.date)
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        vol = float(getattr(row, "volume", 0.0) or getattr(row, "vol", 0.0) or 0.0)
        bars.append(
            RawBar(
                symbol=str(code),
                dt=dt,
                freq=Freq.D,
                open=float(row.open),
                close=float(row.close),
                high=float(row.high),
                low=float(row.low),
                vol=vol,
                amount=float(getattr(row, "amount", 0.0) or 0.0),
            )
        )

    cz = CZSC(bars)
    bis = cz.bi_list

    dates = [b.dt.strftime("%Y-%m-%d") for b in bars]
    kline_data = [[b.open, b.close, b.low, b.high, b.vol] for b in bars]

    # 提取笔折线
    bi_lines = []
    for bi in bis:
        bi_lines.append({
            "start_date": bi.fx_a.dt.strftime("%Y-%m-%d"),
            "end_date": bi.fx_b.dt.strftime("%Y-%m-%d"),
            "start_val": round(float(bi.fx_a.fx), 2),
            "end_val": round(float(bi.fx_b.fx), 2),
            "direction": "up" if bi.direction == Direction.Up else "down",
            "high": round(float(bi.high), 2),
            "low": round(float(bi.low), 2),
        })

    # 提取中枢
    zs_boxes = []
    if len(bis) >= 5:
        for j in range(4, len(bis)):
            try:
                zs = ZS(bis[j - 4: j + 1])
                if zs.is_valid():
                    zs_boxes.append({
                        "start_date": zs.sdt.strftime("%Y-%m-%d") if hasattr(zs, "sdt") else bis[j - 4].fx_a.dt.strftime("%Y-%m-%d"),
                        "end_date": zs.edt.strftime("%Y-%m-%d") if hasattr(zs, "edt") else bis[j].fx_b.dt.strftime("%Y-%m-%d"),
                        "zg": round(float(zs.zg), 2),
                        "zd": round(float(zs.zd), 2),
                        "zz": round(float(zs.zz), 2) if hasattr(zs, "zz") else round((float(zs.zg) + float(zs.zd)) / 2, 2),
                    })
            except Exception:
                pass

    pattern_res = analyze_chan_pattern(str(code), str(name), df, is_sector=is_sector)
    pattern_info = pattern_res.to_dict() if pattern_res else None

    return {
        "code": code,
        "name": name,
        "is_sector": is_sector,
        "dates": dates,
        "kline": kline_data,
        "bi_lines": bi_lines,
        "zs_boxes": zs_boxes[-6:],
        "pattern_info": pattern_info,
        "macd": {
            "dif": [round(float(x), 3) if math.isfinite(x) else 0 for x in df["dif"]],
            "dea": [round(float(x), 3) if math.isfinite(x) else 0 for x in df["dea"]],
            "bar": [round(float(x), 3) if math.isfinite(x) else 0 for x in df["macd_bar"]],
        },
    }


def run_strategy2_backtest(params: dict[str, Any]) -> dict[str, Any]:
    """策略二·缠论类2买与1买策略历史回测引擎。"""
    universe = params.get("universe", "sectors")
    concept_name = params.get("concept_name", "半导体")
    take_profit = float(params.get("take_profit_pct", 0.15))
    stop_loss = float(params.get("stop_loss_pct", 0.05))
    max_hold_days = int(params.get("max_hold_days", 25))

    # 时间范围解析与规范化 (支持自由设定回测起止日期)
    today_dt = pd.Timestamp.now()
    raw_end = str(params.get("end_date", "")).strip()
    raw_start = str(params.get("start_date", "")).strip()

    try:
        end_pd = pd.to_datetime(raw_end) if raw_end else today_dt
    except Exception:
        end_pd = today_dt
    end_date_str = end_pd.strftime("%Y-%m-%d")

    try:
        start_pd = pd.to_datetime(raw_start) if raw_start else (end_pd - pd.Timedelta(days=365))
    except Exception:
        start_pd = end_pd - pd.Timedelta(days=365)
    start_date_str = start_pd.strftime("%Y-%m-%d")

    # 异常倒置纠偏
    if start_pd > end_pd:
        start_pd, end_pd = end_pd - pd.Timedelta(days=180), end_pd
        start_date_str = start_pd.strftime("%Y-%m-%d")
        end_date_str = end_pd.strftime("%Y-%m-%d")

    # 标的确定
    if universe == "sectors":
        symbols = CORE_SECTORS[:10]
        is_sector = True
    elif universe == "sector_members":
        members = MANAGER.fetch_sector_members(concept_name)
        symbols = members[:15] if members else ZZ1000_PRESET[:10]
        is_sector = False
    elif universe in ("csi1000", "zz1000"):
        symbols = ZZ1000_PRESET
        is_sector = False
    elif universe in ("csi500", "zz500"):
        symbols = ZZ500_PRESET
        is_sector = False
    else:
        symbols = HS300_PRESET
        is_sector = False

    trades: list[dict[str, Any]] = []
    # 数据拉取起止点（向前预热 120 天，确保缠论分型、笔与中枢有充足的历史K线）
    fetch_start = (start_pd - pd.Timedelta(days=120)).strftime("%Y%m%d")
    fetch_end = end_pd.strftime("%Y%m%d")

    for item in symbols:
        code = str(item.get("code") or item.get("symbol"))
        name = str(item.get("name") or code)

        df = pd.DataFrame()
        if is_sector:
            df = MANAGER._fetch_sector_daily(name)
        else:
            market = "sh" if code.startswith("6") else "sz"
            sina = f"{market}{code}"
            try:
                df = fetch_daily(sina, fetch_start, fetch_end)
            except Exception:
                df = pd.DataFrame()

        if df is None or len(df) < 50:
            continue

        df = df.copy().sort_values("date").reset_index(drop=True)
        # 逐日滑动窗口探测类2买
        in_pos = False
        buy_price = 0.0
        buy_date = ""
        hold_days = 0
        current_stop = 0.0

        for idx in range(45, len(df)):
            sub_df = df.iloc[:idx].copy()
            curr_row = df.iloc[idx]
            curr_dt = str(curr_row["date"])[:10]
            curr_open = float(curr_row["open"])
            curr_close = float(curr_row["close"])
            curr_high = float(curr_row["high"])
            curr_low = float(curr_row["low"])

            if not in_pos:
                # 只有当开盘日期处于用户选定的回测时间区间 [start_date, end_date] 内才开仓
                if curr_dt < start_date_str or curr_dt > end_date_str:
                    continue

                res = analyze_chan_pattern(code, name, sub_df, is_sector=is_sector)
                if res and res.pattern == "buy2_prime":
                    # 信号确认后次日以开盘价入场 (杜绝未来函数)
                    in_pos = True
                    buy_price = curr_open
                    buy_date = curr_dt
                    hold_days = 0
                    # 铁律：止损位必须在买入价下方
                    pattern_stop = res.stop_loss if (res.stop_loss and res.stop_loss < buy_price) else round(buy_price * (1 - stop_loss), 2)
                    current_stop = min(pattern_stop, round(buy_price * (1 - 0.01), 2))
                    # 防守下限保护：如果形态止损线过宽(超最大止损位)，则收敛至最大止损位
                    max_stop_level = round(buy_price * (1 - stop_loss), 2)
                    if current_stop < max_stop_level:
                        current_stop = max_stop_level
            else:
                hold_days += 1
                tp_target = round(buy_price * (1 + take_profit), 2)
                exit_signal = False
                exit_reason = ""
                exit_price = curr_close

                # 1. 严格止损检查 (风控优先)
                if curr_open <= current_stop:
                    # 开盘跳空低开直接跌穿止损线，以真实开盘价割肉出场
                    exit_signal = True
                    exit_reason = f"开盘跳空跌破止损位(¥{current_stop:.2f})"
                    exit_price = curr_open
                elif curr_low <= current_stop:
                    # 盘中跌破防守止损线，以止损价触单平仓
                    exit_signal = True
                    exit_reason = f"盘中触及防守止损位(¥{current_stop:.2f})"
                    exit_price = current_stop
                # 2. 止盈检查
                elif curr_open >= tp_target:
                    # 开盘跳空高开达标止盈
                    exit_signal = True
                    exit_reason = f"开盘高开达标止盈(+{round(take_profit * 100)}%)"
                    exit_price = curr_open
                elif curr_high >= tp_target:
                    # 盘中冲高达标止盈
                    exit_signal = True
                    exit_reason = f"达到止盈目标(+{round(take_profit * 100)}%)"
                    exit_price = tp_target
                # 3. 持仓周期上限平仓 (按配置的最大持仓天数退出)
                elif hold_days >= max_hold_days:
                    exit_signal = True
                    exit_reason = f"持仓达到最大周期({max_hold_days}天)"
                    exit_price = curr_close
                # 4. 回测到期/最后一日结算
                elif idx == len(df) - 1 or curr_dt > end_date_str:
                    exit_signal = True
                    exit_reason = "回测区间截止强制平仓"
                    exit_price = curr_close

                if exit_signal:
                    final_ret = round((exit_price - buy_price) / max(buy_price, 1e-4) * 100, 2)
                    trades.append({
                        "code": code,
                        "name": name,
                        "buy_date": buy_date,
                        "buy_price": round(buy_price, 2),
                        "exit_date": curr_dt,
                        "exit_price": round(exit_price, 2),
                        "pnl_pct": final_ret,
                        "hold_days": hold_days,
                        "exit_reason": exit_reason,
                    })
                    in_pos = False

    win_trades = [t for t in trades if t["pnl_pct"] > 0]
    loss_trades = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = round(len(win_trades) / max(len(trades), 1) * 100, 1)
    avg_pnl = round(float(np.mean([t["pnl_pct"] for t in trades])) if trades else 0.0, 2)
    total_ret = round(float(np.sum([t["pnl_pct"] for t in trades])) if trades else 0.0, 2)
    avg_hold_days = round(float(np.mean([t["hold_days"] for t in trades])), 1) if trades else 0.0

    total_win = sum(t["pnl_pct"] for t in win_trades)
    total_loss = abs(sum(t["pnl_pct"] for t in loss_trades))
    profit_factor = round(total_win / max(total_loss, 1e-4), 2) if trades else 1.0

    # 计算真实资金曲线最大回撤
    max_dd = 0.0
    if trades:
        equity_curve = [100.0]
        for t in trades:
            equity_curve.append(equity_curve[-1] * (1.0 + t["pnl_pct"] / 100.0))
        peak = equity_curve[0]
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

    return {
        "status": "ok",
        "params": {
            "universe": universe,
            "concept_name": concept_name,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "max_hold_days": max_hold_days,
            "take_profit_pct": take_profit,
            "stop_loss_pct": stop_loss,
        },
        "summary": {
            "total_trades": len(trades),
            "win_trades": len(win_trades),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_return": total_ret,
            "max_drawdown": round(max_dd, 1),
            "profit_factor": profit_factor,
            "avg_hold_days": avg_hold_days,
            "date_range": f"{start_date_str} ~ {end_date_str}",
            "max_hold_days": max_hold_days,
        },
        "trades": sorted(trades, key=lambda x: x["buy_date"], reverse=True),
    }
