"""因子5：把 Serenity 的公开前瞻 thesis 映射为 A 股研究股票池。

它不是跨市场跟单器：
1. 只读取公开帖子；
2. 复用 serenity-research-model 的主题提取与语义复核；
3. 将看多主题映射到可审计的 A 股概念代理池；
4. 输出研究候选，而非交易指令。

运行 ``python -m strategy.run_factor5_serenity --refresh`` 可从维护中的公开
归档拉取最新帖子；也可用 ``--posts`` 指向用户导出的公开帖子文件。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".cursor" / "skills" / "serenity-research-model"
DEFAULT_POSTS = (
    SKILL_ROOT / "runs" / "public_materials_20260816" / "aleabitoreddit_tweets.csv"
)
DEFAULT_OUTPUT = ROOT / "strategy" / "runs" / "factor5_serenity_thesis_picks_latest.csv"
PUBLIC_ARCHIVE_URL = (
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/"
    "data/aleabitoreddit_tweets.csv"
)

# A 股概念代理池。每一个代码都保留在主题层，而非伪造“Serenity 点名过该公司”。
# 后续可以按公司公告、客户认证和概念成分变动审计并更新。
THEME_MAP: dict[str, dict[str, Any]] = {
    "photonics-cpo": {
        "concept": "光通信 / CPO / 光芯片",
        "symbols": {
            "300308": "中际旭创",
            "300394": "天孚通信",
            "002281": "光迅科技",
            "688498": "源杰科技",
            "688313": "仕佳光子",
        },
    },
    "memory-hbm": {
        "concept": "存储芯片 / HBM / 封测",
        "symbols": {
            "603986": "兆易创新",
            "688008": "澜起科技",
            "688525": "佰维存储",
            "688766": "普冉股份",
            "600584": "长电科技",
        },
    },
    "power-grid": {
        "concept": "数据中心电力 / 备电 / 温控",
        "symbols": {
            "002335": "科华数据",
            "002364": "中恒电气",
            "300693": "盛弘股份",
            "300274": "阳光电源",
            "300499": "高澜股份",
        },
    },
    "robotics-physical-ai": {
        "concept": "人形机器人 / 执行器 / 减速器",
        "symbols": {
            "300124": "汇川技术",
            "002050": "三花智控",
            "603667": "五洲新春",
            "688017": "绿的谐波",
            "300024": "机器人",
        },
    },
    "neocloud": {
        "concept": "算力基础设施 / IDC",
        "symbols": {
            "000977": "浪潮信息",
            "000938": "紫光股份",
            "603019": "中科曙光",
            "300383": "光环新网",
            "603881": "数据港",
        },
    },
    "semiconductor": {
        "concept": "半导体设备 / 材料",
        "symbols": {
            "688012": "中微公司",
            "688120": "华海清科",
            "603290": "斯达半导",
            "002371": "北方华创",
            "300346": "南大光电",
        },
    },
}

_BEARISH_TERMS = (" not long", " short ", " bearish", " avoid ", " exit")
_BEARISH_SELL_RE = re.compile(r"\b(?:i|we)\s+(?:would\s+)?sell\s+(?:\$|\w)", re.IGNORECASE)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
ASHARE_CLOSE_TIME = dt.time(15, 0)


def _load_serenity_mvp():
    """显式加载 Skill 的公开文本解析器，不复制其主题/清洗规则。"""
    path = SKILL_ROOT / "scripts" / "serenity_mvp.py"
    if not path.exists():
        raise FileNotFoundError(f"未找到 Serenity Research Model Skill: {path}")
    spec = importlib.util.spec_from_file_location("_serenity_mvp_factor5", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Serenity 解析器: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def refresh_public_posts(destination: Path) -> Path:
    """下载维护方公开归档；不会接触 X 凭据、Cookie 或私有数据。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        PUBLIC_ARCHIVE_URL,
        headers={"User-Agent": "myquan-factor5-public-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())
    return destination


def _asof_datetime(value: str | dt.date | dt.datetime | None) -> dt.datetime:
    """将截至时点规范为北京时间。

    未传入时使用运行时的当前时刻，避免把当天尚未发布的帖子带入实时候选池；
    仅传日期时视为该日收盘后的历史研究快照。
    """
    if value is None:
        return dt.datetime.now(SHANGHAI_TZ)
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=SHANGHAI_TZ) if value.tzinfo is None else value.astimezone(SHANGHAI_TZ)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.max, tzinfo=SHANGHAI_TZ)
    raw = str(value).strip()
    if len(raw) == 10:
        return dt.datetime.combine(dt.date.fromisoformat(raw), dt.time.max, tzinfo=SHANGHAI_TZ)
    parsed = _parse_post_time(raw)
    if parsed is None:
        raise ValueError(f"无法解析截至时点: {value!r}")
    return parsed


