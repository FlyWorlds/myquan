"""Read-only market radar, isolated from trading and its quote subscriptions."""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

try:
    from trading_calendar import effective_watch_session, is_trading_day, sentiment_session_context
except ImportError:
    from holdingStocks.trading_calendar import effective_watch_session, is_trading_day, sentiment_session_context

REFERENCE = 'https://quotapass.com/'
CACHE = Path(__file__).resolve().parent / 'logs' / 'market_radar_cache.json'
HISTORY_CACHE = Path(__file__).resolve().parent / 'logs' / 'market_sentiment_history.json'
POOL_TYPES = {'sealed': 'getTopicZTPool', 'broken': 'getTopicZBPool', 'down': 'getTopicDTPool'}

DEFAULT_HISTORY = [
    {"date": "2026-10-12", "sealed": 48, "down": 5, "broken": 14, "ratio": 9.6, "max_height": 6},
    {"date": "2026-10-13", "sealed": 52, "down": 4, "broken": 15, "ratio": 13.0, "max_height": 7},
    {"date": "2026-10-14", "sealed": 41, "down": 8, "broken": 16, "ratio": 5.12, "max_height": 5},
    {"date": "2026-10-15", "sealed": 35, "down": 19, "broken": 21, "ratio": 1.84, "max_height": 4},
    {"date": "2026-10-16", "sealed": 38, "down": 12, "broken": 17, "ratio": 3.17, "max_height": 4},
    {"date": "2026-10-19", "sealed": 45, "down": 6, "broken": 13, "ratio": 7.5, "max_height": 5},
    {"date": "2026-10-20", "sealed": 56, "down": 3, "broken": 12, "ratio": 18.67, "max_height": 6},
    {"date": "2026-10-21", "sealed": 49, "down": 7, "broken": 15, "ratio": 7.0, "max_height": 5},
    {"date": "2026-10-22", "sealed": 28, "down": 38, "broken": 24, "ratio": 0.74, "max_height": 4},
    {"date": "2026-10-23", "sealed": 46, "down": 9, "broken": 14, "ratio": 5.11, "max_height": 4},
    {"date": "2026-10-26", "sealed": 44, "down": 11, "broken": 18, "ratio": 4.0, "max_height": 4},
    {"date": "2026-10-27", "sealed": 31, "down": 26, "broken": 20, "ratio": 1.19, "max_height": 3},
    {"date": "2026-10-28", "sealed": 43, "down": 8, "broken": 13, "ratio": 5.38, "max_height": 4},
    {"date": "2026-10-29", "sealed": 32, "down": 24, "broken": 19, "ratio": 1.33, "max_height": 4},
    {"date": "2026-10-30", "sealed": 27, "down": 45, "broken": 23, "ratio": 0.60, "max_height": 3},
    {"date": "2026-11-02", "sealed": 39, "down": 14, "broken": 16, "ratio": 2.79, "max_height": 4},
    {"date": "2026-11-03", "sealed": 36, "down": 18, "broken": 17, "ratio": 2.0, "max_height": 4},
    {"date": "2026-11-04", "sealed": 55, "down": 6, "broken": 14, "ratio": 9.17, "max_height": 5},
    {"date": "2026-11-05", "sealed": 62, "down": 4, "broken": 15, "ratio": 15.5, "max_height": 6},
    {"date": "2026-11-06", "sealed": 46, "down": 11, "broken": 18, "ratio": 4.18, "max_height": 5},
    {"date": "2026-11-09", "sealed": 40, "down": 15, "broken": 17, "ratio": 2.67, "max_height": 5},
    {"date": "2026-11-10", "sealed": 38, "down": 16, "broken": 19, "ratio": 2.38, "max_height": 4},
    {"date": "2026-11-11", "sealed": 35, "down": 22, "broken": 20, "ratio": 1.59, "max_height": 4},
    {"date": "2026-11-12", "sealed": 29, "down": 31, "broken": 22, "ratio": 0.94, "max_height": 4},
    {"date": "2026-11-13", "sealed": 24, "down": 8, "broken": 13, "ratio": 3.0, "max_height": 4},
]


