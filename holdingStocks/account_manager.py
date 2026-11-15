"""多账户管理模块 (Account Manager)。

支持交易工作台的多账户体系：
1. 默认账户平滑兼容：原系统实盘/纸盘作为 'acc_default'，数据无损继承。
2. 账户隔离：每个账户拥有独立资金、独立持仓 (positions)、独立已平仓记录 (closed_today)。
3. 账户属性：支持长线 (long_term) 与短线 (short_term) 标签，独立挂载策略与风控规则。
4. 后台执行解耦：每个账户独立在后台运行与核算，前端切换仅切换观察视窗，绝不影响后台。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
ACCOUNTS_CONFIG_FILE = _ROOT / "accounts_config.json"
ACCOUNTS_DATA_DIR = _ROOT / "accounts_data"

# 默认账户模板
DEFAULT_ACCOUNT_ID = "acc_default"


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ensure_env() -> None:
    ACCOUNTS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS_CONFIG_FILE.exists():
        initial_config = {
            "version": 1,
            "active_account_id": DEFAULT_ACCOUNT_ID,
            "accounts": [
                {
                    "id": DEFAULT_ACCOUNT_ID,
                    "name": "默认主账户",
                    "type": "long_term",
                    "is_default": True,
                    "initial_capital": 300000.0,
                    "color": "blue",
                    "description": "系统默认主账户，长线核心底仓与稳健配置",
                    "mounted_strategies": [
                        "strategy1",
                        "strategy3",
                        "strategy17",
                        "strategy37",
                        "strategy38",
                    ],
                    "risk_rules": {
                        "max_position_pct": 0.25,
                        "stop_loss_pct": -0.08,
                        "max_hold_days": 60,
                        "cash_gate_sensitive": False,
                    },
                    "created_at": _now_str(),
                }
            ],
        }
        ACCOUNTS_CONFIG_FILE.write_text(
            json.dumps(initial_config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def get_accounts_config() -> dict[str, Any]:
    _ensure_env()
    try:
        return json.loads(ACCOUNTS_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ACCOUNT] 读取账户配置文件失败: {e}")
        return {"active_account_id": DEFAULT_ACCOUNT_ID, "accounts": []}


def save_accounts_config(cfg: dict[str, Any]) -> None:
    _ensure_env()
    tmp = ACCOUNTS_CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, ACCOUNTS_CONFIG_FILE)


def get_account_file(account_id: str) -> Path:
    _ensure_env()
    return ACCOUNTS_DATA_DIR / f"holdings_{account_id}.json"


def get_account_holdings_data(account_id: str) -> dict[str, Any]:
    """获取指定账户的持仓数据。若是默认账户，返回当前主账本；若是子账户，从专属文件读取。"""
    _ensure_env()
    if account_id == DEFAULT_ACCOUNT_ID:
        try:
            from holdingStocks.index import load_holdings
            return load_holdings()
        except Exception:
            try:
                from index import load_holdings
                return load_holdings()
            except Exception:
                pass

    f = get_account_file(account_id)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ACCOUNT] 读取账户 {account_id} 账本失败: {e}")

    # 获取初始资金配置
    cfg = get_accounts_config()
    acc = next((a for a in cfg.get("accounts", []) if a["id"] == account_id), None)
    init_cap = float(acc.get("initial_capital", 100000.0)) if acc else 100000.0

    # 兜底返回标准空账本
    data = {
        "account_id": account_id,
        "updated_at": _now_str(),
        "account_total": init_cap,
        "account_cash": init_cap,
        "paper_equity_base": init_cap,
        "positions": {},
        "closed_today": {},
        "realized_today": {},
    }
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def save_account_holdings_data(account_id: str, data: dict[str, Any]) -> None:
    """持久化保存子账户的持仓数据。"""
    _ensure_env()
    if account_id == DEFAULT_ACCOUNT_ID:
        try:
            from holdingStocks.index import save_holdings
            save_holdings(data)
            return
        except Exception:
            try:
                from index import save_holdings
                save_holdings(data)
                return
            except Exception:
                pass

    f = get_account_file(account_id)
    tmp = f.with_suffix(".tmp")
    data["updated_at"] = _now_str()
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def list_accounts_summary() -> list[dict[str, Any]]:
    """获取所有账户的元数据及实时资产与持仓摘要，供前端胶囊导航栏展示。"""
    cfg = get_accounts_config()
    res = []
    for a in cfg.get("accounts", []):
        aid = a["id"]
        h_data = get_account_holdings_data(aid)
        
        # 统计持仓数量与浮动市值
        positions = h_data.get("positions") or {}
        active_positions = 0
        total_market_value = 0.0
        for p in positions.values():
            if not isinstance(p, dict):
                continue
            qty = int(p.get("qty") or 0)
            if qty > 0:
                active_positions += 1
                price = float(p.get("cost") or 0.0)
                total_market_value += qty * price

        available_cash = float(h_data.get("account_cash") or h_data.get("account_total") or a.get("initial_capital", 0.0))
        account_total = float(h_data.get("account_total") or (available_cash + total_market_value))

        res.append({
            "id": aid,
            "name": a.get("name", "未命名账户"),
            "type": a.get("type", "short_term"),
            "is_default": bool(a.get("is_default", False)),
            "initial_capital": a.get("initial_capital", 100000.0),
            "color": a.get("color", "blue"),
            "description": a.get("description", ""),
            "mounted_strategies": a.get("mounted_strategies", []),
            "risk_rules": a.get("risk_rules", {}),
            "created_at": a.get("created_at", ""),
            "account_total": account_total,
            "available_cash": available_cash,
            "market_value": total_market_value,
            "positions_count": active_positions,
        })
    return res


def create_account(payload: dict[str, Any]) -> dict[str, Any]:
    """创建新账户。"""
    cfg = get_accounts_config()
    accounts = cfg.get("accounts", [])

    name = str(payload.get("name", "")).strip() or "新账户"
    acc_type = payload.get("type", "short_term")
    if acc_type not in ("long_term", "short_term"):
        acc_type = "short_term"

    initial_capital = float(payload.get("initial_capital") or 100000.0)
    color = str(payload.get("color") or ("amber" if acc_type == "short_term" else "blue"))
    description = str(payload.get("description", "")).strip()
    mounted_strategies = list(payload.get("mounted_strategies") or (["strategy38"] if acc_type == "short_term" else ["strategy1"]))
    
    # 风控规则
    default_risk = {
        "max_position_pct": 0.20 if acc_type == "short_term" else 0.30,
        "stop_loss_pct": -0.04 if acc_type == "short_term" else -0.10,
        "max_hold_days": 5 if acc_type == "short_term" else 90,
        "cash_gate_sensitive": True if acc_type == "short_term" else False,
    }
    user_risk = payload.get("risk_rules") or {}
    for k, v in user_risk.items():
        if v is not None:
            default_risk[k] = v

    new_id = f"acc_{acc_type[:5]}_{int(time.time())}"
    account_entry = {
        "id": new_id,
        "name": name,
        "type": acc_type,
        "is_default": False,
        "initial_capital": initial_capital,
        "color": color,
        "description": description,
        "mounted_strategies": mounted_strategies,
        "risk_rules": default_risk,
        "created_at": _now_str(),
    }
    accounts.append(account_entry)
    cfg["accounts"] = accounts
    save_accounts_config(cfg)

    # 初始化其专属持仓文件
    init_data = {
        "account_id": new_id,
        "updated_at": _now_str(),
        "account_total": initial_capital,
        "account_cash": initial_capital,
        "paper_equity_base": initial_capital,
        "positions": {},
        "closed_today": {},
        "realized_today": {},
    }
    f = get_account_file(new_id)
    f.write_text(json.dumps(init_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return account_entry


def update_account(account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新指定账户配置。"""
    cfg = get_accounts_config()
    accounts = cfg.get("accounts", [])
    acc = next((a for a in accounts if a["id"] == account_id), None)
    if not acc:
        raise ValueError(f"未找到账户: {account_id}")

    if "name" in payload and payload["name"]:
        acc["name"] = str(payload["name"]).strip()
    if "type" in payload and payload["type"] in ("long_term", "short_term"):
        acc["type"] = payload["type"]
    if "initial_capital" in payload and payload["initial_capital"] is not None:
        acc["initial_capital"] = float(payload["initial_capital"])
    if "color" in payload and payload["color"]:
        acc["color"] = str(payload["color"])
    if "description" in payload:
        acc["description"] = str(payload["description"]).strip()
    if "mounted_strategies" in payload and isinstance(payload["mounted_strategies"], list):
        acc["mounted_strategies"] = payload["mounted_strategies"]
    if "risk_rules" in payload and isinstance(payload["risk_rules"], dict):
        acc.setdefault("risk_rules", {}).update(payload["risk_rules"])

    save_accounts_config(cfg)
    return acc


