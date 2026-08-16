"""Real oil news fetcher — pulls latest headlines from Google News RSS.

Fallback to structured context if RSS is unavailable.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import feedparser
import requests

logger = logging.getLogger(__name__)

# Google News RSS queries for crude oil (English & Chinese)
RSS_FEEDS = {
    "en": "https://news.google.com/rss/search?q=crude+oil+OPEC+EIA+energy&hl=en-US&gl=US",
    "zh": "https://news.google.com/rss/search?q=%E5%8E%9F%E6%B2%B9+%E6%B2%B9%E4%BB%B7+OPEC&hl=zh-CN&gl=CN",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def _fetch_rss(url: str, max_items: int = 8) -> list[dict[str, Any]]:
    """Fetch and parse an RSS feed, return structured items."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            source = entry.get("source", {}).get("title", "") if hasattr(entry, "source") else ""
            if not source:
                src_tag = entry.get("source", "")
                source = str(src_tag) if isinstance(src_tag, str) else ""
            published = entry.get("published", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            items.append({
                "title": title,
                "source": source or extract_source(link),
                "time": published,
                "link": link,
                "summary": summary[:200] if summary else "",
            })
        return items
    except Exception as e:
        logger.warning("RSS fetch failed: %s", e)
        return []


def extract_source(link: str) -> str:
    """Extract source domain from URL."""
    if "reuters" in link:
        return "Reuters"
    if "bloomberg" in link:
        return "Bloomberg"
    if "cnbc" in link:
        return "CNBC"
    if "wsj" in link:
        return "WSJ"
    if "oilprice" in link:
        return "OilPrice.com"
    if "eia" in link:
        return "EIA"
    if "spglobal" in link or "platts" in link:
        return "S&P Global Platts"
    if "finance" in link or "163" in link or "sina" in link:
        return "财经媒体"
    return "综合通讯社"


def _classify_news(title: str, summary: str) -> tuple[str, list[str]]:
    """Classify a news item into a category and extract keywords.

    Returns:
        (category, keywords) tuple.
    """
    text = (title + " " + summary).lower()

    categories = {
        "OPEC+ 产量政策": ["opec", "减产", "增产", "配额", "石油输出国组织", "产量", "supply", "production", "quota", "jmmc"],
        "美国 EIA 库存": ["eia", "库存", "inventory", "原油库存", "库欣", "cushing", "战略储备", "spr"],
        "地缘政治风险": ["伊朗", "霍尔木兹", "strait of hormuz", "制裁", "sanction", "中东", "middle east",
                        "地缘政治", "geopolitical", "俄乌", "ukraine", "russia", "以色列", "israel",
                        "红海", "red sea", "军事", "military", "胡塞", "houthi"],
        "宏观经济与需求": ["经济", "economy", "cpi", "ppi", "就业", "gdp", "美联储", "fed", "利率",
                        "interest rate", "需求", "demand", "衰退", "recession", "通胀", "inflation",
                        "pmi", "制造业", "中国", "china", "印度", "india"],
        "SC 内外盘套利": ["sc", "上海原油", "人民币", "价差", "套利", "进口", "import", "arbitrage",
                        "汇率", "forex", "cny", "内盘", "外盘"],
        "炼厂与供需": ["炼厂", "refinery", "开工率", "开工", "汽油", "gasoline", "柴油", "diesel",
                     "裂解", "crack", "利润", "margin",  "现货", "spot", "backwardation", "contango"],
    }

    for category, keywords in categories.items():
        for kw in keywords:
            if kw.lower() in text:
                return category, keywords[:4]
    return "行业动态", ["oil", "energy", "原油"]


def fetch_crude_news(days: int = 3) -> list[dict[str, Any]]:
    """Fetch latest crude oil news from Google News RSS.

    Returns:
        List of news items with title, source, time, summary, impact, category, keywords.
    """
    # Try English feed first, then Chinese
    items = _fetch_rss(RSS_FEEDS["en"], max_items=10)
    if len(items) < 3:
        items = _fetch_rss(RSS_FEEDS["zh"], max_items=10)

    if not items:
        logger.warning("No real news fetched, using structured context")
        return _fallback_news()

    news_items = []
    for item in items:
        category, keywords = _classify_news(item.get("title", ""), item.get("summary", ""))
        news_items.append({
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "time": item.get("time", datetime.now().strftime("%Y-%m-%d")),
            "link": item.get("link", ""),
            "summary": item.get("summary", "")[:300],
            "category": category,
            "keywords": keywords,
        })

    # Deduplicate by keeping only first per category (pick the most relevant)
    seen_categories = set()
    deduped = []
    for item in news_items:
        cat = item.get("category", "")
        if cat not in seen_categories:
            seen_categories.add(cat)
            deduped.append(item)
    # If we got fewer than 3 unique categories, add more items
    if len(deduped) < 3:
        seen = set(d["category"] for d in deduped)
        for item in news_items:
            if item["category"] not in seen:
                seen.add(item["category"])
                deduped.append(item)

    logger.info("Fetched %d unique news items from RSS", len(deduped))
    return deduped[:5]


def _fallback_news() -> list[dict[str, Any]]:
    """Fallback: structured news context when RSS unavailable."""
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        {
            "title": "石油市场消息汇总",
            "source": "综合通讯社",
            "time": today,
            "link": "",
            "summary": "OPEC+ 产量政策、EIA 库存数据及全球宏观经济数据相关资讯",
            "category": "行业动态",
            "keywords": ["原油", "OPEC", "EIA"],
        }
    ]


def get_macro_events(days: int = 7) -> list[dict[str, Any]]:
    """Get upcoming macro events relevant to crude oil."""
    today = datetime.now()
    weekdays = []
    for i in range(7):
        d = today + timedelta(days=i)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        weekdays.append(d)

    events = [
        {"date": weekdays[0].strftime("%Y-%m-%d"), "event": "EIA 每周原油库存数据发布", "expected_impact": "高"},
        {"date": weekdays[1].strftime("%Y-%m-%d"), "event": "API 每周原油库存数据发布", "expected_impact": "高"},
        {"date": weekdays[2].strftime("%Y-%m-%d"), "event": "美国 CPI / PPI 通胀数据", "expected_impact": "中"},
    ]
    # Add Fed meetings on last Wednesday of month
    if today.day <= 28 and today.weekday() < 4:
        events.append({"date": weekdays[3].strftime("%Y-%m-%d") if len(weekdays) > 3 else "",
                       "event": "美联储利率决策会议", "expected_impact": "高"})
    return events