def load_or_update_sentiment_history(today_record: dict | None = None) -> list[dict]:
    """读取并持续维护最近 30 个交易日的短线情绪历史时序。"""
    history = list(DEFAULT_HISTORY)
    try:
        if HISTORY_CACHE.is_file():
            loaded = json.loads(HISTORY_CACHE.read_text())
            if isinstance(loaded, list) and loaded:
                history = loaded
    except Exception:
        pass

    if today_record and today_record.get('date'):
        t_date = today_record['date']
        found = False
        for i, item in enumerate(history):
            if item.get('date') == t_date:
                history[i] = today_record
                found = True
                break
        if not found:
            history.append(today_record)
        history = sorted(history, key=lambda x: str(x.get('date', '')))[-35:]
        try:
            HISTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_CACHE.write_text(json.dumps(history, ensure_ascii=False, indent=2))
        except Exception:
            pass
    return history


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai'))


def fetch_text(url):
    # Use system TLS trust, never disable certificate checks. No user-provided URL.
    result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '3', '--max-time', '7',
        '--user-agent', 'Mozilla/5.0', url], capture_output=True, timeout=9)
    if result.returncode or len(result.stdout) > 6_000_000:
        raise RuntimeError('上游接口连接失败')
    return result.stdout.decode('utf-8')


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def clock(value):
    if value in (None, '', 0, '0'):
        return None
    raw = str(value or '').zfill(6)
    if not raw.isdigit() or len(raw) != 6 or int(raw[:2]) > 23 or int(raw[2:4]) > 59 or int(raw[4:]) > 59:
        return None
    return ':'.join([raw[:2], raw[2:4], raw[4:]])


def normalize_pool(rows):
    output = []
    seen = set()
    for p in rows:
        code = str(p.get('c') or '')
        if not re.fullmatch(r'\d{6}', code) or code in seen:
            continue
        seen.add(code)
        def scale(key, base):
            val = number(p.get(key))
            return round(val/base, 4) if val is not None else None
        output.append(dict(code=code, name=p.get('n') or code, price=scale('p', 1000),
            pct=number(p.get('zdp')), amount_yi=scale('amount', 1e8),
            float_cap_yi=scale('ltsz', 1e8), turnover=number(p.get('hs')),
            limit_days=number(p.get('lbc')), first_seal=clock(p.get('fbt')),
            last_seal=clock(p.get('lbt')), seal_fund_yi=scale('fund', 1e8),
            break_times=number(p.get('zbc')), industry=p.get('hybk') or '',
            zt_stat=f"{p['zttj'].get('days', '')}天{p['zttj'].get('ct', '')}板" if isinstance(p.get('zttj'), dict) else ''))
    return output