def _last_completed_a_share_close(asof: dt.datetime) -> dt.date:
    """返回最近一个已经完成收盘的 A 股交易日。

    当前未接入交易日历，节假日仅按周末回退；生产运行仍应以 Pandadata
    交易日历校验，避免把长假首日误作普通周末。
    """
    day = asof.date()
    if day.weekday() < 5 and asof.timetz().replace(tzinfo=None) >= ASHARE_CLOSE_TIME:
        return day
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _parse_post_time(value: str) -> dt.datetime | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _signal_window(
    asof: dt.datetime,
    lookback_days: int,
) -> tuple[dt.datetime, dt.datetime]:
    """返回信号窗口：最近已完成的 A 股收盘后至实际截至时点。"""
    if lookback_days > 0:
        start_day = asof.date() - dt.timedelta(days=lookback_days)
        start = dt.datetime.combine(start_day, dt.time.min, tzinfo=SHANGHAI_TZ)
    else:
        close_day = _last_completed_a_share_close(asof)
        start = dt.datetime.combine(close_day, ASHARE_CLOSE_TIME, tzinfo=SHANGHAI_TZ)
    return start, asof


def _is_bearish(text: str) -> bool:
    lower = f" {text.lower()} "
    return any(term in lower for term in _BEARISH_TERMS) or bool(_BEARISH_SELL_RE.search(text))


def active_theme_signals(
    posts_path: str | Path | None = DEFAULT_POSTS,
    *,
    asof: str | dt.date | dt.datetime | None = None,
    lookback_days: int = 0,
    post_limit: int = 0,
) -> list[dict[str, Any]]:
    """从事件窗口内全部公开帖提取 Serenity 本人的前瞻主题信号。

    排除引用文本单独出现的代码、回顾收益帖和明显空头/卖出帖；保留带主题但
    没有美股 ticker 的帖子，因为因子5要映射的是 A 股概念，而非复制美股代码。
    先完成主题与语义筛选，再按时间排序；窗口起点为上一个 A 股交易日的
    15:00（Asia/Shanghai），周末因此覆盖周五收盘后的材料。 ``post_limit``
    仅为兼容历史研究用途，默认 0 表示不截断。
    """
    mvp = _load_serenity_mvp()
    posts_path = Path(posts_path or DEFAULT_POSTS)
    asof_time = _asof_datetime(asof)
    earliest, latest = _signal_window(asof_time, int(lookback_days))
    recent_posts: list[tuple[dt.datetime, dict[str, Any]]] = []
    for post in mvp.read_posts(posts_path):
        created_at = str(post.get("created_at") or post.get("createdAtISO") or post.get("date") or "")
        created = _parse_post_time(created_at)
        if created is not None and earliest < created <= latest:
            recent_posts.append((created, post))
    recent_posts.sort(key=lambda item: item[0], reverse=True)

    signals: list[dict[str, Any]] = []
    posts_to_analyze = recent_posts if int(post_limit) <= 0 else recent_posts[: int(post_limit)]
    for created_at, post in posts_to_analyze:
        text = str(post.get("text") or post.get("full_text") or post.get("content") or "").strip()
        if not text or _is_bearish(text):
            continue
        created = created_at.date().isoformat()

        themes = [theme for theme in mvp.keyword_hits(text, mvp.THEME_KEYWORDS) if theme in THEME_MAP]
        if not themes:
            continue
        # semantic_review expects a ticker-level row. A blank ticker intentionally
        # keeps theme-only thesis posts, while quoted-only material is filtered.
        review = mvp.semantic_review({"ticker": "", "text": text, "quoted_text": post.get("quoted_text", "")})
        if review["review_decision"] in {
            "delete",
            "delete_from_this_signal",
            "remove_from_forward_signal_keep_as_track_record_context",
        }:
            continue
        conviction, reasons = mvp.score_conviction(text)
        age_days = (asof_time.date() - created_at.date()).days
        # Recent/repeated, mechanism-rich posts receive more research attention.
        weight = float(review["signal_weight"]) * (1 + 0.25 * conviction) / (1 + age_days / 7)
        signals.append(
            {
                "created_at": created,
                "themes": themes,
                "weight": round(weight, 6),
                "conviction_score": conviction,
                "conviction_reasons": ";".join(reasons),
                "ticker_mentions": ";".join(mvp.extract_tickers(text)),
                "claim": mvp.compact_claim(text),
                "url": str(post.get("url") or ""),
            }
        )
    return signals


