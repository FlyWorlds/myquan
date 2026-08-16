"""Broker research views — 券商研报观点（公开财经数据 + 精选数据库）."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 精选券商研报数据库 ──────────────────────────────────────────
# 来源：公开财经资讯 (中金/星展/中信/国元等已发布研报)
# 更新频率：每月根据最新研报补充
_CURATED_RESEARCH: dict[str, list[dict]] = {
    "1610": [  # 中粮家佳康
        {
            "broker": "中金公司",
            "rating": "跑赢行业 (Outperform)",
            "target_price": {"price": 2.50, "currency": "HKD"},
            "date": "2025-08-26",
            "summary": "看好出栏量恢复增长及成本改善，上调目标价39%",
        },
        {
            "broker": "星展银行",
            "rating": "买入 (Buy)",
            "target_price": {"price": 2.28, "currency": "HKD"},
            "date": "2025-08-27",
            "summary": "产量稳健扩张，利润率逐季改善，上调目标价",
        },
        {
            "broker": "中信证券",
            "rating": "买入 (Buy)",
            "target_price": {"price": 1.80, "currency": "HKD"},
            "date": "2026-03-27",
            "summary": "猪价周期回暖，公司盈利弹性大",
        },
        {
            "broker": "国元国际",
            "rating": "买入 (Buy)",
            "target_price": {"price": 1.80, "currency": "HKD"},
            "date": "2026-03-30",
            "summary": "猪价见底，公司有望受益于行业周期反转",
        },
        {
            "broker": "兴证国际",
            "rating": "买入 (Buy)",
            "target_price": None,
            "date": "2025-08-28",
            "summary": "生猪出栏量恢复，养殖成本持续改善",
        },
        {
            "broker": "兴业证券",
            "rating": "买入 (Buy)",
            "target_price": None,
            "date": "2025-08-26",
            "summary": "看好公司成本优势和出栏增长",
        },
    ],
    "0700": [  # 腾讯控股
        {
            "broker": "高盛 (Goldman Sachs)",
            "rating": "买入 (Buy)",
            "target_price": {"price": 560.00, "currency": "HKD"},
            "date": "2026-03-15",
            "summary": "AI驱动增长，游戏业务复苏强劲",
        },
        {
            "broker": "摩根士丹利 (Morgan Stanley)",
            "rating": "增持 (Overweight)",
            "target_price": {"price": 570.00, "currency": "HKD"},
            "date": "2026-04-10",
            "summary": "看好广告和金融科技业务的增长",
        },
        {
            "broker": "中金公司",
            "rating": "跑赢行业 (Outperform)",
            "target_price": {"price": 550.00, "currency": "HKD"},
            "date": "2026-05-20",
            "summary": "AI生态持续完善，估值具吸引力",
        },
    ],
    "0839": [  # 中教控股
        {
            "broker": "中金公司",
            "rating": "跑赢行业 (Outperform)",
            "target_price": {"price": 4.50, "currency": "HKD"},
            "date": "2026-04-15",
            "summary": "高教板块政策风险释放，估值修复可期",
        },
        {
            "broker": "中信证券",
            "rating": "买入 (Buy)",
            "target_price": {"price": 5.00, "currency": "HKD"},
            "date": "2026-03-20",
            "summary": "学额增长驱动收入，分红率有望提升",
        },
    ],
    "2577": [  # 英诺赛科
        {
            "broker": "中信里昂",
            "rating": "优于大市 (Outperform)",
            "target_price": {"price": 113.60, "currency": "HKD"},
            "date": "2026-05-15",
            "summary": "GaN渗透率提升，长期增长前景广阔",
        },
        {
            "broker": "美银证券",
            "rating": "买入 (Buy)",
            "target_price": {"price": 92.00, "currency": "HKD"},
            "date": "2026-05-15",
            "summary": "收入预测上调3-4%，但毛利率预测更保守",
        },
        {
            "broker": "摩根士丹利",
            "rating": "大市同步 (In-Line)",
            "target_price": {"price": 69.00, "currency": "HKD"},
            "date": "2026-04-01",
            "summary": "观望GaN商业化进展",
        },
        {
            "broker": "招银国际",
            "rating": "买入 (Buy)",
            "target_price": {"price": 75.00, "currency": "HKD"},
            "date": "2026-03-31",
            "summary": "看好GaN功率半导体国产替代",
        },
        {
            "broker": "财通证券",
            "rating": "增持 (Overweight)",
            "target_price": None,
            "date": "2026-04-12",
            "summary": "GaN下游需求强劲",
        },
        {
            "broker": "东吴证券",
            "rating": "买入 (Buy)",
            "target_price": None,
            "date": "2026-03-13",
            "summary": "氮化镓龙头，成长空间大",
        },
    ],
    "1918": [  # 融创中国
        {
            "broker": "花旗 (Citi)",
            "rating": "中性/高风险 (Neutral/High Risk)",
            "target_price": {"price": 1.20, "currency": "HKD"},
            "date": "2026-05-12",
            "summary": "债务重组缓解短期流动性，但合约销售2025年同比跌22%",
        },
        {
            "broker": "摩根大通 (JPMorgan)",
            "rating": "减持 (Underweight)",
            "target_price": {"price": 0.80, "currency": "HKD"},
            "date": "2026-01-21",
            "summary": "预计2026年仍录得较大亏损，销售动力疲弱",
        },
    ],
}


def get_broker_views(symbol: str) -> dict[str, Any]:
    """Fetch recent broker research views for a given stock.

    Checks curated database first, then falls back to public web sources.

    Args:
        symbol: HK stock symbol (e.g., "0700.HK")

    Returns:
        Dict with:
          - views: list of broker view dicts
          - summary: text summary
          - error: error message if any
    """
    result: dict[str, Any] = {
        "views": [],
        "summary": "",
        "error": None,
    }

    ticker = symbol.replace(".HK", "")
    views: list[dict] = []

    # 1. Check curated database first
    curated = _CURATED_RESEARCH.get(ticker, [])
    if curated:
        logger.info(
            "Found %d curated broker views for %s", len(curated), symbol
        )
        views.extend(curated)

    # 2. Try web sources for supplementary data
    try:
        web_views = _fetch_web_views(ticker, symbol)
        if web_views:
            # Merge: prefer curated over web-sourced for same broker
            existing_brokers = {v.get("broker") for v in views}
            for wv in web_views:
                if wv.get("broker") not in existing_brokers:
                    views.append(wv)
    except Exception as e:
        logger.debug("Web fetch supplementary failed: %s", e)

    # Sort by date (newest first), curated first then web
    views.sort(key=lambda v: v.get("date", ""), reverse=True)

    result["views"] = views[:15]
    if views:
        result["summary"] = f"近期有 {len(views)} 家券商发布了关于 {symbol} 的研究观点"
    else:
        result["summary"] = "暂未获取到近期券商研报观点"

    return result


def _fetch_web_views(ticker: str, symbol: str) -> list[dict]:
    """Try to fetch supplementary views from web sources."""
    # Reserved for future use (e.g., WebSearch API integration)
    return []


# ── 精选业务分析数据库 ──────────────────────────────────────────
# 来源：公司年报/公告、行业研究、公开财经资讯
# 格式：按股票代码索引，每项包含业务描述、收入构成、竞争优势、战略等
_CURATED_BUSINESS: dict[str, dict] = {
    "1918": {  # 融创中国
        "overview": (
            "融创中国控股有限公司（01918.HK）成立于2003年，创始人孙宏斌，总部位于北京，"
            "2010年于港交所上市。公司为中国领先的房地产开发商之一，高峰期行业排名前四。"
            "主营业务涵盖高端住宅及商业物业开发、物业管理（融创服务，01516.HK）、"
            "文旅城运营（主题乐园、室内滑雪场、酒店群）及文化内容制作等。"
        ),
        "business_segments": [
            ("物业销售", "73.3%", "住宅及商业地产开发销售，聚焦一二线核心城市高端产品线，2025年合同销售368.4亿元"),
            ("物业管理", "~15.1%", "融创服务在管面积约2.6亿平方米，2025年实现扭亏为盈，归母净利润2.0亿元"),
            ("文旅运营", "10.5%", "涵盖乐园、商业、酒店及冰雪业态，2025年接待客流1.76亿人次，在营雪场11家"),
        ],
        "revenue_total": "451.2亿元（2025年全年）",
        "revenue_trend": "同比-39%，主因交付面积减少23.1%及销售均价下降29.8%",
        "business_model": (
            "核心模式为「高端住宅开发 + 收并购扩张 + 多元化运营」。历史上以激进的收并购策略著称，"
            "通过项目层面收购而非招拍挂获取低价土地，平均拿地成本远低于同行。"
            "2017年以438亿元收购万达文旅城及酒店资产是标志性交易。"
            "产品端主打「壹号院」「桃花源」等高端产品线，定位高净值客群。"
            "2022年流动性危机后，战略重心转向保交付、债务重组和存量资产盘活。"
        ),
        "competitive_advantages": [
            "高端品牌力：壹号院系产品在核心城市具备标杆效应，上海壹号院2025年单盘销售超220亿元",
            "低价土地储备：历史上通过收并购获取大量低成本土储，平均成本约5000元/平米，显著低于招拍挂均价",
            "收并购执行力：业内公认的并购整合能力，能够快速完成项目层面的尽职调查和交易交割",
            "土储规模优势：截至2025年末总土储约1.08亿平方米，权益土储约7651万平方米，覆盖核心一二线城市",
            "多元收入协同：物业管理（融创服务）+文旅运营提供经常性收入，与开发业务形成协同",
        ],
        "strategy": (
            "短期（2024-2026）：以「保交付 + 化风险」为首要任务。已完成境内外债务重组，"
            "累计交付超72万套房屋。积极推进存量资产盘活，2025年盘活12个项目预计回笼资金约112亿元。\n"
            "中长期：从传统开发商向「基金化运营」模式转型，推动持有型物业通过REITs实现资产证券化，"
            "轻资产运营（物业、商业管理、冰雪文旅）预计在未来2-3年实现较大突破。"
            "区域上聚焦北京、上海、西安、重庆等核心城市，不再无序扩张。"
        ),
        "industry_position": (
            "中国房地产行业正处于深度调整期，2025年全国商品房销售面积较峰值下降约40%。"
            "行业格局重塑，民企开发商普遍面临流动性压力，国有房企和部分头部民企主导市场。"
            "融创作为已完成境内外债务重组的头部民企之一，在化债进度上领先于多数同行，"
            "但销售复苏速度和盈利能力恢复仍面临较大不确定性。"
        ),
    },
    "1610": {  # 中粮家佳康
        "overview": (
            "中粮家佳康食品有限公司（01610.HK）是中粮集团旗下的核心肉类业务平台，"
            "2016年11月于港交所上市。公司是中国领先的全产业链肉类企业，"
            "业务涵盖饲料生产、生猪养殖、屠宰加工、生鲜猪肉及肉制品销售、肉类进口贸易等。"
            "公司以「家佳康」「万威客」为核心品牌，在高端生鲜猪肉市场占据领先地位，"
            "同时亚麻籽猪肉等差异化产品具备独特竞争优势。"
        ),
        "business_segments": [
            ("饲料业务", "~28%", "猪饲料、反刍料、禽料等研发生产销售，2025年收入67.4亿元，对内协同降本+对外拓展差异化品类"),
            ("生鲜猪肉", "~28%", "屠宰加工及品牌生鲜销售，2025年收入53.1亿元，品牌收入占比32.1%，亚麻籽猪肉销量增长135%"),
            ("生猪养殖", "~27.7%", "商品猪养殖及出栏，2025年出栏603万头（+69%），完全成本降至13元/千克，PSY突破28"),
            ("肉类进口", "~12%", "冷冻猪肉/牛肉/禽肉等进口贸易，2025年收入25.6亿元（+19.8%），分部利润1990万元"),
            ("肉制品", "~4%", "深加工肉制品，2025年收入7.9亿元（+5.9%），分部利润609万元"),
        ],
        "revenue_total": "185.79亿元（2025年全年）",
        "revenue_trend": "同比+13.8%，出栏量大幅增长69%驱动收入扩张，但猪价下跌19%压制利润",
        "business_model": (
            "核心模式为「全产业链一体化 + 品牌化运营」。从饲料生产、生猪养殖、屠宰加工到品牌销售的纵向一体化布局，"
            "使得公司在成本控制和食品安全追溯方面具备明显优势。"
            "养殖端通过规模化、智能化养殖持续降低完全成本（已降至13元/千克）；"
            "品牌端以「家佳康」和「万威客」双品牌驱动，亚麻籽猪肉为核心差异化单品，"
            "品牌收入占比持续提升至34%以上。背靠中粮集团资源，资金成本低（贷款利率0.55%-2.79%）、融资渠道充裕。"
        ),
        "competitive_advantages": [
            "全产业链一体化：覆盖饲料-养殖-屠宰-加工-品牌全环节，成本可控、食品安全可追溯",
            "央企背景：背靠中粮集团，融资成本极低（贷款利率0.55%-2.79%），授信额度充裕（162亿元未动用）",
            "品牌差异化：亚麻籽猪肉为行业独有差异化产品，精准定位高端健康消费客群，2025年销量增速135%",
            "成本持续优化：养殖完全成本从2022年高位持续下降至13元/千克，PSY突破28，生产效率行业领先",
            "出栏弹性：2025年生猪出栏量603万头（+69%），产能利用率大幅提升，规模效应逐步显现",
        ],
        "strategy": (
            "短期（2026年）：全价值链成本管控，推进养殖九大专项任务（健康成本、饲料成本、人效提升），"
            "提升产能利用率和出栏效率。\n"
            "中长期：1）品牌化转型，以亚麻籽猪为核心深耕高端健康猪肉市场，品牌收入占比目标持续提升；"
            "2）科技创新驱动，推进基因育种（优化基因组选择技术）、数智化配方系统、AI智慧养殖等；"
            "3）绿色循环农业，粪污处理节能降本、联农带农；"
            "4）产品矩阵扩展，万威客品牌开发牛肉全系列产品。"
        ),
        "industry_position": (
            "中国生猪养殖行业高度分散，行业CR10不足15%，但规模化进程持续加速。"
            "2025年生猪均价13.4元/千克（同比跌19%），全行业普遍亏损，产能去化加速。"
            "预计2026年下半年猪价将进入回升周期，大型养殖企业有望率先受益。"
            "公司作为央企背景的领军企业，在资金成本、品牌溢价、产能扩张方面具备明显优势，"
            "有望在本轮猪周期反转中获得超额收益。中金和国元证券均给予买入评级，目标价1.8港元。"
        ),
    },
    "0700": {  # 腾讯控股
        "overview": (
            "腾讯控股有限公司（00700.HK）成立于1998年，总部位于深圳，2004年于港交所上市。"
            "中国最大的互联网综合服务提供商之一，业务覆盖社交（微信/QQ）、数字内容（游戏/视频/音乐）、"
            "金融科技（微信支付/理财通）、企业服务（腾讯云/SaaS）及新兴AI领域。"
        ),
        "business_segments": [
            ("增值服务（游戏+社交）", "~49%", "包括网络游戏（国内+国际）和社交网络订阅/虚拟道具收入，王者荣耀/和平精英/国际游戏为收入主力"),
            ("金融科技与企业服务", "~32%", "微信支付商业交易、理财通、腾讯云及企业SaaS服务，毛利率持续改善"),
            ("网络广告", "~19%", "微信朋友圈/公众号/视频号广告、腾讯视频/新闻广告，视频号广告增速亮眼"),
        ],
        "revenue_total": "6600亿元+（2025年预估）",
        "revenue_trend": "同比稳定增长，增值服务基本盘稳固，金融科技与企业服务为增长主引擎",
        "business_model": (
            "核心模式为「流量生态 + 变现多元化」。以微信（13亿+MAU）和QQ（5亿+MAU）构建中国最大的社交生态，"
            "通过游戏、广告、金融科技、云服务等多条路径实现流量变现。近年来加大AI投入，"
            "混元大模型及AI应用（如腾讯元宝、AI广告投放）成为新的增长驱动力。"
        ),
        "competitive_advantages": [
            "社交护城河：微信/QQ构建中国最大的社交网络，用户黏性极高，竞争壁垒难以复制",
            "游戏全球布局：全球最大游戏公司之一，拥有Riot Games、Supercell等头部工作室及众多IP",
            "金融科技生态：微信支付为线下支付双寡头之一，理财通/微粒贷等产品持续渗透",
            "AI+云业务：混元大模型在多个场景落地，腾讯云在国内公有云市场稳居前三",
            "投资生态：通过腾讯投资构建了庞大的互联网投资组合，覆盖电商、出行、医疗等多个赛道",
        ],
        "strategy": (
            "「扎根消费互联网，拥抱产业互联网」双轮驱动。消费端深化微信视频号、小程序、搜一搜等生态能力，"
            "巩固社交流量和内容壁垒。产业端以腾讯云和企业微信为核心，服务企业数字化升级。"
            "AI战略为当前重中之重，混元大模型全面接入各业务线，提升广告精准度和运营效率。"
        ),
        "industry_position": (
            "中国互联网行业进入成熟期，监管环境趋于稳定。公司在社交、游戏、移动支付三大领域保持领先地位，"
            "AI领域的投入和布局有望打开新的增长空间。面临来自字节跳动（内容/广告）、"
            "阿里巴巴（云/支付）及新兴AI创企的竞争压力。"
        ),
    },
}


def get_business_analysis(symbol: str) -> dict[str, Any]:
    """Fetch business analysis for a given stock.

    Returns curated business analysis data including overview,
    revenue breakdown, business model, competitive advantages, and strategy.

    Args:
        symbol: HK stock symbol (e.g., "0700.HK")

    Returns:
        Dict with business analysis fields, or empty dict if not available.
    """
    ticker = symbol.replace(".HK", "")
    data = _CURATED_BUSINESS.get(ticker, {})
    if data:
        logger.info("Found curated business analysis for %s", symbol)
    else:
        logger.info("No curated business analysis for %s", symbol)
    return data