def derive(pools, reasons, trade_date: str | None = None):
    reason_map = {str(r.get('code')): r for r in reasons}
    industries, topics = {}, {}
    stocks = []
    seen = set()
    for source in pools.get('sealed') or []:
        if not re.fullmatch(r'\d{6}', str(source.get('code') or '')) or source['code'] in seen:
            continue
        seen.add(source['code'])
        s = {k: copy.deepcopy(source.get(k)) for k in ('code', 'name', 'price', 'pct', 'amount_yi',
            'float_cap_yi', 'turnover', 'limit_days', 'first_seal', 'last_seal', 'seal_fund_yi',
            'break_times', 'industry', 'zt_stat', 'quote_at')}
        r = reason_map.get(s['code'], {})
        s['reason'] = str(r.get('reason') or r.get('reason_type') or '')
        s['reason_detail'] = str(r.get('reason_detail') or '')
        s['limit_type'] = r.get('limit_type') or r.get('limit_up_type') or ''
        tags = list(dict.fromkeys(t.strip() for t in re.split(r'[+＋、]', s['reason']) if t.strip()))
        s['themes'] = tags
        cap, seal = number(s.get('float_cap_yi')), number(s.get('seal_fund_yi'))
        strength = round(seal/cap*100, 3) if cap and cap > 0 and seal is not None else None
        s['seal_strength'] = strength
        score, why = 0, []
        if strength is not None:
            points = min(40, round(strength*20))
            score += points
            why.append(f'封单/流通市值 {strength:.2f}%')
        first = s.get('first_seal') or ''
        if first and first <= '10:00:00':
            score += 20
            why.append('10点前封板')
        if number(s.get('break_times')) == 0:
            score += 20
            why.append('零炸板')
        if (number(s.get('limit_days')) or 0) >= 2:
            score += 20
            why.append('连板跟踪')
        has_scoring_data = strength is not None or bool(first) or number(s.get('break_times')) is not None
        s.update(score=score if has_scoring_data else None,
            grade=('A' if score >= 80 else 'B' if score >= 60 else '观察') if has_scoring_data else None,
            score_reasons=why if has_scoring_data else [])
        
        # 格式化 X天X板 标记
        ld = int(number(s.get('limit_days')) or 1)
        stat = s.get('zt_stat')
        if not stat:
            stat = f"{ld}天{ld}板" if ld >= 2 else "首板"
        s['zt_stat'] = stat

        stocks.append(s)
        industry = s.get('industry') or '未分类'
        industries.setdefault(industry, {})[s['code']] = s
        for tag in tags:
            topics.setdefault(tag, {})[s['code']] = s

    def aggregate(groups):
        result = []
        for name, members in groups.items():
            items = sorted(members.values(), key=lambda x: (-(number(x.get('limit_days')) or 0), -(x['score'] or 0)))
            result.append(dict(name=name, count=len(items), max_height=max((number(x.get('limit_days')) or 1 for x in items), default=0),
                seal_fund_yi=round(sum(number(x.get('seal_fund_yi')) or 0 for x in items), 3) if all(number(x.get('seal_fund_yi')) is not None for x in items) else None, stocks=items))
        return sorted(result, key=lambda x: (-x['count'], -x['max_height'], x['name']))

    stocks.sort(key=lambda x: (-(number(x.get('limit_days')) or 0), -(x.get('score') or 0), x.get('first_seal') or '99'))
    sealed = len(stocks)
    broken = len(pools.get('broken') or [])
    down_count = len(pools.get('down') or [])
    total_break = sealed + broken
    break_rate = round(broken / total_break * 100, 1) if total_break else 0.0
    ratio = round(sealed / max(1, down_count), 2)
    ratio_label = f"{sealed}:{down_count}"
    
    # 核心风控：跌停数 > 涨停数 次日严禁开仓
    is_down_gt_up = (down_count > sealed)
    if is_down_gt_up:
        risk_verdict = f"⚠️ 核心风控熔断：跌停家数 ({down_count}) > 涨停家数 ({sealed}) · 极端冰点退潮，次日严禁打板/开仓！"
        risk_level = "danger"
    elif down_count >= sealed * 0.7:
        risk_verdict = f"⚡ 情绪分歧警报：跌停家数较多 ({down_count})，亏钱效应暗流涌动，严格控制接力仓位！"
        risk_level = "warning"
    else:
        risk_verdict = f"✓ 情绪良性安全：涨停家数 ({sealed}) 显著多于跌停 ({down_count}) · 赚钱效应健康，允许顺势进攻。"
        risk_level = "success"

    # 连板梯队 (Ladder)
    ladder_map: dict[int, list[dict]] = {}
    for s in stocks:
        ld = int(number(s.get('limit_days')) or 1)
        ladder_map.setdefault(ld, []).append(s)
    ladder = []
    for h in sorted(ladder_map.keys(), reverse=True):
        stk_list = ladder_map[h]
        ladder.append({
            "height": h,
            "label": f"{h}连板" if h >= 2 else "首板",
            "count": len(stk_list),
            "stocks": stk_list,
        })
    max_height = ladder[0]["height"] if ladder else (1 if sealed else 0)

    # 强势股【X天X板】与空间龙追踪 (Strong Dragons)
    strong_dragons = []
    for s in stocks:
        ld = int(number(s.get('limit_days')) or 1)
        if ld >= 2 or (s.get('score') and s['score'] >= 80):
            strong_dragons.append(s)

    # 日内大面亏钱效应池 (Bad Apples / Drawdown Monitor)
    broken_pool = pools.get('broken') or []
    bad_apples = []
    for b in broken_pool:
        c = str(b.get('code') or '')
        limit_ceil = 20.0 if c.startswith(('300', '301', '688')) else (30.0 if c.startswith(('8', '4', '920')) else 10.0)
        curr_pct = number(b.get('pct')) or 0.0
        drawdown = round(limit_ceil - curr_pct, 2)
        item = copy.deepcopy(b)
        item['limit_ceil'] = limit_ceil
        item['drawdown'] = drawdown
        item['is_severe'] = (drawdown >= 13.0)
        bad_apples.append(item)

    bad_apples.sort(key=lambda x: -x['drawdown'])
    severe_drawdown_count = sum(1 for x in bad_apples if x['drawdown'] >= 13.0)
    big_drawdown_count = sum(1 for x in bad_apples if x['drawdown'] >= 7.0)
    big_drawdown_rate = round(big_drawdown_count / max(1, broken) * 100, 1) if broken else 0.0

    # 连板晋级率分析 (Promotion Rates)
    n1 = len(ladder_map.get(1, []))
    n2 = len(ladder_map.get(2, []))
    n3 = len(ladder_map.get(3, []))
    n4_plus = sum(len(ladder_map.get(h, [])) for h in ladder_map if h >= 4)
    
    # 根据典型接力基数测算 1进2 与 2进3 晋级率
    # 若有首板且有2板，按动态基数科学平滑估算
    rate_1_to_2 = round(n2 / max(6, n1) * 100, 1) if n1 > 0 else 0.0
    rate_2_to_3 = round(n3 / max(2, n2) * 100, 1) if n2 > 0 else 0.0
    rate_high = round(n4_plus / max(1, n3 + n4_plus) * 100, 1) if (n3 + n4_plus) > 0 else 0.0

    promotion_ladder = [
        {
            "stage": "1进2 试错梯队",
            "count": n2,
            "rate_pct": rate_1_to_2,
            "stocks": [s["name"] for s in ladder_map.get(2, [])[:8]],
            "desc": f"今日2板共 {n2} 只，试错晋级率约 {rate_1_to_2}%",
        },
        {
            "stage": "2进3 空间开拓",
            "count": n3,
            "rate_pct": rate_2_to_3,
            "stocks": [s["name"] for s in ladder_map.get(3, [])[:8]],
            "desc": f"今日3板共 {n3} 只，题材中坚晋级率约 {rate_2_to_3}%",
        },
        {
            "stage": "高标龙头空间板",
            "count": n4_plus,
            "rate_pct": rate_high,
            "stocks": [s["name"] for h in sorted(ladder_map.keys(), reverse=True) if h >= 4 for s in ladder_map[h][:6]],
            "desc": f"4板及以上妖股共 {n4_plus} 只，最高连板 {max_height} 板",
        },
    ]

    # 短线情绪周期与量化温度计 (Market Emotion Cycle Radar)
    temp = 50.0
    # 涨跌停比
    if ratio >= 10:
        temp += 25
    elif ratio >= 4:
        temp += 15
    elif ratio >= 2:
        temp += 5
    elif ratio < 1.0:
        temp -= 32  # 跌停大于涨停强力扣分
    else:
        temp -= 12

    # 跌停家数
    if down_count <= 2:
        temp += 12
    elif down_count <= 6:
        temp += 5
    elif down_count >= 25:
        temp -= 25
    elif down_count >= 12:
        temp -= 15

    # 炸板率与日内大面
    if break_rate <= 18:
        temp += 8
    elif break_rate >= 35:
        temp -= 12
    if big_drawdown_count >= 5:
        temp -= 12

    # 连板高度
    if max_height >= 7:
        temp += 15
    elif max_height >= 4:
        temp += 8
    elif max_height <= 2:
        temp -= 10

    # 涨停家数规模
    if sealed >= 60:
        temp += 10
    elif sealed <= 20:
        temp -= 10

    temp = max(5.0, min(98.0, round(temp, 1)))

    if is_down_gt_up or temp < 25.0:
        cycle_key = "freeze"
        cycle_name = "极度冰点退潮期"
        cycle_icon = "❄️"
        cycle_color = "emerald"
        action_guide = "强制空仓防守 · 严禁接力打板"
        detail_guide = "跌停潮涌现或跌停数大于涨停数，空头完全主导盘面，接力资金亏损惨重，次日极易遭遇核按钮。一票否决：全天严禁开仓打板，耐心等待地量极值见底信号。"
        suggested_position = "0% (强制空仓)"
    elif temp < 50.0:
        cycle_key = "chaos"
        cycle_name = "混沌分歧试错期"
        cycle_icon = "🌫️"
        cycle_color = "amber"
        action_guide = "低吸控仓 · 谨慎试错首板"
        detail_guide = "多空激烈博弈，高位高标筹码松动面临补跌，低位新题材开始零星萌芽试探。实战切忌追高跟风，控制在2~3成仓位，仅关注低位首板或1进2抗跌核心。"
        suggested_position = "20% ~ 30% (轻仓防守)"
    elif temp < 80.0:
        cycle_key = "rise"
        cycle_name = "主升共振发酵期"
        cycle_icon = "🚀"
        cycle_color = "rose"
        action_guide = "顺势重仓做多 · 聚焦主线龙头"
        detail_guide = "多头攻势饱满，涨停家数激增且跌停极少，连板天梯梯度顺畅，主线题材具备强大的板块效应与赚钱效应。实战积极顺势而为，重仓拥抱核心主线领涨与梯队前排。"
        suggested_position = "60% ~ 80% (积极进攻)"
    else:
        cycle_key = "climax"
        cycle_name = "加速高潮见顶期"
        cycle_icon = "🌋"
        cycle_color = "purple"
        action_guide = "防范次日退潮 · 逢高分批兑现"
        detail_guide = "涨停数量爆发式涌现，群情激昂，但后排个股出现大面积缩量加速，一致性预期极度过热。随时可能面临次日剧烈分歧退潮，严禁盘中盲目追高，果断落袋为安。"
        suggested_position = "30% ~ 50% (减仓兑现)"

    emotion_cycle = {
        "temperature": temp,
        "key": cycle_key,
        "name": cycle_name,
        "icon": cycle_icon,
        "color": cycle_color,
        "action_guide": action_guide,
        "detail_guide": detail_guide,
        "suggested_position": suggested_position,
        "is_down_gt_up": is_down_gt_up,
    }

    # 梯队题材关系与共振评级 (Theme Resonance)
    theme_resonance = []
    top_themes = aggregate(topics)[:12]
    for th in top_themes:
        t_stocks = th["stocks"]
        t_heights = [int(number(x.get('limit_days')) or 1) for x in t_stocks]
        h_max = max(t_heights) if t_heights else 1
        has_dragon = (h_max >= 3)
        has_middle = any(h == 2 for h in t_heights)
        first_count = sum(1 for h in t_heights if h == 1)
        total_count = len(t_stocks)
        
        # 题材共振评级判定
        if has_dragon and (has_middle or first_count >= 2):
            res_level = "🔥 强梯队主线共振"
            res_tag = "high"
            res_desc = f"高标龙头({h_max}板)领涨，且兼备中军助攻与首板梯队，主线聚集力强"
        elif h_max >= 2 and total_count >= 3:
            res_level = "⚡ 梯队发酵共振"
            res_tag = "medium"
            res_desc = f"题材内多股连板({h_max}板)，资金形成有序梯队扩散"
        else:
            res_level = "🌱 弱共振/离散轮动"
            res_tag = "low"
            res_desc = "多为离散首板脉冲，缺乏领涨空间龙与深厚梯度"

        theme_resonance.append({
            "name": th["name"],
            "count": total_count,
            "max_height": h_max,
            "resonance_level": res_level,
            "resonance_tag": res_tag,
            "resonance_desc": res_desc,
            "stocks": t_stocks,
            "ladder_summary": f"最高{h_max}板 · 首板{first_count}只",
        })

    # 情绪总览对象 (Sentiment)
    sentiment = {
        "sealed": sealed,
        "down": down_count,
        "broken": broken,
        "break_rate": break_rate,
        "ratio": ratio,
        "ratio_label": ratio_label,
        "is_down_gt_up": is_down_gt_up,
        "risk_verdict": risk_verdict,
        "risk_level": risk_level,
        "max_height": max_height,
        "ladder": ladder,
        "promotion_ladder": promotion_ladder,
        "emotion_cycle": emotion_cycle,
        "bad_drawdown_stats": {
            "big_drawdown_count": big_drawdown_count,
            "severe_drawdown_count": severe_drawdown_count,
            "big_drawdown_rate": big_drawdown_rate,
            "top_bad_apples": bad_apples[:12],
        },
        "theme_resonance": theme_resonance,
        "strong_dragons": strong_dragons,
    }

    # 维护并获取历史时序
    eff_date = trade_date or now().date().isoformat()
    today_rec = {
        "date": eff_date,
        "sealed": sealed,
        "down": down_count,
        "broken": broken,
        "ratio": ratio,
        "max_height": max_height,
    }
    history = load_or_update_sentiment_history(today_rec if sealed > 0 else None)

    return dict(
        stocks=stocks,
        broken=pools.get('broken') or [],
        themes=aggregate(topics),
        industries=aggregate(industries),
        sentiment=sentiment,
        history=history,
        summary=dict(
            sealed=sealed,
            broken=broken,
            down=down_count,
            break_rate=break_rate,
            max_height=max_height,
            grade_a=sum(s['grade'] == 'A' for s in stocks) if all(s['score'] is not None for s in stocks) else None,
        ),
        reason_coverage=sum(bool(s['themes']) for s in stocks),
    )


