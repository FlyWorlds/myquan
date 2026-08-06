"""行情复盘：汇总大盘 / 账户 / 持仓 / 策略事件，可推送微信机器人。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REVIEW_FILE = ROOT / "market_review_latest.txt"
REVIEW_JSON = ROOT / "market_review_latest.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _f(v: Any, digits: int = 2) -> str:
    if v is None or v == "":
        return "-"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def _pct(v: Any) -> str:
    if v is None or v == "":
        return "-"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return str(v)


@dataclass
class ReviewLine:
    code: str
    name: str
    status: str
    last: float | None = None
    day_chg: Any = None
    day_pnl: float | None = None
    float_pnl: float | None = None
    alert: str = ""
    hit: str = ""
    note: str = ""


@dataclass
class MarketReview:
    generated_at: str
    strategy: str
    session: str = ""
    indices: list[dict[str, Any]] = field(default_factory=list)
    account_total: float | None = None
    account_open: float | None = None
    available_cash: float | None = None
    position_pct: float | None = None
    day_pnl: float | None = None
    day_pnl_pct: float | None = None
    equity_pnl: float | None = None
    equity_pnl_pct: float | None = None
    holdings: list[ReviewLine] = field(default_factory=list)
    alerts: list[ReviewLine] = field(default_factory=list)
    settled: list[ReviewLine] = field(default_factory=list)
    empty_watch: list[ReviewLine] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def build_review(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
    *,
    account_total: float | None = None,
    account_open: float | None = None,
    available_cash: float | None = None,
    strategy: str = "策略一·因子1 ±2.5%",
) -> MarketReview:
    """从盯盘行 + 大盘指数构建复盘对象。"""
    indices = list(indices or [])
    session = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        datetime.now().strftime("%Y-%m-%d"),
    )

    total_mv = 0.0
    day_total = 0.0
    day_n = 0
    for r in rows:
        qty = int(r.get("持仓") or 0)
        if r.get("市值") is not None and qty > 0:
            total_mv += float(r["市值"])
        if r.get("当日盈亏") is not None and (qty > 0 or r.get("已实现")):
            day_total += float(r["当日盈亏"])
            day_n += 1

    position_pct = None
    if account_total and account_total > 0 and total_mv > 0:
        position_pct = round(total_mv / float(account_total) * 100.0, 1)

    equity_pnl = equity_pct = None
    if account_total is not None and account_open is not None:
        equity_pnl = round(float(account_total) - float(account_open), 2)
        if float(account_open) > 0:
            equity_pct = round(equity_pnl / float(account_open) * 100.0, 2)

    day_pnl = round(day_total, 2) if day_n else None
    day_pct = None
    if day_pnl is not None and account_open and float(account_open) > 0:
        day_pct = round(day_pnl / float(account_open) * 100.0, 2)

    holdings: list[ReviewLine] = []
    alerts: list[ReviewLine] = []
    settled: list[ReviewLine] = []
    empty_watch: list[ReviewLine] = []

    for r in rows:
        if r.get("error"):
            continue
        code = str(r.get("代码") or "")
        name = str(r.get("名称") or "")
        pos = str(r.get("持仓状态") or "-")
        alert = str(r.get("预警") or "")
        hit = str(r.get("因子触发") or "")
        qty = int(r.get("持仓") or 0)
        line = ReviewLine(
            code=code,
            name=name,
            status=pos,
            last=r.get("现价") if r.get("现价") is not None else None,
            day_chg=r.get("当日涨幅"),
            day_pnl=float(r["当日盈亏"]) if r.get("当日盈亏") is not None else None,
            float_pnl=float(r["浮盈"]) if r.get("浮盈") is not None else None,
            alert=alert,
            hit=hit,
        )

        if r.get("已实现"):
            line.note = f"结算 {alert or '已实现'}"
            settled.append(line)
            continue

        if qty > 0:
            holdings.append(line)

        # 预警 / 接近 / 待买待卖
        is_alert = pos in {"待买入", "待卖出"} or bool(r.get("近买点") or r.get("近止损"))
        if (
            is_alert
            or hit.startswith("已触发")
            or hit.startswith("接近")
            or "已触" in alert
            or "将" in alert
            or str(r.get("已触买") or "") == "是"
            or str(r.get("已触止损") or "") == "是"
        ):
            alerts.append(line)
        elif qty <= 0:
            empty_watch.append(line)

    return MarketReview(
        generated_at=_now(),
        strategy=strategy,
        session=session,
        indices=indices,
        account_total=account_total,
        account_open=account_open,
        available_cash=available_cash,
        position_pct=position_pct,
        day_pnl=day_pnl,
        day_pnl_pct=day_pct,
        equity_pnl=equity_pnl,
        equity_pnl_pct=equity_pct,
        holdings=holdings,
        alerts=alerts,
        settled=settled,
        empty_watch=empty_watch,
    )


def format_review_text(review: MarketReview, *, max_empty: int = 6) -> str:
    """生成适合微信推送的纯文本复盘。"""
    lines: list[str] = [
        "【行情复盘】",
        f"{review.session} · {review.generated_at}",
        review.strategy,
        "",
        "【大盘】",
    ]
    if not review.indices:
        lines.append("  (无指数数据)")
    for ix in review.indices:
        if ix.get("error"):
            lines.append(f"  {ix.get('name')}: 失败")
            continue
        name = ix.get("name") or ix.get("market") or "-"
        lines.append(
            f"  {name} {_f(ix.get('price'))}  "
            f"{_pct(ix.get('chg_pct'))}  "
            f"({_f(ix.get('chg_points'), 2)}点)"
        )

    lines.append("")
    lines.append("【账户】")
    pos_txt = "-" if review.position_pct is None else f"{review.position_pct:.1f}%"
    lines.append(
        f"  总资产 {_f(review.account_total)} · 可用 {_f(review.available_cash)} · 仓位 {pos_txt}"
    )
    if review.equity_pnl is not None:
        lines.append(
            f"  相对日初 {_f(review.equity_pnl)} ({_pct(review.equity_pnl_pct)})"
        )
    if review.day_pnl is not None:
        lines.append(f"  合计当日盈亏 {_f(review.day_pnl)} ({_pct(review.day_pnl_pct)})")
    else:
        lines.append("  合计当日盈亏 -")

    lines.append("")
    lines.append(f"【持仓】{len(review.holdings)} 只")
    if not review.holdings:
        lines.append("  (空仓)")
    for h in review.holdings:
        pnl = h.day_pnl if h.day_pnl is not None else h.float_pnl
        lines.append(
            f"  {h.name}({h.code}) {h.status} "
            f"现价{_f(h.last)} 涨跌{_fmt_chg(h.day_chg)} "
            f"盈亏{_f(pnl)}"
        )

    if review.settled:
        lines.append("")
        lines.append(f"【策略结算】{len(review.settled)} 只")
        for s in review.settled:
            lines.append(
                f"  {s.name}({s.code}) {_f(s.day_pnl)} · {s.note or s.alert or s.hit}"
            )

    if review.alerts:
        lines.append("")
        lines.append(f"【策略事件/预警】{len(review.alerts)} 只")
        for a in review.alerts:
            tip = a.alert or a.hit or a.status
            lines.append(
                f"  {a.name}({a.code}) {a.status} · {tip} · 现价{_f(a.last)}"
            )

    # 空仓未预警：只列摘要 + 前几只
    empty_n = len(review.empty_watch)
    if empty_n:
        lines.append("")
        lines.append(f"【空仓盯盘】未进预警 {empty_n} 只")
        for e in review.empty_watch[:max_empty]:
            lines.append(
                f"  {e.name}({e.code}) {_fmt_chg(e.day_chg)} · {e.hit or '未触发'}"
            )
        if empty_n > max_empty:
            lines.append(f"  …另有 {empty_n - max_empty} 只")

    lines.append("")
    lines.append("（复盘推送 · 不走大模型）")
    return "\n".join(lines)


def _fmt_chg(v: Any) -> str:
    if v is None or v == "" or v == "-":
        return "-"
    s = str(v).strip()
    if s.endswith("%"):
        try:
            return f"{float(s[:-1]):+.2f}%"
        except ValueError:
            return s
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return s


def save_review(
    review: MarketReview,
    text: str | None = None,
    *,
    text_path: Path = REVIEW_FILE,
    json_path: Path = REVIEW_JSON,
) -> tuple[Path, Path]:
    body = text if text is not None else format_review_text(review)
    text_path.write_text(body + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return text_path, json_path


def send_review_wechat(
    review: MarketReview | None = None,
    *,
    text: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """推送复盘文本到微信机器人（OpenClaw，不走大模型）。"""
    from wechat_notify import send_text

    msg = text
    if msg is None:
        if review is None:
            return False, "无复盘内容"
        msg = format_review_text(review)
    return send_text(msg, config=config)
