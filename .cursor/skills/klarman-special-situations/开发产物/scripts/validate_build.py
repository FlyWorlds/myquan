"""Strict, offline validator for the Q51 BUILD V2 delivery package."""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
ROOT = SCRIPT_ROOT if (SCRIPT_ROOT / "生产产物").is_dir() else SCRIPT_ROOT.parent
DEV = SCRIPT_ROOT if SCRIPT_ROOT.name == "开发产物" else ROOT / "开发产物"
PROD = ROOT / "生产产物"
OPERATIONS = ROOT / "validation" / "operations"
API_DOCUMENT = Path("E:/quantskill/接口文档(1).md")
API_DOCUMENT_SHA256 = "694C193EC3714F1B25D20BBE7F03CC8D3932ECFBE5C2CB881AB15B66A0879D16"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{path} 缺少 YAML frontmatter")
    return text.split("\n---\n", 1)[0]


def _require_files(paths: list[Path]) -> None:
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"缺少 BUILD 交付文件: {missing}")


def _check_dev_package() -> dict[str, Any]:
    required = [
        DEV / "SKILL.md",
        DEV / "skill.json",
        DEV / "scripts" / "build.py",
        DEV / "scripts" / "test.py",
        DEV / "scripts" / "validate_build.py",
        DEV / "references" / "api_guide.md",
        DEV / "demo.mp4",
    ]
    _require_files(required)
    frontmatter = _frontmatter(DEV / "SKILL.md")
    for key in ("name:", "description:", "tags:"):
        if key not in frontmatter:
            raise ValueError(f"开发版 SKILL.md 缺少 BUILD 字段 {key}")
    metadata = json.loads((DEV / "skill.json").read_text(encoding="utf-8"))
    if metadata.get("version") != "7.4.0":
        raise ValueError("skill.json 版本不是 7.4.0")
    if metadata.get("build_type") != "hybrid":
        raise ValueError("skill.json 未声明 hybrid BUILD")
    if metadata.get("data_source") != "panda_data":
        raise ValueError("skill.json 数据源不是 panda_data")

    source_tree_is_available = all(
        (ROOT / relative).exists()
        for relative in ("SKILL.md", "skill.json", "demo.mp4", "scripts", "references")
    )
    if not source_tree_is_available:
        # A portable delivery deliberately contains only 开发产物/ and 生产产物/.
        return {
            "path": str(DEV.resolve()),
            "files": len(required),
            "version": metadata["version"],
            "synchronized": True,
            "source_mode": "portable_delivery",
        }

    # The release package must be a synchronized copy of every development
    # source file. Exclude interpreter caches because they are not artifacts.
    sync_files = [Path("SKILL.md"), Path("skill.json"), Path("demo.mp4")]
    for directory in (ROOT / "scripts", ROOT / "references"):
        sync_files.extend(
            path.relative_to(ROOT)
            for path in directory.rglob("*")
            if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts
        )
    drift = []
    packaged_relatives = {
        path.relative_to(DEV)
        for directory in (DEV / "scripts", DEV / "references")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts
    }
    expected_relatives = {path for path in sync_files if path.parts[0] in {"scripts", "references"}}
    extra = sorted(str(path) for path in packaged_relatives - expected_relatives)
    if extra:
        raise ValueError(f"开发产物包含未登记文件: {extra}")
    for relative in sync_files:
        source = ROOT / relative
        packaged = DEV / relative
        if _sha256(source) != _sha256(packaged):
            drift.append(str(relative))
    if drift:
        raise ValueError(f"开发产物与源码不同步: {drift}")
    return {
        "path": str(DEV.resolve()),
        "files": len(required),
        "version": metadata["version"],
        "synchronized": True,
        "source_mode": "authoring_tree",
    }