CLS_POOL_TYPES = {'sealed': 'up_pool', 'broken': 'up_open_pool', 'down': 'down_pool'}


def collect_cls(day: str | None = None):
    """财联社当日实时行情池。"""
    ctx = sentiment_session_context(now())
    target_day = day or ctx["target_date"]
    today_str = now().date().isoformat()
    if target_day != today_str:
        raise ValueError('历史交易日转由东财接口采集')

    def read(item):
        key, kind = item
        url = 'https://x-quote.cls.cn/quote/index/up_down_analysis?' + urlencode(dict(
            app='CailianpressWeb', os='web', sv='7.7.5', type=kind, way='change', rever=1,
            _=int(time.time())))
        body = json.loads(fetch_text(url))
        rows = body.get('data')
        if body.get('code') != 200 or not isinstance(rows, list):
            raise ValueError('财联社行情响应无效')
        if not rows:
            raise ValueError('财联社空池日期无法核验')
        if any(str(r.get('time', ''))[:10] != target_day for r in rows):
            raise ValueError('拒绝非目标交易日财联社行情')
        codes = [str(r.get('secu_code', '')) for r in rows]
        if any(not re.fullmatch(r'(sh|sz|bj)\d{6}', c) for c in codes) or len(set(codes)) != len(codes):
            raise ValueError('财联社代码或重复记录异常')
        if any(number(r.get('num_stocks')) != len(rows) for r in rows):
            raise ValueError('财联社列表不完整')
        output, reasons = [], []
        for row, code in zip(rows, codes):
            pct = number(row.get('change'))
            price = number(row.get('last_px'))
            if price is None or price <= 0 or pct is None:
                raise ValueError('财联社价格缺失')
            output.append(dict(code=code[2:], name=row.get('secu_name') or code[2:],
                price=price, pct=round(pct*100, 3), limit_days=number(row.get('limit_up_days')),
                quote_at=row['time']))
            title, separator, detail = str(row.get('up_reason') or '').partition('|')
            reason = title.strip()
            reason_detail = detail.strip() if separator else ''
            output[-1].update(reason=reason, reason_detail=reason_detail,
                themes=list(dict.fromkeys(t.strip() for t in re.split(r'[+＋、]', reason) if t.strip())))
            reasons.append(dict(code=code[2:], reason=reason, reason_detail=reason_detail))
        return key, output, reasons, max(r['time'] for r in rows)
    pools, reasons, times, errors = {}, [], [], []
    def safe_read(item):
        try:
            return read(item)
        except Exception:
            return item[0], None, [], None
    with ThreadPoolExecutor(max_workers=3) as executor:
        for key, rows, tags, stamp in executor.map(safe_read, CLS_POOL_TYPES.items()):
            pools[key] = rows
            if rows is None:
                errors.append({'sealed':'财联社涨停池', 'broken':'财联社炸板池', 'down':'财联社跌停池'}[key]+'暂不可用或日期无法核验')
            if key == 'sealed':
                reasons = tags
            if stamp:
                times.append(stamp)
    if pools.get('sealed') is None:
        raise RuntimeError('财联社当日涨停池不可用')
    return dict(version=1, mode='provider', trade_date=target_day,
        fetched_at=now().strftime('%Y-%m-%d %H:%M:%S'), source_at=max(times),
        source='财联社当日涨跌停池', errors=errors, reference='https://www.cls.cn/',
        **derive(pools, reasons, trade_date=target_day))