def delete_account(account_id: str) -> dict[str, Any]:
    """删除指定账户（默认账户禁止删除，有持仓账户需提示先清仓）。"""
    if account_id == DEFAULT_ACCOUNT_ID:
        raise ValueError("默认主账户受系统保护，不可删除")

    cfg = get_accounts_config()
    accounts = cfg.get("accounts", [])
    acc = next((a for a in accounts if a["id"] == account_id), None)
    if not acc:
        raise ValueError(f"未找到账户: {account_id}")

    # 检查是否有未平仓持仓
    h_data = get_account_holdings_data(account_id)
    positions = h_data.get("positions") or {}
    has_pos = any(int(p.get("qty") or 0) > 0 for p in positions.values() if isinstance(p, dict))
    if has_pos:
        raise ValueError("该账户尚有持仓股票，请先平仓或划转后再执行删除")

    # 从配置中移除
    accounts = [a for a in accounts if a["id"] != account_id]
    cfg["accounts"] = accounts
    if cfg.get("active_account_id") == account_id:
        cfg["active_account_id"] = DEFAULT_ACCOUNT_ID
    save_accounts_config(cfg)

    # 移除文件
    f = get_account_file(account_id)
    if f.exists():
        try:
            f.unlink()
        except Exception:
            pass

    return {"status": "success", "deleted_id": account_id}


def set_active_account_id(account_id: str) -> str:
    """切换系统默认活跃账户。"""
    cfg = get_accounts_config()
    acc = next((a for a in cfg.get("accounts", []) if a["id"] == account_id), None)
    if not acc:
        raise ValueError(f"未找到账户: {account_id}")
    cfg["active_account_id"] = account_id
    save_accounts_config(cfg)
    return account_id


def get_active_account_id() -> str:
    cfg = get_accounts_config()
    return cfg.get("active_account_id") or DEFAULT_ACCOUNT_ID


def format_account_tag(account_id: str) -> str:
    """生成用于微信或通知的消息前缀标签，如 【短线起爆】。"""
    cfg = get_accounts_config()
    acc = next((a for a in cfg.get("accounts", []) if a["id"] == account_id), None)
    if not acc:
        return "【主账户】"
    name = acc.get("name", "主账户")
    return f"【{name}】"