def _check_production_package() -> dict[str, Any]:
    required = [PROD / "SKILL.md", PROD / "数据库.parquet"]
    _require_files(required)
    frontmatter = _frontmatter(PROD / "SKILL.md")
    for key in ("name:", "description:", "tags:"):
        if key not in frontmatter:
            raise ValueError(f"生产版 SKILL.md 缺少 BUILD 字段 {key}")

    sys.path.insert(0, str(DEV / "scripts"))
    import build  # noqa: WPS433  (intentional local BUILD import)

    signature = inspect.signature(build.run)
    if list(signature.parameters) != ["input_data", "config"]:
        raise ValueError(f"run 签名不符合 BUILD 约定: {signature}")
    validate_signature = inspect.signature(build.validate_input)
    if list(validate_signature.parameters) != ["input_data"]:
        raise ValueError(f"validate_input 签名不符合 BUILD 约定: {validate_signature}")

    inspection = build.inspect_production(
        PROD / "数据库.parquet", expected_data_version=build.DATA_VERSION
    )
    if inspection.get("status") != "current":
        raise ValueError(f"生产 Parquet 不是 current: {inspection}")
    if inspection.get("scope_types") != ["all_a_share"]:
        raise ValueError(f"生产 Parquet 不是全市场范围: {inspection.get('scope_types')}")
    if inspection.get("duplicate_keys") or inspection.get("invalid_json"):
        raise ValueError(f"生产 Parquet 质量检查失败: {inspection}")
    frame = pd.read_parquet(PROD / "数据库.parquet")
    current = frame[frame["data_version"].astype(str).eq(build.DATA_VERSION)]
    digest_rows = current[current["result_type"].astype(str).eq("research_digest")]
    if digest_rows.empty:
        raise ValueError("当前生产分区缺少 research_digest")
    digest = json.loads(digest_rows.iloc[-1]["result_json"])
    shortlist = digest.get("shortlist") or []
    risks = digest.get("risk_watchlist") or []
    if len(shortlist) > 5 or len(risks) > 5:
        raise ValueError("研究候选或风险观察超过 5 条")
    category_counts = Counter(str(item.get("situation_type") or "") for item in shortlist)
    if any(count > 3 for count in category_counts.values()):
        raise ValueError(f"研究候选类别超过 3 条: {dict(category_counts)}")
    for item in shortlist + risks:
        if item.get("not_trade_signal") is not True:
            raise ValueError("研究卡或风险卡缺少 not_trade_signal=true")
        if item in shortlist and int(item.get("score") or 0) < 60:
            raise ValueError("低于 60 分的记录进入研究榜")
        if item.get("underwriting_status") == "qualified_special_situation" and item in shortlist:
            raise ValueError("合格承保记录泄漏到研究榜")
        if item in shortlist and item.get("situation_type") == "private_placement_supply_risk":
            raise ValueError("定增供给风险泄漏到机会榜")
        breakdown = item.get("score_breakdown")
        if not isinstance(breakdown, dict) or breakdown.get("total") != item.get("score"):
            raise ValueError("研究卡缺少一致的 score_breakdown")

    def date_token(value: Any) -> str | None:
        digits = "".join(character for character in str(value or "") if character.isdigit())[:8]
        if len(digits) != 8:
            return None
        try:
            datetime.strptime(digits, "%Y%m%d")
        except ValueError:
            return None
        return digits

    future_dates = []
    for _, row in current.iterrows():
        trade_date = date_token(row["trade_date"])
        payload = json.loads(row["result_json"])
        if not isinstance(payload, dict):
            continue
        values = [(key, payload.get(key)) for key in ("knowledge_cutoff", "event_date", "source_data_date", "actual_source_date")]
        for key in ("evidence_available_dates", "available_dates"):
            extra_dates = payload.get(key)
            if isinstance(extra_dates, list):
                values.extend((key, value) for value in extra_dates)
        for key, value in values:
            evidence_date = date_token(value)
            if trade_date and evidence_date and evidence_date > trade_date:
                future_dates.append((str(row["target_id"]), key, evidence_date, trade_date))
    if future_dates:
        raise ValueError(f"发现决策日之后证据: {future_dates[:3]}")

    job_path = OPERATIONS / "job_latest.json"
    health_path = OPERATIONS / "health_latest.json"
    if job_path.is_file():
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if job.get("status") != "completed" or job.get("data_version") != build.DATA_VERSION:
            raise ValueError(f"生产任务未完成: {job}")
    if health_path.is_file():
        health = json.loads(health_path.read_text(encoding="utf-8"))
        if health.get("status") != "healthy" or health.get("alerts"):
            raise ValueError(f"生产健康检查未通过: {health.get('status')}")
    dashboard = ROOT / "validation" / "production_dashboard.html"
    dashboard_text = dashboard.read_text(encoding="utf-8")
    for marker in ("今日研究候选", "独立风险观察", "评分贡献", "相关接口说明", "事件解释说明"):
        if marker not in dashboard_text:
            raise ValueError(f"生产看板缺少中文区块: {marker}")
    if API_DOCUMENT.is_file() and _sha256(API_DOCUMENT).lower() != API_DOCUMENT_SHA256.lower():
        raise ValueError("接口文档 SHA-256 与已登记版本不一致")
    inspection["research_digest"] = {
        "shortlist_count": len(shortlist),
        "risk_watch_count": len(risks),
        "unmapped_event_count": digest.get("unmapped_event_count"),
        "not_trade_signal": digest.get("not_trade_signal"),
        "future_evidence_issues": len(future_dates),
    }
    inspection["operations_status"] = "healthy" if health_path.is_file() else "not_checked"
    inspection["dashboard_status"] = "checked"
    inspection["api_document_status"] = "checked" if API_DOCUMENT.is_file() else "not_checked"
    return inspection


def validate(root: Path = ROOT) -> dict[str, Any]:
    if root.resolve() != ROOT.resolve():
        raise ValueError("验证器必须从 Q51 BUILD 根目录运行")
    return {
        "status": "current",
        "build_id": "Q51",
        "data_version": "7.4.0",
        "development": _check_dev_package(),
        "production": _check_production_package(),
    }


def main() -> None:
    print(json.dumps(validate(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