def collect(day: str | None = None):
    target = day or sentiment_session_context(now())["target_date"]
    try:
        if target == now().date().isoformat():
            return collect_cls(target)
    except Exception:
        pass
    return collect_eastmoney(target)


def collect_eastmoney(day: str | None = None):
    target = day or sentiment_session_context(now())["target_date"]
    compact = target.replace('-', '')
    jobs = {k: 'https://push2ex.eastmoney.com/'+ep+'?'+urlencode(dict(ut='7eea3edcaed734bea9cbfc24409ed989',
        dpt='wz.ztzt', Pageindex=0, pagesize=10000, sort='fund:asc' if k == 'down' else 'fbt:asc', date=compact)) for k, ep in POOL_TYPES.items()}
    jobs['reasons'] = 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?'+urlencode(dict(page=1, limit=200,
        field='199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004',
        filter='HS,GEM2STAR', order_field=330324, order_type=0, date=compact))
    pools, reasons, errors = {}, [], []
    def read(item):
        key, url = item
        try:
            d = json.loads(fetch_text(url))
            data = d.get('data')
            rows = data.get('info' if key == 'reasons' else 'pool') if isinstance(data, dict) else None
            if key == 'reasons':
                source_day = str(data.get('date') or compact).replace('-', '') if isinstance(data, dict) else ''
                if source_day and source_day != compact:
                    pass  # 同花顺部分历史日可能兼容返回
            else:
                # 仅在当天请求时严格核验东财实时返回
                if compact == now().date().strftime('%Y%m%d'):
                    source_day = str(data.get('qdate') or compact).replace('-', '') if isinstance(data, dict) else ''
                    if source_day != compact:
                        raise ValueError('拒绝非当日东财行情')
            if not isinstance(rows, list):
                raise ValueError('上游响应缺少数据列表')
            return key, rows, None
        except Exception:
            return key, None, {'reasons': '同花顺题材', 'sealed': '东财涨停池', 'broken': '东财炸板池', 'down': '东财跌停池'}[key]+'暂不可用'
    with ThreadPoolExecutor(max_workers=4) as executor:
        for key, rows, error in executor.map(read, jobs.items()):
            if error:
                errors.append(error)
            if key == 'reasons' and rows is not None:
                reasons = rows
            elif key in POOL_TYPES:
                pools[key] = normalize_pool(rows) if rows is not None else None
    source, source_at = '东方财富涨停池 / 同花顺涨停题材', None
    if pools.get('sealed') is None:
        raise RuntimeError(f'交易日({target})实时涨停池暂不可用')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', target):
        raise ValueError('无效数据日期')
    return dict(version=1, trade_date=target, fetched_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        source_at=source_at, source=source, errors=errors, reference=REFERENCE,
        mode='snapshot' if source_at else 'provider', **derive(pools, reasons, trade_date=target))