def build_candidates(
    posts_path: str | Path | None = DEFAULT_POSTS,
    *,
    asof: str | dt.date | dt.datetime | None = None,
    lookback_days: int = 0,
    post_limit: int = 0,
    max_candidates: int = 5,
    max_per_theme: int = 2,
    eligible_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """生成按 Serenity 新近公开帖加权的 A 股研究候选池。

    默认分析上一个 A 股交易日 15:00 后的全部帖子，再按主题强度轮询分配，
    最多 5 只、单主题最多 2 只。这让因子5保持事件驱动：
    无合格新帖就没有新增候选，不把历史主题机械地滚动为持仓信号。
    """
    aggregate: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"theme_weight": 0.0, "post_count": 0, "latest_post": "", "us_tickers": set(), "claims": []}
    )
    for signal in active_theme_signals(
        posts_path,
        asof=asof,
        lookback_days=lookback_days,
        post_limit=post_limit,
    ):
        for theme in signal["themes"]:
            bucket = aggregate[theme]
            bucket["theme_weight"] += signal["weight"]
            bucket["post_count"] += 1
            bucket["latest_post"] = max(bucket["latest_post"], signal["created_at"])
            bucket["us_tickers"].update(filter(None, signal["ticker_mentions"].split(";")))
            bucket["claims"].append(signal["claim"])

    theme_rows: dict[str, list[dict[str, Any]]] = {}
    for theme, state in aggregate.items():
        mapping = THEME_MAP[theme]
        rows: list[dict[str, Any]] = []
        for code, name in mapping["symbols"].items():
            if eligible_codes is not None and code not in eligible_codes:
                continue
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "theme": theme,
                    "concept": mapping["concept"],
                    "theme_score": round(state["theme_weight"], 6),
                    "source_post_count": state["post_count"],
                    "latest_source_date": state["latest_post"],
                    "source_us_tickers": ";".join(sorted(state["us_tickers"])),
                    "source_claims": " | ".join(state["claims"][:3]),
                    "selection_basis": "Serenity public forward-theme mapping; not a direct US-ticker substitution",
                    "source_skill": "serenity-research-model",
                }
            )
        theme_rows[theme] = sorted(rows, key=lambda row: row["code"])

    max_candidates = max(0, int(max_candidates))
    max_per_theme = max(0, int(max_per_theme))
    selected: list[dict[str, Any]] = []
    theme_order = sorted(
        theme_rows,
        key=lambda theme: (-float(aggregate[theme]["theme_weight"]), theme),
    )
    # 轮询而不是先取完单一主题，确保多个合格主题均有最低一个席位。
    for slot in range(max_per_theme):
        for theme in theme_order:
            if len(selected) >= max_candidates:
                return selected
            rows = theme_rows[theme]
            if slot < len(rows):
                selected.append(rows[slot])
    return selected


def write_snapshot(
    output: str | Path = DEFAULT_OUTPUT,
    *,
    posts_path: str | Path | None = DEFAULT_POSTS,
    asof: str | dt.date | dt.datetime | None = None,
    lookback_days: int = 0,
    post_limit: int = 0,
    max_candidates: int = 5,
    max_per_theme: int = 2,
    eligible_codes: set[str] | None = None,
) -> Path:
    """写入动态候选池；每次运行都以可追溯的帖子时间窗重建。"""
    posts_path = Path(posts_path or DEFAULT_POSTS)
    candidates = build_candidates(
        posts_path,
        asof=asof,
        lookback_days=lookback_days,
        post_limit=post_limit,
        max_candidates=max_candidates,
        max_per_theme=max_per_theme,
        eligible_codes=eligible_codes,
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank", "code", "name", "theme", "concept", "theme_score", "source_post_count",
        "latest_source_date", "source_us_tickers", "source_claims", "selection_basis", "source_skill",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, row in enumerate(candidates, 1):
            writer.writerow({"rank": rank, **row})
    asof_time = _asof_datetime(asof)
    window_start, window_end = _signal_window(asof_time, int(lookback_days))
    metadata = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "asof": asof_time.isoformat(),
        "lookback_days": lookback_days,
        "post_limit": post_limit,
        "max_candidates": max_candidates,
        "max_per_theme": max_per_theme,
        "eligible_universe_size": len(eligible_codes) if eligible_codes is not None else None,
        "signal_window_start": window_start.isoformat(),
        "signal_window_end": window_end.isoformat(),
        "posts_path": str(posts_path),
        "candidate_count": len(candidates),
        "source_skill": "serenity-research-model",
        "research_only": True,
    }
    path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成因子5 Serenity 公开帖 → A股主题候选池")
    parser.add_argument("--posts", type=Path, default=DEFAULT_POSTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--asof",
        default=None,
        help="YYYY-MM-DD 或 ISO 时间；不传则使用当前北京时间",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=0,
        help="帖子信号窗口；默认0=最近 A 股收盘后至截至时点，正数仅用于研究回看",
    )
    parser.add_argument("--post-limit", type=int, default=0, help="历史研究兼容：正数限制最新帖子数；默认0=分析全部")
    parser.add_argument("--max-candidates", type=int, default=5, help="候选股总数上限；默认5")
    parser.add_argument("--max-per-theme", type=int, default=2, help="单主题候选上限；默认2")
    parser.add_argument("--refresh", action="store_true", help="刷新维护方公开帖子归档，不使用私有凭据")
    args = parser.parse_args()
    if args.refresh:
        refresh_public_posts(args.posts)
    output = write_snapshot(
        args.output,
        posts_path=args.posts,
        asof=args.asof,
        lookback_days=args.lookback_days,
        post_limit=args.post_limit,
        max_candidates=args.max_candidates,
        max_per_theme=args.max_per_theme,
    )
    print(output)


if __name__ == "__main__":
    main()