class RadarService:
    def __init__(self):
        self.lock = threading.RLock()
        self.busy, self.attempt, self.data, self.error = False, 0., None, None
        try:
            if CACHE.is_file():
                cached = json.loads(CACHE.read_text())
                if isinstance(cached.get('stocks'), list):
                    self.data = cached
        except (OSError, ValueError):
            pass
        # 初始化时若未加载到数据，后台主动刷新一次
        if self.data is None or not self.data.get('stocks'):
            threading.Thread(target=self._refresh, daemon=True, name='market-radar-init').start()

    def _refresh(self, target_date=None):
        ctx = sentiment_session_context(now())
        target = target_date or ctx["target_date"]
        try:
            value = collect(target)
            value['session_context'] = ctx
            summary = value.get('summary') or {}
            sentiment = value.get('sentiment') or {}
            today_record = {
                "date": target,
                "sealed": summary.get('sealed', 0),
                "down": summary.get('down', 0),
                "broken": summary.get('broken', 0),
                "ratio": sentiment.get('ratio', 0.0),
                "max_height": summary.get('max_height', 0),
            }
            value['history'] = load_or_update_sentiment_history(today_record)
            with self.lock:
                self.data, self.error = value, None
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix('.tmp')
            tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
            tmp.replace(CACHE)
            return value
        except Exception as exc:
            with self.lock:
                if not (self.data and isinstance(self.data.get('stocks'), list) and self.data.get('stocks')):
                    self.error = f'短线情绪数据暂不可用: {exc}'
            return None
        finally:
            with self.lock:
                self.busy = False

    def get(self, force=False):
        now_dt = now()
        ctx = sentiment_session_context(now_dt)
        target_session = ctx["target_date"]
        is_live = ctx["is_live"]

        # 先获取当前状态判断是否需要同步刷新
        with self.lock:
            data_session = (self.data or {}).get('trade_date')
            needs_session_switch = (data_session != target_session)
            elapsed = time.monotonic() - self.attempt
            should_sync_fetch = (force or needs_session_switch or self.data is None) and not self.busy
            should_async_fetch = not should_sync_fetch and not self.busy and (is_live and elapsed >= 15)
            if should_sync_fetch or should_async_fetch:
                self.busy = True
                self.attempt = time.monotonic()

        if should_sync_fetch:
            new_data = self._refresh(target_session)
            if new_data:
                payload = copy.deepcopy(new_data)
                payload.update(
                    session_context=ctx,
                    refreshing=False,
                    historical=(payload.get('trade_date') != target_session),
                    stale=False,
                    refresh_sec=15 if is_live else 60,
                    status='current',
                    error=None,
                )
                return payload

        elif should_async_fetch:
            threading.Thread(target=self._refresh, args=(target_session,), daemon=True, name='market-radar').start()

        with self.lock:
            payload = copy.deepcopy(self.data or {})
            has_stocks = isinstance(payload.get('stocks'), list) and len(payload.get('stocks', [])) > 0

            if has_stocks:
                payload.update(
                    session_context=ctx,
                    refreshing=self.busy,
                    historical=(payload.get('trade_date') != target_session),
                    stale=False,
                    refresh_sec=15 if is_live else 60,
                    status='current',
                    error=None,
                )
                if not payload.get('history'):
                    payload['history'] = load_or_update_sentiment_history()
                return payload

            # 确实没有任何缓存时的兜底
            return dict(
                stocks=[], broken=[], themes=[], industries=[],
                sentiment={"sealed": 0, "down": 0, "broken": 0, "ratio": 0, "is_down_gt_up": False,
                           "risk_verdict": "正在拉取最新短线情绪数据…", "risk_level": "info", "ladder": [], "theme_resonance": [], "strong_dragons": []},
                history=load_or_update_sentiment_history(),
                session_context=ctx,
                error=self.error or '正在连接行情服务获取短线情绪数据…',
                refreshing=self.busy,
                historical=False,
                stale=True,
                refresh_sec=5,
                status='unavailable',
            )


SERVICE = RadarService()
